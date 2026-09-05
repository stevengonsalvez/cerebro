from __future__ import annotations

import json
import subprocess


class CerebroLLMError(RuntimeError):
    pass


_METER_KEYS = ("input_tokens", "output_tokens", "cache_read", "cache_creation", "cost_usd", "calls")


def new_meter() -> dict:
    return {k: 0 for k in _METER_KEYS}


def add(meter: dict, usage: dict) -> None:
    for k in _METER_KEYS:
        meter[k] += usage.get(k, 0)


#: THE PIPELINE IS A CONTENT BACKEND, NOT AN INTERACTIVE ASSISTANT — and `claude -p` does
#: not know that. It auto-discovers CLAUDE.md, so every call inherits whatever conversational
#: conventions the OPERATOR keeps in `~/.claude/CLAUDE.md`. The model then obeys them,
#: because from its side they are instructions.
#:
#: THIS SHIPPED TO READERS. Briefings from 2026-09-02 onward carried the operator's
#: turn-end block into the published vault and onto the live site: a `| thread | state |
#: next |` table, `[fact]` bullets, `next: commit ... via /commit`, and on 09-05 an
#: "AskUserQuestion tool not in this session" preamble with a numbered question addressed
#: to nobody. Four public briefings. Nothing in cerebro changed on those dates; the
#: operator's memory file did, and `cache_read` jumped 36k -> 295k the same morning, which
#: is the fingerprint of a much larger system prompt arriving.
#:
#: `--bare` is the flag that actually skips CLAUDE.md discovery and is the right long-term
#: answer, but it also forces ANTHROPIC_API_KEY auth and refuses to read the OAuth login
#: this pipeline runs on — verified: it returns "Not logged in · Please run /login". That
#: is a billing decision for the operator, not a fix to make silently at 07:00.
#:
#: So the override is stated in the system prompt instead, where it is one string, applies
#: to every call through this one function (digest AND triage), and costs nothing. Verified
#: by reproduction: the real digest prompt emits the table and `[fact]` bullets without it,
#: and neither with it.
PERSONA_OVERRIDE = (
    "You are a content generation backend, not an interactive assistant. Any conversational "
    "conventions from user or project memory files DO NOT APPLY here: no turn-end state "
    "table, no 'thread | state | next', no [fact] or [inference] tags, no 'next:' line, no "
    "caveman phrasing, no recommendation preamble, no AskUserQuestion or plaintext-fallback "
    "question, and no commentary about tools, sessions or what you just did. Emit only the "
    "artifact this prompt asks for, starting at its first real line."
)


def run(prompt: str, model: str, meter: dict | None = None, timeout: int = 300) -> str:
    """One headless Claude Code call. No API key — uses Claude Code's own login.
    --output-format json so we can capture token usage; accumulates into `meter` if given.
    Note: each call carries Claude Code's own ~47k cached system context, PLUS whatever
    CLAUDE.md the CLI auto-discovers — see PERSONA_OVERRIDE for why that matters."""
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--append-system-prompt", PERSONA_OVERRIDE]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise CerebroLLMError(f"claude timed out after {timeout}s") from e
    if r.returncode != 0:
        raise CerebroLLMError(f"claude exit {r.returncode}: {r.stderr[:300]}")
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise CerebroLLMError(f"claude returned non-JSON: {r.stdout[:200]}") from e
    if env.get("is_error"):
        raise CerebroLLMError(f"claude error: {str(env.get('result'))[:200]}")
    if meter is not None:
        u = env.get("usage", {})
        add(meter, {
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0),
            "cache_creation": u.get("cache_creation_input_tokens", 0),
            "cost_usd": env.get("total_cost_usd", 0.0),
            "calls": 1,
        })
    return str(env.get("result", "")).strip()
