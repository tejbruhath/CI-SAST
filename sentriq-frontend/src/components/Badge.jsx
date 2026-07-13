export function SeverityBadge({ severity }) {
  return <span className={`badge sev-${severity}`}>{severity}</span>;
}

export function VerdictBadge({ verdict }) {
  const v = verdict || "pending";
  const label = v === "false_positive" ? "false pos" : v;
  return <span className={`badge v-${v}`}>{label}</span>;
}

export function ToolBadge({ tool }) {
  return <span className="badge tool">{tool}</span>;
}
