from __future__ import annotations

from pathlib import Path


def read_watchlist(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    body = p.read_text(errors="replace")
    if body.startswith("---"):
        parts = body.split("---", 2)
        body = parts[2] if len(parts) == 3 else body
    queries = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                queries.append(item)
    return queries


def read_vault_watchlists(vault_path: Path) -> dict[str, list[str]]:
    root = vault_path / "Watchlist"
    return {
        "git-search": read_watchlist(root / "git-search.md"),
        "cracked-devs": read_watchlist(root / "cracked-devs.md"),
    }
