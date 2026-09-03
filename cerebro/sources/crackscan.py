from __future__ import annotations

from datetime import date
from pathlib import Path

from ..gitintel import optout as optout_mod
from ..gitintel import roster as roster_mod
from ..gitintel import vault_seed
from ..gitintel.crackscore import cheap_score, deep_score
from ..gitintel.github_client import GitHubClient, resolve_token
from ..gitintel.owner_resolve import resolve_owner
from ..models import Signal
from .base import now_iso


def fetch(cfg: dict, settings) -> list[Signal]:
    """Auto-discover cracked devs and admit the strongest as tier-3 roster entries.

    Funnel: seed repos -> human owner -> cheap-score all -> deep-score top-N (token
    budget permitting) -> admit score>=threshold up to admit_max -> append tier-3.
    Every admitted and considered candidate is emitted as a Signal for the briefing.
    Deterministic under test via an optional cfg['now'] ISO clock.

    F049 — THE OPT-OUT GATE SITS ON THE CANDIDATE LIST, AND THAT PLACEMENT IS COURT
    SETTLED. This function emits a `crackscan/considered` Signal for every candidate it
    merely considered, not only for the ones it admits, and those Signals go into the
    vault through the existing pipeline. Gating the roster append, or the `Devs/` write
    stage, or anything else downstream therefore still leaks an opted-out login into
    `Signals/`. The gate is applied TWICE inside this one function — once where the
    candidate list is built, once immediately before `out` is assembled — so a future
    refactor that reintroduces a path to `_signal()` cannot leak either.

    A MALFORMED CONSENT FILE RAISES OUT OF HERE. `optout.load` fails closed on purpose
    (see its module docstring): returning unfiltered candidates because the file could
    not be read is the one failure mode this gate exists to make impossible.
    """
    consent = optout_mod.load(cfg.get("optout_path") or optout_mod.DEFAULT_PATH)
    token = resolve_token(cfg, settings)  # None -> GitHubClient falls back to its own env read
    client = GitHubClient(settings, token=token)

    top_n = int(cfg.get("top_n", 10))
    admit_max = int(cfg.get("admit_max", 5))
    threshold = float(cfg.get("score_threshold", 0.55))
    window_days = int(cfg.get("window_days", 90))
    min_remaining = int(cfg.get("min_remaining", 200))
    now = cfg.get("now")  # optional fixed clock (tests inject; None -> live wall clock)
    roster_path = cfg.get("roster_path") or roster_mod.DEFAULT_PATH

    # 1. seed repos -> human owner logins, dropping non-humans and already-rostered
    existing, _ = roster_mod.load_roster(roster_path)
    seen = {d.slug for d in existing}
    logins: list[str] = []
    for full in _seed_repos(cfg, settings):
        try:
            login = resolve_owner(full, client)  # org owner -> top human committer, else None
        except Exception:  # noqa: BLE001 — one bad repo must not sink the scan
            continue
        if not login:
            continue
        slug = optout_mod.slug(login)
        if not slug or slug in seen:
            continue
        # F049, barrier 1. Dropped HERE, before `seen`/`logins`, so the login never
        # reaches cheap_score, never reaches the roster append, and never reaches
        # `_signal()`.
        if slug in consent.logins:
            continue
        seen.add(slug)
        logins.append(login)

    if not logins:
        return []

    cache = getattr(client, "cache", None)

    # 2. cheap-score everyone (no events call)
    scored = []
    for login in logins:
        try:
            scored.append(cheap_score(login, client, cache, captured_at=now))
        except Exception:  # noqa: BLE001
            continue
    scored.sort(key=lambda s: s.score, reverse=True)

    # 3. deep-score top-N — skipped when the token budget is tight
    remaining = _int(client.rate_limit.get("remaining"))
    if remaining is None or remaining >= min_remaining:
        for i, base in enumerate(scored[:top_n]):
            try:
                scored[i] = deep_score(base, client, window_days=window_days, now=now)
            except Exception:  # noqa: BLE001
                pass
        scored.sort(key=lambda s: s.score, reverse=True)

    # 4. admit score>=threshold, capped at admit_max; the rest are considered-only
    admitted, considered = [], []
    for s in scored:
        if len(admitted) < admit_max and s.score >= threshold:
            admitted.append(s)
        else:
            considered.append(s)

    # F049, barrier 2. Defence in depth INSIDE the same function: barrier 1 already
    # removed these logins, so this loop is a no-op today by construction. It is here
    # because everything between it and barrier 1 is score plumbing that has been
    # rewritten before and will be rewritten again, and the failure mode of a leak is a
    # published Signal about a person who asked not to be here.
    admitted = [s for s in admitted if optout_mod.slug(s.login) not in consent.logins]
    considered = [s for s in considered if optout_mod.slug(s.login) not in consent.logins]

    if admitted:
        roster_mod.append_devs(roster_path, [_dev_dict(s) for s in admitted])

    out = [_signal(s, "crackscan/admitted") for s in admitted]
    out += [_signal(s, "crackscan/considered") for s in considered]
    return out


