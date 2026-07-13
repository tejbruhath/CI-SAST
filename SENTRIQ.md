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
| Fix generation | Same module — unified-diff patch for real, high-severity findings (Tasks B6/B7, minus the AST-RAG context retriever). |
| Orchestration | `sentriq/tasks.py` — Celery chain: clone → run tools locally → normalize → dedup → persist → triage → fix. Replaces the old k8s-Job dispatcher. |
| Persistence | Postgres via Django models: Scan, Finding, Triage, FixSuggestion, HitlAction, ProvenanceEvent (A8 provenance store). |
| API | DRF (`/api/v1/`): scans, findings, HITL gate, provenance, ASPM metrics. |
| Frontend | `sentriq-frontend/` — React/Vite dashboard: submit scans, browse/filter findings, view triage + fix diff, approve/deny/edit (HITL), ASPM metrics (Tasks A9/A10). |

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
   → DeepSeek fix patch for real & severity >= FIX_MIN_SEVERITY
   → provenance event written at every stage
Frontend polls /findings, /metrics; HITL approve/deny/edit → /findings/{id}/hitl
```

Scanners run as their **official Docker images** via the host daemon (the
worker mounts `/var/run/docker.sock`) — no k8s, no bespoke tool images.

## Run it
```bash
cp .env.example .env       # already provided; DeepSeek key is a throwaway — ROTATE IT
# HOST_DATA_DIR must be an absolute path (default /tmp/sentriq-data). See the
# DinD note in docker-compose.yml for why host and worker share the same path.
docker compose up --build
```
- Frontend: http://localhost:3000
- API: http://localhost:8080/api/v1/
- First run pulls the five scanner images on demand (first scan of each type is
  slower while images download).

Submit a static scan with a public git URL, or a dynamic scan with a target
URL. Set `LLM_ENABLED=false` in `.env` to run scanners without spending DeepSeek
tokens.

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/scans` | submit a scan `{pipeline: static\|dynamic, target, ref?}` |
| GET | `/api/v1/scans` · `/scans/{id}` | list / detail |
| GET | `/api/v1/findings` | filter: `severity, tool, type, verdict, scan` |
| GET | `/api/v1/findings/{id}` | detail incl. triage, fixes, HITL history |
| POST | `/api/v1/findings/{id}/hitl` | `{action: approve\|deny\|edit, note?, edited_diff?}` |
| GET | `/api/v1/provenance?scan=` | append-only audit trail |
| GET | `/api/v1/metrics` | ASPM rollup |

## Local dev without Docker
```bash
cd ci-utils && python -m venv .venv && .venv/bin/pip install -r requirements.txt
USE_SQLITE=1 .venv/bin/python manage.py migrate
USE_SQLITE=1 .venv/bin/python smoke_test.py     # end-to-end pipeline test (tools + LLM mocked)
```
Component self-tests: `python -m sentriq.schema`, `python -m sentriq.aggregator`,
`python -m sentriq.adapters.<tool>`.

## Provenance / build note
The three dynamic-analysis-adjacent adapters (semgrep, zap, nuclei) were built
in parallel by delegated `opencode` (kimi-k2.7-code) instances against the
`schema.py` + adapter-interface contract; gitleaks and trivy were ported from
the proven ci-utils aggregator. All five pass their self-tests.
