const SEV_ORDER = ["critical", "high", "medium", "low", "info"]; // bar segment order

const SEV_BG = {
  critical: "bg-error", // red
  high: "bg-tertiary-container",
  medium: "bg-secondary-container",
  low: "bg-primary",
  info: "bg-surface-variant", // muted
};

function Tile({ label, value, children, valueClass = "text-on-surface" }) {
  // Small metric card with label, big number, optional extra content.
  return (
    <div className="bg-surface border-2 border-outline p-4 flex flex-col gap-2">
      <div className="font-code-label text-code-label text-outline uppercase">{label}</div>
      <div className={`font-headline-sm text-headline-sm font-black ${valueClass}`}>{value}</div>
      {children} {/* e.g. severity bar under Findings */}
    </div>
  );
}

export default function MetricsPanel({ metrics }) {
  // Dashboard metric tiles from GET /metrics.
  if (!metrics) return null; // still loading
  const { totals, by_severity } = metrics; // API shape
  const totalSev = SEV_ORDER.reduce((a, s) => a + (by_severity[s] || 0), 0) || 1; // avoid /0

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 shrink-0">
      <Tile label="Findings" value={totals.findings}>
        <div className="flex h-2 w-full">
          {SEV_ORDER.map((s) => {
            const n = by_severity[s] || 0; // count for this severity
            if (!n) return null; // skip empty segments
            return (
              <span
                key={s}
                title={`${s}: ${n}`} // hover tooltip
                className={SEV_BG[s]}
                style={{ width: `${(n / totalSev) * 100}%` }} // proportional width
              />
            );
          })}
        </div>
      </Tile>

      <Tile
        label="Critical / High"
        value={(by_severity.critical || 0) + (by_severity.high || 0)} // risk hot count
        valueClass="text-error"
      />

      <Tile label="Scans" value={totals.scans} /> {/* total scan runs */}

      <Tile label="Fixes Proposed" value={totals.fixes_proposed} valueClass="text-primary" /> {/* AI patches */}

      <Tile label="Fixes Approved" value={totals.fixes_approved} valueClass="text-tertiary" /> {/* HITL approvals */}
    </section>
  );
}
