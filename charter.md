# /godmode CEREBRO Vault → stevengonsalvez.com/cerebro — CHARTER (the constitution)

Every loop iteration re-reads this file. It is the source of truth for how the
programme runs.

— REPOS / WORKTREES (cross-repo programme) —
· PROGRAMME ROOT (state, charter, plans, beads, cerebro-side code):
  `/Users/stevengonsalvez/.agents-in-a-box/worktrees/by-name/cerebro--f-host-the-vault--b73e0fbf`
  repo `stevengonsalvez/cerebro`, base branch `main`, working branch `f/host-the-vault`.
· SITE CHECKOUT (all Next.js work): `/Users/stevengonsalvez/.agents-in-a-box/godmode/cerebro-vault-site/site`
  repo `stevengonsalvez/stevengonsalvez.github.io`, base `main`, working branch `f/cerebro-section`.
  transcrypt initialised there (aes-256-cbc, password = the repo name); `.env` decrypts.
· CONTENT SOURCE (read-only to this programme): `stevengonsalvez/cerebro-vault` — PUBLIC,
  auto-pushed daily 07:00 by `scripts/run.sh`. Daily/ ≈61 notes, Signals/ ≈909 notes.
  NEVER commit to cerebro-vault. Local probe clone: `/tmp/cerebro-vault-probe`.
· Epics are labelled with the repo they touch. Stacked branches apply PER REPO.

— OUTCOME (terminal states, not activities) —
Every feature in the registry (`.agents/plans/cerebro-vault-site-registry.md`) is either
SHIPPED with green verification behind a PR, or PARKED with a Feasibility Court verdict
(downgraded tier + named blocker). At minimum, ALL of these are SHIPPED:
1. `stevengonsalvez.com/cerebro` exists: index + one page per `Daily/*.md`, in the site's
   newspaper aesthetic, reachable from the site nav.
2. `/cerebro/signals` — ONE page, client-side searchable/filterable over every signal
   (date, source, category, score, tag). NO per-signal URLs; page count stays flat as the
   vault grows ~25 notes/day.
3. A vault→site content pipeline that publishes a new daily briefing with ZERO human
   action after the 07:00 cerebro run, and that survives Vercel's build sandbox.
4. A generated WEEKLY Cerebro roundup that lands as an item in the EXISTING `/feed.xml`
   (which Kit consumes) — subscribers keep exactly one email a week. No second Kit list.
5. Scraped third-party article bodies are provably NOT republished anywhere on the site.
6. All of the above is MERGED and LIVE on the real `https://stevengonsalvez.com/cerebro`,
   verified by probing the production domain — not a preview URL.

— LOCKED HUMAN DECISIONS (settled 2026-08-20; the Court may NOT re-litigate these) —
· Scope = dailies + one signal archive page. No per-signal URLs.
· Newsletter = weekly roundup item in the existing `/feed.xml`. No separate Kit list, no
  daily email.
· Signal notes embed full trafilatura-scraped source text. Render ONLY: title, category,
  tags, source, score, triage `reason`, `Community take`, and a link out to the original.
  The scraped body is stripped at ingest. This is a legal/SEO constraint, not a preference.
· Execution mode = full godmode factory.

— GRANTED AUTHORITY (interview, 2026-08-21; these OVERRIDE the defaults) —
Stevie was asked four scoped authority questions and chose maximum autonomy on all four.
His instruction framing: "first /interview me with all you need like credentials or
anything .. so that you can execute the godmode autonomously".
1. VERCEL: FULL, including production deploys. I may create deploy hooks, set env vars,
   run `vercel --prod`, and promote deployments on project
   `prj_uTsBw2o1KA1EPAy1AyFYKOhIo0Ut` (scope `stevengonsalvezs-projects`).
