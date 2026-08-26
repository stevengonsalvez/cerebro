"""T04 — measure the F011/F002 human pre-filter against the real vault seed pool.

A throwaway measurement harness, committed so the number is reproducible. Answers
three questions about `owner_resolve.is_human`, over every distinct owner the F001
vault lane yields:

  (a) how many owners are `type: Organization` (they go to the F002 contributor
      fallback, at a measured REST cost);
  (b) how many are `[bot]` or in VENDOR_ORGS (the cheap pre-filter's real job);
  (c) how many pass type/bot/vendor and are dropped ONLY by the name/bio non-empty
      clause at owner_resolve.py:21.

(c) is the point. That clause is not a Court verdict and it silently drops real
engineers who have no bio. This script PRINTS the dropped logins so each can be
inspected by hand and the clause kept or relaxed on evidence, never on taste.

Public read endpoints only. The token is read from the environment and never printed.

    export GITHUB_TOKEN_CRACKSCAN=...   # from Bitwarden item `xyora`
    python scripts/measure_prefilter.py <vault-cache-path>
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from cerebro.gitintel import vault_seed
from cerebro.gitintel.owner_resolve import VENDOR_ORGS, is_human

API = "https://api.github.com"


def get_user(login: str, token: str) -> dict | None:
    req = urllib.request.Request(
        f"{API}/users/{login}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "cerebro-devs-prefilter-measurement",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            return None
        except Exception:  # noqa: BLE001
            if attempt < 2:
                time.sleep(2)
                continue
            return None
    return None


def main() -> int:
    corpus = sys.argv[1] if len(sys.argv) > 1 else ""
    token = os.environ.get("GITHUB_TOKEN_CRACKSCAN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        print("no token in GITHUB_TOKEN_CRACKSCAN / GITHUB_TOKEN")
        return 2

    seeds = vault_seed.seed_repos(corpus)
    owners = sorted({s.owner for s in seeds}, key=str.lower)
    print(f"seed pairs {len(seeds)}  distinct owners {len(owners)}")

    orgs, bots, vendors, missing, humans = [], [], [], [], []
    bio_only_drops = []

    for i, login in enumerate(owners, 1):
        u = get_user(login, token)
        if u is None:
            missing.append(login)
            continue
        low = login.lower()
        if low.endswith("[bot]") or low in VENDOR_ORGS:
            bots.append(login) if low.endswith("[bot]") else vendors.append(login)
            continue
        if (u.get("type") or "").lower() != "user":
            orgs.append(login)
            continue
        if is_human(u):
            humans.append(login)
        else:
            # passed type + bot + vendor; dropped ONLY by the name/bio clause
            bio_only_drops.append((login, u.get("name"), u.get("bio"),
                                   u.get("public_repos"), u.get("followers"),
                                   u.get("created_at")))
        if i % 25 == 0:
            print(f"  ... {i}/{len(owners)}", flush=True)

    print()
    print(f"(a) type: Organization        {len(orgs)}   -> F002 contributor fallback")
    print(f"    {orgs}")
    print(f"(b) [bot] suffix              {len(bots)}")
    print(f"    vendor org logins         {len(vendors)}  {vendors}")
    print(f"    404 / deleted             {len(missing)}  {missing}")
    print(f"    passing is_human()        {len(humans)}")
    print(f"(c) dropped ONLY by name/bio  {len(bio_only_drops)}")
    for login, name, bio, repos, followers, created in bio_only_drops:
        print(f"    {login:<28} name={name!r} bio={bio!r} "
              f"repos={repos} followers={followers} created={created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
