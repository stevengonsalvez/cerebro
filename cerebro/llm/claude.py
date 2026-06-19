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


def run(prompt: str, model: str, meter: dict | None = None, timeout: int = 300) -> str:
    """One headless Claude Code call. No API key — uses Claude Code's own login.
    --output-format json so we can capture token usage; accumulates into `meter` if given.
    Note: each call carries Claude Code's own ~47k cached system context."""
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
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
