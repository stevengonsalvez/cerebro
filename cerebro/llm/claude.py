from __future__ import annotations

import subprocess


class CerebroLLMError(RuntimeError):
    pass


# Skip the user's MCP servers — ~halves Claude Code's headless startup (34s → 16s).
_BASE = ["claude", "-p", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']


def run(prompt: str, model: str, timeout: int = 300) -> str:
    """One headless Claude Code call. No API key — uses Claude Code's own login.
    Prompt passed as argv (well under ARG_MAX even for an 80-item batch)."""
    cmd = ["claude", "-p", prompt, "--model", model,
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise CerebroLLMError(f"claude timed out after {timeout}s") from e
    if r.returncode != 0:
        raise CerebroLLMError(f"claude exit {r.returncode}: {r.stderr[:300]}")
    return r.stdout.strip()
