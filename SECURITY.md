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
