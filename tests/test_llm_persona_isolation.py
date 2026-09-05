"""The pipeline runs through `claude -p`, which auto-discovers CLAUDE.md.

That is not a hypothetical. Briefings from 2026-09-02 to 2026-09-05 shipped the operator's
turn-end block into the public vault and onto the live site — a `| thread | state | next |`
table, `[fact]` bullets, a `next:` line, and one "AskUserQuestion tool not in this session"
preamble with a numbered question addressed to nobody. Nothing in cerebro changed on those
dates. `~/.claude/CLAUDE.md` did.

These tests pin the boundary, not the wording: every call through `claude.run` must carry
an override that tells the model it is a content backend rather than an assistant.
"""
from __future__ import annotations

from cerebro.llm import claude


def _cmd(monkeypatch) -> list[str]:
    """Capture the argv `run()` would execute, without spending a call."""
    seen: dict = {}

    class _R:
        returncode = 0
        stdout = '{"result": "ok", "usage": {}}'
        stderr = ""

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return _R()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    claude.run("some prompt", "sonnet")
    return seen["cmd"]


def test_every_call_carries_a_persona_override(monkeypatch):
    cmd = _cmd(monkeypatch)
    assert "--append-system-prompt" in cmd, (
        "without this the model inherits the operator's CLAUDE.md and publishes it"
    )
    assert cmd[cmd.index("--append-system-prompt") + 1] == claude.PERSONA_OVERRIDE


def test_the_override_names_the_artefacts_that_actually_leaked(monkeypatch):
    """Each string here was measured in a PUBLISHED briefing, not imagined."""
    o = claude.PERSONA_OVERRIDE.lower()
    for leaked in ("thread | state | next", "[fact]", "next:", "askuserquestion", "caveman"):
        assert leaked.lower() in o, f"the override must name {leaked!r}, which reached readers"


def test_the_override_is_not_silently_emptied(monkeypatch):
    """A blank or whitespace override would satisfy the flag check and fix nothing."""
    assert len(claude.PERSONA_OVERRIDE.strip()) > 200


def test_mcp_stays_isolated_too(monkeypatch):
    """The pre-existing isolation must survive this change."""
    cmd = _cmd(monkeypatch)
    assert "--strict-mcp-config" in cmd
    assert '{"mcpServers":{}}' in cmd
