from __future__ import annotations

import argparse

from . import __version__


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="cerebro", description="Daily tech-signal pipeline → Obsidian"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="write to _scratch/, mute ntfy")
    ap.add_argument("--source", help="run a single source (debug)")
    ap.add_argument("--version", action="version", version=f"cerebro {__version__}")
    args = ap.parse_args()

    # imports after arg-parse so --help/--version work without config present
    from .config import load
    from .state import State

    settings = load(dry_run_override=True if args.dry_run else None)
    state = State()
    enabled = [k for k, v in settings.sources.items() if v.get("enabled")]
    print(
        f"cerebro ready · dry_run={settings.dry_run} · vault={settings.vault_path} "
        f"· sources={enabled}"
    )
    # orchestrator is wired in Phase 7
    state.close()


if __name__ == "__main__":
    main()
