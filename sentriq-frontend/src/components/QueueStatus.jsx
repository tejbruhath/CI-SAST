// `triagingScan` is the repo's active scan while it's in the AI-triage phase
// (tools done, triage_done < triage_total) — findings are already in the DB
// at this point but hidden from the table until the scan finishes, so this is
// the only signal a user has that something is still happening.
export default function QueueStatus({ queue, triagingScan }) {
  // Banner for Celery queue depth + optional AI triage progress.
  return (
    <div className="flex flex-col gap-2">
      {/* Worker / queue summary */}
      <div className="bg-surface-container border-2 border-outline p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 bg-primary rounded-none border border-black animate-pulse" /> {/* live indicator */}
          <p className="font-code-label text-code-label text-on-surface uppercase tracking-wide">
            SYSTEM STATUS:{" "}
            <span className="text-primary font-bold">
              {queue.queue_depth} {queue.queue_depth === 1 ? "scan" : "scans"} in queue {/* pluralize */}
            </span>
            <span className="text-outline mx-2">·</span>
            <span className="text-on-surface-variant">
              {queue.active_tasks} {queue.active_tasks === 1 ? "tool" : "tools"} running {/* concurrent tools */}
            </span>
          </p>
        </div>
        <span className="material-symbols-outlined text-outline">dns</span> {/* server icon */}
      </div>

      {/* AI triage phase banner (optional) */}
      {triagingScan && (
        <div className="bg-tertiary/10 border-2 border-tertiary p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-tertiary animate-spin text-[20px]">sync</span> {/* spinning */}
            <p className="font-code-label text-code-label text-on-surface uppercase tracking-wide">
              AI TRIAGE RUNNING:{" "}
              <span className="text-tertiary font-bold">
                {triagingScan.triage_done}/{triagingScan.triage_total} findings {/* progress fraction */}
              </span>
              <span className="text-outline mx-2">·</span>
              <span className="text-on-surface-variant">{triagingScan.progress_pct}% complete</span>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
