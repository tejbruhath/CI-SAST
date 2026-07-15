---
title: Known concerns & open risks
source: whole repo — maintained by hand, not generated
updated: 2026-07-15
---

# Known concerns & open risks

> Things that are wrong, unproven, or deliberately deferred. Written down so they
> are decisions rather than surprises. Each entry says what's wrong, why it
> matters, and what fixing it costs.

Ordered by "how badly would this bite us", not by area.

## Security

### 1. PRs are opened with a shared PAT, not the acting user's token
`scm.py` authenticates every PR with `SENTRIQ_GIT_TOKEN` (a `repo`-scope PAT):

```python
if not config.GIT_TOKEN:
    raise ScmError("SENTRIQ_GIT_TOKEN is not set — cannot open a PR")
return {"Authorization": f"Bearer {config.GIT_TOKEN}", ...}
```

Every PR is therefore authored by whoever owns that PAT, no matter who clicked
the button, and that one credential can write to every repo it can see. The
acting user's OAuth token is **already stored** (encrypted, `repo` scope) on
`UserProfile.github_access_token` — the PR should use it.

Invisible today because there is one user and both credentials are theirs. It
becomes a correctness *and* attribution bug the moment a second person logs in.

**Fix:** thread the requesting user through `create_pr` and use their decrypted
token in `scm`. Medium: `create_pr` is a Celery task, so it needs a `user_id`
argument rather than `request.user`.

### 2. Repository source code is sent to a third party
Triage sends a code snippet, and fix generation sends **the whole file**
(windowed at 12k chars) to DeepSeek's API. For private repos this is real data
egress to a third party, and it is not disclosed anywhere in the UI.

**Fix:** at minimum, say so plainly in the UI/README. Properly: a per-repo
opt-out, and/or a self-hosted model. `LLM_ENABLED=false` already disables both
stages if you need a hard off switch.

### 3. Secrets live in `.env` next to what they protect
`TOKEN_ENCRYPTION_KEY` encrypts the stored GitHub tokens, but sits in the same
`.env` as `POSTGRES_PASSWORD`. Anyone who can read `.env` can read the DB *and*
decrypt every user's GitHub token — the encryption buys nothing against that
attacker. It only protects against a DB-only leak (a stolen dump/backup), which
is a real but narrow threat.

**Fix (prod only):** a real secret manager / KMS. `.env` is correctly gitignored
and is fine for local dev.

### 4. The DeepSeek key in `.env` is a throwaway that still needs rotating
`SENTRIQ.md` says "DeepSeek key is a throwaway — ROTATE IT". It is still live and
still in `.env`. It is not in git history (`.env` is untracked), so this is a
low-grade item, but it was shared in a build context.

