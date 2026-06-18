# Security Policy

CEREBRO is a public repository that handles personal data flows (email, vault) and
paid API keys. It is built **secrets-out**: no credential, token, cookie, or private
endpoint is ever committed.

## Secret handling

| Secret | Where it lives | Never |
|--------|----------------|-------|
| `ANTHROPIC_API_KEY` | Bitwarden Secrets Manager (`bws secret get`) | in repo, env files, or logs |
| `BWS_ACCESS_TOKEN` (bootstrap) | macOS Keychain (`cerebro-bws`), exported by `scripts/run.sh` | in the launchd plist or repo |
| `ntfy` topic | `config/settings.yaml` (gitignored) | committed |
| Vault path | `config/settings.yaml` (gitignored) | committed |
| bird / gog auth | managed by those CLIs outside the repo | committed |

Rule: if it authenticates, authorizes, or addresses a private channel, it goes in
Bitwarden or Keychain — not the repo. Committed `*.example` files hold placeholders only.

## Scanning (defense in depth)

Two independent scanners run **both** locally (pre-commit) and in CI (every push/PR):

- **gitleaks** — regex/entropy secret detection. Config: `.gitleaks.toml`.
- **GitGuardian ggshield** — 400+ detectors + validity checks. Config: `.gitguardian.yaml`.

CI: `.github/workflows/security.yml`. Local: `.pre-commit-config.yaml` (run
`pre-commit install`). The ggshield CI job is a no-op until `GITGUARDIAN_API_KEY`
is added to repo secrets (`gh secret set GITGUARDIAN_API_KEY`).

GitHub-native secret scanning + push protection are also enabled on this repo
(free for public repos).

## If a secret is ever committed

1. **Revoke/rotate the credential immediately** (the leaked value is compromised the
   moment it is pushed to a public repo — rotation, not history rewrite, is the fix).
2. Purge from history (`git filter-repo`) and force-push.
3. Confirm gitleaks + ggshield pass on the rewritten history.

## Reporting

Found something? Open a private security advisory via the repo's **Security →
Advisories** tab, or contact the maintainer directly. Do not file a public issue
containing the sensitive detail.
