from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Signal

_TRACK = re.compile(r"^(utm_|ref$|fbclid|gclid|mc_|igshid|si$)")
_WORD = re.compile(r"\w+")


def canonical(url: str) -> str:
    """Strip tracking params, lowercase host, drop fragment + trailing slash."""
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    q = [(k, v) for k, v in parse_qsl(p.query) if not _TRACK.match(k)]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(q), ""))


def simhash(text: str) -> int:
    """63-bit simhash over word tokens — near-dup detection across sources.
    63 not 64 bits so it fits SQLite's signed-INTEGER column."""
    bits = [0] * 63
    for tok in _WORD.findall(text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        for i in range(63):
            bits[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(63) if bits[i] > 0)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dedupe(signals: list[Signal], state=None, dedup_days: int = 14, threshold: int = 3) -> list[Signal]:
    """Drop same-run dups (url-hash + simhash Hamming<=threshold) and anything seen
    in the last `dedup_days` (via state). Sets canonical_url/url_hash/simhash on keepers."""
    seen_sim: list[int] = state.recent_simhashes(dedup_days) if state else []
    seen_hash: set[str] = set()
    out: list[Signal] = []
    for s in signals:
        s.canonical_url = canonical(s.url)
        s.url_hash = hashlib.sha256(s.canonical_url.encode()).hexdigest()[:16]
        s.simhash = simhash(f"{s.title} {s.clean_text}"[:1000])
        if s.url_hash in seen_hash:
            continue
        if state and state.seen_recent(s.url_hash, dedup_days):
            continue
        if any(_hamming(s.simhash, o) <= threshold for o in seen_sim):
            continue
        seen_hash.add(s.url_hash)
        seen_sim.append(s.simhash)
        out.append(s)
    return out


if __name__ == "__main__":  # ponytail: smallest runnable check for canonical + near-dup
    assert canonical("https://A.com/x/?utm_source=z&id=1#frag") == "https://a.com/x?id=1"
    a = Signal(url="https://x.com/p?utm_source=t", title="GLM 5.2 passes the vibe check", source="rss")
    b = Signal(url="https://x.com/p", title="GLM 5.2 passes the vibe check!!", source="hn")  # near-dup
    c = Signal(url="https://y.com/q", title="totally unrelated terminal tui release", source="hn")
    kept = dedupe([a, b, c])
    assert len(kept) == 2, [s.title for s in kept]   # b collapses into a; c survives
    print("dedup self-check OK")
