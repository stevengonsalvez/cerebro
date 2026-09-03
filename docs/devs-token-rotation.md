# Rotating the GitHub token the devs lane runs on

**Status: the current token is treated as COMPROMISED and is over-scoped by a factor of
seventeen.** This is the ordered procedure to replace it. Two steps are yours; the rest is
scripted. Do them in this order.

---

## Why, in numbers

`cerebro devs-token-check` run against the token in Bitwarden item `xyora` on 2026-08-27:

```
exit 5   token sha256:b7de4f23
scopes:  admin:enterprise, admin:gpg_key, admin:org, admin:org_hook, admin:public_key,
         admin:repo_hook, admin:ssh_signing_key, codespace, delete:packages, gist,
         notifications, project, repo, user, workflow, write:discussion, write:packages
```

Seventeen scopes. The charter recorded five; the live header carries twelve more,
including `user` (read/write the account profile), `gist`, `notifications`, `project`,
`codespace`, `admin:gpg_key` and `admin:ssh_signing_key` — collectively, near-total control
of the account, including the ability to add an SSH or GPG signing key.

What the devs lane actually uses is five public read endpoints:

```
GET /users/{login}                        humanness pre-filter, owner resolution
GET /users/{login}/repos                  the repos[] card
GET /repos/{owner}/{repo}                 seed-repo resolution
GET /repos/{owner}/{repo}/contributors    contributor fan-out
GET /rate_limit                           the token check itself
```

Every one of them answers unauthenticated. The token buys rate limit (5,000/hour instead
of 60), and nothing else.

The value also appeared once in a session transcript, which makes this a compromised
credential rather than a hygiene item: rotation, not tightening, is the fix.

---

## What the target token looks like

Mint at <https://github.com/settings/personal-access-tokens/new> — **Fine-grained**, not
"Tokens (classic)".

| field | value |
|---|---|
| Token name | `cerebro-devs-public-read` |
| Resource owner | `stevengonsalvez` (the personal account, **not** an organisation) |
| Expiration | 90 days |
| Repository access | **Public Repositories (read-only)** |
| Repository permissions | none — the option above already grants public read |
| Account permissions | **none**. Leave every row on "No access" |

A fine-grained token returns **no `x-oauth-scopes` header at all**. That is the green
state, and `devs-token-check` is written to read header-absence as "no classic scope
exists" rather than "unknown". Exit 0 is what you are looking for.

---

## The order, and why it is not negotiable

```
┌────────┐   ┌───────────┐   ┌──────────┐   ┌────────┐   ┌────────┐
│ 1 mint │──▶│ 2 store   │──▶│ 3 live   │──▶│ 4 verify│──▶│5 revoke│
│ (you)  │   │ Bitwarden │   │ .env     │   │ exit 0 │   │ (you)  │
└────────┘   └───────────┘   └──────────┘   └────────┘   └────────┘
```

Revoking first takes the 07:00 launchd run (`com.cerebro.daily`) down for a day: the lane
falls back to 60 calls/hour, the REST failure meter goes non-zero, the run is marked
degraded and refuses its churn deletions. Revoke LAST, after step 4 is green.

---

## 1. Mint (you)

Use the table above. Copy the value once; GitHub will not show it again.

## 2. Store it in Bitwarden (you paste, the shell does the rest)

The item is a **Secure Note** called `xyora`, whose body is `export KEY='value'` lines. It
currently carries two keys with the same value:

```
export GITHUB_TOKEN_CRACKSCAN='...'
export GITHUB_TOKEN_XYORA='...'
```

Replace both. `read -s` keeps the value out of shell history and off the screen:

```sh
export BW_SESSION="$(bw unlock --passwordfile ~/.secrets/bw-master --raw)"
read -rs -p "new fine-grained token: " NEW_PAT; echo
printf "export GITHUB_TOKEN_CRACKSCAN='%s'\nexport GITHUB_TOKEN_XYORA='%s'\n" \
  "$NEW_PAT" "$NEW_PAT" > /tmp/xyora-note.txt
bw get item xyora --session "$BW_SESSION" \
  | jq --rawfile note /tmp/xyora-note.txt '.notes = $note' \
  | bw encode | bw edit item "$(bw get item xyora --session "$BW_SESSION" | jq -r .id)" \
      --session "$BW_SESSION" > /dev/null
rm -f /tmp/xyora-note.txt
bw sync --session "$BW_SESSION" > /dev/null
```

## 3. Put it in the live install's environment

