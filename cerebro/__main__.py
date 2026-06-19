from __future__ import annotations

import argparse

from . import __version__


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="cerebro", description="Daily tech-signal pipeline → Obsidian"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="write to _scratch/, mute ntfy")
    ap.add_argument("--version", action="version", version=f"cerebro {__version__}")
    args = ap.parse_args()

    from .config import load
    from .orchestrator import run

    settings = load(dry_run_override=True if args.dry_run else None)
    st, paths = run(settings)
    print(
        f"\n✓ {st.raw} raw → {st.after_dedup} deduped → {st.after_triage} triaged → "
        f"{st.digested} in briefing  (dry_run={settings.dry_run}, x_ok={st.x_ok})"
    )
    print(f"  daily note: {paths['daily']}")


if __name__ == "__main__":
    main()
