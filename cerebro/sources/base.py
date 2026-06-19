from __future__ import annotations

import datetime

import requests

UA = "cerebro/0.1 (+https://github.com/stevengonsalvez/cerebro)"
TIMEOUT = 20


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def http_get(url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", TIMEOUT)
    return requests.get(url, headers={"User-Agent": UA}, **kw)
