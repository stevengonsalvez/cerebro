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
    # require at least one human signal
    return bool((user.get("name") or "").strip() or (user.get("bio") or "").strip())


def resolve_owner(full_name: str, client) -> str | None:
    """repo 'owner/name' -> human login. If owner is an org, fall back to top
    human committer. Returns login or None if no human found."""
    owner = full_name.split("/")[0]
    u = client.get_user(owner)
    if u and is_human(u):
        return u.get("login")
    # org / non-human owner: top committers
    try:
        contribs = client.request(f"/repos/{full_name}/contributors", {"per_page": 5})
    except Exception:
        return None
    for c in contribs or []:
        cu = client.get_user(c.get("login", ""))
        if cu and is_human(cu):
            return cu.get("login")
    return None
