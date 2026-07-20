import { useEffect, useState } from "react";
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

const btnBase =
  "w-full border-2 font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 transition-colors focus:outline-none font-bold disabled:opacity-50 disabled:cursor-not-allowed";
const btnPrimary = `${btnBase} bg-primary border-primary text-on-primary hover:bg-primary-fixed`;
const btnGhost = `${btnBase} bg-surface-container border-outline-variant text-on-surface hover:border-primary hover:text-primary`;
const btnDanger = `${btnBase} bg-surface-container border-error text-error hover:bg-error hover:text-black`;

export default function FindingDetail({
  finding,
  onClose,
  onFixWithAi,
  onCreatePr,
  onApprove,
  onDeny,
  onEdit,
  busy,
  fixing,
}) {
  const [editing, setEditing] = useState(false);
  const [editedDiff, setEditedDiff] = useState("");

  // Escape closes, like any dialog.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Reset edit mode when the open finding changes.
  useEffect(() => {
    setEditing(false);
    setEditedDiff("");
  }, [finding?.id]);

  if (!finding) return null;

  const fix = finding.fixes && finding.fixes[0];
  const triage = finding.triage;
  const isCritical = finding.severity === "critical";
  const hasDiff = Boolean(fix && (fix.diff || "").trim());
  const isProposed = fix && fix.status === "proposed";
  const isFailed = fix && fix.status === "failed";
  const isDenied = fix && fix.status === "denied";
  const isApproved = fix && (fix.status === "approved" || fix.status === "edited");
  const prDisabled = !fix || fix.status !== "approved" || busy || !hasDiff;

  const githubSlug = parseGithubSlug(finding.scan_target);
  const githubDevUrl =
    fix && fix.branch && githubSlug && finding.file
      ? `https://github.dev/${githubSlug}/blob/${fix.branch}/${finding.file.replace(/^\//, "")}${
          finding.line != null ? `#L${finding.line}` : ""
        }`
      : null;

  const startEdit = () => {
    setEditedDiff(fix?.diff || "");
    setEditing(true);
  };

  const saveEdit = () => {
    onEdit?.(finding.id, editedDiff);
    setEditing(false);
  };

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
              {fixing && (
                <span className="text-tertiary font-code-label text-code-label border-2 border-tertiary px-2 py-1 uppercase font-bold animate-pulse">
                  FIXING…
                </span>
              )}
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

          {/* In-queue state when dialog stayed open / reopened mid-fix */}
          {fixing && !fix && (
            <section className="flex flex-col gap-3 border-2 border-tertiary bg-surface-container p-5">
              <h3 className="font-headline-sm text-headline-sm text-tertiary uppercase border-b-2 border-outline-variant pb-2 flex items-center gap-2">
                <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>
                Generating fix
              </h3>
              <p className="font-body-md text-body-md text-on-surface-variant">
                Fix with AI is queued / running. This panel will update when the suggestion lands.
              </p>
            </section>
          )}

          {/* Suggested Fix / guidance */}
          {fix && (
            <section className="flex flex-col gap-4">
              <h3 className="font-headline-sm text-headline-sm text-on-surface uppercase border-b-2 border-outline-variant pb-2">
                {isFailed ? "Fix generation failed" : hasDiff ? "Suggested Fix" : "Recommended remediation"}
              </h3>
              <p className="font-body-md text-body-md text-on-surface-variant whitespace-pre-wrap">
                {fix.explanation || (isFailed ? "Unknown failure" : "")}
              </p>
              {editing ? (
                <textarea
                  value={editedDiff}
                  onChange={(e) => setEditedDiff(e.target.value)}
                  rows={14}
                  className="w-full border-2 border-outline-variant bg-surface-container p-3 font-code-label text-code-label text-on-surface focus:border-primary outline-none"
                  spellCheck={false}
                />
              ) : (
                hasDiff && <DiffViewer diff={fix.diff} filename={finding.file} />
              )}
              {isDenied && (
                <p className="font-code-label text-code-label text-outline uppercase">Status: DENIED</p>
              )}
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
        <footer className="p-6 border-t-2 border-outline-variant bg-surface flex flex-col gap-3 shrink-0">
          {!fix && !fixing && (
            <button
              onClick={() => { onFixWithAi(finding.id); onClose(); }}
              disabled={busy}
              className={btnPrimary}
            >
              <span className="material-symbols-outlined text-[18px]">auto_fix</span>
              Fix with AI
            </button>
          )}

          {fixing && !fix && (
            <button disabled className={`${btnGhost} opacity-70 cursor-not-allowed`}>
              <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>
              Fixing…
            </button>
          )}

          {isFailed && (
            <button
              onClick={() => { onFixWithAi(finding.id); }}
              disabled={busy || fixing}
              className={btnPrimary}
            >
              <span className="material-symbols-outlined text-[18px]">refresh</span>
              Retry Fix with AI
            </button>
          )}

          {isProposed && !editing && (
            <div className="flex flex-col sm:flex-row gap-3">
              <button onClick={() => onDeny?.(finding.id)} disabled={busy} className={btnDanger}>
                Deny
              </button>
              {hasDiff && (
                <button onClick={startEdit} disabled={busy} className={btnGhost}>
                  Edit
                </button>
              )}
              <button onClick={() => onApprove?.(finding.id)} disabled={busy} className={btnPrimary}>
                Approve
              </button>
            </div>
          )}

          {isProposed && editing && (
            <div className="flex flex-col sm:flex-row gap-3">
              <button onClick={() => setEditing(false)} disabled={busy} className={btnGhost}>
                Cancel
              </button>
              <button onClick={saveEdit} disabled={busy} className={btnPrimary}>
                Save edit
              </button>
            </div>
          )}

          {isApproved && (
            <>
              {githubDevUrl && (
                <a href={githubDevUrl} target="_blank" rel="noreferrer" className="block w-full">
                  <button className={btnGhost}>
                    <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                    Edit on GitHub
                  </button>
                </a>
              )}

              <div>
                {fix.pr_status === "open" && fix.pr_url ? (
                  <a href={fix.pr_url} target="_blank" rel="noreferrer" className="block w-full">
                    <button className={btnPrimary}>
                      <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                      View Pull Request
                    </button>
                  </a>
                ) : fix.pr_status === "creating" ? (
                  <button disabled className={`${btnGhost} opacity-70 cursor-not-allowed`}>
                    <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>
                    Creating Pull Request…
                  </button>
                ) : hasDiff ? (
                  <button
                    onClick={() => onCreatePr(finding.id)}
                    disabled={prDisabled}
                    className={btnGhost}
                  >
                    <span className="material-symbols-outlined text-[18px]">merge</span>
                    Create Pull Request
                  </button>
                ) : (
                  <p className="font-code-label text-[10px] text-on-surface-variant uppercase">
                    Guidance-only fix — no code patch to open a PR for. Follow the steps above.
                  </p>
                )}
                {prDisabled && hasDiff && fix.status !== "approved" && (
                  <p className="mt-2 font-code-label text-[10px] text-on-surface-variant uppercase">
                    Approve the fix to enable PR creation
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
