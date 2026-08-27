# Security Policy

CEREBRO is a public repository. It is built **secrets-out**: no credential, token, cookie, or
private endpoint is ever committed.

## Secret handling

The pipeline holds **no API keys** — every external capability self-authenticates outside the repo:

| Capability | Auth mechanism | Repo sees |
|------------|----------------|-----------|
| LLM (triage + digest) | **Claude Code** on the machine (`claude -p`) — uses its own login/subscription | nothing |
| X / Twitter | `bird` reads the browser's `x.com` cookie (Firefox/Chrome) | nothing |
| Gmail newsletters | `gws` (Google Workspace CLI) — its own Google OAuth | nothing |
| Notifications | `ntfy` topic in `config/settings.yaml` (gitignored) | nothing |

The only sensitive value CEREBRO itself stores is the **ntfy topic** (anyone with it can read/publish
to that channel) — it lives only in the gitignored `config/settings.yaml`. Committed `*.example`
files hold placeholders only. There is no API key to vault, so no secret-manager is required for v1;
if a real secret is ever introduced, store it in the OS Keychain (or a secrets manager) — never the repo.

## Standing note: the GitHub PAT the devs lane runs on (open)

The devs discovery lane (`cerebro devs-refresh`) reads five public GitHub endpoints. The
token it authenticates with — Bitwarden item `xyora`, keys `GITHUB_TOKEN_CRACKSCAN` and
`GITHUB_TOKEN_XYORA` — is a **classic PAT carrying seventeen scopes**, measured
2026-08-27 by `cerebro devs-token-check` (exit 5, `token sha256:b7de4f23`):

```
admin:enterprise, admin:gpg_key, admin:org, admin:org_hook, admin:public_key,
admin:repo_hook, admin:ssh_signing_key, codespace, delete:packages, gist,
notifications, project, repo, user, workflow, write:discussion, write:packages
```

Nothing in this repository needs any of them: every endpoint the lane calls answers
unauthenticated, and the token buys rate limit alone (5,000/hour against 60). The scope
set includes `user`, `admin:gpg_key` and `admin:ssh_signing_key`, i.e. near-total control
of the account.

The value was additionally **exposed once in a session transcript**, so it is treated as a
COMPROMISED credential rather than as a hygiene item: the fix is rotation, not tightening.

- Replacement procedure, paste-ready and ordered: [`docs/devs-token-rotation.md`](docs/devs-token-rotation.md).
  Order is mint → Bitwarden → live `.env` → verify → revoke. Revoking first takes the
  07:00 run down for a day.
- Target state: a **fine-grained** token, resource owner `stevengonsalvez`, repository
  access *Public Repositories (read-only)*, **no** account permissions, 90-day expiry.
  Such a token returns no `x-oauth-scopes` header at all.
- Enforced daily, not documented once: `scripts/run.sh` runs `cerebro devs-token-check`
  before the refresh. Exit 5 = over-scoped or refused, exit 6 = no token reached the
  process, 0 = allowed. Both failures page and neither blocks the run.
- The value is never printed, logged or written: the check emits scope NAMES and a
  `sha256(value)[:8]` fingerprint, asserted by a test that searches the real CLI's whole
  output for a known value.
- `tests/test_public_boundary.py` fails the build if any devs-lane module reads a
  credential from the environment for itself, or names an endpoint off the public-read
  allowlist.

This note stays here until the rotation is done and `devs-token-check` exits 0 against the
live install.

## Scanning (defense in depth)

Two independent scanners run **both** locally (pre-commit) and in CI (every push/PR):

- **gitleaks** — regex/entropy secret detection. Config: `.gitleaks.toml`.
- **GitGuardian ggshield** — 400+ detectors + validity checks. Config: `.gitguardian.yaml`.

CI: `.github/workflows/security.yml` (both jobs green; `GITGUARDIAN_API_KEY` is set in repo secrets).
Local: `.pre-commit-config.yaml` (run `pre-commit install`). GitHub-native secret scanning + push
protection + Dependabot are also enabled.

## If a secret is ever committed

1. **Revoke/rotate the credential immediately** — a value pushed to a public repo is compromised the
   moment it lands; rotation, not history rewrite, is the fix.
2. Purge from history (`git filter-repo`) and force-push.
3. Confirm gitleaks + ggshield pass on the rewritten history.

## Reporting

Open a private security advisory via the repo's **Security → Advisories** tab, or contact the
maintainer directly. Do not file a public issue containing the sensitive detail.
