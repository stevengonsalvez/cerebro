from __future__ import annotations

VENDOR_ORGS = {
    "google", "microsoft", "vercel", "facebook", "meta", "aws", "amazon",
    "apple", "netflix", "cloudflare", "openai", "anthropic", "github",
    "gitlab", "huggingface", "nvidia", "intel", "ibm", "oracle", "adobe",
    "stripe", "shopify", "atlassian", "jetbrains", "docker", "kubernetes",
}


def is_human(user: dict) -> bool:
    """Reject org/bot/empty accounts. user = github user payload."""
    if not user:
        return False
    if (user.get("type") or "").lower() != "user":
        return False
    login = (user.get("login") or "").lower()
    if login.endswith("[bot]") or login in VENDOR_ORGS:
        return False
    # Require any public presence, NOT a filled-in profile.
    #
    # MEASURED, not chosen (T04, scripts/measure_prefilter.py, 2026-08-26, over the
    # real 175-owner vault seed pool): a name/bio-only clause dropped 8 of the 91
    # non-org, non-vendor accounts — 8.8% of the human pool. All eight were inspected
    # by hand and seven ship substantial original work under their own login:
    # BigPizzaV3/CodexPlusPlus 29.7k stars, DietrichGebert/ponytail 112k,
    # tt-a1i/archify 17.7k, bradautomates/claude-video 16.3k, kangarooking/cangjie-skill
    # 9.0k, eneskirca/nodeterm 1.3k, JCodesMore/fix-claude-code. An empty `bio` is a
    # profile-completeness fact, not a humanness signal, and it correlates with a
    # region, not with automation. The eighth (deepreinforce-ai, 0 repos, created
    # 2026-08-05) has zero 90d activity and is handled by the low-n label, which the
    # Court settled must never become suppression.
    #
    # What still rejects a genuinely empty shell: no name, no bio, no public repos and
    # no followers. Real automation is caught downstream by SHAPE, per the Court's
    # ruling that name-pattern filtering is provably insufficient.
    if (user.get("name") or "").strip() or (user.get("bio") or "").strip():
        return True
    return _count(user.get("public_repos")) > 0 or _count(user.get("followers")) > 0


def _count(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def resolve_owner(full_name: str, client) -> str | None:
    """repo 'owner/name' -> human login. If owner is an org, fall back to top
    human committer. Returns login or None if no human found."""
    owner, _, name = full_name.partition("/")
    u = client.get_user(owner)
    if u and is_human(u):
        return u.get("login")
    # org / non-human owner: top committers.
    #
    # The path is built from `owner` and `name` SEPARATELY rather than by interpolating
    # `full_name` whole. Both produce the same string, but only this form has the same
    # shape as the `/repos/{owner}/{repo}/contributors` template on F053's public-read
    # allowlist, so `tests/test_public_boundary.py` can check it by structure instead of
    # taking a one-placeholder f-string on trust.
    try:
        contribs = client.request(f"/repos/{owner}/{name}/contributors", {"per_page": 5})
    except Exception:
        return None
    for c in contribs or []:
        cu = client.get_user(c.get("login", ""))
        if cu and is_human(cu):
            return cu.get("login")
    return None
