function statusColor(s) {
  return {
    complete: "var(--ok)", partial: "var(--med)", failed: "var(--crit)",
    running: "var(--accent)", queued: "var(--muted)",
  }[s] || "var(--muted)";
}

export default function ScansList({ scans, onPick, activeScan }) {
  if (!scans.length) return <div className="spinner">No scans yet.</div>;
  return (
    <div>
      {scans.map((s) => (
        <div key={s.id} className="scan-row" onClick={() => onPick(s.id)}
          style={activeScan === s.id ? { color: "var(--accent)" } : undefined}>
          <div className="t" title={s.target}>
            <span className="badge tool" style={{ marginRight: 6 }}>{s.pipeline}</span>
            {s.target.replace(/^https?:\/\//, "")}
          </div>
          <div className="s" style={{ color: statusColor(s.status) }}>
            {s.status} · {s.finding_count}
          </div>
        </div>
      ))}
    </div>
  );
}
