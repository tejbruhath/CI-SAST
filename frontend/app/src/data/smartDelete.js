/**
 * Pure data layer: turn a flat list of v3.0.0 mega-artifacts into the
 * repo -> branch -> commit -> finding tree the explorer renders, apply
 * "smart delete" (fingerprint-diff lifecycle), and thread author blame.
 *
 * Smart delete (the MVP rule):
 *   A finding is ACTIVE on a branch only while its fingerprint is present in
 *   the branch's latest commit. When a newer commit no longer reports a
 *   fingerprint that an older commit did, that finding is auto-removed from
 *   the active tree and retained only as "resolved" history. Per-commit,
 *   resolved(C) = fingerprints present in C's parent (the immediately older
 *   commit) that are absent from C.
 *
 * Author blame:
 *   Walking a branch's commits oldest -> newest, the FIRST commit a
 *   fingerprint appears in is the one that introduced it. Every finding
 *   (active or resolved) carries introducedBy {author, sha, shortSha,
 *   epoch} = the responsible commit. The commit that RESOLVED a finding
 *   (first newer commit where the fingerprint disappears) carries
 *   resolvedBy on the resolved entry. This is how responsibilities get
 *   pinned down.
 *
 * Framework-free, unit-tested in node (see smartDelete.test.mjs).
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

/** "Tej Bruhath B <x@y.com>" -> { name, email } (author string is freeform). */
export function parseAuthor(raw) {
  const s = String(raw || "unknown").trim();
  const m = s.match(/^(.*?)\s*<([^>]+)>\s*$/);
  if (m) return { name: m[1].trim() || m[2], email: m[2].trim() };
  return { name: s || "unknown", email: null };
}

function commitRef(commit) {
  const a = parseAuthor(commit.author);
  return {
    author: a.name,
    email: a.email,
    sha: commit.sha,
    shortSha: commit.id,
    epoch: commit.dateEpoch,
    message: commit.msg,
  };
}

/** Build the full repo tree with lifecycle, resolved history + author blame. */
export function buildRepoTree(artifacts) {
  const repos = new Map(); // repoKey -> { meta, branches: Map<branch, Map<sha, art>> }

  for (const art of artifacts) {
    const m = art.metadata || {};
    const repoKey = (m.repo && (m.repo.path || m.repo.name)) || "unknown";
    const branchKey = m.branch || "unknown";
    const sha = (m.commit && m.commit.sha) || "unknown";

    if (!repos.has(repoKey)) repos.set(repoKey, { meta: m, branches: new Map() });
    const repo = repos.get(repoKey);
    if (!repo.branches.has(branchKey)) repo.branches.set(branchKey, new Map());
    const branch = repo.branches.get(branchKey);

    // de-dupe re-runs of the same commit: keep the most-recently generated one
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
      const arts = [...shaMap.values()].sort((a, b) => commitEpoch(b) - commitEpoch(a));
      repoRuns += arts.length;

      // newest -> oldest
      const commits = arts.map((art) => {
        const m = art.metadata || {};
        const c = m.commit || {};
        return {
          id: c.short_sha || (c.sha ? c.sha.slice(0, 8) : "unknown"),
          sha: c.sha || "unknown",
          msg: c.message ? c.message.split("\n")[0] : "(no message)",
          author: c.author_name || "unknown",
          dateEpoch: commitEpoch(art),
          pipelineUrl: (m.pipeline && m.pipeline.url) || null,
          jobUrl: (m.job && m.job.url) || null,
          status: statusOf(art),
          findings: flattenFindings(art),
        };
      });

      // --- author blame: oldest -> newest, first appearance wins ------------
      // introducedByFp: fingerprint -> commitRef of the commit that first
      // reported it. Chronological (oldest first) so first-seen is authoritative.
      const introducedByFp = new Map();
      for (let i = commits.length - 1; i >= 0; i--) {
        const ref = commitRef(commits[i]);
        for (const f of commits[i].findings) {
          if (!introducedByFp.has(f.id)) introducedByFp.set(f.id, ref);
          f.introducedBy = introducedByFp.get(f.id);
        }
      }

      // --- lifecycle + resolved via fingerprint diff vs parent (older) ------
      for (let i = 0; i < commits.length; i++) {
        const parent = commits[i + 1]; // older commit
        const parentIds = new Set(parent ? parent.findings.map((f) => f.id) : []);
        const currentIds = new Set(commits[i].findings.map((f) => f.id));
        const resolvedByRef = commitRef(commits[i]); // this commit resolved them

        for (const f of commits[i].findings) {
          f.life = parentIds.has(f.id) ? "existing" : "new";
        }
        commits[i].resolved = parent
          ? parent.findings
              .filter((f) => !currentIds.has(f.id))
              .map((f) => ({
                ...f,
                life: "resolved",
                introducedBy: introducedByFp.get(f.id) || f.introducedBy,
                resolvedBy: resolvedByRef,
              }))
          : [];
      }

      const latest = commits[0];
      const activeFindings = latest ? latest.findings : [];

      // branch-wide resolved rollup (every finding ever smart-deleted on this
      // branch), de-duped by fingerprint, newest resolution kept -- powers the
      // dedicated "Resolved" view.
      const resolvedRollup = new Map();
      for (const c of commits) {
        for (const r of c.resolved || []) {
          const existing = resolvedRollup.get(r.id);
          if (!existing || (r.resolvedBy?.epoch || 0) > (existing.resolvedBy?.epoch || 0)) {
            resolvedRollup.set(r.id, r);
          }
        }
      }
      // a finding that was resolved then reintroduced and is active again
      // shouldn't show as resolved
      const activeIds = new Set(activeFindings.map((f) => f.id));
      const branchResolved = [...resolvedRollup.values()].filter((r) => !activeIds.has(r.id));

      branchOut.push({
        id: slug(branchKey),
        name: branchKey,
        owner: latest ? parseAuthor(latest.author).name : "unknown",
        findings: activeFindings.length,
        sev: maxSeverity(activeFindings),
        updatedEpoch: latest ? latest.dateEpoch : 0,
        commits,
        resolvedHistory: branchResolved,
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
      projectId: (repo.meta.repo && repo.meta.repo.id) || null,
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
  const resolved = repos.reduce(
    (n, r) => n + r.branches.reduce((m, b) => m + (b.resolvedHistory?.length || 0), 0),
    0
  );
  return { active, runs, critical, resolved };
}

export { SEV_RANK };
