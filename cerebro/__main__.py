from __future__ import annotations

import argparse

from . import __version__


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="cerebro", description="Daily tech-signal pipeline → Obsidian"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="write to _scratch/, mute ntfy")
    ap.add_argument("--health", action="store_true",
                    help="print per-source yield/failure history and exit")
    ap.add_argument("--version", action="version", version=f"cerebro {__version__}")
    args = ap.parse_args()

    if args.health:
        from .state import State
        s = State()
        print(f"{'source':16}{'runs':>6}{'avg':>8}{'zero/fail':>11}   last_seen")
        for src, runs, avg, zf, last in s.source_summary():
            print(f"{src:16}{runs:>6}{avg:>8}{zf:>11}   {last}")
        s.close()
        return

    from .config import load
    from .orchestrator import run

    settings = load(dry_run_override=True if args.dry_run else None)
    st, paths = run(settings)
    total = st.input_tokens + st.output_tokens + st.cache_read + st.cache_creation
    print(
        f"\n✓ {st.raw} raw → {st.after_dedup} deduped → {st.after_triage} triaged → "
        f"{st.digested} in briefing  (dry_run={settings.dry_run}, x_ok={st.x_ok})"
    )
    print(
        f"  tokens: {total:,} total (in {st.input_tokens:,} · out {st.output_tokens:,} · "
        f"cache-read {st.cache_read:,} · cache-create {st.cache_creation:,}) · "
        f"{st.llm_calls} claude calls · ~${st.cost_usd:.2f} API-equiv"
    )
    print(f"  daily note: {paths['daily']}")


if __name__ == "__main__":
    main()
