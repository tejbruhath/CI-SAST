import { SeverityBadge, VerdictBadge, ToolBadge } from "./Badge.jsx";

const SEVS = ["critical", "high", "medium", "low", "info"];
const TOOLS = ["gitleaks", "semgrep", "trivy", "zap", "nuclei"];
const VERDICTS = ["real", "false_positive", "noise", "error"];

// Renders the AI-fix remediation lifecycle for one finding.
// No fix → "FIX WITH AI". Fix proposed → "APPROVE NEEDED" (click to approve).
// Approved → "APPROVED" (it will be included in the next PR).
// creating → QUEUED. open → DONE (links to PR). failed → RETRY.
//
// Nothing reaches a PR without passing through the approve step here.
function FixCell({ id, fix, onFixWithAi, onApprove, fixingIds, busy }) {
  const stop = (e) => e.stopPropagation();
  const disabled = busy || fixingIds?.has(id);

  if (fixingIds?.has(id)) {
    return <span className="text-tertiary font-bold animate-pulse">FIXING…</span>;
  }

  const action = (label, cls, onClick) => (
    <button type="button" disabled={disabled}
      onClick={onClick}
      className={`px-2 py-1 border font-code-label text-code-label uppercase font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}>
      {label}
    </button>
  );

  if (!fix) {
    return action(
      "FIX WITH AI",
      "border-primary text-primary hover:bg-primary hover:text-black",
      (e) => { stop(e); onFixWithAi?.(id); }
    );
  }

  const { pr_status, pr_url } = fix;

  if (pr_status === "open") {
    return pr_url ? (
      <a href={pr_url} target="_blank" rel="noreferrer" onClick={stop}
         className="text-primary font-bold hover:underline">DONE ↗</a>
    ) : <span className="text-primary font-bold">DONE</span>;
  }

  if (pr_status === "creating") {
    return <span className="text-tertiary font-bold animate-pulse">QUEUED…</span>;
  }

  if (pr_status === "failed") {
    return action(
      "RETRY",
      "border-error text-error hover:bg-error hover:text-black",
      (e) => { stop(e); onFixWithAi?.(id); }
    );
  }

  if (fix.status === "denied") return <span className="text-outline">DENIED</span>;

  if (fix.status === "approved" || fix.status === "edited") {
    return (
      <span className="text-primary font-bold" title="Included in the next PR">
        ✓ APPROVED
      </span>
    );
  }

  // proposed: the fix exists but you have not okayed it yet.
  return action(
    "APPROVE NEEDED",
    "border-tertiary text-tertiary hover:bg-tertiary hover:text-black",
    (e) => { stop(e); onApprove?.(id); }
  );
}

export default function FindingsTable({ findings, filters, setFilters, onPick, selected, onFixWithAi, onApprove, fixingIds, busy }) {
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });

  return (
    // min-h-0 lets this box shrink inside the flex column so the list below —
    // and only the list — is what scrolls.
    <section className="bg-surface border-2 border-outline flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
      <div className="p-4 border-b-2 border-outline bg-surface-container-low flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3 shrink-0">
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

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto">
        <table className="w-full table-fixed text-left border-collapse font-body-sm text-body-sm">
          <thead className="sticky top-0 z-10">
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
              findings.map((f) => (
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
                    <SeverityBadge severity={f.severity} blink={f.severity === "critical" && (f.verdict === "real" || f.verdict == null)} />
                  </td>
                  <td className="p-3 border-r-2 border-outline text-on-surface-variant">
                    <div className="line-clamp-2" title={f.message}>{f.message}</div>
                  </td>
                  <td className="p-3 border-r-2 border-outline font-code-label text-outline break-words">
                    {f.file ? (f.line ? `${f.file}:${f.line}` : f.file) : "—"}
                  </td>
                  <td className="p-3 border-r-2 border-outline">
                    <VerdictBadge verdict={f.verdict} severity={f.severity} />
                  </td>
                  <td className="p-3 font-code-label text-xs">
                    <FixCell id={f.id} fix={f.fix} onFixWithAi={onFixWithAi} onApprove={onApprove} fixingIds={fixingIds} busy={busy} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
