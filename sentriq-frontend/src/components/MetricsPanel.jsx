const SEV_ORDER = ["critical", "high", "medium", "low", "info"];
const SEV_VAR = {
  critical: "var(--crit)", high: "var(--high)", medium: "var(--med)",
  low: "var(--low)", info: "var(--info)",
};

export default function MetricsPanel({ metrics }) {
  if (!metrics) return null;
  const { totals, by_severity } = metrics;
  const totalSev = SEV_ORDER.reduce((a, s) => a + (by_severity[s] || 0), 0) || 1;

  return (
    <div className="metrics">
      <div className="tile">
        <div className="label">Findings</div>
        <div className="value">{totals.findings}</div>
        <div className="sevbar">
          {SEV_ORDER.map((s) => {
            const n = by_severity[s] || 0;
            if (!n) return null;
            return <span key={s} title={`${s}: ${n}`}
              style={{ width: `${(n / totalSev) * 100}%`, background: SEV_VAR[s] }} />;
          })}
        </div>
      </div>
      <div className="tile">
        <div className="label">Critical / High</div>
        <div className="value" style={{ color: "var(--crit)" }}>
          {(by_severity.critical || 0) + (by_severity.high || 0)}
        </div>
      </div>
      <div className="tile">
        <div className="label">Scans</div>
        <div className="value">{totals.scans}</div>
      </div>
      <div className="tile">
        <div className="label">Fixes Proposed</div>
        <div className="value">{totals.fixes_proposed}</div>
      </div>
      <div className="tile">
        <div className="label">Fixes Approved</div>
        <div className="value" style={{ color: "var(--ok)" }}>{totals.fixes_approved}</div>
      </div>
    </div>
  );
}