2. KIT: FULL, including sending real broadcasts to real subscribers. Constrained by intent,
   not by permission: a send must be a genuine weekly roundup issue, never a "test blast".
   Prefer Kit's own preview/test-send to steven.gonsalvez+kit@gmail.com before any
   list-wide send. Never delete subscribers.
3. SHIP: merge my own PRs to `main` on BOTH repos once verification is green, so /cerebro
   is LIVE on stevengonsalvez.com at the end of the run. Human review is passive.
4. ROADMAP GATE: PRE-BLESSED. Present the roadmap for the record, PushNotification once,
   then start building immediately without waiting.

— CREDENTIALS (all resolved; never commit any of them) —
· Site `.env` (transcrypt, password = repo name) carries VERCEL_TOKEN / VERCEL_PROJECT /
  VERCEL_SCOPE / KIT_API_KEY / KIT_FORM_ID / NEXT_PUBLIC_KIT_FORM_ID / POSTHOG_* /
  DEV_TO_API_KEY. Load with `set -a; . .env; set +a`. Verified working 2026-08-21.
· Kit account 2820210, FREE plan (1000-subscriber limit) — whether RSS-driven broadcasts
  exist on this tier is an OPEN QUESTION the Court must settle against the live API.
· `gh` authed as stevengonsalvez. GPG key 907EC78C72C6AFF6, cache warm, `commit.gpgsign=true`.
· here.now: domain explainers.stevengonsalvez.com, index slug coral-cipher-ejrg. Cerebro is
  on the PUBLIC list in the protect rule — dashboard and evidence pages ship unlocked.
· LIVE cerebro install (what launchd actually runs at 07:00):
  `/Users/stevengonsalvez/d/git/cerebro`, `dry_run: false`, config/settings.yaml +
  .env both gitignored there. The deploy-hook URL belongs in THAT .env, and landing it is
  part of shipping, not a follow-up for the human.

— PIPELINE (state machine per epic) —
Feasibility Court (once) → Roadmap + epic beads (once) → [HUMAN GATE: roadmap blessing]
→ per epic: Plan (planner → adversarial review → revise → verify-the-revise) → Execute
(build-pair → pair review → adversarial epic review → VERIFY → fix loop ≤2 → build gate)
→ epic bead closed only when verification green → stacked PR.
Epics serial on stacked branches unless blessed-parallel AND provably disjoint. Epics in
DIFFERENT repos are inherently disjoint and MAY run parallel once blessed.

— MODEL POLICY —
· BRAIN (brainstorm / roadmap / adversarial review) = fable
· BUILD = opus + `codex:codex-rescue` pair; disagreements surfaced, never silently resolved.
· TEST/VALIDATE = sonnet. SCAFFOLD = sonnet.

— VERIFICATION DOCTRINE —
· Lanes for this programme: **Web UI** (Next.js pages — the dominant lane), **Library**
  (the Python roundup generator + any content transform in cerebro), **API** (the
  `/cerebro/feed.xml` + `/feed.xml` routes: real HTTP request, assert XML shape).
· Mock ONLY the human at the input boundary. Everything else real: the real vault
  markdown, a real `next build`, a real `next start`, a real browser drive, a real
  `curl` at the feed route.
· Read the artefact, never blank-check: assert the ACTUAL briefing text renders, the
  ACTUAL filter narrows results, the ACTUAL feed item appears. "200 OK" is not a pass.
· CONTENT-SAFETY GATE (every epic that touches rendering): grep the built output in
  `.next/` / the served HTML for a known scraped-body sentence from a Signals note and
  assert ZERO hits. A rendering epic cannot ship without this probe green.
· Validation ladder (ALL of it, in order — later rungs do not excuse skipping earlier ones):
  localhost `npm run build` + `npm start` → Vercel PREVIEW deploy from the PR → merge to
  `main` → production deploy → probe the REAL `https://stevengonsalvez.com/cerebro`.
  The programme is not done until the last rung is green on the real domain.
