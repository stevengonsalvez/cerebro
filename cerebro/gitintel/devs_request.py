"""Self-requests to join the tracked roster, from a GitHub issue to a roster entry.

THE ONLY THING THAT CROSSES FROM THE ISSUE INTO THE FILE IS A LOGIN, AND IT IS VALIDATED
FIRST. Everything else is either derived from GitHub's own public account data or is a fixed
machine string. That is deliberate rather than minimal: the issue is filed by anyone on the
internet, `config/cracked_devs.yaml` is a tracked file in a public repo, and the roster's
`name` reaches a rendered page. A free-text field from a stranger that ends up as copy about
a named person is the one shape this section must not have, so there is no such field.

SELF-NOMINATION ONLY. The issue author must be the account being requested. There is no
cheap way to verify that somebody speaks for a third party, and "add this person" from an
unrelated account is a request to publish a page about someone who never asked. `github`
gives the author's login reliably, so this is one comparison and it is not negotiable.

WHAT BEING ACCEPTED ACTUALLY MEANS, because the issue form has to say it honestly: a roster
entry makes the login a pool candidate. It does NOT create a page. `pool.roster_lane` emits
no signal hashes, so a login the vault lane has never produced still fails the provenance
floor — a profile appears when CEREBRO has kept a signal about a repository they own or push
to, and not before. See pool.roster_lane's docstring.

TIER 3 IS LOAD-BEARING. `wiring.max_tier` is 2, and `roster.active()` filters on it, so a
tier-3 entry is never wired into `sources.x.accounts` or `sources.rss.feeds`. Asking to be
tracked is not the same as asking for your blog to be ingested, and `roster_lane` reads the
unfiltered list, so the pool still sees them.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import re
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ROSTER_PATH = ROOT / "config" / "cracked_devs.yaml"

#: GitHub's own login rule: alphanumerics and single inner hyphens, 39 max. Anchored, so a
#: login carrying a quote, a newline or a YAML metacharacter cannot reach the file at all —
#: which is why the writer below can use a plain literal without escaping gymnastics.
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

#: GitHub renders an untouched optional field as this exact string.
NO_RESPONSE = "_no response_"

#: The heading an issue form writes above the handle field. Matched case-insensitively on
#: the label text, so re-wording the form's `description` does not break the parser.
HANDLE_LABEL = "github handle"


class RequestError(Exception):
    """A request that must not become a roster entry, with the reason to post back."""


@dataclass(frozen=True)
class Request:
    login: str
    name: str
    issue: int


def parse_handle(body: str) -> str:
    """The handle out of a GitHub issue-form body, or raise.

    Issue forms render as `### <label>` followed by the value. Nothing else in the body is
    read: the form's free-text field exists for a human to read on the issue, and giving it
    a route into a tracked file is the thing this module refuses to do.
    """
    section: list[str] | None = None
    for line in (body or "").splitlines():
        if line.startswith("###"):
            if section is not None:
                break
            if line.lstrip("#").strip().lower().startswith(HANDLE_LABEL):
                section = []
            continue
        if section is not None:
            section.append(line)
    value = "\n".join(section or []).strip()
    if not value or value.lower() == NO_RESPONSE:
        raise RequestError("the GitHub handle field was empty.")
    # A handle, not a URL and not an @mention. Tolerating those forms is friendlier than
    # bouncing somebody for a leading @, and the regex below still decides what is legal.
    value = value.strip().lstrip("@").rstrip("/")
    value = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", value, flags=re.I)
    if not LOGIN_RE.match(value):
        raise RequestError(
            f"`{value[:60]}` is not a GitHub login. Put just the handle in that field, "
            "for example `octocat`."
        )
    return value


def validate(
    *,
    login: str,
    author: str,
    issue: int,
    roster_logins: set[str],
    denied: set[str],
    opted_out: set[str],
    probe,
) -> Request:
    """Everything that must be true before a login may be written, or raise.

    `probe(login)` returns GitHub's public account JSON, or None when there is no such
    account. Injected rather than called directly so the rules can be tested without a
    network, and so the caller owns the token and the rate limit.
    """
    lower = login.lower()
    if lower != (author or "").strip().lower():
        raise RequestError(
            "this flow is self-nomination only — the account asking has to be the account "
            "being added. If you are asking on somebody else's behalf, they can open the "
            "request themselves."
        )
    if lower in {o.lower() for o in opted_out}:
        raise RequestError(
            "this account has asked not to be listed. Removing that request is a change "
            "only the owner makes, so this needs a human."
        )
    if lower in {d.lower() for d in denied}:
        raise RequestError("this account is on the exclusion list, which a human reviews.")
    if lower in {r.lower() for r in roster_logins}:
        raise RequestError("this account is already on the roster.")
    account = probe(login)
    if account is None:
        raise RequestError(f"GitHub has no public account called `{login}`.")
    if str(account.get("type") or "") != "User":
        raise RequestError(
            "only user accounts are tracked — this login is "
            f"{str(account.get('type') or 'not a user').lower()}."
        )
    # GitHub's own public display name, never a field from the issue. Falls back to the
    # login, which is public by definition and safe to render.
    name = str(account.get("name") or "").strip() or login
    return Request(login=login, name=name, issue=issue)


def roster_entry(req: Request, *, today: str | None = None) -> str:
    """The YAML block to append, exactly as it will appear in the file.

    A plain literal is safe because `LOGIN_RE` already excluded every character that means
    anything to YAML, and `name` is quoted with its own quotes stripped for the same reason.
    """
    day = today or _dt.date.today().isoformat()
    name = re.sub(r'["\n\r\\]', "", req.name)[:80]
    return (
        f"\n  # Self-requested in #{req.issue}. Tier 3: a pool candidate, deliberately above\n"
        f"  # wiring.max_tier so nothing here is wired into the ingestion sources.\n"
        f"  - name: \"{name}\"\n"
        f"    tier: 3\n"
        f"    x: null\n"
        f"    github: {req.login}\n"
        f"    blog: null\n"
        f"    blog_feed: null\n"
        f"    reddit: null\n"
        f"    tags: []\n"
        f"    why: \"Asked to be tracked in #{req.issue}\"\n"
        f"    added: \"{day}\"\n"
        f"    discovered_via: request\n"
    )


def append_to_roster(entry: str, path: pathlib.Path | None = None) -> pathlib.Path:
    """Append one entry to the roster file.

    APPEND, NEVER RE-SERIALISE. Loading the YAML and dumping it back would rewrite all 113
    lines, drop every comment and re-quote every string — a diff nobody can review for a
    change that adds twelve lines. `devs:` is the last top-level key, so the end of the file
    is the end of that list.
    """
    p = path or ROSTER_PATH
    text = p.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + entry, encoding="utf-8")
    return p


# ——— the entry point the workflow calls ———


def _probe(login: str):
    """GitHub's public account record for `login`, or None. Public read, no scopes needed."""
    import os

    import requests

    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://api.github.com/users/{login}", headers=headers, timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def main(argv=None) -> int:
    """Read the issue out of the environment, decide, and say what happened on stdout.

    THE ISSUE NEVER TOUCHES A SHELL. Body, author and number arrive as environment
    variables, not as workflow-expression interpolation into a `run:` block, because the
    body is written by anyone on the internet and `${{ }}` inside a shell script is a
    command-injection hole rather than a style choice.

    Exit 0 means an entry was appended and the caller should open the PR. Exit 2 means the
    request was refused for a stated reason and the caller should post it back. Exit 1 is
    reserved for the flow itself breaking, which is not the requester's problem.
    """
    import json
    import os

    from . import denylist, optout
    from .roster import load_roster

    # An override seam, for the same reason lib/vault/paths.ts has one on the site side: a
    # test of this function must never be one typo away from appending to the real roster.
    roster = pathlib.Path(os.environ["CEREBRO_ROSTER"]) if os.environ.get("CEREBRO_ROSTER") else ROSTER_PATH

    out: dict[str, str] = {}
    try:
        login = parse_handle(os.environ.get("ISSUE_BODY", ""))
        devs, _ = load_roster(roster)
        req = validate(
            login=login,
            author=os.environ.get("ISSUE_AUTHOR", ""),
            issue=int(os.environ.get("ISSUE_NUMBER") or 0),
            roster_logins={d.github for d in devs if d.github},
            denied=set(denylist.load().denied),
            opted_out=set(optout.load().logins),
            probe=_probe,
        )
    except RequestError as exc:
        out = {"status": "refused", "reason": str(exc)}
        print(json.dumps(out))
        _write_github_output(out)
        return 2

    append_to_roster(roster_entry(req), roster)
    out = {"status": "added", "login": req.login, "name": req.name, "issue": str(req.issue)}
    print(json.dumps(out))
    _write_github_output(out)
    return 0


def _write_github_output(values: dict) -> None:
    """Publish the decision as workflow outputs, when running inside Actions.

    Values are written with a random heredoc delimiter rather than `k=v`: a refusal reason
    can contain a newline, and a `k=v` line that does is how untrusted text becomes an extra
    output somebody else's step trusts.
    """
    import os
    import secrets

    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in values.items():
            delim = f"ghadelim_{secrets.token_hex(8)}"
            fh.write(f"{k}<<{delim}\n{v}\n{delim}\n")


if __name__ == "__main__":  # pragma: no cover — exercised by the workflow
    raise SystemExit(main())
