"""T07 — F053: the public-read boundary, asserted so it stays true as lanes are added.

WHY THIS FILE EXISTS IN e02 SPECIFICALLY. F053's SHIP condition is that the boundary
"ships as an asserted boundary so it stays true as lanes are added", and e02 is the epic
that adds a lane. The xyora token carries `admin:enterprise`, `admin:org`, `repo`,
`workflow` and `delete:packages`. NOTHING in the devs lane needs any of that, and the
charter makes using a non-public-read endpoint with it a STOP condition. A code review
cannot hold that line across future edits; a build failure can.

Four properties, checked over every devs-lane module by AST rather than by grep:

  1. every API-shaped string literal matches the allowlist of public read paths,
  2. no module reaches for a mutating HTTP verb,
  3. no module reads an env var except through `resolve_token`,
  4. no module logs, prints or formats the token value.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cerebro.gitintel.fanout import PUBLIC_READ_PATHS

#: Every module the devs lane runs. A new lane module MUST be added here — the sweep is
#: extended, never narrowed, and a module missing from this list is unguarded.
DEVS_LANE_MODULES = [
    "cerebro/gitintel/fanout.py",
    "cerebro/gitintel/pool.py",
    "cerebro/gitintel/fork_provenance.py",
    "cerebro/gitintel/facets.py",
    "cerebro/gitintel/devs_spike.py",
    "cerebro/gitintel/admission.py",
    "cerebro/gitintel/shape.py",
    "cerebro/gitintel/vault_seed.py",
    "cerebro/gitintel/denylist.py",
    "cerebro/gitintel/owner_resolve.py",
    "cerebro/gitintel/gharchive.py",
    # e03's three. EXTENDED, NEVER NARROWED. `repo_facts.py` is the one that matters
    # here: it is the epic that adds a REST path, and `/users/{login}/repos` had to enter
    # `fanout.PUBLIC_READ_PATHS` in the same diff as the call that needed it.
    "cerebro/gitintel/optout.py",
    "cerebro/gitintel/repo_facts.py",
    "cerebro/sink/devs.py",
    # e06. EXTENDED, NEVER NARROWED. `growth.py` reaches no endpoint at all, and that is
    # a property worth pinning: a growth reader that started making REST calls would be
    # spending quota on a number nobody may display yet.
    "cerebro/gitintel/growth.py",
    "cerebro/gitintel/portfolio.py",
    # `contract.py` posts SQL to the anonymous ClickHouse endpoint and `token_check.py` is
    # the one module that holds a credential on purpose. Both are swept for exactly that
    # reason: the module nobody thought needed guarding is where the next widening lands.
    "cerebro/gitintel/contract.py",
    "cerebro/gitintel/token_check.py",
]

#: The allowlist, as regexes over a formatted path. Sourced from `fanout.PUBLIC_READ_PATHS`
#: so the code and the test cannot drift: adding a path to the module is a deliberate,
#: reviewable edit that shows up in the diff beside the call that needs it.
_ALLOWED = tuple(
    re.compile("^" + re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", re.escape(t)) + "$")
    for t in PUBLIC_READ_PATHS
)

#: A string literal that looks like a GitHub API path. `/users/x`, `/repos/a/b`. Plain
#: prose and file paths are excluded by requiring a known first segment.
_API_SHAPED = re.compile(r"^/(users|repos|orgs|user|search|installation|app|admin|enterprises|teams|notifications|gists)(/|$)")

MUTATING = {"post", "put", "patch", "delete", "head_"}


def _tree(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def _api_literals(path):
    """Every API-shaped string constant in the module, with `{placeholders}` normalised.

    An f-string's own Constant children are skipped: `f"/repos/{o}/{r}"` must be checked
    as the whole path, not as the fragment `/repos/` — which would fail the allowlist and
    hide the real check behind a spurious failure.
    """
    tree = _tree(path)
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for piece in node.values:
                inside_fstring.add(id(piece))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in inside_fstring:
                continue
            v = node.value
            if _API_SHAPED.match(v):
                out.append(v)
        elif isinstance(node, ast.JoinedStr):
            # An f-string path: rebuild it with a placeholder per interpolation so
            # `f"/repos/{owner}/{repo}"` is checked as `/repos/{owner}/{repo}`.
            parts = []
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    parts.append(piece.value)
                else:
                    parts.append("{x}")
            joined = "".join(parts)
            if _API_SHAPED.match(joined):
                out.append(joined)
    return out


def _matches_allowlist(literal: str) -> bool:
    concrete = re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "PLACEHOLDER", literal)
    return any(rx.match(concrete) for rx in _ALLOWED)


@pytest.mark.parametrize("path", DEVS_LANE_MODULES)
def test_every_api_path_in_the_lane_is_on_the_public_read_allowlist(path):
    """A path not on the list is either a mistake or a deliberate widening. Either way it
    must show up in a diff beside the reason for it, not arrive silently."""
    for literal in _api_literals(path):
        assert _matches_allowlist(literal), (
            f"{path}: {literal!r} is not on PUBLIC_READ_PATHS. The xyora token carries "
            f"admin:org and repo scope; using it off the allowlist is a charter STOP "
            f"condition.")


@pytest.mark.parametrize("path", DEVS_LANE_MODULES)
def test_no_lane_module_reaches_for_a_mutating_http_verb(path):
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Attribute) and node.attr.lower() in MUTATING:
            src = getattr(node.value, "id", "")
            assert src not in ("requests", "session", "client", "http"), \
                f"{path}: {src}.{node.attr} — the devs lane is read-only"
        if isinstance(node, ast.Call):
            fn = node.func
            name = (fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")).lower()
            assert name not in {"post", "put", "patch", "delete"} or path.endswith(
                "gharchive.py"), f"{path}: calls {name}()"


#: The ONLY env vars a lane module may read for itself, each named with why it is not a
#: credential. EXTENDED, NEVER WIDENED INTO A PATTERN: the entry is a literal name, so a
#: module reading `os.environ.get(some_variable)` is still a build failure, and the
#: credential-shaped names below are still unreachable.
#:
#:   CEREBRO_GHARCHIVE_ENDPOINT   a URL for the anonymous, tokenless ClickHouse endpoint.
#:                                It exists so a REAL transport outage can be induced from
#:                                a shell (V8), because a degradation path only ever
#:                                reached by monkeypatch is a path nobody has tested.
ALLOWED_ENV_NAMES = frozenset({"CEREBRO_GHARCHIVE_ENDPOINT"})


def _env_name_read(node):
    """The literal env name an `os.environ.get(...)`/`os.environ[...]` reads, or None.

    None means "not a plain literal read", which is exactly the case this test refuses to
    let through: a computed env name cannot be audited from the diff.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and isinstance(node.func.value, ast.Attribute) \
            and node.func.value.attr == "environ":
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "environ":
        idx = node.slice
        if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
            return idx.value
    return None


