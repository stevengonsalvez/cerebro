from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def _load_dotenv() -> None:
    """Tiny no-dep .env loader: KEY=VALUE lines from repo-root .env into os.environ
    (shell env wins). Lets secrets ride in a gitignored .env (kept in Bitwarden) so
    the pipeline is portable to another machine."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass
class Settings:
    vault_path: pathlib.Path
    dry_run: bool
    depth: dict
    dedup_days: int
    prerank_keep: int
    models: dict
    ntfy_topic: str
    schedule: dict
    github: dict
    sources: dict
    matrix: dict
    # Opt-in autoresearch signal-export sink; off by default so standalone
    # cerebro users are untouched (autoresearch SPEC 3.1 / 5.1).
    export: dict = field(default_factory=lambda: {"enabled": False})


def _load(name: str) -> dict:
    p = CONFIG / name
    if not p.exists():
        raise FileNotFoundError(
            f"missing config: {p} — copy settings.example.yaml to settings.yaml"
        )
    return yaml.safe_load(p.read_text()) or {}


def load(dry_run_override: bool | None = None, allow_example: bool = False) -> Settings:
    try:
        s = _load("settings.yaml")
    except FileNotFoundError:
        if not allow_example:
            raise
        s = _load("settings.example.yaml")
    dry = s.get("dry_run", True)
    if dry_run_override is not None:
        dry = dry_run_override
    vp = pathlib.Path(os.path.expanduser(os.environ.get("CEREBRO_VAULT") or s["vault_path"]))
    if not vp.is_absolute():               # relative paths (e.g. ./vault submodule) anchor to repo root
        vp = ROOT / vp
    return Settings(
        vault_path=vp,
        dry_run=dry,
        depth=s.get("depth", {"min": 15, "max": 25, "score_threshold": 0.5}),
        dedup_days=s.get("dedup_days", 14),
        prerank_keep=s.get("prerank_keep", 180),
        models=s.get("models", {"triage": "haiku", "digest": "sonnet"}),
        ntfy_topic=os.environ.get("NTFY_TOPIC") or s.get("ntfy", {}).get("topic", ""),
        schedule=s.get("schedule", {"hour": 7, "minute": 0}),
        github=s.get("github", {
            "token_env": "GITHUB_TOKEN",
            "cache_path": "cerebro-gitintel.sqlite",
            "cache_ttl_hours": 24,
            "request_timeout_seconds": 20,
            "max_enrich": 8,
        }),
        sources=_load("sources.yaml"),
        matrix=_load("interest-matrix.yaml"),
        export=s.get("export", {"enabled": False}),
    )
