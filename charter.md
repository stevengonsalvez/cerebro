# /godmode CEREBRO Devs — automated cracked-dev discovery — CHARTER (the constitution)

Every loop iteration re-reads this file. Base branch: `main` in both repos.

— REPOS / WORKTREES —
· PROGRAMME ROOT + python pipeline: `/Users/stevengonsalvez/.agents-in-a-box/worktrees/by-name/cerebro--f-host-the-vault--b73e0fbf`
  (repo `stevengonsalvez/cerebro`). LIVE install that launchd runs 07:00: `/Users/stevengonsalvez/d/git/cerebro`.
· SITE: `/Users/stevengonsalvez/.agents-in-a-box/godmode/cerebro-vault-site/site`
  (repo `stevengonsalvez/stevengonsalvez.github.io`, transcrypt initialised, `.env` decrypts).
· CONTENT SOURCE, read-only: `stevengonsalvez/cerebro-vault` (PUBLIC). NEVER commit to it.

— OUTCOME (terminal states) —
1. `stevengonsalvez.com/cerebro/devs` is LIVE: a ranked, filterable index plus a page per
   developer, built from the same vault→clone→static-page path the signals archive uses.
2. Candidates are discovered by THREE lanes: the vault's own GitHub repos, stargazer/
   contributor fan-out from those, and GH Archive as ENRICHMENT (see SETTLED FACTS).
3. Scoring is REBUILT on defensible signals. The current follower/star-derived model is gone.
4. A working OPT-OUT exists before the section goes live. Not a follow-up.
5. The section feeds the weekly roundup, `/feed.xml` and the Kit newsletter like the archive does.
6. Everything merged and verified on the real production domain.

— OWNER DECISIONS (interview 2026-08-26; the Court may NOT re-litigate) —
· Discovery = all three lanes.
· Output = a published `/cerebro/devs` site section.
· Ethics = public data only, FACTUAL framing, working opt-out. Describe activity
  ("shipped 240 commits across 12 repos in 30 days"); never judge the person.
  NO "cracked" badge. NO league table of humans.
· Scoring = rebuilt, not patched.

— SETTLED FACTS (proven this session; do NOT re-derive or contradict) —
· crackscan has NEVER made a GitHub API call in production. `seed_repos: []` and
  `vault/Entities/repos` absent → `_seed_repos()` returns `[]` → `fetch()` exits at
  `crackscan.py:50-51`. 6 runs, 0 signals, no error.
· ADMISSION IS ARITHMETICALLY IMPOSSIBLE. `WEIGHTS = commit .35 / follower .25 /
  portfolio .25 / ships .15` (`crackscore.py:18`); on a cold cache follower and portfolio are
  structurally 0 (`metrics.py:121-123` returns 0.0 without a snapshot ≥7d old). Max = 0.50
  against a 0.55 threshold. Verified twice.
· `record=False` (`crackscore.py:39,44`) → crackscan never writes the history its own scoring
  needs. It cannot self-heal.
· Live gitintel cache holds 4.99 days of snapshots across 20 logins. Growth needs ≥7.
· Every admit test overrides the threshold to 0.02 (`tests/test_source_crackscan.py:115,140,
  171,192`). Nothing exercises the real 0.55. That is why this shipped broken.
· The vault already holds 176 distinct GitHub repos / 218 signals — a free seed list that
  grows daily.
· GH ARCHIVE IS FREE, no billing, no auth: POST SQL to
  `https://play.clickhouse.com/?user=play` against `github_events`. Verified working.
  BigQuery NOT required. CAVEAT: since mid-2025 the feed is almost only PushEvent, so
  stars/forks/issues/PRs are undercounted for 2025-26.
· 691,239 distinct actors pushed in the last 7 days — the raw pool.

— THE CENTRAL DESIGN CONSTRAINT (proven empirically; reject any design that violates it) —
GH ARCHIVE VOLUME RANKING IS INVERTED, NOT MERELY NOISY.
Top-5 by raw 7d PushEvent: `github-actions[bot]` 634k, an automation account 29.8k,
`renovate[bot]`, `swa-runner-app[bot]`, `pull[bot]`. Filtering bots by NAME still surfaces
mass-repo spam fingerprinted at ~1 push per repo across 200-300 repos. Filtering by depth
still surfaces automation at ~147 pushes/repo/week and AWS service accounts.
Meanwhile: `simonw` = 53 pushes / 22 repos / 17 active days over THIRTY days;
`t3dotgg` = 90 pushes / 1 repo / 24 active days. A volume leaderboard ranks spam ~30×
above Simon Willison.
THEREFORE: GH Archive is an ENRICHMENT lane over candidates already anchored by quality,
never a discovery lane ranked by volume. CONSISTENCY (active days) and LOW daily volume
distinguish real engineers; raw totals ANTI-CORRELATE with quality.
Any epic that ranks candidates by event volume is wrong on arrival.

— PRIOR ART (see `.agents/research/2026-08-26_20-36-31_vamo-and-cracked-dev-discovery.md`) —
· Vamo is index-first (ingest → query); crackscan is seed-first. Steal the ARCHITECTURE,
  not the signals — Vamo ranks on stars/followers/contribution counts, the gameable set.
