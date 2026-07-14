import { PipelineBadge, StatusBadge } from "./Badge.jsx";

export default function ScanCard({ scan, active, onClick }) {
  const total = scan.tools_requested.length;
  const doneCount = scan.tools_done.length + scan.tools_failed.length;

  return (
    <div
      onClick={onClick}
      className={`border-2 bg-background p-3 relative overflow-hidden group hover:border-primary transition-colors cursor-pointer ${
        active ? "border-primary" : "border-outline-variant"
      }`}
    >
      <div className="flex justify-between items-start mb-3">
        <div>
          <PipelineBadge pipeline={scan.pipeline} />
          <p className="font-body-sm text-body-sm text-on-surface font-bold mt-1 group-hover:text-primary transition-colors truncate max-w-[180px]">
            {scan.target.replace(/^https?:\/\//, "")}
          </p>
        </div>
        <StatusBadge status={scan.status} />
      </div>

      {scan.status === "queued" ? (
        <div className="font-code-label text-code-label text-primary">Queue position #{scan.queue_position}</div>
      ) : (
        <>
          <div className="h-4 w-full border-2 border-outline-variant bg-surface-container relative mb-2">
            <div
              className={`h-full bg-primary border-r-2 border-outline-variant ${scan.status === "running" ? "progress-striped" : ""}`}
              style={{ width: `${scan.progress_pct}%` }}
            />
            <span className="absolute inset-0 flex items-center justify-center font-code-label text-[10px] text-on-surface mix-blend-difference font-bold">
              {scan.progress_pct}%
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {scan.tools_requested.map((tool) => {
              let state = "pending";
              if (scan.tools_done.includes(tool)) state = "done";
              else if (scan.tools_failed.includes(tool)) state = "failed";
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

      {scan.status !== "queued" && scan.status !== "running" && (
        <div className="mt-2 font-code-label text-[10px] text-on-surface-variant uppercase">
          {scan.finding_count} findings
        </div>
      )}
    </div>
  );
}
