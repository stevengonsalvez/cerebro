from __future__ import annotations

import re


def slug(value: str) -> str:
    value = value.strip().lower().replace("/", "--")
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "artifact"
