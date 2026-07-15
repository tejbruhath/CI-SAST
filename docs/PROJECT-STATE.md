---
title: Project state
source: whole repo — maintained by hand
updated: 2026-07-15
---

# Project state

> Snapshot of where Sentriq actually is: what works, what is *proven* to work,
> what is merely believed to work, and what to do next. Written to be read cold
> after time away.

**Status:** the core loop runs end to end — scan → triage → on-demand fix →
approve → one PR. The backend is verified against the live DeepSeek API and a
real repo. The frontend is **not** click-verified (see Evidence below).

## The one-paragraph version

Sentriq scans a GitHub repo with gitleaks/semgrep/trivy, normalizes every
finding to one schema, and has DeepSeek triage each as `real` /
`false_positive` / `noise`. **Nothing is patched automatically.** You click *Fix
with AI* on a finding you care about, the LLM proposes an edit, and the backend
computes the diff. You then *approve* it. Only approved fixes go into a single
pull request. Every stage writes a `ProvenanceEvent`, so the whole chain is
auditable.

## How to run it

```bash
docker compose -f deps.compose.yml up -d   # Postgres :5433, Redis :6380
./start.sh                                 # migrate + API :8000 + worker + beat + UI :3000
```

**Not** the root `docker-compose.yml` — that's the full containerised build, not
the dev path. Open http://localhost:3000 and log in with GitHub.

A backend `401` on `/api/v1/metrics` is healthy: the API is `IsAuthenticated`.

```bash
cd ci-utils
USE_SQLITE=1 .venv/bin/python manage.py test sentriq   # 24 tests
USE_SQLITE=1 .venv/bin/python smoke_test.py            # end-to-end, tools+LLM mocked
.venv/bin/python -m sentriq.deepseek                   # offline self-check
cd ../sentriq-frontend && npm run build                # the ONLY frontend check that exists
```

## What is built and working

| Area | State |
|---|---|
| Static pipeline (gitleaks, semgrep, trivy) | Working, proven on real repos (~47 findings on VaulS.ai). |
| Dynamic pipeline (zap, nuclei) | **Never completed once.** Unproven — see concerns #11. |
| Unified schema + dedup | Working, self-tested. |
| LLM triage | Working. Every finding triaged; verdict drives the STATUS column. |
| Fix generation | Working. LLM picks `old_str`/`new_str`; `difflib` builds the diff. |
| On-demand fix (`Fix with AI`) | Working, verified live (3.1s, diff applied clean). |
| Approval gate | Working, test-pinned: unapproved fixes cannot reach a PR. |
| Batch PR (one branch, all approved) | Working, mock-tested. **Not yet run against real GitHub.** |
| GitHub OAuth login | Working. 8h sliding sessions, token revoked on logout. |
| ASPM metrics panel | Wired (it existed but was rendered nowhere until 2026-07-15). |
| Assets tab | Real (repo list + severity rollup). |
| Orphan scan reaper | Working, on worker boot **and** a 10-min beat schedule. |

## Evidence — what is actually proven

This section exists because "it builds" is not "it works".

**Proven by running it:**
- Fix diffs apply. Measured: **12/12** regenerated patches passed
  `git apply --check` against the real scanned repo (previously **0/18**).
- On-demand fix through the live worker + live DeepSeek: task succeeded in
  3.1s, produced an applyable diff, stored `approved`.
- Auth returns 401 (not 403) unauthenticated — checked against the running server.
- The list API genuinely omits `triage`/`details`; the detail API includes them
  (this asymmetry caused a real bug — see below).
- 24 backend tests, smoke test, and three module self-checks pass.

