from __future__ import annotations

import tomllib
from pathlib import Path


def test_ui_static_assets_are_packaged() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text())

    assert "ui/static/*" in config["tool"]["setuptools"]["package-data"]["cerebro"]
