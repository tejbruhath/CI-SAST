/**
 * Pure data layer: turn a flat list of v3.0.0 mega-artifacts into the
 * repo -> branch -> commit -> finding tree the explorer renders, and apply
 * "smart delete" (fingerprint-diff lifecycle) across each branch's commit chain.
 *
 * Smart delete (the MVP rule):
 *   A finding is ACTIVE on a branch only while its fingerprint is present in the
 *   branch's latest commit. When a newer commit no longer reports a fingerprint
 *   that an older commit did, that finding is auto-removed from the active tree
 *   and retained only as "resolved" history. Per-commit, resolved(C) = the
 *   fingerprints present in C's parent (the immediately older commit) that are
 *   absent from C.
 *
 * This module is framework-free and unit-tested in node (see smartDelete.test.mjs).
 */
import { SEV_RANK, maxSeverity, slug } from "./util.js";

const TOOL_KEYS = ["gitleaks", "trivy", "sonarqube"];

/** Flatten a single artifact's three finding arrays into a uniform shape. */
export function flattenFindings(artifact) {
  const out = [];
  for (const key of TOOL_KEYS) {
    for (const f of artifact[key] || []) {
      const d = f.details || {};
      out.push({
        id: f.fingerprint || f.id,
        sev: f.severity || "info",
        severityScore: f.severity_score,
        tool: f.tool || key,
        type: f.type || "finding",
        file: f.file || "unknown",
        line: f.line ?? null,
        rule: f.rule_id || f.rule || "unknown",
        msg: f.message || "",
        url: f.url || null,
        package: d.package_name || null,
        installed: d.installed_version || null,
        fixed: d.fixed_version || null,
        cvss: d.cvss_score ?? null,
        effort: d.effort_minutes ?? null,
        entropy: d.entropy ?? null,
        tags: d.tags || [],
      });
    }
  }
  return out;
}

function commitEpoch(artifact) {
  const m = artifact.metadata || {};
  return (m.commit && m.commit.timestamp_epoch) || m.generated_at_epoch || 0;
}

/** Build the full repo tree with lifecycle + resolved history applied. */
export function buildRepoTree(artifacts) {
  // group: repo -> branch -> (sha -> best artifact)
  const repos = new Map();

  for (const art of artifacts) {
    const m = art.metadata || {};
    const repoKey = (m.repo && (m.repo.path || m.repo.name)) || "unknown";
    const branchKey = m.branch || "unknown";
    const sha = (m.commit && m.commit.sha) || "unknown";

    if (!repos.has(repoKey)) repos.set(repoKey, { meta: m, branches: new Map() });
    const repo = repos.get(repoKey);
    if (!repo.branches.has(branchKey)) repo.branches.set(branchKey, new Map());
    const branch = repo.branches.get(branchKey);

    // de-dupe re-runs of the same commit: keep the most recently generated one
    const prev = branch.get(sha);
    if (!prev || (art.metadata.generated_at_epoch || 0) >
                 (prev.metadata.generated_at_epoch || 0)) {
      branch.set(sha, art);
    }
  }

  const result = [];
  for (const [repoKey, repo] of repos) {
    const branchOut = [];
    let repoRuns = 0;

    for (const [branchKey, shaMap] of repo.branches) {
      // newest -> oldest
      const arts = [...shaMap.values()].sort((a, b) => commitEpoch(b) - commitEpoch(a));
      repoRuns += arts.length;

      const commits = arts.map((art) => {
        const m = art.metadata || {};
        const c = m.commit || {};
        return {
          id: c.short_sha || (c.sha ? c.sha.slice(0, 8) : "unknown"),
          sha: c.sha || "unknown",
          msg: c.message ? c.message.split("\n")[0] : "(no message)",
          author: c.author_name || "unknown",
          dateEpoch: commitEpoch(art),
          status: statusOf(art),
          findings: flattenFindings(art),
        };
      });

      // lifecycle + resolved via fingerprint diff against the parent (older) commit
      for (let i = 0; i < commits.length; i++) {
        const parent = commits[i + 1]; // older commit
        const parentIds = new Set(parent ? parent.findings.map((f) => f.id) : []);
        const currentIds = new Set(commits[i].findings.map((f) => f.id));

        for (const f of commits[i].findings) {
          f.life = parentIds.has(f.id) ? "existing" : "new";
        }
        commits[i].resolved = parent
          ? parent.findings
              .filter((f) => !currentIds.has(f.id))
              .map((f) => ({ ...f, life: "resolved" }))
          : [];
      }

      const latest = commits[0];
      const activeFindings = latest ? latest.findings : [];
      branchOut.push({
        id: slug(branchKey),
        name: branchKey,
        owner: latest ? latest.author : "unknown",
        findings: activeFindings.length,
        sev: maxSeverity(activeFindings),
        updatedEpoch: latest ? latest.dateEpoch : 0,
        commits,
      });
    }

    branchOut.sort((a, b) => b.updatedEpoch - a.updatedEpoch);
    const activeCount = branchOut.reduce((n, b) => n + b.findings, 0);
    const allActive = branchOut.flatMap((b) => b.commits[0]?.findings || []);

    result.push({
      id: slug(repoKey),
      name: (repo.meta.repo && repo.meta.repo.name) || repoKey,
      path: (repo.meta.repo && repo.meta.repo.path) || repoKey,
      url: (repo.meta.repo && repo.meta.repo.url) || null,
      visibility: (repo.meta.repo && repo.meta.repo.visibility) || "n/a",
      findings: activeCount,
      runs: repoRuns,
      sev: maxSeverity(allActive),
      updatedEpoch: Math.max(0, ...branchOut.map((b) => b.updatedEpoch)),
      branches: branchOut,
    });
  }

  result.sort((a, b) => b.updatedEpoch - a.updatedEpoch);
  return result;
}

function statusOf(art) {
  const t = (art.tools || {});
  // If any tool block is present but empty AND summary has zero, still "passed".
  // We treat presence of an artifact as a completed run; failures would be
  // surfaced by ci-utils as a "partial" job (not backed up as a full artifact).
  const partial = art.metadata && art.metadata.status === "partial";
  return partial ? "partial" : "passed";
}

/** Aggregate headline metrics for the metric cards. */
export function globalMetrics(repos) {
  const active = repos.reduce((n, r) => n + r.findings, 0);
  const runs = repos.reduce((n, r) => n + r.runs, 0);
  const allActive = repos.flatMap((r) =>
    r.branches.flatMap((b) => b.commits[0]?.findings || [])
  );
  const critical = allActive.filter((f) => f.sev === "critical").length;
  return { active, runs, critical, resolved: 0 };
}

export { SEV_RANK };
