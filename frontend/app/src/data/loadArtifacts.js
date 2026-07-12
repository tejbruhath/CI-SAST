/**
 * Fetch every mega-artifact.json from ci-utils' archived artifacts (served via
 * nginx proxy at /artifacts/, autoindex_format json).
 *
 *   GET /artifacts/                       -> [{name, type:"directory", ...}, ...]
 *   GET /artifacts/{job_id}/mega-artifact.json -> the artifact
 *
 * No demo/sample fallback: if the endpoint is unreachable or empty, the app
 * shows a real empty/error state (see App.jsx) instead of fabricated data.
 */
import { buildRepoTree } from "./smartDelete.js";

const BASE = "/artifacts";

async function listJson(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`list ${path} -> ${res.status}`);
  return res.json();
}

async function fetchArtifact(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`fetch ${url} -> ${res.status}`);
  return res.json();
}

export async function loadArtifacts() {
  const entries = await listJson(`${BASE}/`);
  if (!Array.isArray(entries)) throw new Error("artifact index is not a list");

  const jobs = [];
  for (const e of entries) {
    if (e.type === "directory") {
      jobs.push(fetchArtifact(`${BASE}/${e.name}/mega-artifact.json`).catch(() => null));
    } else if (e.type === "file" && e.name.endsWith(".json")) {
      jobs.push(fetchArtifact(`${BASE}/${e.name}`).catch(() => null));
    }
  }
  const artifacts = (await Promise.all(jobs)).filter(Boolean);
  return { repos: buildRepoTree(artifacts), count: artifacts.length };
}