### 5. Scanners run via the host Docker socket
The worker mounts `/var/run/docker.sock` and `docker run`s each scanner. Anything
that escapes a scanner container gets **root on the host**, and we run
third-party images against untrusted repo contents. Accepted trade-off for local
dev (it's what removed the k8s dependency); it must not ship to a shared host as
is.

### 6. No cost ceiling on "Fix with AI"
Each click is an LLM call that clones the repo and burns tokens. Nothing rate
limits it, per-user or globally. A held-down button is a bill.

**Fix:** cheap — a per-user/per-finding throttle, or DRF's built-in
`ScopedRateThrottle`.

### 7. `SESSION_COOKIE_SECURE` defaults to false
Correct for local HTTP dev, wrong anywhere with TLS. It is env-driven
(`SESSION_COOKIE_SECURE=true`), so this is a deployment checklist item, not a
code bug.

## Correctness & reliability

### 8. The orphan reaper only runs on worker boot
`reap_orphaned_scans` is wired to celery's `worker_ready` signal. That covers the
common case (worker restarts, stale rows get cleaned), but if a worker dies and
is never restarted, scans stay `RUNNING` forever — exactly the 23-hour zombie
that started this. Nothing reaps on a schedule.

**Fix:** celery beat with a periodic schedule. Small, but adds a beat process to
run.

### 9. Redis has no persistence volume
`deps.compose.yml` runs `redis:7-alpine` with no volume. Any `docker compose
down`/recreate silently drops every queued task while the Postgres rows survive —
manufacturing orphans. The reaper now catches them *after* `CELERY_TASK_TIME_LIMIT`
(1h), but the work is still lost, silently.

**Fix:** add a volume + `appendonly yes`, or accept it and rely on the reaper.
Worth noting the failure is *silent* — no user-visible signal that a scan died.

### 10. ~~Triage is a serial LLM loop~~ — fixed 2026-07-15
`_triage_and_fix` used to iterate findings one at a time, one blocking HTTP
call each. Now it batches findings in groups of `TRIAGE_BATCH_SIZE` (100,
DeepSeek's concurrent-request ceiling) and fans each batch out across a
`ThreadPoolExecutor` — worker threads do only the DeepSeek HTTP calls, no ORM
access, so there's no per-thread DB connection leak and it stays test-safe
under `TestCase`'s transaction wrapping. `Scan.triage_total`/`triage_done` are
saved after each batch. Findings are still gated behind the whole scan
finishing (that part of this concern is now tracked as #15), but the wait
itself is ~100x shorter for a same-sized repo and the dashboard now shows an
"AI TRIAGE RUNNING: done/total" indicator (`QueueStatus.jsx`) instead of going
quiet.

### 11. The dynamic pipeline has never completed successfully
The only dynamic scan ever attempted (`c750ce07`) is the zombie. The `nuclei`
image isn't even pulled locally. ZAP + nuclei adapters pass their unit
self-tests, but the end-to-end dynamic path is **unproven**. Treat "dynamic
works" as an unverified claim.

### 12. "Edit on GitHub" only appears after a PR exists
The button builds `https://github.dev/<owner>/<repo>/blob/<branch>/<file>#L<line>`,
which needs the fix branch to exist on GitHub. `fix.branch` is only set inside
`create_pr`. So the intended flow — *click Edit, land on the file with the fix
already applied and the cursor on the line* — only works **after** Create PR.

There is no way around this: you cannot pre-load a patch into Codespaces/github.dev
via URL. The options are (a) push the branch at fix-generation time (a clone +
push per fix — slow and litters the remote with branches), or (b) keep it
post-PR. Currently (b), and the button is simply hidden until then.

### 13. Sidebar "Create PR" picks the finding for you
It fires PR creation for the first finding that has a fix, rather than one you
chose. With several fixes ready, which one it picks is not obvious from the UI.

**Fix:** make it open a picker, or scope it to the selected finding.

### 14. The HITL surface is now dead code
`POST /findings/{id}/hitl`, the `HitlAction` model, and `api.js`'s `hitl()` still
exist, but no UI calls them — the approve/deny/edit gate was removed in favour of
"clicking Fix with AI is the approval". Dead endpoints are attack surface and rot.

**Fix:** delete them, or wire an explicit review step back in. Decide, don't drift.

### 15. Findings are hidden until the whole scan completes
By design (you asked for it): the list filters to
`scan__status__in=[complete, partial, failed]`. The consequence is that a scan
which never completes shows **nothing** — no partial results, and no explanation
in the UI. Combined with #10, a big repo means minutes of an empty dashboard.

### 23. AI-picked fix versions have no live source of truth
`deepseek.generate_fix` uses one system prompt (`FIX_SYSTEM`) for every finding
type: "propose the minimal edit that fixes it." For a code-level finding (SQLi
in our own code, a missing sanitizer) that framing is right. For a
dependency-version finding (Trivy flagging `Django==4.2.13` for CVE-2024-42005)
it is wrong: the model named `4.2.15` — the version where that specific CVE's
changelog entry landed, straight from training-data memory. It shipped in a
real PR (`tejbruhath/VaulS.ai#2`) and CodeRabbit's OSV-Scanner pass on that PR
flagged it: `4.2.15` itself carries dozens of later CVEs, and the whole 4.2 LTS
line reached end-of-life in April 2026 (final release `4.2.30`). "Minimal
version bump that resolves the named CVE" and "current secure version" are
different questions, and only an LLM with zero live data was asked to answer
one of them by guessing at the other.

**Fix:** split the fix-prompt on finding type. Dependency/SCA findings
(Trivy, etc.) should resolve the target version from a live source — PyPI's
simple API, or OSV's `fixed` range for the package — and hand the LLM only the
old_str/new_str mechanics against that resolved version. Code-edit findings
keep the current LLM-only path; there's no freshness problem there. Small: one
new lookup function, one branch in `generate_fix`.

**Broader lesson:** don't ask an LLM a question that has a live, checkable
answer. Detection (OSV-Scanner's fixed-range data) and remediation (picking a
replacement version) are different problems; only the first is safe to
delegate to a model with a training cutoff.

### 24. `metrics` ignored `?repo=` — one repo's dashboard showed another's totals
`GET /api/v1/metrics` never took a `repo` param, unlike `/scans` and
`/findings`, which both filter on `scan__target__icontains=repo`. Every repo's
dashboard showed the same account-wide totals (findings, critical/high, scans,
fixes proposed/approved) while the findings table below it was correctly
scoped — a silent mismatch, not an error, so it read as "this repo has 94
findings" when the live table said zero. Fixed 2026-07-15: `metrics()` now
filters `all_findings`/`scans_qs`/`own_fixes` on `repo` when the query param is
present; `api.js` and `App.jsx` now pass the selected repo through.

## Testing gaps

### 16. The frontend has no tests at all
No vitest, no testing-library, no Playwright. Every frontend change in this repo
is verified by `npm run build` succeeding — which proves imports resolve and
nothing more. Zero assertions about behaviour.

### 17. The dashboard interaction fixes were never clicked
The dialog-race fix (stale poll reopening a closed dialog / showing the previous
row), the tab routing, and the scroll containment are **reasoned and
build-verified, not observed**. The Chrome extension isn't connected here, and
headless automation dead-ends on the OAuth-gated repo picker. This is the
weakest evidence in the repo — treat those fixes as unconfirmed until someone
clicks through.

### 18. On-demand fix generation is only mock-tested
`test_fixapi.py` mocks `deepseek.generate_fix` and the executor. The real path
(clone → read file → LLM → applyable diff) was verified manually against the
live API (12/12 patches applied), but nothing automated covers it, and that
manual run predates the on-demand task.

## Architecture notes

### 19. Polling, and whether SSE is worth it
The dashboard polls 3 endpoints every 3s, plus the open finding's detail. At one
user this is genuinely fine. **Webhooks are the wrong tool** — they're
server→server (GitHub→us) and cannot push to a browser. **SSE is the right tool**
for scan progress and triage/fix landing, but it forces the backend to ASGI: a
sync gunicorn worker is pinned for the life of every open stream. Not worth it
until there are enough concurrent users for polling to actually hurt.

### 20. There is no pagination at all — just a silent hard slice
`REST_FRAMEWORK` configures `LimitOffsetPagination` with `PAGE_SIZE=100`, which
reads like pagination exists. **It does not.** Those settings only apply to
generic/ViewSet views, and every view here is a plain `@api_view` function, so
the setting is inert. What actually limits the response is a hardcoded slice:

```python
return Response(FindingListSerializer(qs[:500], many=True).data)   # findings
return Response(ScanSerializer(qs[:100], many=True).data)          # scans
return Response(ProvenanceSerializer(qs[:500], many=True).data)    # provenance
```

Past those limits, rows are dropped with no `next` link, no count, and no signal
to the client. A repo with >500 findings silently shows 500. Not urgent (a scan
currently yields ~47), but it is a silent-truncation bug, and the misleading
settings make it look solved.

**Fix:** either wire real pagination (DRF's `paginate_queryset` in the function
views) or drop the inert `PAGE_SIZE`/`DEFAULT_PAGINATION_CLASS` settings so the
config stops lying.

### 21. The verdict filter's "pending" option matches nothing
`FindingsTable` offers `VERDICTS = [..., "pending"]` in the filter dropdown, and
the view does:

```python
if verdict:
    qs = qs.filter(triage__verdict=verdict)
```

No `Triage` row is ever written with verdict `pending` — the model's default is
never used because `_triage_and_fix` always supplies a real verdict (or
`error`). An untriaged finding has **no Triage row at all**, so "pending" should
mean `triage__isnull=True`. As written, selecting *pending* always returns an
empty list.

**Fix:** map `pending` → `filter(triage__isnull=True)` and expose `error` in the
dropdown (that verdict is real and currently unfilterable). Small.

### 22. Logging out on one device breaks the others
Logout now revokes the GitHub token and blanks
`UserProfile.github_access_token` — good for "strict logout", but the token is
per-*user*, not per-session. If you're logged in on two browsers, logging out of
one leaves the other with a live Django session whose GitHub token is gone:
`/repos` starts returning 401 "GitHub account not connected" while the UI still
believes you're signed in.

**Fix:** either store tokens per-session, or on logout flush *all* of that user's
sessions (`Session.objects` filtered by `_auth_user_id`) so the state stays
consistent. Low impact at one user, genuinely confusing at more.