def _seed_repos(cfg: dict, settings) -> list[str]:
    """Candidate 'owner/name' repos from explicit cfg, the vault's repo entities, and
    — only when `cfg['use_vault_seed_lane']` is truthy — the vault's Signal notes.

    ponytail: seed_handles (x/reddit->github) and trending re-mining are deferred —
    no identity resolver exists for x/reddit yet, and trending fan-out is untested
    network cost. Add those lanes when a resolver lands.
    """
    repos: list[str] = []
    for r in cfg.get("seed_repos") or []:
        r = str(r).strip()
        if "/" in r:
            repos.append(r)
    vault_path = getattr(settings, "vault_path", "")
    repos += _vault_repos(vault_path)
    if cfg.get("use_vault_seed_lane") and vault_path:
        # F001 vault Signal-note lane. STILL OFF, and the F049 gate landing is NOT the
        # reason to turn it on. e01's comment here promised e03 would flip it; that
        # promise predates the measurement and is overridden.
        #
        # Flipping it feeds roughly 175 vault owners into `cheap_score`/`deep_score` —
        # the follower/star scorer the charter condemned and ordered REBUILT, whose
        # admission arithmetic is provably impossible on a cold cache — and emits a
        # `crackscan/considered` Signal per candidate into the live public vault. The
        # opt-out gate removes ONE hazard from that lane; it does not make a condemned
        # funnel worth switching on.
        #
        # The lane's real consumer is the devs pipeline, which mines the same Signal
        # notes for free via `gitintel/vault_seed.py` and never touches this scorer.
        # Retiring this flag belongs to whoever retires `crackscore.py`.
        repos += [s.full_name for s in vault_seed.seed_repos(vault_path)]

    out, seen = [], set()
    for r in repos:
        k = r.lower()
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _vault_repos(vault_path) -> list[str]:
    if not vault_path:
        return []
    base = Path(vault_path) / "Entities" / "repos"
    if not base.is_dir():
        return []
    out: list[str] = []
    for note in sorted(base.glob("*.md")):
        try:
            fm = _frontmatter(note.read_text(encoding="utf-8"))
        except OSError:
            continue
        full = fm.get("full_name") or fm.get("repo") or ""
        if "/" in full:
            out.append(full)
    return out


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"')
    return fm


def _dev_dict(s) -> dict:
    return {
        "name": s.login,
        "tier": 3,
        "github": s.login,
        "why": f"crackscan score={s.score}",
        "added": date.today().isoformat(),
        "discovered_via": "crackscan",
    }


def _signal(s, tag: str) -> Signal:
    return Signal(
        url=f"https://github.com/{s.login}",
        title=f"crackscan: {s.login} (score {s.score})",
        source="github",  # folds into the per_source github bucket
        captured=now_iso(),
        clean_text=s.reason,
        source_tags=[tag],
        entity_tags=[f"developer/{s.login}"],
        meta={
            "login": s.login,
            "score": s.score,
            "commits_per_day": s.commits_per_day,
            "followers_gained_30d": s.followers_gained_30d,
            "portfolio_momentum": s.portfolio_momentum,
            "ships_score": s.ships_score,
            "deep": s.deep,
        },
    )


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
