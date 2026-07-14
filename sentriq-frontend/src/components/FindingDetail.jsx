import { useState } from "react";
import { SeverityBadge, ToolBadge, VerdictBadge } from "./Badge.jsx";
import DiffViewer from "./DiffViewer.jsx";

export default function FindingDetail({ finding, onClose, onHitl, onCreatePr, busy }) {
  const [note, setNote] = useState("");
  if (!finding) return null;

  const fix = finding.fixes && finding.fixes[0];
  const triage = finding.triage;
  const lastHitl = finding.hitl_actions && finding.hitl_actions[0];
  const isCritical = finding.severity === "critical";
  const hitlApproved = lastHitl?.action === "approve";

  const prDisabled = !fix || fix.status !== "approved" || (isCritical && !hitlApproved) || busy;

  const act = async (action) => {
    await onHitl(finding.id, action, "reviewer", note, null);
    setNote("");
  };

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/80 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full md:w-[600px] bg-surface-container border-l-4 border-outline-variant shadow-[-8px_0_0_0_rgba(42,47,61,0.5)] flex flex-col z-50">
        {/* Header */}
        <header className="p-6 border-b-2 border-outline-variant flex flex-col gap-4 shrink-0 bg-surface">
          <div className="flex justify-between items-start">
            <div className="flex items-center gap-3 flex-wrap">
              <SeverityBadge severity={finding.severity} blink={isCritical && !hitlApproved} />
              <ToolBadge tool={finding.tool} />
              <span className="text-on-surface-variant font-code-label text-code-label border-2 border-outline-variant px-2 py-1 uppercase">
                {finding.type}
              </span>
            </div>
            <button onClick={onClose} aria-label="Close drawer" className="text-on-surface-variant hover:text-primary transition-colors focus:outline-none">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
          <div>
            <h2 className="font-headline-md text-headline-md text-on-surface mb-1">{finding.message}</h2>
            <div className="flex items-center gap-2 text-on-surface-variant font-code-label text-code-label flex-wrap">
              <span className="material-symbols-outlined text-[16px]">build</span>
              <span>{finding.tool}</span>
              <span className="w-1 h-1 bg-outline-variant rounded-full mx-1" />
              <span className="material-symbols-outlined text-[16px]">description</span>
              <span>{finding.file ? (finding.line ? `${finding.file}:${finding.line}` : finding.file) : "—"}</span>
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-8 bg-background">
          {/* Triage */}
          <section className="flex flex-col gap-4 border-2 border-outline-variant bg-surface-container p-5">
            <div className="flex justify-between items-center border-b-2 border-outline-variant pb-3 mb-1">
              <h3 className="font-headline-sm text-headline-sm text-primary uppercase tracking-wider">AI Triage</h3>
              {triage && (
                <div className="flex items-center gap-2">
                  <span className="font-code-label text-code-label text-on-surface-variant">CONFIDENCE:</span>
                  <span className="font-code-label text-code-label text-primary">{(triage.confidence * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
            {triage ? (
              <>
                <div className="flex items-center gap-3 mb-2">
                  <span className="material-symbols-outlined text-error material-symbols-filled">warning</span>
                  <span className="font-headline-sm text-headline-sm text-error uppercase">Verdict: {triage.verdict}</span>
                </div>
                <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">{triage.rationale}</p>
              </>
            ) : (
              <p className="font-body-md text-body-md text-on-surface-variant">Not triaged yet.</p>
            )}
          </section>

          {/* Suggested Fix */}
          {fix && (
            <section className="flex flex-col gap-4">
              <h3 className="font-headline-sm text-headline-sm text-on-surface uppercase border-b-2 border-outline-variant pb-2">
                Suggested Fix
              </h3>
              <p className="font-body-md text-body-md text-on-surface-variant">{fix.explanation}</p>
              <DiffViewer diff={fix.diff} filename={finding.file} />
            </section>
          )}

          {/* Raw details */}
          <section className="flex flex-col gap-2">
            <h3 className="font-headline-sm text-headline-sm text-on-surface uppercase border-b-2 border-outline-variant pb-2">
              Raw Details
            </h3>
            <pre className="border-2 border-outline-variant bg-surface-container p-4 overflow-x-auto font-code-label text-code-label text-on-surface-variant">
              {JSON.stringify(finding.details, null, 2)}
            </pre>
          </section>
        </div>

        {/* Footer */}
        <footer className="p-6 border-t-2 border-outline-variant bg-surface flex flex-col gap-4 shrink-0">
          {isCritical && !hitlApproved && (
            <div className="flex items-center gap-3 bg-error-container text-on-error-container p-3 border-2 border-error">
              <span className="material-symbols-outlined material-symbols-filled">error</span>
              <span className="font-body-md text-body-md font-bold uppercase">Critical — Human approval required before auto-remediation.</span>
            </div>
          )}

          {fix && (
            <>
              <div className="flex gap-3 w-full">
                <button
                  onClick={() => act("deny")}
                  disabled={busy}
                  className="flex-1 bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 hover:border-primary hover:text-primary transition-colors focus:outline-none uppercase disabled:opacity-50"
                >
                  Deny
                </button>
                <button
                  onClick={() => act("edit")}
                  disabled={busy}
                  className="flex-1 bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 hover:border-primary hover:text-primary transition-colors focus:outline-none uppercase disabled:opacity-50"
                >
                  Edit
                </button>
                <button
                  onClick={() => act("approve")}
                  disabled={busy}
                  className="flex-1 bg-primary border-2 border-primary text-on-primary font-code-label text-code-label py-3 hover:bg-primary-fixed hover:border-primary-fixed transition-colors focus:outline-none uppercase font-bold disabled:opacity-50"
                >
                  Approve
                </button>
              </div>

              <div className="pt-2">
                {fix.pr_status === "open" && fix.pr_url ? (
                  <a href={fix.pr_url} target="_blank" rel="noreferrer" className="block w-full">
                    <button className="w-full bg-primary text-on-primary border-2 border-primary font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 hover:bg-primary-fixed transition-colors">
                      <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                      View Pull Request
                    </button>
                  </a>
                ) : fix.pr_status === "creating" ? (
                  <button disabled className="w-full bg-surface-container border-2 border-outline-variant text-outline font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 opacity-70 cursor-not-allowed">
                    <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>
                    Creating Pull Request…
                  </button>
                ) : (
                  <button
                    onClick={() => onCreatePr(finding.id)}
                    disabled={prDisabled}
                    className="w-full bg-surface-container border-2 border-outline-variant text-outline font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 hover:border-primary hover:text-primary transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
                  >
                    <span className="material-symbols-outlined text-[18px]">merge</span>
                    Create Pull Request
                  </button>
                )}
                {prDisabled && fix && (
                  <p className="mt-2 font-code-label text-[10px] text-on-surface-variant uppercase">
                    {isCritical && !hitlApproved
                      ? "Critical finding requires HITL approval first"
                      : fix.status !== "approved"
                      ? "Approve the fix to enable PR creation"
                      : ""}
                  </p>
                )}
              </div>
            </>
          )}
        </footer>
      </div>
    </>
  );
}
