/**
 * TEST-ONLY fixtures for smartDelete.test.mjs. Never imported by app code —
 * the app has no built-in demo/sample data; it only ever renders real
 * mega-artifact.json content fetched from ci-utils.
 *
 * These objects are shaped as real v3.0.0 mega-artifacts, one per commit scan,
 * so the test exercises the exact same code path as production data would.
 *
 * The proofx/sas_test chain is deliberately crafted so the older commit reports
 * `generic-api-key:...:17` which the newer commit does NOT -> that finding gets
 * smart-deleted (moves to resolved history) in the active tree.
 */
const T = 1783857600; // 2026-07-12T12:00:00Z
const DAY = 86400;

function artifact({ repo, path, branch, sha, short, msg, author, ts, gen,
                    gitleaks = [], trivy = [], sonarqube = [] }) {
  const all = [...gitleaks, ...trivy, ...sonarqube];
  const bySev = {};
  for (const f of all) bySev[f.severity] = (bySev[f.severity] || 0) + 1;
  return {
    metadata: {
      schema_version: "3.0.0",
      job_id: sha.slice(0, 8),
      generated_at_epoch: gen,
      repo: { name: repo, path, url: `https://gitlab.example/${path}`,
              id: "1", visibility: "private" },
      branch,
      commit: { sha, short_sha: short, author_name: author, message: msg,
                timestamp_epoch: ts },
    },
    tools: {
      gitleaks: { version: "8.18.0" },
      trivy: { version: "0.50.0", scanners: ["vuln"] },
      sonarqube: { scanner_version: "5.0.1.3006", server_version: "9.9.4",
                   edition: "community" },
    },
    gitleaks,
    trivy,
    sonarqube,
    summary: {
      total_findings: all.length,
      by_tool: { gitleaks: gitleaks.length, trivy: trivy.length,
                 sonarqube: sonarqube.length },
      by_severity: bySev,
    },
  };
}

const gl = (rule, file, line, sev) => ({
  fingerprint: `${rule}:${file}:${line}`, rule_id: rule, tool: "gitleaks",
  type: "secret", severity: sev, severity_score: sev === "critical" ? 4 : 3,
  message: `Secret: ${rule} in ${file}:${line}`, file, line, url: null,
  details: { secret_type: rule, entropy: 4.2 },
});
const tv = (cve, pkg, sev, file, installed, fixed, cvss) => ({
  fingerprint: `${cve}:${file}:${pkg}`, rule_id: cve, tool: "trivy",
  type: "vulnerability", severity: sev, severity_score: sev === "critical" ? 4 : 2,
  message: `${pkg}: known vulnerability`, file, line: null,
  url: `https://nvd.nist.gov/vuln/detail/${cve}`,
  details: { package_name: pkg, installed_version: installed,
             fixed_version: fixed, cvss_score: cvss, pkg_type: "pip" },
});
const sq = (key, rule, sev, type, file, line, msg, effort) => ({
  fingerprint: key, rule_id: rule, tool: "sonarqube", type, severity: sev,
  severity_score: sev === "high" ? 3 : sev === "medium" ? 2 : 1, message: msg,
  file, line, url: `https://sonar.example/project/issues?open=${key}&id=proj`,
  details: { sonar_type: type.toUpperCase(), effort_minutes: effort, tags: [] },
});

export const TEST_ARTIFACTS = [
  // aotm_proofx / sas_test — newer commit (secret-17 dropped -> resolved)
  artifact({
    repo: "aotm_proofx", path: "aotm/aotm_proofx", branch: "sas_test",
    sha: "efe62e946bfadd6d15e0276bf6def6b6935e79bb", short: "efe62e94",
    msg: "Merge patch-1 into sas_test", author: "GitLab Runner",
    ts: T - 5 * 60, gen: T - 4 * 60,
    trivy: [
      tv("CVE-2023-4863", "Pillow", "critical", "requirements.txt", "9.0.0", "10.0.1", 9.8),
      tv("CVE-2024-6345", "setuptools", "medium", "requirements.txt", "65.5.0", "70.0.0", 6.5),
    ],
    sonarqube: [
      sq("sonar-27", "python:S3776", "high", "code_smell", "vulnerable_payload.py", 27,
         "Reduce Cognitive Complexity from 151 to 15.", 45),
      sq("sonar-61", "python:S930", "high", "bug", "vulnerable_payload.py", 61,
         "Incorrect number of arguments passed to function.", 10),
      sq("todo-42", "python:S1135", "low", "code_smell", ".gitlab-ci.yml", 42,
         "Track the work required by this TODO.", 5),
    ],
  }),
  // aotm_proofx / sas_test — older commit (has the secret + Pillow)
  artifact({
    repo: "aotm_proofx", path: "aotm/aotm_proofx", branch: "sas_test",
    sha: "91bc60d2aa11ce55d0c0a2b7c9f0e1d2a3b4c5d6", short: "91bc60d2",
    msg: "Add SAST aggregation schema", author: "Tej",
    ts: T - DAY, gen: T - DAY + 120,
    gitleaks: [gl("generic-api-key", "vulnerable_payload.py", 17, "critical")],
    trivy: [tv("CVE-2023-4863", "Pillow", "critical", "requirements.txt", "9.0.0", "10.0.1", 9.8)],
  }),
  // aotm_proofx / main
  artifact({
    repo: "aotm_proofx", path: "aotm/aotm_proofx", branch: "main",
    sha: "8d7ad140ffee0011223344556677889900aabbcc", short: "8d7ad140",
    msg: "Stabilize result aggregator", author: "Tej",
    ts: T - 2 * DAY, gen: T - 2 * DAY + 60,
    sonarqube: [
      sq("agg-88", "python:S3776", "high", "code_smell", "aggregator.py", 88,
         "Reduce Cognitive Complexity from 24 to 15.", 30),
    ],
  }),
  // ci-utils / main
  artifact({
    repo: "ci-utils", path: "platform/ci-utils", branch: "main",
    sha: "1af83c11ddeeff00112233445566778899aabbcc", short: "1af83c11",
    msg: "Persist finding fingerprints", author: "Platform Team",
    ts: T - 40 * 60, gen: T - 38 * 60,
    sonarqube: [
      sq("redis-54", "python:S2245", "high", "security_hotspot", "redis_store.py", 54,
         "Review this random number generator used in a security context.", 20),
    ],
  }),
];
