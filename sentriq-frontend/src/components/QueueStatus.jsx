export default function QueueStatus({ queue }) {
  return (
    <div className="bg-surface-container border-2 border-outline p-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-3 h-3 bg-primary rounded-none border border-black animate-pulse" />
        <p className="font-code-label text-code-label text-on-surface uppercase tracking-wide">
          SYSTEM STATUS:{" "}
          <span className="text-primary font-bold">
            {queue.queue_depth} {queue.queue_depth === 1 ? "scan" : "scans"} in queue
          </span>
          <span className="text-outline mx-2">·</span>
          <span className="text-on-surface-variant">
            {queue.active_tasks} {queue.active_tasks === 1 ? "tool" : "tools"} running
          </span>
        </p>
      </div>
      <span className="material-symbols-outlined text-outline">dns</span>
    </div>
  );
}
