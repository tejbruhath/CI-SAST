import { mockUser } from "./data/user.js";
import { mockRepos } from "./data/repos.js";
import { initialScans } from "./data/scans.js";
import { initialFindings } from "./data/findings.js";

// ---------------------------------------------------------------------------
// In-memory mock state
// ---------------------------------------------------------------------------
let currentUser = null; // set on login
let scans = JSON.parse(JSON.stringify(initialScans));
let findings = JSON.parse(JSON.stringify(initialFindings));
let nextScanId = 100;
let nextFindingId = 100;
let nextFixId = 100;
let nextHitlId = 100;

// Pre-canned finding templates for newly completed scans
const findingTemplates = [
  {
    tool: "gitleaks",
    pipeline: "static",
    type: "secret",
    severity: "critical",
    severity_score: 4,
    rule_id: "aws-access-key",
    message: "AWS Access Key ID exposed in configuration",
    file: "config/prod.yml",
    line: 14,
    details: { secret_type: "aws-access-key", entropy: 4.7, match: "AKIA..." },
    triage: {
      verdict: "real",
      confidence: 0.94,
      rationale: "High-entropy AWS key assigned to a config variable.",
      citation: { rule: "aws-access-key", file: "config/prod.yml", line: 14, why: "entropy + context" },
      model: "deepseek-v4-flash",
    },
    fix: {
      diff:
        '--- a/config/prod.yml\n+++ b/config/prod.yml\n@@ -11,7 +11,7 @@\n aws:\n-  access_key_id: "AKIA..."\n+  access_key_id: "${AWS_ACCESS_KEY_ID}"\n',
      explanation: "Replace hardcoded key with environment variable reference.",
    },
  },
  {
    tool: "semgrep",
    pipeline: "static",
    type: "sast",
    severity: "high",
    severity_score: 3,
    rule_id: "python.django.security.injection.sql.sql-injection",
    message: "User input flows into a raw SQL query",
    file: "src/db/query.js",
    line: 42,
    details: { cwe: ["CWE-89"], owasp: ["A03:2021 - Injection"], category: "security" },
    triage: {
      verdict: "real",
      confidence: 0.91,
      rationale: "Unparameterized query with user input.",
      citation: { rule: "sql-injection", file: "src/db/query.js", line: 42, why: "unsanitized input" },
      model: "deepseek-v4-flash",
    },
    fix: {
      diff:
        '--- a/src/db/query.js\n+++ b/src/db/query.js\n@@ -40,7 +40,7 @@\n function getUser(user_id) {\n-    return cursor.execute(f"SELECT * FROM users WHERE id = {user_id}");\n+    return cursor.execute("SELECT * FROM users WHERE id = ?", [user_id]);\n }\n',
      explanation: "Use parameterized queries.",
    },
  },
  {
    tool: "trivy",
    pipeline: "static",
    type: "vulnerability",
    severity: "medium",
    severity_score: 2,
    rule_id: "CVE-2024-1234",
    message: "django: SQL injection in QuerySet.explain",
    file: "requirements.txt",
    line: null,
    details: { package_name: "django", installed_version: "4.2.0", fixed_version: "4.2.16", cvss_score: 6.5, pkg_type: "pip", cwe: ["CWE-89"] },
    triage: {
      verdict: "real",
      confidence: 0.87,
      rationale: "Known CVE with published patch.",
      citation: { rule: "CVE-2024-1234", file: "requirements.txt", line: null, why: "known CVE" },
      model: "deepseek-v4-flash",
    },
    fix: {
      diff:
        '--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1,4 +1,4 @@\n-django==4.2.0\n+django>=4.2.16\n',
      explanation: "Bump Django to patched version.",
    },
  },
  {
    tool: "zap",
    pipeline: "dynamic",
    type: "dast",
    severity: "high",
    severity_score: 3,
    rule_id: "40018",
    message: "SQL Injection",
    file: "https://staging.example.com/search?q=1",
    line: null,
    details: { cweid: "89", wascid: "19", confidence: "2", solution: "Use parameterized queries." },
    triage: {
      verdict: "real",
      confidence: 0.89,
      rationale: "Confirmed SQL injection via dynamic scanner.",
      citation: { rule: "40018", file: "https://staging.example.com/search", line: null, why: "scanner evidence" },
      model: "deepseek-v4-flash",
    },
    fix: {
      diff: "No file diff available for DAST finding.",
      explanation: "Apply parameterized queries to the search endpoint.",
    },
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function requireAuth() {
  if (!currentUser) {
    const err = new Error("Unauthorized");
    err.status = 401;
    throw err;
  }
}

function computeProgress(scan) {
  const total = scan.tools_requested.length;
  if (total === 0) return 0;
  const done = scan.tools_done.length + scan.tools_failed.length;
  return Math.round((done / total) * 100);
}

function autoApproveIfEligible(finding, autoFixSeverity) {
  const severityRank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
  const thresholdRank = severityRank[autoFixSeverity] ?? 3;
  const findingRank = severityRank[finding.severity] ?? 0;

  if (findingRank >= thresholdRank && finding.severity !== "critical" && finding.fixes.length > 0) {
    finding.fixes[0].status = "approved";
    finding.hitl_actions.unshift({
      id: `hitl-${nextHitlId++}`,
      action: "approve",
      actor: "sentriq-auto",
      note: "Auto-approved based on scan policy",
      created_at: new Date().toISOString(),
    });
  }
}

function generateFindingsForScan(scan) {
  const created = [];
  const templates = findingTemplates.filter((t) => scan.tools_requested.includes(t.tool));

  for (const tpl of templates) {
    const id = `find-${nextFindingId++}`;
    const fixId = `fix-${nextFixId++}`;
    const finding = {
      id,
      scan: scan.id,
      tool: tpl.tool,
      pipeline: tpl.pipeline,
      type: tpl.type,
      severity: tpl.severity,
      severity_score: tpl.severity_score,
      rule_id: tpl.rule_id,
      message: tpl.message,
      file: tpl.file,
      line: tpl.line,
      url: null,
      fingerprint: `${tpl.tool}:${tpl.rule_id}:${tpl.file}:${tpl.line ?? ""}`,
      details: { ...tpl.details },
      triage: { ...tpl.triage, created_at: new Date().toISOString() },
      fixes: [
        {
          id: fixId,
          diff: tpl.fix.diff,
          explanation: tpl.fix.explanation,
          status: "proposed",
          model: "deepseek-v4-flash",
          pr_status: "none",
          branch: "",
          pr_url: "",
          pr_error: "",
          created_at: new Date().toISOString(),
        },
      ],
      hitl_actions: [],
    };
    autoApproveIfEligible(finding, scan.auto_fix_severity);
    created.push(finding);
  }

  return created;
}

// ---------------------------------------------------------------------------
// Scan simulation loop
// ---------------------------------------------------------------------------
setInterval(() => {
  let queueDepth = scans.filter((s) => s.status === "queued").length;
  let activeCount = scans.filter((s) => s.status === "running").length;

  // Move queued scans to running if capacity available (max 2 concurrent)
  if (activeCount < 2) {
    const nextQueued = scans.find((s) => s.status === "queued");
    if (nextQueued) {
      nextQueued.status = "running";
      activeCount++;
      queueDepth--;
    }
  }

  // Advance running scans
  for (const scan of scans) {
    if (scan.status !== "running") continue;

    const pendingTools = scan.tools_requested.filter(
      (t) => !scan.tools_done.includes(t) && !scan.tools_failed.includes(t)
    );
    if (pendingTools.length === 0) continue;

    // Advance one tool every tick
    const tool = pendingTools[0];
    const shouldFail = Math.random() < 0.1; // 10% failure rate
    if (shouldFail) {
      scan.tools_failed.push(tool);
    } else {
      scan.tools_done.push(tool);
    }

    const remaining = scan.tools_requested.filter(
      (t) => !scan.tools_done.includes(t) && !scan.tools_failed.includes(t)
    );

    if (remaining.length === 0) {
      scan.status = scan.tools_failed.length > 0 ? "partial" : "complete";
      if (scan.status !== "failed" && scan.tools_done.length === 0) {
        scan.status = "failed";
      }
      // Generate findings for completed scans
      const newFindings = generateFindingsForScan(scan);
      findings.push(...newFindings);
      scan.finding_count = findings.filter((f) => f.scan === scan.id).length;
    }

    scan.progress_pct = computeProgress(scan);
  }

  // Update queue positions
  let position = 1;
  for (const scan of scans) {
    if (scan.status === "queued") {
      scan.queue_position = position++;
    } else {
      scan.queue_position = 0;
    }
  }
}, 2500);

// ---------------------------------------------------------------------------
// Mock API
// ---------------------------------------------------------------------------
export const mockApi = {
  auth: {
    me: async () => {
      await sleep(400);
      if (!currentUser) {
        const err = new Error("Unauthorized");
        err.status = 401;
        throw err;
      }
      return currentUser;
    },

    loginWithGitHub: async () => {
      await sleep(1200);
      currentUser = { ...mockUser };
      return currentUser;
    },

    devLogin: async () => {
      await sleep(300);
      currentUser = { ...mockUser };
      return currentUser;
    },

    logout: async () => {
      await sleep(200);
      currentUser = null;
      return null;
    },
  },

  repos: {
    list: async () => {
      requireAuth();
      await sleep(600);
      return [...mockRepos];
    },
  },

  scans: {
    list: async () => {
      requireAuth();
      await sleep(300);
      return [...scans].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    },

    create: async ({ pipeline, target, ref, tools, auto_fix_severity }) => {
      requireAuth();
      await sleep(400);

      const selectedTools = tools && tools.length > 0 ? tools : getDefaultTools(pipeline);
      const scan = {
        id: `scan-${nextScanId++}`,
        pipeline,
        target,
        ref: ref || "HEAD",
        status: "queued",
        tools_requested: selectedTools,
        tools_done: [],
        tools_failed: [],
        progress_pct: 0,
        queue_position: scans.filter((s) => s.status === "queued").length + 1,
        auto_fix_severity: auto_fix_severity || "high",
        finding_count: 0,
        created_at: new Date().toISOString(),
      };
      scans.unshift(scan);
      return scan;
    },
  },

  queue: {
    status: async () => {
      requireAuth();
      await sleep(200);
      return {
        queue_depth: scans.filter((s) => s.status === "queued").length,
        active_tasks: scans.filter((s) => s.status === "running").length,
      };
    },
  },

  findings: {
    list: async (params = {}) => {
      requireAuth();
      await sleep(300);
      let result = [...findings];
      if (params.scan) result = result.filter((f) => f.scan === params.scan);
      if (params.severity) result = result.filter((f) => f.severity === params.severity);
      if (params.tool) result = result.filter((f) => f.tool === params.tool);
      if (params.verdict) result = result.filter((f) => (f.triage?.verdict || "pending") === params.verdict);
      return result.sort((a, b) => b.severity_score - a.severity_score || a.tool.localeCompare(b.tool));
    },

    get: async (id) => {
      requireAuth();
      await sleep(200);
      const f = findings.find((x) => x.id === id);
      if (!f) throw new Error("Finding not found");
      return f;
    },

    hitl: async (id, action, actor, note, edited_diff) => {
      requireAuth();
      await sleep(400);
      const f = findings.find((x) => x.id === id);
      if (!f) throw new Error("Finding not found");

      f.hitl_actions.unshift({
        id: `hitl-${nextHitlId++}`,
        action,
        actor: actor || "anonymous",
        note: note || "",
        edited_diff: edited_diff || null,
        created_at: new Date().toISOString(),
      });

      const fix = f.fixes[0];
      if (fix) {
        fix.status = { approve: "approved", deny: "denied", edit: "edited" }[action] || fix.status;
        if (action === "edit" && edited_diff) {
          fix.diff = edited_diff;
        }
      }

      return { status: "recorded", action };
    },

    createPr: async (id) => {
      requireAuth();
      await sleep(1500);
      const f = findings.find((x) => x.id === id);
      if (!f) throw new Error("Finding not found");

      const fix = f.fixes[0];
      if (!fix) throw new Error("No fix to open a PR for");

      // Critical findings require explicit HITL approval
      if (f.severity === "critical") {
        const lastHitl = f.hitl_actions[0];
        if (!lastHitl || lastHitl.action !== "approve") {
          const err = new Error("Critical finding requires human approval before PR");
          err.status = 409;
          throw err;
        }
      }

      if (fix.status !== "approved") {
        const err = new Error("Approve the fix before opening a PR");
        err.status = 409;
        throw err;
      }

      fix.pr_status = "open";
      fix.branch = `sentriq/fix-${f.id}`;
      fix.pr_url = `https://github.com/tejbruhath/${f.scan}/pull/${Math.floor(Math.random() * 1000) + 1}`;
      return { status: "open", pr_url: fix.pr_url };
    },
  },

  metrics: async () => {
    requireAuth();
    await sleep(200);
    const by_sev = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    for (const f of findings) {
      by_sev[f.severity] = (by_sev[f.severity] || 0) + 1;
    }
    return {
      totals: {
        scans: scans.length,
        findings: findings.length,
        fixes_proposed: findings.filter((f) => f.fixes.length > 0).length,
        fixes_approved: findings.filter((f) => f.fixes.some((x) => x.status === "approved")).length,
      },
      by_severity: by_sev,
      by_tool: {},
      by_type: {},
      by_verdict: {},
      scans_by_status: {},
    };
  },
};

function getDefaultTools(pipeline) {
  return pipeline === "static" ? ["gitleaks", "semgrep", "trivy"] : ["zap", "nuclei"];
}
