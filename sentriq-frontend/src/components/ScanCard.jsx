import { PipelineBadge, StatusBadge } from "./Badge.jsx"; // status chips

export default function ScanCard({ scan, active, onClick, onShowFindings }) {
  // Compact card for one scan: progress, tools, findings CTA.
  const total = scan.tools_requested.length; // planned tools (may be unused visually)
  const doneCount = scan.tools_done.length + scan.tools_failed.length; // finished tools

  return (
    <div
      onClick={onClick} // select this scan in parent state
      className={`border-2 bg-background p-3 relative overflow-hidden group hover:border-primary transition-colors cursor-pointer ${
        active ? "border-primary" : "border-outline-variant" // highlight when selected
      }`}
    >
      <div className="flex justify-between items-start mb-3">
        <div>
          <PipelineBadge pipeline={scan.pipeline} /> {/* static|dynamic */}
          <p className="font-body-sm text-body-sm text-on-surface font-bold mt-1 group-hover:text-primary transition-colors truncate max-w-[180px]">
            {scan.target.replace(/^https?:\/\//, "")} {/* strip scheme for display */}
          </p>
        </div>
        <StatusBadge status={scan.status} /> {/* lifecycle status */}
      </div>

      {scan.status === "queued" ? (
        <div className="font-code-label text-code-label text-primary">Queue position #{scan.queue_position}</div> // FIFO place
      ) : (
        <>
          {/* Progress bar */}
          <div className="h-4 w-full border-2 border-outline-variant bg-surface-container relative mb-2">
            <div
              className={`h-full bg-primary border-r-2 border-outline-variant ${scan.status === "running" ? "progress-striped" : ""}`}
              style={{ width: `${scan.progress_pct}%` }} // 0–100 from serializer
            />
            <span className="absolute inset-0 flex items-center justify-center font-code-label text-[10px] text-on-surface mix-blend-difference font-bold">
              {scan.progress_pct}%
            </span>
          </div>
          {/* Per-tool chips */}
          <div className="flex flex-wrap gap-1">
            {scan.tools_requested.map((tool) => {
              let state = "pending"; // not finished yet
              if (scan.tools_done.includes(tool)) state = "done"; // success
              else if (scan.tools_failed.includes(tool)) state = "failed"; // error
              const style =
                state === "done"
                  ? "bg-primary/20 text-primary border-primary/50"
                  : state === "failed"
                  ? "bg-error/20 text-error border-error/50"
                  : "bg-surface-container-high text-on-surface-variant border-outline-variant";
              return (
                <span key={tool} className={`font-code-label text-[10px] px-1.5 py-0.5 border uppercase ${style}`}>
                  {tool}
                </span>
              );
            })}
          </div>
        </>
      )}

      {/* Footer when terminal */}
      {scan.status !== "queued" && scan.status !== "running" && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="font-code-label text-[10px] text-on-surface-variant uppercase">
            {scan.finding_count} findings
          </span>
          {(scan.status === "complete" || scan.status === "partial") && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onShowFindings?.(scan.id); }} // don't re-fire card click
              className="px-2 py-1 border border-primary text-primary font-code-label text-[10px] uppercase font-bold hover:bg-primary hover:text-black transition-colors"
            >
              Show findings
            </button>
          )}
        </div>
      )}
    </div>
  );
}