**NOT proven — believed only:**
- **Every frontend interaction.** The dialog-race fix, tab routing, scroll
  containment, the approve flow, and the PR dialog are build-verified and
  reasoned, never clicked. No Chrome extension available; headless automation
  dead-ends on the OAuth-gated repo picker. This is the weakest evidence in the
  repo (concerns #17).
- **Batch PR against real GitHub.** Mock-tested only; never opened a real PR.
- **The dynamic pipeline.** The only attempt is a 23-hour zombie.

## Decisions worth not re-litigating

- **The LLM never authors a diff.** It returns `old_str`/`new_str` and `difflib`
  computes the patch. Asking the model for a unified diff gave a **100%**
  `git apply` failure rate — it invents hunk headers, and for SCA findings
  (`line=None`) it invented whole files. An LLM cannot count lines. This is the
  single most important design fact in the codebase.
- **Anchors fail closed.** `old_str` must appear exactly once or the fix is
  rejected. A rejected fix is cheap; a corrupting patch in a security PR is not.
- **Session cookies, not JWT.** For a same-site SPA, httpOnly session cookies
  are strictly safer than JWT in localStorage (XSS can't read them; CSRF is
  handled). JWT here would be a downgrade dressed as hardening.
- **No automatic fixes.** `auto_fix_severity` defaults to `"none"` in *both* the
  API and the UI form. These two must never drift — when they did, scans made
  `proposed` fixes no UI could approve and every PR attempt 409'd.
- **Approval is consent.** A fix *existing* is the AI's opinion; approving it is
  the user's decision. Create PR is gated on approval, never on existence.
- **Polling, not SSE.** Webhooks are the wrong tool (server→server, can't reach
  a browser). SSE is right but forces ASGI. At one user, 3s polling is fine.
  Revisit when concurrency hurts, not before.
- **Findings are hidden until the scan completes**, because triage runs at the
  end. Combined with the serial LLM loop, that means minutes of empty dashboard
  on a big repo — a known trade-off, not an accident.

## Bugs found and fixed (2026-07-14/15)

Kept as a record of *how* things broke, since the same mistakes recur.

1. **0/18 AI patches applied.** LLM authored diffs by hand. Root cause, not
   symptom: it never saw the file. → `old_str`/`new_str` + `difflib`.
2. **`auto_fix_severity="none"` silently disabled ALL triage** — an early
   `return` sat above the triage loop, so "don't auto-fix" meant "no AI at all".
3. **A triaged finding read "Not triaged yet."** The 3s poll merged a *list* row
   (no `triage` field) into the open dialog. The same stale-closure write made a
   closed dialog reopen and showed row 1 when you clicked row 2. → selection is
   an id; detail is fetched with an `alive` guard.
4. **`start.sh` never started a Celery worker**, so `run_scan.delay()` was a
   no-op and scans never left "queued".
5. **A scan sat "RUNNING" for 23 hours.** Killing the worker leaves the row
   orphaned forever; nothing reaped it. Redis had no persistence, so recreating
   the container silently dropped queued work. → reaper + appendonly Redis.
6. **409 "approve the fix before opening a PR" with no approve button.** The
   approve UI had been removed while scans still produced `proposed` fixes.
7. **`src/mocks/` broke the Vite build** — it imported four `./data/*.js` files
   that were never committed, so mock mode had never worked a single day.
8. **`MetricsPanel` was built and rendered nowhere.** A whole feature (ASPM,
   Task A10) unreachable from the UI.
9. **PRs opened with a shared PAT**, attributing every PR to the PAT's owner
   regardless of who clicked. → acting user's OAuth token, PAT as fallback.

## What to do next

Roughly in value order. Full detail and cost in [concerns](concerns.md).

1. **Click through the UI once** and confirm the approve → PR flow. It is the
   single biggest unknown (concerns #17).
2. **Open one real PR** to prove `create_batch_pr` against live GitHub.
3. **Parallelize triage** (concerns #10). It is a serial loop of ~60 LLM calls;
   minutes of empty dashboard. Biggest UX win available, and not small.
4. **Prove or delete the dynamic pipeline** (concerns #11).
5. **Decide the HITL surface's fate** (concerns #14) — `/hitl` is now used only
   by the approve button; the deny/edit paths are UI-less.
6. **Frontend tests** (concerns #16). There are none at all.

## Map of the code

```
ci-utils/                 Django backend
  sentriq/
    schema.py             the Finding contract (start here)
    adapters/             one per scanner
    executor.py           docker run, git clone/apply/push
    aggregator.py         dedup
    deepseek.py           triage + fix (read the diff-authoring note)
    tasks.py              Celery: run_scan, generate_fix, create_pr,
                          create_batch_pr, reap_orphaned_scans
    views.py / urls.py    DRF API
    auth_views.py         GitHub OAuth + session hardening
    models.py             Postgres system of record
sentriq-frontend/src/     React dashboard (App.jsx holds all state)
docs/                     this doc set
deps.compose.yml          Postgres + Redis only — the dev path
start.sh                  runs everything locally
```
