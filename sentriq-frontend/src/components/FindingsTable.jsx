import { SeverityBadge, VerdictBadge, ToolBadge } from "./Badge.jsx";

const SEVS = ["critical", "high", "medium", "low", "info"];
const TOOLS = ["gitleaks", "semgrep", "trivy", "zap", "nuclei"];
const VERDICTS = ["real", "false_positive", "noise", "pending"];

// Renders the AI-fix remediation lifecycle for one finding.
// No fix generated → "—". Fix ready → START (triggers PR). creating → QUEUED.
// open → DONE (links to PR). failed → RETRY. proposed/denied → review states.
function FixCell({ fix, onStart, busy }) {
  const stop = (e) => e.stopPropagation();
  const btn = (label, cls) => ({ label, cls });

  if (!fix) return <span className="text-outline">—</span>;
  const { status, pr_status, pr_url } = fix;

  if (pr_status === "open") {
    return pr_url ? (
      <a href={pr_url} target="_blank" rel="noreferrer" onClick={stop}
         className="text-primary font-bold hover:underline">DONE ↗</a>
    ) : <span className="text-primary font-bold">DONE</span>;
  }
  if (pr_status === "creating") {
    return <span className="text-tertiary font-bold animate-pulse">QUEUED…</span>;
  }

  const action = (label, cls) => (
    <button type="button" disabled={busy}
      onClick={(e) => { stop(e); onStart(); }}
      className={`px-2 py-1 border font-code-label text-code-label uppercase font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}>
      {label}
    </button>
  );

  if (pr_status === "failed") {
    return action("RETRY", "border-error text-error hover:bg-error hover:text-black");
  }
  if (status === "approved" || status === "edited") {
    return action("START", "border-primary text-primary hover:bg-primary hover:text-black");
  }
  if (status === "denied") return <span className="text-outline">DENIED</span>;
  return <span className="text-tertiary" title="Approve the fix in the detail panel first">NEEDS APPROVAL</span>;
}

export default function FindingsTable({ findings, filters, setFilters, onPick, selected, onCreatePr, busy }) {
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });

  return (
    <section className="bg-surface border-2 border-outline flex-1 flex flex-col min-w-0">
      <div className="p-4 border-b-2 border-outline bg-surface-container-low flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
        <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase tracking-tight flex items-center gap-2">
          <span className="material-symbols-outlined text-error">bug_report</span>
          Live Findings
        </h2>
        <div className="flex flex-wrap gap-2">
          <select value={filters.severity || ""} onChange={set("severity")} className="bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-1 px-2 focus:border-primary outline-none">
            <option value="">ALL SEVS</option>
            {SEVS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select value={filters.tool || ""} onChange={set("tool")} className="bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-1 px-2 focus:border-primary outline-none">
            <option value="">ALL TOOLS</option>
            {TOOLS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select value={filters.verdict || ""} onChange={set("verdict")} className="bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-1 px-2 focus:border-primary outline-none">
            <option value="">ALL VERDICTS</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v === "false_positive" ? "false pos" : v}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-x-auto flex-1">
        <table className="w-full table-fixed text-left border-collapse font-body-sm text-body-sm">
          <thead>
            <tr className="bg-surface-container font-code-label text-code-label text-outline uppercase border-b-2 border-outline">
              <th className="p-3 border-r-2 border-outline font-medium w-20">Tool</th>
              <th className="p-3 border-r-2 border-outline font-medium w-24">Severity</th>
              <th className="p-3 border-r-2 border-outline font-medium">Type</th>
              <th className="p-3 border-r-2 border-outline font-medium w-36">File / Line</th>
              <th className="p-3 border-r-2 border-outline font-medium w-28">Status</th>
              <th className="p-3 font-medium w-28">Fix</th>
            </tr>
          </thead>
          <tbody className="text-on-surface">
            {findings.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-8 text-center text-on-surface-variant font-body-md">
                  No findings match.
                </td>
              </tr>
            ) : (
              findings.map((f) => {
                const status = f.hitl_actions?.[0]?.action || (f.triage?.verdict === "noise" ? "dismissed" : "unresolved");
                const statusLabel = status === "approve" ? "approved" : status === "deny" ? "denied" : status === "edit" ? "edited" : status;
                const statusColor =
                  status === "approve"
                    ? "text-primary"
                    : status === "deny" || status === "dismissed"
                    ? "text-outline"
                    : f.severity === "critical"
                    ? "text-error"
                    : "text-tertiary";

                return (
                  <tr
                    key={f.id}
                    className={`border-b border-outline hover:bg-surface-container-highest transition-colors cursor-pointer ${
                      selected === f.id ? "bg-surface-container-high" : ""
                    }`}
                    onClick={() => onPick(f.id)}
                  >
                    <td className="p-3 border-r-2 border-outline font-code-label">
                      <ToolBadge tool={f.tool} />
                    </td>
                    <td className="p-3 border-r-2 border-outline">
                      <SeverityBadge severity={f.severity} blink={f.severity === "critical" && statusLabel === "unresolved"} />
                    </td>
                    <td className="p-3 border-r-2 border-outline text-on-surface-variant">
                      <div className="line-clamp-2" title={f.message}>{f.message}</div>
                    </td>
                    <td className="p-3 border-r-2 border-outline font-code-label text-outline break-words">
                      {f.file ? (f.line ? `${f.file}:${f.line}` : f.file) : "—"}
                    </td>
                    <td className={`p-3 border-r-2 border-outline font-bold font-code-label text-xs uppercase ${statusColor}`}>{statusLabel}</td>
                    <td className="p-3 font-code-label text-xs">
                      <FixCell fix={f.fix} busy={busy} onStart={() => onCreatePr?.(f.id)} />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
