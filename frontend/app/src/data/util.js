export const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

export const SEV_COLOR = {
  critical: "var(--viz-series-4)",
  high: "var(--viz-series-3)",
  medium: "var(--viz-series-2)",
  low: "var(--viz-series-1)",
  info: "var(--viz-muted)",
};

export function maxSeverity(findings) {
  let best = null;
  for (const f of findings) {
    if (best == null || (SEV_RANK[f.sev] || 0) > (SEV_RANK[best] || 0)) best = f.sev;
  }
  return best || "info";
}

export function slug(s) {
  return String(s || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "unknown";
}

export function formatRelative(epochSeconds) {
  if (!epochSeconds) return "unknown";
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - epochSeconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  const d = Math.floor(diff / 86400);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
  "Oct", "Nov", "Dec"];

export function formatCommitDate(epochSeconds) {
  if (!epochSeconds) return "unknown date";
  const d = new Date(epochSeconds * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} · ${hh}:${mm}`;
}