The live install is `/Users/stevengonsalvez/d/git/cerebro`. `cerebro/config.py`'s
`_load_dotenv()` reads `KEY=VALUE` lines (an `export ` prefix is stripped) from
`/Users/stevengonsalvez/d/git/cerebro/.env` into the environment, and the shell wins over
the file.

**That file today carries `NTFY_TOPIC`, `CEREBRO_VAULT`, `X_AUTH_TOKEN` and
`VERCEL_DEPLOY_HOOK_URL` — and no GitHub token at all.** So this step is an ADDITION, not
a replacement, and until it is done the 07:00 devs stage runs unauthenticated at 60
calls/hour. `devs-token-check` exits **6** in exactly that state, which is the difference
between "the token is wrong" and "no token reached the process".

```sh
cd /Users/stevengonsalvez/d/git/cerebro
cp .env ".env.bak-$(date +%s)"
grep -v '^export GITHUB_TOKEN_CRACKSCAN=' .env > .env.new && mv .env.new .env
printf "export GITHUB_TOKEN_CRACKSCAN='%s'\n" "$NEW_PAT" >> .env
chmod 600 .env
```

## 4. Verify (green before you revoke anything)

```sh
cd /Users/stevengonsalvez/d/git/cerebro
.venv/bin/python -m cerebro devs-token-check; echo "EXIT=$?"
```

Expect **`EXIT=0`** and a summary line reading
`scopes: none (fine-grained token, header absent)`. Exit 5 means the token still carries
classic scopes (you minted a classic one); exit 6 means step 3 did not take.

Then one real public read, and the rate limit that proves the token was actually used:

```sh
set -a; . /Users/stevengonsalvez/d/git/cerebro/.env; set +a
curl -s -o /dev/null -w 'users/simonw -> %{http_code}\n' \
  -H "Authorization: Bearer $GITHUB_TOKEN_CRACKSCAN" \
  https://api.github.com/users/simonw
curl -s -H "Authorization: Bearer $GITHUB_TOKEN_CRACKSCAN" \
  https://api.github.com/rate_limit | jq '.resources.core.limit'
unset GITHUB_TOKEN_CRACKSCAN
```

Expect `users/simonw -> 200` and a core limit of **5000**. A limit of 60 means the header
was ignored and the token is not in play — do not proceed.

Finally, one full dry run against the live free lane, which is the real end-to-end proof:

```sh
cd /Users/stevengonsalvez/d/git/cerebro
.venv/bin/python -m cerebro devs-refresh --dry-run --out logs/devs/rotation-check \
  > /tmp/rotation-dryrun.log 2>&1; echo "EXIT=$?"
grep -E '"rest_failures"|"healthy"' /tmp/rotation-dryrun.log
```

Expect `"healthy": true` and `"rest_failures": 0`. A non-zero failure count means the new
token is being refused, and the corpus would freeze rather than publish.

## 5. Revoke the old token (you)

Only now. <https://github.com/settings/tokens> → the classic token whose fingerprint is
`sha256:b7de4f23` → **Delete**.

Confirm the old value is dead:

```sh
export BW_SESSION="$(bw unlock --passwordfile ~/.secrets/bw-master --raw)"
# the OLD value, from the pre-rotation backup you kept out of band, not from Bitwarden
curl -s -o /dev/null -w 'old token -> %{http_code}\n' \
  -H "Authorization: Bearer $OLD_PAT" https://api.github.com/rate_limit
unset OLD_PAT
```

Expect `401`.

---

## Afterwards

- `scripts/run.sh` runs `cerebro devs-token-check` every morning, soft-failing and paging.
  A green rotation makes that line invisible; a bad one pages within a day.
- The fine-grained token expires in 90 days. Expiry looks like exit **5** (`401`), not
  exit 6. Diarise the renewal for day 83.
- Nothing in this repository, in `logs/devs/` or in any artifact ever contains the value:
  the check prints scope names and `sha256(value)[:8]` only, and a test runs the real CLI
  with a known value in the environment and searches every byte of its output for it.

## One thing this procedure cannot clean up

The **old** value is still sitting in plaintext in this worktree's Claude Code hook logs:

```
logs/chat.json
logs/user_prompt_submit.json
logs/subagent_stop.json
```

All three are gitignored (`.gitignore:25`) and none is tracked — verified with
`git grep -lF`, which returns nothing. They are local session transcripts, not repository
content, and they are exactly why this token counts as compromised rather than merely
over-scoped. Deleting them is worth doing after step 5, but it is not a substitute for
step 5: revocation is what makes the exposed value worthless.
