const SEV_ORDER = ["critical", "high", "medium", "low", "info"];

const SEV_BG = {
  critical: "bg-error",
  high: "bg-tertiary-container",
  medium: "bg-secondary-container",
  low: "bg-primary",
  info: "bg-surface-variant",
};

function Tile({ label, value, children, valueClass = "text-on-surface" }) {
  return (
    <div className="bg-surface border-2 border-outline p-4 flex flex-col gap-2">
      <div className="font-code-label text-code-label text-outline uppercase">{label}</div>
      <div className={`font-headline-sm text-headline-sm font-black ${valueClass}`}>{value}</div>
      {children}
    </div>
  );
}

export default function MetricsPanel({ metrics }) {
  if (!metrics) return null;
  const { totals, by_severity } = metrics;
  const totalSev = SEV_ORDER.reduce((a, s) => a + (by_severity[s] || 0), 0) || 1;

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 shrink-0">
      <Tile label="Findings" value={totals.findings}>
        <div className="flex h-2 w-full">
          {SEV_ORDER.map((s) => {
            const n = by_severity[s] || 0;
            if (!n) return null;
            return (
              <span
                key={s}
                title={`${s}: ${n}`}
                className={SEV_BG[s]}
                style={{ width: `${(n / totalSev) * 100}%` }}
              />
            );
          })}
        </div>
      </Tile>

      <Tile
        label="Critical / High"
        value={(by_severity.critical || 0) + (by_severity.high || 0)}
        valueClass="text-error"
      />

      <Tile label="Scans" value={totals.scans} />

      <Tile label="Fixes Proposed" value={totals.fixes_proposed} valueClass="text-primary" />

      <Tile label="Fixes Approved" value={totals.fixes_approved} valueClass="text-tertiary" />
    </section>
  );
}
