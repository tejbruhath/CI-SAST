export function SeverityBadge({ severity, blink = false }) {
  const styles = {
    critical: "bg-error text-on-error border-error",
    high: "bg-tertiary-container text-on-tertiary-container border-on-tertiary-container",
    medium: "bg-secondary-container text-on-surface border-outline",
    low: "bg-primary text-on-primary border-primary",
    info: "bg-surface-variant text-on-surface border-outline-variant",
  };

  return (
    <span
      className={`inline-block font-code-label text-[10px] px-2 py-0.5 border-2 uppercase font-bold ${
        styles[severity] || styles.info
      } ${blink && severity === "critical" ? "animate-blink" : ""}`}
    >
      {severity}
    </span>
  );
}

export function VerdictBadge({ verdict }) {
  const v = verdict || "pending";
  const label = v === "false_positive" ? "FALSE POS" : v;
  const styles = {
    real: "bg-error text-on-error border-error",
    false_positive: "bg-surface-variant text-on-surface border-outline-variant",
    noise: "bg-surface-container-high text-on-surface-variant border-outline",
    pending: "bg-primary text-on-primary border-primary",
    error: "bg-error-container text-on-error-container border-error",
  };

  return (
    <span className={`inline-block font-code-label text-[10px] px-2 py-0.5 border-2 uppercase font-bold ${styles[v] || styles.pending}`}>
      {label}
    </span>
  );
}

export function ToolBadge({ tool }) {
  return (
    <span className="inline-block font-code-label text-[10px] px-2 py-0.5 border-2 border-outline-variant bg-surface-container-high text-on-surface uppercase">
      {tool}
    </span>
  );
}

export function PipelineBadge({ pipeline }) {
  return (
    <span className="inline-block font-code-label text-[10px] px-1 uppercase border border-outline bg-secondary-container text-on-surface">
      {pipeline} pipeline
    </span>
  );
}

export function StatusBadge({ status }) {
  const styles = {
    queued: "bg-surface-variant text-on-surface border-outline-variant",
    running: "bg-primary text-on-primary border-primary animate-pulse",
    complete: "bg-primary text-on-primary border-primary",
    partial: "bg-tertiary-container text-on-tertiary-container border-on-tertiary-container",
    failed: "bg-error text-on-error border-error",
  };

  return (
    <span className={`inline-flex items-center gap-1 font-code-label text-code-label px-2 py-1 border-2 uppercase font-bold ${styles[status] || styles.queued}`}>
      {status === "running" && (
        <span className="material-symbols-outlined text-[14px]">sync</span>
      )}
      {status}
    </span>
  );
}
