"""`notify.push_failure` — the alert for everything that breaks after the briefing
is written. `cerebro/sink/notify.py` had no test file at all before this one."""
from __future__ import annotations

from types import SimpleNamespace

from cerebro.sink import notify


def _settings(topic="cerebro-test-topic", dry_run=False):
    return SimpleNamespace(ntfy_topic=topic, dry_run=dry_run)


def test_push_failure_posts_the_message_to_the_configured_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    notify.push_failure("run.sh failed at line 42 (rc 1)", _settings())
    assert len(calls) == 1
    argv = calls[0][0][0]
    assert "https://ntfy.sh/cerebro-test-topic" in argv
    assert "Title: CEREBRO FAILED" in argv
    assert "run.sh failed at line 42 (rc 1)" in argv


def test_push_failure_is_a_noop_without_a_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append(a))
    notify.push_failure("boom", _settings(topic=""))
    assert calls == []


def test_push_failure_swallows_a_broken_curl(monkeypatch):
    def explode(*a, **k):
        raise OSError("curl: command not found")
    monkeypatch.setattr(notify.subprocess, "run", explode)
    notify.push_failure("boom", _settings())      # must not raise


def test_push_failure_still_alerts_in_dry_run(monkeypatch):
    """Deliberate divergence from push(): a run that dies is news either way."""
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append(a))
    notify.push_failure("boom", _settings(dry_run=True))
    assert len(calls) == 1


def test_push_failure_truncates_a_runaway_message(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append(a))
    notify.push_failure("x" * 5000, _settings())
    argv = calls[0][0]
    assert len(argv[argv.index("-d") + 1]) == 400


def test_push_is_still_muted_in_dry_run(monkeypatch):
    """Guard that adding push_failure did not change push()'s contract."""
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append(a))
    notify.push(SimpleNamespace(digested=3), "/tmp/x.md", _settings(dry_run=True))
    assert calls == []
