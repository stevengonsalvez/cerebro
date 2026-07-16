"""Unit tests for the autoresearch signal-export sink (cerebro/sink/export.py).

Covers the SPEC 3.1 mapping (vault-note-shaped Signal -> research-signal), the
500-per-request chunking, fail-soft POST, and the ledger pre-filter fail-open
behaviour. Network is always mocked; no test hits a real service.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cerebro.models import Signal
from cerebro.sink import export


# --- helpers -----------------------------------------------------------------
def make_settings(*, enabled=True, dry_run=False, url="", token_env="AR_TOKEN",
                  tenant_id="meridian", export_dir=None):
    cfg = {
        "enabled": enabled,
        "autoresearch_url": url,
        "token_env": token_env,
        "tenant_id": tenant_id,
    }
    if export_dir is not None:
        cfg["dir"] = str(export_dir)
    return SimpleNamespace(export=cfg, dry_run=dry_run)


def make_signal(**over):
    base = dict(
        url="https://github.com/UKGovernmentBEIS/inspect_ai",
        title="Inspect AI is trending",
        source="github_trending",
        canonical_url="github.com/UKGovernmentBEIS/inspect_ai",
        url_hash="deadbeefcafef00d",
        clean_text="Inspect AI adds new scorers.",
        simhash=4611686018427387900,
        score=0.85,
        category="coding-agents",
        tags=["evals", "inspect"],
        captured="2026-07-16T09:00:00Z",
        meta={"reason": "eval-authoring guidance is behind upstream"},
    )
    base.update(over)
    return Signal(**base)


class FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise export.requests.HTTPError(f"status {self.status_code}")


# --- SPEC 3.1 mapping --------------------------------------------------------
def test_mapping_full_fields():
    payload = export.signal_to_payload(make_signal(), "meridian", run_id="2026-07-16T09:00:00")
    assert payload["schemaVersion"] == 1
    assert payload["id"] == "sig-cerebro-deadbeefcafef00d"
    assert payload["tenant_id"] == "meridian"
    assert payload["fingerprint"] == (
        "sha256:fbe9b51ec5c338101e13f2a96e993842b06d171a155c0281d4a1590fa8598098"
    )
    assert payload["fingerprint_basis"] == "url"
    assert payload["source"] == "github_trending"
    assert payload["title"] == "Inspect AI is trending"
    assert payload["category"] == "coding-agents"
    assert payload["score"] == pytest.approx(0.85)
    assert payload["reason"] == "eval-authoring guidance is behind upstream"
    assert payload["captured_at"] == "2026-07-16T09:00:00Z"
    assert payload["url"] == "https://github.com/UKGovernmentBEIS/inspect_ai"
    assert payload["simhash"] == "4611686018427387900"   # decimal string
    assert payload["tags"] == ["evals", "inspect"]
    assert payload["excerpt"] == "Inspect AI adds new scorers."
    assert payload["run_id"] == "2026-07-16T09:00:00"


def test_mapping_category_and_reason_fallback():
    s = make_signal(category="", meta={})
    payload = export.signal_to_payload(s, "meridian")
    assert payload["category"] == "misc"                     # schema requires minLength 1
    assert payload["reason"] == "cerebro github_trending signal"
    assert "run_id" not in payload                           # omitted when empty


def test_mapping_content_basis_when_no_url():
    s = make_signal(url="", url_hash="", simhash=0)
    payload = export.signal_to_payload(s, "meridian")
    assert payload["fingerprint_basis"] == "content"
    assert payload["fingerprint"] == export.fingerprint_content("Inspect AI is trending")
    assert "url" not in payload
    assert payload["simhash"].isdigit()                      # recomputed 63-bit simhash


def test_excerpt_truncated_to_4000():
    s = make_signal(clean_text="x" * 5000)
    payload = export.signal_to_payload(s, "meridian")
    assert len(payload["excerpt"]) == 4000


def test_captured_at_naive_gets_utc_suffix():
    payload = export.signal_to_payload(make_signal(captured="2026-07-16T09:00:00"), "t")
    assert payload["captured_at"] == "2026-07-16T09:00:00Z"


def test_captured_at_blank_defaults_to_now_utc():
    payload = export.signal_to_payload(make_signal(captured=""), "t")
    assert export._DT_RE.match(payload["captured_at"])       # always schema-shaped


# --- write(): jsonl + gating -------------------------------------------------
def test_write_disabled_is_noop(tmp_path):
    settings = make_settings(enabled=False, export_dir=tmp_path)
    stats = SimpleNamespace(run_id="2026-07-16T09:00:00")
    assert export.write([make_signal()], settings, stats) == {}
    assert list(tmp_path.iterdir()) == []


def test_write_produces_jsonl(tmp_path):
    settings = make_settings(url="", export_dir=tmp_path)     # no url -> no POST
    stats = SimpleNamespace(run_id="2026-07-16T09:00:00")
    result = export.write([make_signal(), make_signal(url_hash="second")], settings, stats)
    out = tmp_path / "signals-2026-07-16T09-00-00.jsonl"      # colons sanitized in filename
    assert out.exists()
    assert result["jsonl"] == str(out)
    assert result["n"] == 2
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "sig-cerebro-deadbeefcafef00d"


# --- POST batching + fail-soft ----------------------------------------------
def test_post_chunks_at_500(tmp_path, monkeypatch):
    sent_sizes = []

    def fake_post(endpoint, json=None, headers=None, timeout=None):
        sent_sizes.append(len(json))
        return FakeResp(200)

    monkeypatch.setattr(export.requests, "post", fake_post)
    monkeypatch.setenv("AR_TOKEN", "tok")
    settings = make_settings(url="https://ar.internal", export_dir=tmp_path)
    stats = SimpleNamespace(run_id="run")
    signals = [make_signal(url_hash=f"h{i}") for i in range(1101)]
    result = export.write(signals, settings, stats)
    assert sent_sizes == [500, 500, 101]                     # chunked at 500
    assert result["posted"] == 1101


def test_post_failure_is_fail_soft_and_keeps_jsonl(tmp_path, monkeypatch):
    def boom(endpoint, json=None, headers=None, timeout=None):
        raise export.requests.ConnectionError("service down")

    monkeypatch.setattr(export.requests, "post", boom)
    monkeypatch.setenv("AR_TOKEN", "tok")
    settings = make_settings(url="https://ar.internal", export_dir=tmp_path)
    stats = SimpleNamespace(run_id="run")
    result = export.write([make_signal()], settings, stats)   # must not raise
    assert result["posted"] == 0
    assert (tmp_path / "signals-run.jsonl").exists()          # jsonl kept


def test_post_skipped_without_token(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(export.requests, "post", lambda *a, **k: called.append(1) or FakeResp())
    monkeypatch.delenv("AR_TOKEN", raising=False)
    settings = make_settings(url="https://ar.internal", export_dir=tmp_path)
    result = export.write([make_signal()], settings, SimpleNamespace(run_id="run"))
    assert called == []                                       # no token -> no POST
    assert result["posted"] == 0


def test_post_skipped_in_dry_run(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(export.requests, "post", lambda *a, **k: called.append(1) or FakeResp())
    monkeypatch.setenv("AR_TOKEN", "tok")
    settings = make_settings(url="https://ar.internal", dry_run=True, export_dir=tmp_path)
    export.write([make_signal()], settings, SimpleNamespace(run_id="run"))
    assert called == []                                       # dry-run mutes network


# --- ledger pre-filter fail-open --------------------------------------------
def test_prefilter_noop_when_disabled():
    signals = [make_signal()]
    assert export.prefilter(signals, make_settings(enabled=False)) is signals


def test_prefilter_noop_without_url():
    signals = [make_signal()]
    assert export.prefilter(signals, make_settings(url="")) is signals


def test_prefilter_drops_already_tried(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        # first signal is already tried (200), second is unseen (404)
        return FakeResp(200) if url.endswith("cafef00d_fp1") else FakeResp(404)

    fps = iter(["cafef00d_fp1", "cafef00d_fp2"])
    monkeypatch.setattr(export, "_fingerprint", lambda s: (next(fps), "url"))
    monkeypatch.setattr(export.requests, "get", fake_get)
    monkeypatch.setenv("AR_TOKEN", "tok")
    settings = make_settings(url="https://ar.internal")
    kept = export.prefilter([make_signal(), make_signal(url_hash="b")], settings)
    assert len(kept) == 1                                     # tried one dropped


def test_prefilter_fail_open_on_unreachable(monkeypatch):
    def boom(url, headers=None, timeout=None):
        raise export.requests.ConnectionError("autoresearch down")

    monkeypatch.setattr(export.requests, "get", boom)
    monkeypatch.setenv("AR_TOKEN", "tok")
    signals = [make_signal(), make_signal(url_hash="b")]
    kept = export.prefilter(signals, make_settings(url="https://ar.internal"))
    assert kept == signals                                    # nothing dropped when service is down


def test_prefilter_fail_open_on_server_error(monkeypatch):
    monkeypatch.setattr(export.requests, "get", lambda *a, **k: FakeResp(500))
    monkeypatch.setenv("AR_TOKEN", "tok")
    signals = [make_signal()]
    kept = export.prefilter(signals, make_settings(url="https://ar.internal"))
    assert kept == signals                                    # 5xx keeps the signal (fail-open)