· STILL FORBIDDEN, any occurrence = STOP:
  - any write (commit/push/force) to the `cerebro-vault` repo — it is the pipeline's output,
    not ours; corrupting it corrupts the daily briefing history;
  - a full live (non-`--dry-run`) run of the cerebro pipeline — it burns real LLM budget and
    writes real vault notes. Invoking ONLY a new, scoped roundup entrypoint against the
    existing corpus is allowed and is not a pipeline run;
  - deleting Kit subscribers, or sending a broadcast that is not a genuine weekly roundup;
  - merging a PR whose verification is not green, or force-pushing `main` on either repo;
  - committing any secret, or converting site `.env` back to plaintext.
· Node 22 (`v22.13.0`, nvm) is the runtime for every site build/test invocation.
· Evidence uploaded to here.now, linked from the dashboard Evidence tab AND the PR body.

— COMMIT POLICY —
· Atomic single-concern conventional commits, named paths only (never `git add -A`), no AI
  attribution. Sign (`-S`) — key 907EC78C72C6AFF6, cache warm; never spawn GUI pinentry from
  a headless shell — else `--no-gpg-sign` and batch re-sign before the PR.
· One PR per epic, labelled `godmode-review`, stacked on the previous epic's branch WITHIN
  its repo. I merge it myself once verification is green (granted authority #3), squash-merge,
  delete the branch. The PR body still carries the full evidence trail so the merge is
  auditable after the fact.
· NEVER commit: `.agents/`, `explainers/`, dashboards, scratch, `.env` (stays transcrypt
  ciphertext), `config/settings.yaml`, the fetched vault cache dir.
· `.agents/` and `explainers/` are already gitignored in the cerebro repo. Verify the site
  repo gitignores the vault cache dir BEFORE the first content-pipeline commit.

— LIVE DASHBOARD —
· slug `cerebro-vault-site`, password none. Local file: `explainers/cerebro-vault-site.html`.
· HOOK-OWNED: every state.json write renders + republishes it. Keep state.json truthful,
  always write `current_note`. That IS the dashboard duty.

— LOOP PROTOCOL (each wake) —
1. Read this charter + `.agents/scratch/cerebro-vault-site-state.json`.
2. Check running workflow; on completion persist artifacts, verify commits landed,
   advance the state machine, launch the next stage.
3. `lease.sh refresh` EVERY wake (lost lease = handoff note, read-only, stop re-arming).
4. Update beads + state (state via Write/Edit tool ONLY; stamp `phase_since` on flips;
   publish phase explainers via `explainer-publish.sh` after SHIP / HUMAN_GATE / DONE).
5. ScheduleWakeup ~600s, reason = current phase, prompt = the driver re-entry string.
· STOP RULES: workflow errors ×2 on one stage | validation fails ×3 on one epic | ANY
  forbidden operation above | epic > ~15M subagent tokens.

— TERMINATION —
backlog-dry (default). No `--budget`, no `--deadline` set. On termination: final summary,
PushNotification, stop re-arming.

— SUCCESS CRITERIA (ALL MUST BE TRUE) —
1. Every registry feature has a Court verdict recorded.
2. Every blessed epic: plan artifact + reviewed + executed + verification green + PR raised;
   parked features carry verdicts.
3. Dashboard live and updated throughout.
4. Evidence exists for every closed epic (build log, browser artefacts, feed probe, PR link).
5. The content-safety grep is green on the final built site.

— OPERATING RULES — NON-NEGOTIABLE —
1. PLAN FIRST per epic. 2. WORK AUTONOMOUSLY (one human gate + stop rules). 3. SELF-VERIFY
every step. 4. DEBUG YOURSELF. 5. NO PLACEHOLDERS in shipped code. 6. PROGRESS LOG
(dashboard + beads). 7. STAY ON GOAL. 8. IF BLOCKED, log + continue parallelizable work.
9. CHECK SUCCESS BEFORE STOPPING.
