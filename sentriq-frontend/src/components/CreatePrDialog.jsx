import { useEffect } from "react";

// Confirmation gate for PR creation.
//
// The whole point is that it is explicit about scope: it lists exactly the
// fixes you approved, and says plainly that nothing else goes in. After the PR
// exists we can offer "open code diffs", because only then is there a branch
// on GitHub for github.dev to open.
export default function CreatePrDialog({
  approved,      // [{ id, message, file, severity, rule_id }]
  repoSlug,      // "owner/repo"
  result,        // null | { pr_url, branch, count }
  busy,
  onConfirm,
  onClose,
}) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  // github.dev opens the web editor on a branch that already contains the
  // fixes — the closest thing to "Codespaces with the diffs applied" that a
  // URL can express. It only works once the branch is pushed, i.e. post-PR.
  const diffsUrl =
    result?.branch && repoSlug
      ? `https://github.dev/${repoSlug}/tree/${result.branch}`
      : null;

  return (
    <>
      <div className="fixed inset-0 bg-black/80 z-[60]" onClick={() => !busy && onClose()} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Create pull request"
        className="fixed inset-[6%] md:inset-x-[22%] md:inset-y-[12%] bg-surface-container border-4 border-outline-variant shadow-[8px_8px_0_0_rgba(0,0,0,0.6)] flex flex-col z-[61] overflow-hidden"
      >
        <header className="p-6 border-b-2 border-outline-variant shrink-0 bg-surface flex justify-between items-start">
          <div>
            <h2 className="font-headline-md text-headline-md text-on-surface uppercase">
              {result ? "Pull request opened" : "Create pull request"}
            </h2>
            <p className="font-code-label text-code-label text-outline uppercase mt-1">{repoSlug}</p>
          </div>
          <button onClick={onClose} disabled={busy} aria-label="Close dialog"
            className="text-on-surface-variant hover:text-primary transition-colors disabled:opacity-40">
            <span className="material-symbols-outlined">close</span>
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto p-6 flex flex-col gap-4 bg-background">
          {!result && (
            <div className="bg-primary/10 border-2 border-primary p-3 flex gap-3 items-start">
              <span className="material-symbols-outlined text-primary text-[20px]">check_circle</span>
              <p className="font-body-md text-body-md text-on-surface">
                Only the <strong>{approved.length}</strong> fix{approved.length === 1 ? "" : "es"} you
                approved will go into this pull request. Findings you have not approved are not
                touched, and no other file is modified.
              </p>
            </div>
          )}

          <h3 className="font-headline-sm text-headline-sm text-on-surface uppercase border-b-2 border-outline-variant pb-2">
            {result ? `Included (${result.count})` : `Approved fixes (${approved.length})`}
          </h3>

          {approved.length === 0 ? (
            <p className="font-body-md text-on-surface-variant">
              Nothing approved yet. Approve a fix first — the FIX column shows
              “APPROVE NEEDED” for any fix awaiting you.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {approved.map((f) => (
                <li key={f.id} className="border-2 border-outline-variant bg-surface-container p-3 flex gap-3 items-start">
                  <span className="font-code-label text-code-label text-tertiary uppercase shrink-0">{f.severity}</span>
                  <div className="min-w-0">
                    <div className="font-body-sm text-on-surface line-clamp-2">{f.message}</div>
                    <div className="font-code-label text-code-label text-outline mt-1">
                      {f.file || "—"}{f.rule_id ? ` · ${f.rule_id}` : ""}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {result && (
            <div className="bg-primary/10 border-2 border-primary p-3">
              <p className="font-body-md text-on-surface">
                Branch <span className="font-code-label text-primary">{result.branch}</span> was
                pushed with these fixes applied.
              </p>
            </div>
          )}
        </div>

        <footer className="p-6 border-t-2 border-outline-variant bg-surface shrink-0 flex flex-col gap-3">
          {result ? (
            <div className="flex gap-3">
              {result.pr_url && (
                <a href={result.pr_url} target="_blank" rel="noreferrer" className="flex-1">
                  <button className="w-full bg-primary text-on-primary border-2 border-primary font-code-label text-code-label py-3 uppercase font-bold flex justify-center items-center gap-2 hover:bg-inverse-primary hover:text-white transition-colors">
                    <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                    View pull request
                  </button>
                </a>
              )}
              {diffsUrl && (
                <a href={diffsUrl} target="_blank" rel="noreferrer" className="flex-1">
                  <button className="w-full bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 uppercase flex justify-center items-center gap-2 hover:border-primary hover:text-primary transition-colors">
                    <span className="material-symbols-outlined text-[18px]">code</span>
                    Open code diffs
                  </button>
                </a>
              )}
            </div>
          ) : (
            <div className="flex gap-3">
              <button onClick={onClose} disabled={busy}
                className="flex-1 bg-surface-container border-2 border-outline-variant text-on-surface font-code-label text-code-label py-3 uppercase hover:border-primary hover:text-primary transition-colors disabled:opacity-50">
                Cancel
              </button>
              <button onClick={onConfirm} disabled={busy || approved.length === 0}
                className="flex-1 bg-primary text-on-primary border-2 border-primary font-code-label text-code-label py-3 uppercase font-bold hover:bg-inverse-primary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center gap-2">
                {busy && <span className="material-symbols-outlined animate-spin text-[18px]">sync</span>}
                {busy ? "Opening…" : `Create PR with ${approved.length}`}
              </button>
            </div>
          )}
        </footer>
      </div>
    </>
  );
}
