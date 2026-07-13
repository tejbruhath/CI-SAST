# Sentriq SaaS

The current architecture is a single-tenant self-hosted pipeline. SaaS requires fundamental changes across three dimensions: **infrastructure model, data model, and business layer.** Here's the full delta.

---

## 1. The Biggest Structural Change — Agent Model

Right now scanners run inside the customer's CI. For SaaS you cannot own the customer's CI/CD runner. You also cannot ask customers to send raw source code to your servers — no security-conscious company will agree to that.

The answer is an **agent model:**

```
Current:
  Customer CI → scanners run → findings → your pipeline (self-hosted)

SaaS:
  Customer CI → lightweight agent runs scanners locally
             → agent ships only SARIF findings to your API
             → your platform processes findings, generates fixes
             → fix patches sent back to agent
             → agent raises PR via customer's SCM token
```

Customer code never leaves their environment. You only ever see SARIF output and the specific vulnerable code snippets needed for fix generation — scoped, minimal, encrypted in transit.

This is how Snyk, GitGuardian, and Semgrep Cloud all work.

---

## 2. Multi-tenancy Everywhere

Every component in the current architecture is single-tenant. Each needs a `tenant_id` scope:

| Component | Change needed |
| --- | --- |
| RAG Corpus | Shared public corpus (CVE/CWE/OWASP) + isolated per-tenant codebase index |
| Provenance Store | Partition by tenant. No cross-tenant reads ever. |
| ASPM Dashboard | Per-tenant view with RBAC |
| Vector Store | Namespace isolation per tenant |
| LLM calls | Per-tenant token budget + cost tracking |
| Fix Generator | Per-tenant configuration (thresholds, which models, which scanners) |

---

## 3. New Components Required

**SCM Abstraction Layer**
Current architecture is GitLab-native. SaaS needs to support GitHub, GitLab, Bitbucket, Azure DevOps. Abstract all SCM calls behind a provider interface so pipeline logic is SCM-agnostic.

```
SCMProvider interface:
  - create_pr(tenant, branch, diff)
  - get_file(tenant, path, ref)
  - post_comment(tenant, pr_id, body)
  - list_repos(tenant)
```

**Webhook Receiver + API Gateway**
Replace GitLab CI trigger with an inbound webhook endpoint. Customer's CI POSTs SARIF to your API. You process async, respond via SCM API.

```
POST /api/v1/scan
  → auth (tenant API key)
  → SARIF payload
  → enqueue to pipeline
  → async processing
  → fix patch returned via SCM API
```

**Onboarding Flow**
OAuth App install on GitHub/GitLab → repo selection → webhook setup → first scan. Must be under 5 minutes to first finding. This is your activation metric.

**Billing + Metering Layer**
Stripe for billing. Usage tracking per tenant: scans/month, findings processed, LLM tokens consumed, PRs raised. This directly controls your margins because LLM costs will be your largest variable cost.

**BYOK (Bring Your Own Key)**
Enterprise customers will not let you route their code context through your LLM API calls. They want to use their own Claude/OpenAI/Azure OpenAI keys. Your model router needs to support customer-supplied API keys as a first-class option.

**SOC2 Compliance Layer**
Not optional for enterprise sales. Requires:

- Encryption at rest + in transit everywhere
- Access logging on all tenant data reads
- Data retention policies
- Penetration test report
- Vendor risk questionnaire answers

This is 6–12 months of work to get Type II certification. Start the audit period early.

---

## 4. Pricing Model

Three tiers is standard for this market:

```
Free
  Public / OSS repos only
  SAST + SCA only (no DAST/IAST)
  Community models only (no Claude routing)
  Limited findings/month
  → Drives adoption, builds trust

Pro  ($X/seat/month or $Y/repo/month)
  Private repos
  Full scanner suite
  Full model routing
  ASPM dashboard
  → Your primary revenue driver

Enterprise  (custom contract)
  SSO / SAML
  BYOK for LLMs
  On-prem / VPC deployment option
  SOC2 report + SLA
  Dedicated support
  → High ACV, long sales cycle
```

---

## 5. The "Access to Customer Code" Problem for Fix Generation

The fix generator needs the vulnerable file, callers, imports. In the agent model, you never have the full codebase. You need to solve this:

**Option A — Agent fetches context locally**
The agent runs context assembly (AST-aware RAG) locally on the customer's machine, then ships the assembled context bundle (not the full codebase) to your fix generator. Your LLM only sees the minimal required snippet.

**Option B — Encrypted ephemeral compute**
Customer code sent encrypted, processed in isolated compute, deleted after patch generation. Requires strong trust and SOC2 evidence.

**Option A is correct for most customers.** Keep code on their infrastructure, ship only what the LLM needs.

---

## 6. What the SaaS Architecture Looks Like

```
CUSTOMER ENVIRONMENT
  CI/CD Pipeline
      ↓
  GitguardAI Agent
  (runs scanners locally, assembles context, ships SARIF + context bundles)
      ↓
      ↓ HTTPS — SARIF + minimal context bundle
      ↓

YOUR INFRASTRUCTURE
  API Gateway + Webhook Receiver
      ↓
  Auth + Tenant Resolution
      ↓
  [Existing pipeline — fully multi-tenant]
  Triage → Segregator → Router → Fix Generator → HITL
      ↓
  Patch diff + PR instructions
      ↓
      ↓ SCM API (GitHub/GitLab/Bitbucket)
      ↓

CUSTOMER ENVIRONMENT
  PR raised on customer's repo
  Dev reviews in their HITL interface
      ↓
  ASPM Dashboard (your hosted UI, per-tenant)
```

---

## 7. What Does Not Change

The core pipeline logic — SARIF normalization, triage, segregator, router, fix generator, validation loop, provenance store, ASPM — stays architecturally identical. You're wrapping it with a multi-tenant API surface and replacing the CI trigger with a webhook receiver.

The pipeline is already well-designed for this. The SaaS layer is additive, not a redesign.

---

## The One Thing That Will Kill You If You Get It Wrong

**LLM cost per tenant.** Claude calls for complex fix generation are expensive. At scale, if you're not tracking cost per scan per tenant and enforcing budgets, you will run negative margins on Pro tier customers. Build usage metering and per-tenant LLM budgets from day one, not as an afterthought.

---

**TL;DR:** Three structural changes for SaaS — agent model (code never leaves customer), multi-tenant data layer everywhere, and a new business surface (SCM abstraction, webhook receiver, billing, onboarding, BYOK). The core pipeline architecture doesn't change. The hardest non-technical problem is SOC2 compliance, which gates enterprise sales. Start the audit period early.