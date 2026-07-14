import { useEffect } from "react";
import { SeverityBadge, ToolBadge, VerdictBadge } from "./Badge.jsx";
import DiffViewer from "./DiffViewer.jsx";

function parseGithubSlug(targetUrl) {
  if (typeof targetUrl !== "string") return null;
  let u = targetUrl.trim();
  u = u.replace(/^https?:\/\/[^/@]*@/, "https://");
  let m = u.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/);
  if (m) return `${m[1]}/${m[2]}`;
  m = u.match(/^git@github\.com:([^/]+)\/([^/]+?)(?:\.git)?$/);
  if (m) return `${m[1]}/${m[2]}`;
  return null;
}

export default function FindingDetail({ finding, onClose, onFixWithAi, onCreatePr, busy }) {
  // Escape closes, like any dialog.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!finding) return null;

  const fix = finding.fixes && finding.fixes[0];
  const triage = finding.triage;
  const isCritical = finding.severity === "critical";

  const prDisabled = !fix || fix.status !== "approved" || busy;

  const githubSlug = parseGithubSlug(finding.scan_target);
  const githubDevUrl =
    fix && fix.branch && githubSlug && finding.file
      ? `https://github.dev/${githubSlug}/blob/${fix.branch}/${finding.file.replace(/^\//, "")}${
          finding.line != null ? `#L${finding.line}` : ""
        }`
      : null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/80 z-40" onClick={onClose} />

      {/* Centered dialog: 10% margins on every side (i.e. 80% of the viewport),
          tighter on small screens. Fixed inset — never grows the page. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={finding.message}
        className="fixed inset-[4%] md:inset-[10%] bg-surface-container border-4 border-outline-variant shadow-[8px_8px_0_0_rgba(0,0,0,0.6)] flex flex-col z-50 overflow-hidden"
      >
        {/* Header */}
        <header className="p-6 border-b-2 border-outline-variant flex flex-col gap-4 shrink-0 bg-surface">
          <div className="flex justify-between items-start">
            <div className="flex items-center gap-3 flex-wrap">
              <SeverityBadge severity={finding.severity} blink={isCritical} />
              <ToolBadge tool={finding.tool} />
              <span className="text-on-surface-variant font-code-label text-code-label border-2 border-outline-variant px-2 py-1 uppercase">
                {finding.type}
              </span>
            </div>
            <button onClick={onClose} aria-label="Close dialog" className="text-on-surface-variant hover:text-primary transition-colors focus:outline-none">
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
        <div className="flex-1 min-h-0 overflow-y-auto p-6 flex flex-col gap-8 bg-background">
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
              <p className="font-body-md text-body-md text-on-surface-variant">
                Not triaged yet — triage runs once every scanner in the scan has finished.
              </p>
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
              {finding.details && Object.keys(finding.details).length
                ? JSON.stringify(finding.details, null, 2)
                : "— none reported by this tool"}
            </pre>
          </section>
        </div>

        {/* Footer */}
        <footer className="p-6 border-t-2 border-outline-variant bg-surface flex flex-col gap-4 shrink-0">
          {!fix && (
            <button
              onClick={() => onFixWithAi(finding.id)}
              disabled={busy}
              className="w-full bg-primary border-2 border-primary text-on-primary font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 hover:bg-primary-fixed transition-colors focus:outline-none font-bold disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">auto_fix</span>
              Fix with AI
            </button>
          )}

          {fix && (
            <>
              {githubDevUrl && (
                <a href={githubDevUrl} target="_blank" rel="noreferrer" className="block w-full">
                  <button className="w-full bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 hover:border-primary hover:text-primary transition-colors focus:outline-none">
                    <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                    Edit on GitHub
                  </button>
                </a>
              )}

              <div>
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
                    {fix.status !== "approved"
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
