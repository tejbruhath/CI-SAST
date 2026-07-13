import { SeverityBadge, VerdictBadge, ToolBadge } from "./Badge.jsx";

const SEVS = ["critical", "high", "medium", "low", "info"];
const TOOLS = ["gitleaks", "semgrep", "trivy", "zap", "nuclei"];
const VERDICTS = ["real", "false_positive", "noise", "pending"];

export default function FindingsTable({ findings, filters, setFilters, onPick, selected }) {
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });

  return (
    <div>
      <div className="filters">
        <select value={filters.severity || ""} onChange={set("severity")}>
          <option value="">All severities</option>
          {SEVS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filters.tool || ""} onChange={set("tool")}>
          <option value="">All tools</option>
          {TOOLS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={filters.verdict || ""} onChange={set("verdict")}>
          <option value="">All verdicts</option>
          {VERDICTS.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      {findings.length === 0 ? (
        <div className="empty">No findings match.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Severity</th><th>Tool</th><th>Finding</th>
              <th>Location</th><th>Triage</th><th>Fix</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => (
              <tr key={f.id} className={`f-row ${selected === f.id ? "sel" : ""}`}
                onClick={() => onPick(f.id)}>
                <td><SeverityBadge severity={f.severity} /></td>
                <td><ToolBadge tool={f.tool} /></td>
                <td>{f.message}<div className="file mono">{f.rule_id}</div></td>
                <td className="mono file">
                  {f.file ? (f.line ? `${f.file}:${f.line}` : f.file) : "—"}
                </td>
                <td><VerdictBadge verdict={f.verdict} /></td>
                <td>{f.has_fix ? <span className="fix-dot">●</span> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
