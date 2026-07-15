export function SeverityBadge({ severity, blink = false }) {
  // Color map for normalized severity labels.
  const styles = {
    critical: "bg-error text-on-error border-error", // highest risk
    high: "bg-tertiary-container text-on-tertiary-container border-on-tertiary-container",
    medium: "bg-secondary-container text-on-surface border-outline",
    low: "bg-primary text-on-primary border-primary",
    info: "bg-surface-variant text-on-surface border-outline-variant", // lowest
  };

  return (
    <span
      className={`inline-block font-code-label text-[10px] px-2 py-0.5 border-2 uppercase font-bold ${
        styles[severity] || styles.info // unknown severity → info style
      } ${blink && severity === "critical" ? "animate-blink" : ""}`} // optional pulse for critical
    >
      {severity} {/* raw severity text */}
    </span>
  );
}

export function VerdictBadge({ verdict, severity }) {
  // LLM triage verdict chip (real / FP / noise / pending).
  const v = verdict || "pending"; // default when triage not done
  const label = v === "false_positive" ? "FALSE POSITIVE" : v.toUpperCase(); // pretty label
  const isHighSeverity = severity === "critical" || severity === "high"; // red only if bad + real
  const textColor =
    v === "real" ? (isHighSeverity ? "text-error" : "text-tertiary") : "text-outline"; // real vs not
  const borderColor =
    v === "real" ? (isHighSeverity ? "border-error" : "border-tertiary") : "border-outline";

  return (
    <span
      className={`inline-block font-code-label text-[10px] px-2 py-0.5 border-2 uppercase font-bold bg-surface ${textColor} ${borderColor}`}>
      {label}
    </span>
  );
}

export function ToolBadge({ tool }) {
  // Scanner name chip (gitleaks, semgrep, …).
  return (
    <span className="inline-block font-code-label text-[10px] px-2 py-0.5 border-2 border-outline-variant bg-surface-container-high text-on-surface uppercase">
      {tool}
    </span>
  );
}

export function PipelineBadge({ pipeline }) {
  // static vs dynamic pipeline tag.
  return (
    <span className="inline-block font-code-label text-[10px] px-1 uppercase border border-outline bg-secondary-container text-on-surface">
      {pipeline} pipeline
    </span>
  );
}

export function StatusBadge({ status }) {
  // Scan lifecycle status with optional spinner for running.
  const styles = {
    queued: "bg-surface-variant text-on-surface border-outline-variant", // waiting
    running: "bg-primary text-on-primary border-primary animate-pulse", // in progress
    complete: "bg-primary text-on-primary border-primary", // all tools ok
    partial: "bg-tertiary-container text-on-tertiary-container border-on-tertiary-container", // some tools failed
    failed: "bg-error text-on-error border-error", // hard fail
  };

  return (
    <span className={`inline-flex items-center gap-1 font-code-label text-code-label px-2 py-1 border-2 uppercase font-bold ${styles[status] || styles.queued}`}>
      {status === "running" && (
        <span className="material-symbols-outlined text-[14px]">sync</span> // spinning-ish icon
      )}
      {status} {/* status text */}
    </span>
  );
}
