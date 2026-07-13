// Thin API client for the Sentriq backend. Base is same-origin (/api/v1 is
// proxied in dev, served behind the same host in prod) unless VITE_API_BASE set.
const BASE = (import.meta.env.VITE_API_BASE || "") + "/api/v1";

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${path}: ${body}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  createScan: (pipeline, target, ref) =>
    req("/scans", { method: "POST", body: JSON.stringify({ pipeline, target, ref }) }),
  scans: () => req("/scans"),
  scan: (id) => req(`/scans/${id}`),
  findings: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return req("/findings" + (q ? `?${q}` : ""));
  },
  finding: (id) => req(`/findings/${id}`),
  hitl: (id, action, actor, note, edited_diff) =>
    req(`/findings/${id}/hitl`, {
      method: "POST",
      body: JSON.stringify({ action, actor, note, edited_diff }),
    }),
  createPr: (id) => req(`/findings/${id}/pr`, { method: "POST" }),
  metrics: () => req("/metrics"),
  provenance: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return req("/provenance" + (q ? `?${q}` : ""));
  },
};
