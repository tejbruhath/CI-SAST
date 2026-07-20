import { useEffect, useMemo, useState } from "react";

const SEVERITY_OPTIONS = [
  { value: "critical_high", label: "Critical + High", sevs: ["critical", "high"] },
  { value: "critical", label: "Critical only", sevs: ["critical"] },
  { value: "high", label: "High only", sevs: ["high"] },
  { value: "medium_plus", label: "Medium and up", sevs: ["critical", "high", "medium"] },
  { value: "all", label: "All severities", sevs: null },
];
const TOOL_OPTIONS = ["all", "gitleaks", "semgrep", "trivy", "zap", "nuclei"];
const VERDICT_OPTIONS = ["real", "all", "false_positive", "noise"];

// A finding is fixable if it has no fix yet, or its last fix attempt failed —
// anything proposed/approved/edited already has a real result, don't reclaim it.
function isFixable(f) {
  return !f.fix || f.fix.status === "failed";
}

export function matchesFixAllFilters(f, { severity, tool, verdict }) {
  const sevs = SEVERITY_OPTIONS.find((o) => o.value === severity)?.sevs;
  if (sevs && !sevs.includes(f.severity)) return false;
  if (tool !== "all" && f.tool !== tool) return false;
  if (verdict !== "all" && (f.verdict || "real") !== verdict) return false;
  return isFixable(f);
}

// Bulk-queue confirmation, mirrors CreatePrDialog's shape: pick scope, see the
// live count, confirm once. Nothing fires until Confirm — filters alone never
// touch the network.
export default function FixAllDialog({ findings, busy, onConfirm, onClose }) {
  const [severity, setSeverity] = useState("critical_high");
  const [tool, setTool] = useState("all");
  const [verdict, setVerdict] = useState("real");

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const matches = useMemo(
    () => findings.filter((f) => matchesFixAllFilters(f, { severity, tool, verdict })),
    [findings, severity, tool, verdict]
  );

  const selectCls =
    "bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-2 px-2 focus:border-primary outline-none w-full";

  return (
    <>
      <div className="fixed inset-0 bg-black/80 z-[60]" onClick={() => !busy && onClose()} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Fix all with AI"
        className="fixed inset-[6%] md:inset-x-[22%] md:inset-y-[12%] bg-surface-container border-4 border-outline-variant shadow-[8px_8px_0_0_rgba(0,0,0,0.6)] flex flex-col z-[61] overflow-hidden"
      >
        <header className="p-6 border-b-2 border-outline-variant shrink-0 bg-surface flex justify-between items-start">
          <h2 className="font-headline-md text-headline-md text-on-surface uppercase">Fix all with AI</h2>
          <button onClick={onClose} disabled={busy} aria-label="Close dialog"
            className="text-on-surface-variant hover:text-primary transition-colors disabled:opacity-40">
            <span className="material-symbols-outlined">close</span>
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto p-6 flex flex-col gap-4 bg-background">
          <p className="font-body-md text-body-md text-on-surface-variant">
            Queues an on-demand AI fix for every matching finding that doesn't already have one.
            Nothing is approved automatically — review and Approve each in the detail dialog.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="flex flex-col gap-1 font-code-label text-code-label text-outline uppercase">
              Severity
              <select value={severity} onChange={(e) => setSeverity(e.target.value)} className={selectCls}>
                {SEVERITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 font-code-label text-code-label text-outline uppercase">
              Tool
              <select value={tool} onChange={(e) => setTool(e.target.value)} className={selectCls}>
                {TOOL_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t === "all" ? "All tools" : t}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 font-code-label text-code-label text-outline uppercase">
              Verdict
              <select value={verdict} onChange={(e) => setVerdict(e.target.value)} className={selectCls}>
                {VERDICT_OPTIONS.map((v) => (
                  <option key={v} value={v}>{v === "false_positive" ? "false pos" : v === "all" ? "all" : v}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="bg-primary/10 border-2 border-primary p-3">
            <p className="font-body-md text-on-surface">
              <strong>{matches.length}</strong> finding{matches.length === 1 ? "" : "s"} match{matches.length === 1 ? "es" : ""} and will be queued.
            </p>
          </div>
        </div>

        <footer className="p-6 border-t-2 border-outline-variant bg-surface shrink-0 flex gap-3">
          <button onClick={onClose} disabled={busy}
            className="flex-1 bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 uppercase hover:border-primary hover:text-primary transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button onClick={() => onConfirm(matches.map((f) => f.id))} disabled={busy || matches.length === 0}
            className="flex-1 bg-primary text-on-primary border-2 border-primary font-code-label text-code-label py-3 uppercase font-bold hover:bg-inverse-primary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center gap-2">
            {busy && <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>}
            {busy ? "Queuing…" : `Fix ${matches.length} with AI`}
          </button>
        </footer>
      </div>
    </>
  );
}
