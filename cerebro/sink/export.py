from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests

from ..models import Signal

ROOT = pathlib.Path(__file__).resolve().parents[2]

# The 12 sources the signal-export family accepts; an unknown source is a hard
# reject downstream (the tried ledger depends on knowing provenance). Vendored
# from specs/signal-export so cerebro never has to depend on the kernel repo.
SIGNAL_SOURCES = (
    "reflect", "hackernews", "showhn", "yclaunches", "ycrfs", "reddit",
    "github_trending", "ossinsight", "rss", "gmail", "x", "manual",
)

_TRACKING_RE = re.compile(r"^(utm_.*|ref|fbclid)$")
_WORD = re.compile(r"\w+")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

_MAX_BATCH = 500      # ingest cap per request (SPEC 5.1: 413 beyond 500)
_LEDGER_TIMEOUT = 2   # seconds; bound the extra pre-filter latency
_POST_TIMEOUT = 30    # seconds; batch ingest POST


# --- vendored fingerprint canonicalization -----------------------------------
# Byte-identical to core/contracts/signal_export.py and the reference exporter
# specs/signal-export/reference/export_cerebro.py (SPEC Section 5.1 step 1). The
# service recomputes the fingerprint from the payload and rejects a mismatch, so
# these must agree exactly. Vendored here to keep cerebro free of any kernel-repo
# dependency; a conformance test pins the digest against the shared test vectors.
def canonicalize_url(url: str) -> str:
    """Lowercase host, strip scheme + leading www., drop utm_*/ref/fbclid params,
    sort the rest, drop fragment + trailing slash."""
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    params = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_RE.match(k)
    ]
    params.sort()
    query = urlencode(params)
    path = parts.path.rstrip("/")
    canonical = netloc + path
    if query:
        canonical += "?" + query
    return canonical


def fingerprint_url(url: str) -> str:
    """'sha256:' + full 64-char hex digest of the canonicalized url."""
    return "sha256:" + hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()