@pytest.mark.parametrize("path", DEVS_LANE_MODULES)
def test_no_lane_module_reads_an_env_var_directly(path):
    """Token resolution lives in ONE place (`github_client.resolve_token`) so there is one
    thing to audit. A module reading `os.environ` for itself is a second, unaudited path
    to a credential.

    NARROWED, NOT WEAKENED, in e06: exactly one literal name is allowed
    (`ALLOWED_ENV_NAMES`), it is a URL for a tokenless endpoint, and every other read —
    including any computed name — still fails. `test_the_env_allowlist_still_rejects_a
    _credential_shaped_read` below is the negative control that proves it.
    """
    tree = _tree(path)
    allowed_nodes: set[int] = set()
    for node in ast.walk(tree):
        name = _env_name_read(node)
        if name is None:
            continue
        assert name in ALLOWED_ENV_NAMES, \
            f"{path}: reads os.environ[{name!r}] directly"
        allowed_nodes.update(id(sub) for sub in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            assert id(node) in allowed_nodes, f"{path}: reads os.environ directly"
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in ("getenv",):
                raise AssertionError(f"{path}: calls getenv directly")


def test_the_env_allowlist_names_one_url_and_no_credential():
    """A one-entry allowlist is auditable; a pattern is not."""
    assert ALLOWED_ENV_NAMES == {"CEREBRO_GHARCHIVE_ENDPOINT"}
    for name in ALLOWED_ENV_NAMES:
        assert "TOKEN" not in name.upper() and "SECRET" not in name.upper()
        assert "KEY" not in name.upper() and "PASS" not in name.upper()


@pytest.mark.parametrize("source", [
    "import os\nX = os.environ.get('GITHUB_TOKEN')\n",
    "import os\nX = os.environ['GITHUB_TOKEN_XYORA']\n",
    "import os\nX = os.environ.get(name)\n",
    "import os\nX = os.getenv('GITHUB_TOKEN')\n",
])
def test_the_env_allowlist_still_rejects_a_credential_shaped_read(source, tmp_path):
    """THE NEGATIVE CONTROL FOR THE NARROWING. Each of these is what the rule exists to
    stop, and each must still fail after the allowlist landed."""
    module = tmp_path / "lane.py"
    module.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        test_no_lane_module_reads_an_env_var_directly(str(module))


@pytest.mark.parametrize("path", DEVS_LANE_MODULES)
def test_no_lane_module_logs_prints_or_formats_the_token(path):
    """The charter's hardest line: never print a token. A `log.info(f"...{token}")` is how
    a credential reaches a run log that is then pasted into a PR."""
    src = Path(path).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for piece in node.values:
            if isinstance(piece, ast.FormattedValue):
                names = {n.id for n in ast.walk(piece) if isinstance(n, ast.Name)}
                attrs = {n.attr for n in ast.walk(piece) if isinstance(n, ast.Attribute)}
                bad = (names | attrs) & {"token", "TOKEN", "secret", "api_key", "pat"}
                assert not bad, f"{path}: interpolates {bad} into a string"


def test_the_allowlist_is_exactly_the_five_paths_the_lane_needs():
    """Small on purpose. Every entry is one call site: owner resolution / humanness
    pre-filter, the e03 repo lane, fork provenance, contributor fan-out, and e06's token
    check. Growing it is a deliberate edit that shows in the diff beside the call that
    needed it.

    `/rate_limit` is registered here rather than left unlisted because it IS a call this
    lane makes with the credential. It is the only endpoint whose purpose is metadata, it
    does not consume the limit it reports, and it is the one place the token's scopes are
    legible — which is what F059's guard reads."""
    assert PUBLIC_READ_PATHS == (
        "/users/{login}",
        "/users/{login}/repos",
        "/repos/{owner}/{repo}",
        "/repos/{owner}/{repo}/contributors",
        "/rate_limit",
    )
    from cerebro.gitintel.token_check import RATE_LIMIT_PATH
    assert RATE_LIMIT_PATH in PUBLIC_READ_PATHS


def test_the_allowlist_actually_rejects_something():
    """A matcher that accepts everything asserts nothing. These are all real GitHub
    endpoints the xyora token's scopes would happily reach."""
    for bad in ("/user/repos", "/orgs/anthropic/members", "/repos/a/b/collaborators",
                "/admin/users", "/repos/a/b/actions/secrets", "/notifications"):
        assert not _matches_allowlist(bad), f"{bad} should not be on the allowlist"
    for good in ("/users/simonw", "/users/simonw/repos", "/repos/simonw/llm",
                 "/repos/simonw/llm/contributors"):
        assert _matches_allowlist(good)


def test_the_sweep_covers_every_module_the_devs_lane_imports():
    """A lane module missing from DEVS_LANE_MODULES is unguarded. This catches the case
    where e03 adds a module and forgets to register it."""
    listed = {Path(p).name for p in DEVS_LANE_MODULES}
    reached = set()
    frontier = ["devs_spike.py"]
    while frontier:
        name = frontier.pop()
        if name in reached:
            continue
        reached.add(name)
        p = Path("cerebro/gitintel") / name
        if not p.is_file():
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None:
                for alias in node.names:
                    frontier.append(f"{alias.name}.py")
            elif isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                frontier.append(f"{node.module.split('.')[0]}.py")
    # Modules the spike genuinely reaches, minus infrastructure with no API surface.
    infrastructure = {"github_client.py", "cache.py", "roster.py", "identity.py"}
    missing = {m for m in reached if (Path("cerebro/gitintel") / m).is_file()} \
        - listed - infrastructure
    assert not missing, f"unguarded devs-lane modules: {sorted(missing)}"