· committers.top uses followers only as a coarse pre-filter, never as the ranking signal.
· OpenRank: PageRank over a contribution graph, built to counter star/contributor gaming.
· Degree of Authorship (Fritz et al., TOSEM 2014): authorship + deliveries + others' changes
  since, with logarithmic decay. Separates a 500-line feature from 100 one-line fixes.
· Truck factor (Avelino, SQJ 2019): greedy removal by authorship finds who is irreplaceable.
· Bot filtering: BoDeGHa (comment-pattern, F1 ~0.98, pip, unscoped token) and BIMAN.
  NAME-PATTERN FILTERING ALONE IS PROVABLY INSUFFICIENT — demonstrated above.
· GitHub Innovation Graph threshold-gates any metric below 100 unique developers.

— GRANTED AUTHORITY (carried forward verbatim from the cerebro-vault-site charter) —
1. VERCEL: FULL, including production deploys, on `prj_uTsBw2o1KA1EPAy1AyFYKOhIo0Ut`.
2. KIT: FULL including sending, constrained by intent — a send must be a genuine issue.
3. SHIP: self-merge to `main` on BOTH repos once verification is green.
4. ROADMAP GATE: PRE-BLESSED. Present the roadmap for the record, PushNotification once,
   then build immediately without waiting.

— CREDENTIALS —
· GitHub PAT in Bitwarden item `xyora` (keys `GITHUB_TOKEN_CRACKSCAN`, `GITHUB_TOKEN_XYORA`).
  bw creds `~/.secrets/bitwarden-credentials`, master `~/.secrets/bw-master`.
  Verified: login `xyora`, 5000 core + 5000 graphql/hr, public repo 200, user events 200.
  ⚠ SECURITY: despite being described as public-read-only it carries `admin:enterprise`,
  `admin:org`, `repo`, `workflow`, `delete:packages`. NOTHING here needs any of that.
  Use ONLY public read endpoints. Surface the recommendation to replace it at handover.
· Site `.env` (transcrypt) carries VERCEL_*, KIT_*, POSTHOG_*. here.now, gh and GPG as before.

— VERIFICATION DOCTRINE —
· Lanes: Library (the python scoring/discovery modules), API (real ClickHouse + GitHub
  queries, asserted on shape), Web UI (drive the real /cerebro/devs pages).
· Mock ONLY the human. Run the real ClickHouse queries and the real build.
· Read the artefact: assert the ACTUAL people rendered and the ACTUAL numbers, recomputed
  independently. A transparency page publishing a wrong number about a named person is worse
  than no page.
· SANITY GATE, every scoring change: run the ranking and eyeball the top 20. If it contains
  a bot, a service account, or a mass-repo spammer, the scoring is wrong — ship nothing.
· OPT-OUT GATE: prove the opt-out actually removes someone, end to end, before launch.
· Ladder: local → Vercel preview → merge → production probe on the real domain.

— STILL FORBIDDEN (any occurrence = STOP) —
· Any write/push to `cerebro-vault`.
· A full live non-`--dry-run` run of the cerebro pipeline.
· Publishing anything but public GitHub data, or any judgement of a person.
· Using a non-public-read GitHub endpoint with the xyora token.
· Launching the section without a working opt-out.
· Regressing the content-safety gate or the daily publish path.
· Force-pushing `main`, or merging on un-green verification.

— COMMIT POLICY —
Atomic single-concern conventional commits, SIGNED (-S, key 907EC78C72C6AFF6), explicit
pathspec, never `git add -A`, no AI attribution. Never commit `.agents/`, `vault-cache/`,
env files, or ANY token. Two long-lived PRs, one per repo, self-merged at the launch epic.
`beads_mode: state-only` — the cerebro repo has no `.beads/`.

— LOOP PROTOCOL (each wake) —
1. Read this charter + `.agents/scratch/cerebro-devs-state.json`.
2. Check the running workflow; on completion persist artifacts, verify commits, advance,
   launch the next stage. 3. `lease.sh refresh` EVERY wake. 4. Update state via the
   Write/Edit tool ONLY; stamp `phase_since`; publish phase explainers after SHIP/DONE.
5. ScheduleWakeup ~600-2400s, reason = current phase.
· STOP RULES: workflow errors ×2 on one stage | validation fails ×3 on one epic | any
  forbidden operation | epic > ~15M subagent tokens.
· LEASE/HOSTNAME: this machine's hostname churns. If the lease holder's SESSION token equals
  this session's id, it is STALE not CONTENDED — reclaim and continue.

— TERMINATION —
backlog-dry. No budget or deadline set. On termination: final summary, PushNotification,
stop re-arming.

— SUCCESS CRITERIA (ALL must be true) —
1. Every registry feature has a Court verdict. 2. Every blessed epic planned, reviewed,
executed, verified green, PR raised and merged. 3. Dashboard live throughout. 4. The top-20
ranking contains zero bots/service accounts/spammers, verified by eye. 5. The opt-out is
proven to work end to end. 6. `/cerebro/devs` verified live on the production domain.
