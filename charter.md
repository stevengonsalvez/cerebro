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

— SETTLED FACTS (proven by the driver; do NOT re-investigate or re-litigate) —
· Vercel's build sandbox DOES execute a user-authored prebuild `git clone`. Proven live on
  preview `dpl_HppnyHHHfeyX8NpstsWbxDZmnTVw`, build log: `[vault] ok sha=c807866
  daily=61 signals=909 in 389ms`, `✓ Compiled successfully in 13.7s`. F001 is confirmed;
  F003 push-sync stays PARKED and no epic carries pivot machinery for it.
· Site baseline before /cerebro: 696 static pages, 13.7s compile. Measure against that.
· Vercel runs Node 24.x; local is Node 22.13.0. Everything must pass on both.
· Kit never polls RSS. The weekly email ships via the repo's own build-digest.py
  fetch-parse-POST path, so the free-plan RSS question is closed and irrelevant.
· 0 of 909 signal notes carry a rating; any rating-dependent feature is PARKED.

— LEASE / HOSTNAME CHURN (observed live 2026-08-21 02:24) —
This machine's hostname changes under it (`MB1412-5457` → `MB1412-5508`, DHCP-style churn).
The lease holder token is `machine/user/SESSION`, so a hostname change makes the driver look
like a different machine and trips a spurious "lease lost". DIAGNOSTIC RULE: if the holder's
SESSION token equals this session's id, no competing driver can exist — a rival could not
hold this session's id — so the lease is STALE, not CONTENDED, and the skill's own
"auto-claims a stale one" path applies: re-claim, clear the marker, continue. Only treat a
lease-lost as real when the holder's SESSION token DIFFERS from this session's id. Never
skip this check and never force-claim past a genuinely different, fresh holder.

— WEEKLY-ROUNDUP SEQUENCING (measured 2026-08-21 18:45; affects e05 and e07 done-conditions) —
The public vault has NO `Weekly/` directory (sha a2db16f, 62 dailies, 929 signals). It cannot
have one yet: the `run.sh` that generates and stages the roundup lives in cerebro PR #17, which
is unmerged, so this morning's 07:00 run used the old script. The first real Weekly note can
therefore only appear after BOTH (a) PR #17 merges, and (b) the next run covering a COMPLETE
ISO week fires. Today is Friday 2026-08-21.
CONSEQUENCES, binding:
· e05 MUST render /cerebro correctly with zero Weekly notes, and the build MUST NOT fail on an
  absent Weekly/ dir. This is today's actual state, not a hypothetical edge case.
· e07 MUST NOT have "a weekly roundup is live on the site" as a done-condition — that is not
  achievable at launch and waiting for it would stall the programme for days. e07's weekly
  done-condition is: the page and the /feed.xml item render correctly FROM A LOCALLY GENERATED
  roundup fixture, and the production path is proven ready. The first real issue lands on its
  own once the pipeline runs post-merge.
· Tell Stevie this plainly at handover rather than letting him discover an empty weekly page.

— PROVEN PRE-EXISTING FAILURE (do NOT fix, do NOT let it block the e07 merge) —
The site repo's `publish` workflow (`.github/workflows/publish_devto.yml`) fails, and has
failed on `main` continuously since at least 2026-07-22 (runs at 3b0df68, de64d55, 5607a1f,
a73b589, aef9f3f, 640a56c — all `failure`). Cause: `Error: Cannot find published article on
dev.to: Your Agents Are Talking Behind Your Back`, i.e. `_devto/banter/2026/week-14-agents-
talking-to-agents.md` has no matching dev.to article. Proof it is not ours: that file was
last touched 2026-04-20 (f7ec7bb) and THIS branch has 0 commits touching it; the PR changes
0 files under `_devto/` at all. So PR #68 shows `mergeStateStatus: UNSTABLE` for a reason
that predates the programme by a month.
CONSEQUENCE: e07 merges on Vercel + the site's own test suite being green, and explicitly
ignores the `publish` check. Do not "fix" Stevie's dev.to sync as a side effect of this
programme — surface it to him instead; it means his blog→dev.to publishing has been silently
broken for weeks, which is his call to act on, not the factory's.

— SECRET CONTAINMENT (added after the e04 adversarial review found a real leak path) —
The dashboard is PASSWORDLESS and auto-republishes on every state.json write, and here.now
evidence pages are public. Therefore the Vercel deploy-hook URL (a bearer secret: anyone
holding it can trigger builds) must NEVER appear in state.json, `current_note`, a dashboard
render, an evidence upload, a PR body, or a commit. Its only homes are the LIVE install's
gitignored `/Users/stevengonsalvez/d/git/cerebro/.env` and, during the run,
`.agents/scratch/cerebro-vault-site-secrets.env` (gitignored, never rendered). Every command
that could echo it is redacted at the source. Same rule for VERCEL_TOKEN and KIT_API_KEY.

— CORPUS DRIFT (the vault is a moving target mid-run) —
The vault gains one daily + ~25 signal notes at 07:00 every day, and this programme is
running across that boundary. NO test, assertion, or done-condition may hardcode a corpus
aggregate (61 dailies / 909 signals / 1346 links). Aggregates are derived at run time from
the cache and asserted as floors or as internal-consistency invariants. Per-file facts about
named landmine notes stay hardcoded — those files do not change.

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
· PR SHAPE (deliberate deviation from the default one-PR-per-epic, recorded not hidden):
  TWO long-lived PRs, one per repo — SITE `f/cerebro-section` accumulating e01-e06, and
  CEREBRO `f/host-the-vault` carrying e04. Rationale: stacked per-epic PRs exist so a human
  can review increments, but granted authority #3 makes ME the merger, so five stacked
  site PRs would be ceremony with no reviewer. Each epic still gets its own atomic commits
  and its own evidence section appended to the PR body, so the audit trail per epic is
  intact and Stevie can read the history epic by epic after the fact.
  Both PRs merge at e07 (the terminal launch epic), squash-merge, branch deleted.
· BEADS: the CEREBRO repo has no `.beads/` and does not use beads. Rather than introduce a
  tracker Stevie never asked for, epic state lives in `state.json`'s `epics` map and the
  roadmap artifact. `beads_mode: "state-only"`. This is the sanctioned fail-open.
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
