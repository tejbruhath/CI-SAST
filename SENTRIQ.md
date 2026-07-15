# Sentriq — AI Security Remediation Pipeline

Sentriq scans code and running apps with multiple security tools, normalizes
every finding into one schema, uses an LLM (DeepSeek) to triage real-vs-false
and propose fixes, and surfaces it all in a dashboard with a human approval
gate. This is the **core single-pipeline loop** from the `sentriq_md/`
architecture — runnable end to end, backend + frontend, no Kubernetes.

## What's in this build

| Stage | Implementation |
|---|---|
| Scanners | gitleaks (secrets), semgrep (SAST), trivy (SCA) — *static*; OWASP ZAP baseline + nuclei — *dynamic*. Each is a self-contained **adapter** (`ci-utils/sentriq/adapters/`) that runs the tool's official container and normalizes its output. |
| Unified schema | `sentriq/schema.py` — the one `Finding` shape everything speaks (Task A1). |
| Aggregate + dedup | `sentriq/aggregator.py` — fingerprint + semantic (type·file·line) dedup across tools (Tasks B2/B3). |
| LLM triage | `sentriq/deepseek.py` — DeepSeek `deepseek-v4-flash`, JSON-mode; classifies real / false_positive / noise with a citation (Task B4). |
| Fix generation | Same module — the LLM names the exact text to replace and `difflib` computes the unified diff against the real file, so patches actually apply (Tasks B6/B7, minus the AST-RAG context retriever). |
| Orchestration | `sentriq/tasks.py` — Celery: `run_scan` (clone → tools → normalize → dedup → persist → triage), plus `generate_fix` (on demand), `create_batch_pr` (one PR of approved fixes) and `reap_orphaned_scans`. Replaces the old k8s-Job dispatcher. |
| Persistence | Postgres via Django models: Scan, Finding, Triage, FixSuggestion, HitlAction, ProvenanceEvent (A8 provenance store). |
| API | DRF (`/api/v1/`), GitHub-OAuth session auth: scans, findings, on-demand fix, approval, batch PR, provenance, ASPM metrics. |
| Frontend | `sentriq-frontend/` — React/Vite dashboard: submit scans, browse/filter findings by AI verdict, request a fix per finding, review the diff, approve it, and ship every approved fix as one PR. ASPM metrics + assets (Tasks A9/A10). |

### Deliberately deferred (from the full architecture)
IAST, continuous fuzzing, the AST-aware RAG context retriever, real SCM PR
automation, cross-pipeline (CI+CD) correlation UI, and the entire SaaS layer
(multi-tenancy, billing, agent model, BYOK). The pipeline is structured so
these are additive.

## Architecture at a glance
```
POST /api/v1/scans {pipeline, target}
   → Celery run_scan
       static:  git clone → gitleaks + semgrep + trivy   (docker run each)
       dynamic: ZAP baseline + nuclei against target URL
   → adapters normalize native output → unified Findings
   → aggregate + dedup → persist (Postgres)
   → DeepSeek triage each finding (real/FP/noise + citation)
   → NO patch is written automatically (auto_fix_severity defaults to "none")
   → provenance event written at every stage
User clicks "Fix with AI" on a finding  → POST /findings/{id}/fix
   → DeepSeek picks old_str/new_str → difflib builds the diff
User approves it                        → POST /findings/{id}/hitl
User clicks "Create PR"                 → POST /pr → ONE branch + ONE PR
                                           carrying only the approved fixes
```

Scanners run as their **official Docker images** via the host daemon (the
worker mounts `/var/run/docker.sock`) — no k8s, no bespoke tool images.

## Run it (local dev — the normal path)
```bash
cp .env.example .env       # fill in DEEPSEEK_API_KEY + the GitHub OAuth app
docker compose -f deps.compose.yml up -d   # Postgres :5433, Redis :6380
./start.sh                                 # migrate + API :8000 + worker + beat + UI :3000
```
- Frontend: http://localhost:3000 — log in with GitHub, pick a repo, scan.
- API: http://localhost:8000/api/v1/ (a `401` here is healthy: auth required)
- First run pulls the scanner images on demand, so the first scan of each type
  is slower.

`start.sh` runs the Celery **worker and beat** as well as the API — without the
worker, scans are dispatched with `.delay()` and never leave "queued".

Set `LLM_ENABLED=false` in `.env` to run scanners without spending DeepSeek
tokens. **No fixes are generated automatically**: a scan triages everything,
then you click *Fix with AI* on what matters.

The root `docker-compose.yml` is the full containerised build, not the dev path.

**New here, or back after a while? Read [docs/PROJECT-STATE.md](docs/PROJECT-STATE.md)** —
what works, what's proven, what's next — and [docs/concerns.md](docs/concerns.md)
for the known gaps.

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/scans` | submit a scan `{pipeline: static\|dynamic, target, ref?}` |
| GET | `/api/v1/scans` · `/scans/{id}` | list / detail |
| GET | `/api/v1/findings` | filter: `severity, tool, type, verdict, scan` |
| GET | `/api/v1/findings/{id}` | detail incl. triage, fixes, HITL history |
| POST | `/api/v1/findings/{id}/fix` | generate an AI fix on demand (202) |
| POST | `/api/v1/findings/{id}/hitl` | `{action: approve\|deny\|edit, note?, edited_diff?}` |
| POST | `/api/v1/pr` | `{repo}` — ONE PR with every **approved** fix |
| GET | `/api/v1/provenance?scan=` | append-only audit trail |
| GET | `/api/v1/metrics` | ASPM rollup |

## Local dev without Docker
```bash
cd ci-utils && python -m venv .venv && .venv/bin/pip install -r requirements.txt
USE_SQLITE=1 .venv/bin/python manage.py migrate
USE_SQLITE=1 .venv/bin/python manage.py test tests     # 24 tests
USE_SQLITE=1 .venv/bin/python smoke_test.py     # end-to-end pipeline test (tools + LLM mocked)
```
Component self-tests: `python -m sentriq.schema`, `python -m sentriq.aggregator`,
`python -m sentriq.adapters.<tool>`.

## Provenance / build note
The three dynamic-analysis-adjacent adapters (semgrep, zap, nuclei) were built
in parallel by delegated `opencode` (kimi-k2.7-code) instances against the
`schema.py` + adapter-interface contract; gitleaks and trivy were ported from
the proven ci-utils aggregator. All five pass their self-tests.
