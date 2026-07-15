---
title: Sentriq docs — index
source: docs/
---

# Sentriq docs

Read in this order if you're new. Each doc quotes the real source it covers, so
if a quote and the code disagree, **the code is right and the doc is a bug**.

## Start here

| Doc | What it covers |
|---|---|
| [PROJECT-STATE](PROJECT-STATE.md) | **Where the project actually is** — what works, what's proven, what's unverified, what's next. Read this first after time away. |
| [concerns](concerns.md) | Every known gap and risk, with cost-to-fix. The honest list. |
| [00-overview](00-overview.md) | The pipeline end to end. |

## The pipeline, in order of data flow

| Doc | Component |
|---|---|
| [01-schema](01-schema.md) | The unified `Finding` shape everything speaks. |
| [02-adapters](02-adapters.md) | Per-tool adapters (gitleaks, semgrep, trivy, zap, nuclei). |
| [03-executor](03-executor.md) | Running scanners as Docker containers; clone/apply/push. |
| [04-aggregator](04-aggregator.md) | Fingerprint + semantic dedup across tools. |
| [05-deepseek](05-deepseek.md) | LLM triage + fix generation. **Read the diff-authoring trap.** |
| [06-data-model](06-data-model.md) | Postgres models: Scan, Finding, Triage, FixSuggestion, Provenance. |
| [07-orchestration](07-orchestration.md) | The Celery tasks that drive it all. |
| [08-api](08-api.md) | DRF endpoints. |
| [09-frontend](09-frontend.md) | React dashboard and the approval gate. |
| [10-deployment](10-deployment.md) | Deployment + configuration. |

## Conventions

- [_STYLE.md](_STYLE.md) — the required structure for every component doc.
  Read it before writing one.
- Docs quote **real code verbatim**. Don't invent snippets.
- Anything unproven belongs in [concerns](concerns.md), not glossed over.
