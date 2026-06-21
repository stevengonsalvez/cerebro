from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


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
    sources: dict
    matrix: dict


def _load(name: str) -> dict:
    p = CONFIG / name
    if not p.exists():
        raise FileNotFoundError(
            f"missing config: {p} — copy settings.example.yaml to settings.yaml"
        )
    return yaml.safe_load(p.read_text()) or {}


def load(dry_run_override: bool | None = None) -> Settings:
    s = _load("settings.yaml")
    dry = s.get("dry_run", True)
    if dry_run_override is not None:
        dry = dry_run_override
    return Settings(
        vault_path=pathlib.Path(os.path.expanduser(s["vault_path"])),
        dry_run=dry,
        depth=s.get("depth", {"min": 15, "max": 25, "score_threshold": 0.5}),
        dedup_days=s.get("dedup_days", 14),
        prerank_keep=s.get("prerank_keep", 180),
        models=s.get("models", {"triage": "haiku", "digest": "sonnet"}),
        ntfy_topic=s.get("ntfy", {}).get("topic", ""),
        schedule=s.get("schedule", {"hour": 7, "minute": 0}),
        sources=_load("sources.yaml"),
        matrix=_load("interest-matrix.yaml"),
    )