def fingerprint_content(title: str) -> str:
    """Fingerprint basis for url-less signals: lowercase, strip punctuation,
    collapse whitespace. Source deliberately NOT in the key, so the same content
    from two sources collides."""
    normalized = re.sub(r"[^\w\s]", " ", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _simhash(text: str) -> int:
    """63-bit simhash, byte-identical to cerebro/process/dedup.py::simhash.
    Only used as a fallback when the Signal has not been through dedup yet."""
    bits = [0] * 63
    for tok in _WORD.findall(text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        for i in range(63):
            bits[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(63) if bits[i] > 0)


def _fingerprint(signal: Signal) -> tuple[str, str]:
    """(fingerprint, basis) for a Signal: url basis when a url is present."""
    url = (signal.url or "").strip()
    if url:
        return fingerprint_url(url), "url"
    return fingerprint_content(signal.title or ""), "content"


def _captured_at(value) -> str:
    """Normalize a captured timestamp to the schema's date-time shape (a timezone
    suffix is required). Defaults to now-UTC when missing or unparseable so a
    naive/blank timestamp never produces a schema-invalid payload."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat() + "T00:00:00Z"
    else:
        text = str(value or "").strip()
        if _DT_RE.match(text):
            return text[:-6] + "Z" if text.endswith("+00:00") else text
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    text = dt.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


# --- SPEC 3.1 mapping: cerebro Signal -> research-signal payload --------------
def signal_to_payload(signal: Signal, tenant_id: str, run_id: str = "") -> dict:
    """Serialize one digest-surviving Signal into a research-signal payload
    (SPEC Section 3.1 cerebro mapping table). Wire keys are snake_case; the
    payload validates against schemas/research-signal.schema.json."""
    fingerprint, basis = _fingerprint(signal)
    stem = signal.url_hash or fingerprint.split(":", 1)[1][:16]
    reason = (signal.meta.get("reason") or "").strip() or f"cerebro {signal.source} signal"
    simhash = signal.simhash or _simhash(f"{signal.title} {signal.clean_text}"[:1000])

    payload: dict = {
        "schemaVersion": 1,
        "id": f"sig-cerebro-{stem}",
        "tenant_id": tenant_id,
        "fingerprint": fingerprint,
        "fingerprint_basis": basis,
        "source": signal.source,
        "title": (signal.title or "").strip(),
        "category": signal.category or "misc",
        "score": float(signal.score or 0.0),
        "reason": reason,
        "captured_at": _captured_at(signal.captured),
        "simhash": str(simhash),
    }
    url = (signal.url or "").strip()
    if url:
        payload["url"] = url
    if signal.tags:
        payload["tags"] = list(signal.tags)
    if signal.clean_text:
        payload["excerpt"] = signal.clean_text[:4000]
    if run_id:
        payload["run_id"] = run_id
    return payload


def _cfg(settings) -> dict:
    return getattr(settings, "export", None) or {}


def _endpoint(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _post_batch(endpoint: str, token: str, payloads: list[dict]) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(endpoint, json=payloads, headers=headers, timeout=_POST_TIMEOUT)
    resp.raise_for_status()


def prefilter(signals: list[Signal], settings) -> list[Signal]:
    """Drop signals already in the autoresearch tried-ledger so they stop
    consuming triage tokens (SPEC 5.1). GET /api/v1/ledger/<fingerprint> per
    signal, timeout-bounded. FAIL-OPEN in every failure mode: disabled config,
    no url, unreachable service, or any non-200 keeps the signal, so cerebro
    never breaks because autoresearch is down."""
    cfg = _cfg(settings)
    url = cfg.get("autoresearch_url")
    if not cfg.get("enabled") or not url:
        return signals
    token = os.environ.get(cfg.get("token_env") or "") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    base = url.rstrip("/")

    out: list[Signal] = []
    dropped = 0
    for s in signals:
        fingerprint, _ = _fingerprint(s)
        try:
            resp = requests.get(
                _endpoint(base, f"/api/v1/ledger/{fingerprint}"),
                headers=headers, timeout=_LEDGER_TIMEOUT,
            )
        except Exception as e:  # noqa: BLE001: autoresearch down must never break cerebro
            print(f"[export] ledger pre-filter unreachable ({type(e).__name__}); keeping all")
            return signals
        if resp.status_code == 200:
            dropped += 1                     # already tried, skip triage
            continue
        out.append(s)                        # 404 or any other status → keep (fail-open)
    if dropped:
        print(f"[export] ledger pre-filter dropped {dropped} already-tried signal(s)")
    return out


def write(signals: list[Signal], settings, stats=None) -> dict:
    """After-vault signal-export sink. No-op unless export.enabled. Serializes
    each signal through the SPEC 3.1 mapping to export/signals-<run_id>.jsonl,
    then, when export.autoresearch_url is set, POSTs the batch (chunked at 500)
    with the Bearer token from the env var named by export.token_env. Fail-soft:
    an HTTP error is logged and the jsonl is kept. Never raises into the run."""
    cfg = _cfg(settings)
    if not cfg.get("enabled"):
        return {}

    tenant_id = cfg.get("tenant_id") or ""
    run_id = getattr(stats, "run_id", "") or ""
    payloads = [signal_to_payload(s, tenant_id, run_id) for s in signals]

    export_dir = pathlib.Path(os.path.expanduser(cfg.get("dir") or "export"))
    if not export_dir.is_absolute():
        export_dir = ROOT / export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    safe_run = re.sub(r"[^0-9A-Za-z._-]", "-", run_id) or "run"
    out_path = export_dir / f"signals-{safe_run}.jsonl"
    body = "\n".join(json.dumps(p, ensure_ascii=False) for p in payloads)
    out_path.write_text(body + ("\n" if payloads else ""))
    print(f"[export] wrote {len(payloads)} signal(s) -> {out_path}")

    result = {"jsonl": str(out_path), "n": len(payloads), "posted": 0}

    url = cfg.get("autoresearch_url")
    if not url or not payloads:
        return result
    if settings.dry_run:
        print("[export] dry-run: skipping POST (jsonl kept)")
        return result
    token = os.environ.get(cfg.get("token_env") or "") or ""
    if not token:
        print(f"[export] no token in env {cfg.get('token_env')!r}; skipping POST (jsonl kept)")
        return result

    endpoint = _endpoint(url, "/api/v1/signals")
    posted = 0
    for i in range(0, len(payloads), _MAX_BATCH):
        chunk = payloads[i:i + _MAX_BATCH]
        try:
            _post_batch(endpoint, token, chunk)
            posted += len(chunk)
        except Exception as e:  # noqa: BLE001: export must never abort the run
            print(f"[export] POST batch at {i} failed: {type(e).__name__}: {e} (jsonl kept)")
    result["posted"] = posted
    print(f"[export] posted {posted}/{len(payloads)} signal(s) -> {endpoint}")
    return result
