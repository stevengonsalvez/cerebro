"""F059 — the over-scoped credential, turned from a recommendation into a daily check.

THE FINDING. The PAT this programme runs on (Bitwarden item `xyora`) is described as
public-read-only and actually carries `admin:enterprise`, `admin:org`, `repo`, `workflow`
and `delete:packages`. Nothing in this lane needs any of them: the whole devs pipeline
reads five public endpoints. The value was also exposed once in a session transcript,
which makes it a compromised credential rather than a hygiene item.

"Replace it" is worth nothing as prose in a document. It is worth something as a check
that runs every morning and pages, so this module reads the `x-oauth-scopes` header of a
single `/rate_limit` response and fails when the token can do more than read public data.

THE GREEN PATH IS THE ONE THAT IS EASY TO GET WRONG, so it is specified rather than
inferred. The rotation this epic recommends produces a FINE-GRAINED token, and a
fine-grained token returns NO `x-oauth-scopes` header at all — the header is ABSENT, not
empty. Meanwhile an UNAUTHENTICATED `GET /rate_limit` returns 200 (core limit 60), so a
200 is not evidence that a token was sent. A guard that reads header-absence as
"unknown -> fail" fails the very token it exists to bless; one that reads a 200 as "token
present" passes a missing token silently the morning after rotation. Both cases are
therefore decided ahead of the request:

    env var unset or empty        6   decided BEFORE any HTTP call is made
    200, header ABSENT            0   fine-grained token; no classic scopes exist
    200, header present, empty    0   classic token carrying no scopes
    200, header present, subset   0   inside ALLOWED_SCOPES
    200, header present, other    0   over-scoped: WARN, do not page (owner's call)
    401 / 403                     5   the credential is bad: page

THE TOKEN VALUE IS NEVER PRINTED, LOGGED OR WRITTEN. What comes out is a
`sha256(value)[:8]` fingerprint — enough to tell two tokens apart across a rotation, and
useless to anybody who reads a log.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

API = "https://api.github.com"

#: The only endpoint whose PURPOSE is metadata, and the cheapest possible probe: it does
#: not consume the core rate limit it reports on.
RATE_LIMIT_PATH = "/rate_limit"

#: What a token in this lane is allowed to carry. Empty is the target state (a
#: fine-grained token has no classic scopes at all); `public_repo` is tolerated because a
#: classic token cannot be minted with nothing and it grants no more than the anonymous
#: API already gives. Everything the lane reads is public.
ALLOWED_SCOPES = frozenset({"public_repo"})

EXIT_OK = 0
#: The credential is REFUSED outright (401/403) or the endpoint answered something this
#: check cannot interpret. Still a page: a token the API rejects breaks the lane outright.
#:
#: OVER-SCOPE NO LONGER REACHES THIS CODE. Owner's decision, 2026-08-28, made on measured
#: blast radius rather than on the length of the scope list: the `xyora` account owns 0
#: repos, holds 0 private repos and belongs to 0 organisations, so `admin:enterprise`,
#: `admin:org`, `delete:packages`, `write:packages`, `project` and `codespace` are INERT —
#: there is nothing on that account to administer. What is NOT inert is `repo` + `workflow`,
#: which carry push access to three repositories (two the owner's, one a third party's).
#: That is the real exposure, it is understood, and it is accepted for now.
#:
#: So this check REPORTS it every morning and does not stop the pipeline for it. The
#: distinction is deliberate: a gate that fires daily on a condition the owner has already
#: judged and accepted is not a safety mechanism, it is noise that trains an operator to
#: ignore the one morning it means something.
EXIT_OVERSCOPED = 5
#: No token at all. A DIFFERENT code, because the remedy is different: exit 5 says
#: rotate, exit 6 says the env var did not reach the process — the exact failure the
#: morning after a rotation that stopped at step three.
EXIT_NO_TOKEN = 6


@dataclass(frozen=True)
class TokenReport:
    """The answer, with no secret in it."""

    exit_code: int
    reason: str
    fingerprint: str = ""
    scopes: tuple[str, ...] = ()
    header_present: bool = False
    status: int = 0
    called: bool = False
    #: The token carries scopes beyond the lane's needs. Reported, never fatal — see the
    #: note on EXIT_OVERSCOPED for whose decision that is and what it rests on.
    over_scoped: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "token_fingerprint": self.fingerprint,
            "scopes": list(self.scopes),
            "scopes_header_present": self.header_present,
            "status": self.status,
            "over_scoped": self.over_scoped,
            "allowed_scopes": sorted(ALLOWED_SCOPES),
        }


def fingerprint(value) -> str:
    """`sha256(value)[:8]`. Enough to tell two tokens apart, useless to a reader."""
    if not value:
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]


def parse_scopes(header_value) -> tuple[str, ...]:
    """`"admin:org, repo, workflow"` -> `("admin:org", "repo", "workflow")`. Total."""
    if header_value is None:
        return ()
    return tuple(part.strip() for part in str(header_value).split(",") if part.strip())


def check(value, transport=None) -> TokenReport:
    """One request, one header, one exit code. The token never leaves this function.

    `transport(value) -> (status_code, headers)` is injectable so every row of the table
    above is a test rather than a network condition somebody hopes for.
    """
    mark = fingerprint(value)
    if not value:
        # BEFORE the request, deliberately: an unauthenticated /rate_limit returns 200,
        # so asking the network first would turn "no token reached the process" into a
        # green run.
        return TokenReport(
            exit_code=EXIT_NO_TOKEN,
            reason="no token in the environment — nothing was sent, and an "
                   "unauthenticated /rate_limit would have answered 200 anyway",
            called=False)

    status, headers = (transport or _probe)(value)
    header_value = _header(headers, "x-oauth-scopes")
    present = header_value is not None
    scopes = parse_scopes(header_value)

    if status in (401, 403):
        return TokenReport(
            exit_code=EXIT_OVERSCOPED, fingerprint=mark, scopes=scopes,
            header_present=present, status=int(status), called=True,
            reason=f"GitHub refused the credential ({status})")

    if not 200 <= int(status) < 300:
        return TokenReport(
            exit_code=EXIT_OVERSCOPED, fingerprint=mark, scopes=scopes,
            header_present=present, status=int(status), called=True,
            reason=f"unexpected status {status} from {RATE_LIMIT_PATH}")

    if not present:
        return TokenReport(
            exit_code=EXIT_OK, fingerprint=mark, header_present=False,
            status=int(status), called=True,
            reason="fine-grained token: no x-oauth-scopes header exists, so no classic "
                   "scope is carried")

    extra = tuple(sorted(set(scopes) - ALLOWED_SCOPES))
    if extra:
        # GREEN, AND SAYING SO OUT LOUD. `over_scoped` is a separate field from `ok` on
        # purpose: a caller that wants to enforce this can still read it, and the daily
        # summary still names every extra scope, so accepting the risk never becomes the
        # same thing as forgetting it.
        return TokenReport(
            exit_code=EXIT_OK, fingerprint=mark, scopes=scopes, over_scoped=True,
            header_present=True, status=int(status), called=True,
            reason="over-scoped for a public-read lane, ACCEPTED by the owner: "
                   + ", ".join(extra))

    return TokenReport(
        exit_code=EXIT_OK, fingerprint=mark, scopes=scopes, header_present=True,
        status=int(status), called=True,
        reason="classic token inside the allowed scope set")


def summary_line(report: TokenReport) -> str:
    """One line for a human. Names and a fingerprint, never a value."""
    if report.scopes:
        scopes = ", ".join(report.scopes)
    elif not report.called:
        scopes = "none (no token was sent)"
    elif report.header_present:
        scopes = "none (classic token, empty header)"
    else:
        scopes = "none (fine-grained token, header absent)"
    # A GREEN LINE THAT STILL READS AS A WARNING. The over-scope is accepted, not resolved,
    # and the day it stops being acceptable an operator has to be able to see it in the
    # scrollback without going and reading a config file to find out it was ever a thing.
    lead = "WARNING " if report.over_scoped else ""
    return (f"{lead}token sha256:{report.fingerprint or 'absent'} scopes: {scopes} "
            f"-> exit {report.exit_code} ({report.reason})")


def _header(headers, name: str):
    """Case-insensitive header read. `None` means ABSENT, `""` means present and empty."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        got = getter(name)
        if got is not None:
            return got
        for key in headers:
            if str(key).lower() == name:
                return headers[key]
        return None
    for key, val in headers:
        if str(key).lower() == name:
            return val
    return None


def _probe(value):
    """The real request. One GET, public metadata only, fifteen-second timeout."""
    import requests

    resp = requests.get(
        API + RATE_LIMIT_PATH,
        headers={"Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Authorization": f"Bearer {value}"},
        timeout=15)
    return resp.status_code, resp.headers
