/**
 * Smart-delete unit test. Run: `npm run test:smartdelete` (or `node this-file`).
 * No build step / test framework required.
 */
import assert from "node:assert";
import { buildRepoTree, globalMetrics } from "./smartDelete.js";
import { TEST_ARTIFACTS } from "./smartDelete.fixtures.mjs";

const repos = buildRepoTree(TEST_ARTIFACTS);

// two repos, proofx sorts first (most recent activity)
const proofx = repos.find((r) => r.name === "aotm_proofx");
assert.ok(proofx, "proofx repo present");
assert.equal(repos.length, 2, "two repos");

// sas_test branch has 2 commits, newest first
const sas = proofx.branches.find((b) => b.name === "sas_test");
assert.ok(sas, "sas_test branch present");
assert.equal(sas.commits.length, 2, "two commits on sas_test");
assert.equal(sas.commits[0].id, "efe62e94", "newest commit first");

const newest = sas.commits[0];
const older = sas.commits[1];

// --- SMART DELETE: the secret present in the older commit is absent from the
//     newer one -> it must NOT be active, and must appear in resolved history.
const secretFp = "generic-api-key:vulnerable_payload.py:17";
assert.ok(older.findings.some((f) => f.id === secretFp), "older commit had the secret");
assert.ok(!newest.findings.some((f) => f.id === secretFp),
  "secret is smart-deleted from the active (newest) commit");
assert.ok(newest.resolved.some((f) => f.id === secretFp && f.life === "resolved"),
  "secret retained in resolved history");
assert.equal(newest.resolved.length, 1, "exactly one resolved finding");

// --- lifecycle tagging via fingerprint diff
const cve = newest.findings.find((f) => f.rule === "CVE-2023-4863");
assert.equal(cve.life, "existing", "carried-over finding tagged existing");
const bug = newest.findings.find((f) => f.id === "sonar-61");
assert.equal(bug.life, "new", "finding not in parent tagged new");

// --- branch active count = newest commit only (older findings not carried)
assert.equal(sas.findings, 5, "branch active findings = newest commit count");
assert.equal(sas.sev, "critical", "branch severity is worst active severity");

// --- older commit has no parent -> everything new, nothing resolved
assert.ok(older.findings.every((f) => f.life === "new"), "root commit findings all new");
assert.equal(older.resolved.length, 0, "root commit has no resolved history");

// --- global metrics
const m = globalMetrics(repos);
assert.ok(m.active > 0 && m.runs >= 4, "global metrics computed");

console.log("SMART-DELETE: all assertions passed");
console.log(`  repos=${repos.length} proofx.branches=${proofx.branches.length}`);
console.log(`  sas_test active=${sas.findings} resolved(newest)=${newest.resolved.length}`);
console.log(`  global: active=${m.active} critical=${m.critical} runs=${m.runs}`);
