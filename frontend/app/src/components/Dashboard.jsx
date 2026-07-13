import React, { useState } from "react";
import { SEV_COLOR, formatCommitDate } from "../data/util.js";
import {
  trajectoryForBranch, findingsByAuthor, findingsByTool, findingsBySeverity,
} from "../data/analytics.js";

const ACCENT = "var(--viz-accent-bg)";
const SEV_SERIES = [
  { key: "critical", color: SEV_COLOR.critical, label: "Critical" },
  { key: "high", color: SEV_COLOR.high, label: "High" },
  { key: "medium", color: SEV_COLOR.medium, label: "Medium" },
  { key: "low", color: SEV_COLOR.low, label: "Low" },
];

/** Multi-line trajectory chart: one line per severity, x = commits oldest->newest. */
function TrajectoryChart({ points, onPointClick }) {
  const width = 640, height = 220, padL = 32, padR = 12, padT = 12, padB = 26;
  const innerW = width - padL - padR, innerH = height - padT - padB;
  const n = points.length;
  const xFor = (i) => (n <= 1 ? padL + innerW / 2 : padL + (innerW * i) / (n - 1));
  const maxY = Math.max(1, ...points.flatMap((p) => SEV_SERIES.map((s) => p[s.key] || 0)));
  const yFor = (v) => padT + innerH - (innerH * v) / maxY;
  const [hoverI, setHoverI] = useState(null);
  const yTicks = [0, Math.round(maxY / 2), maxY].filter((v, i, a) => a.indexOf(v) === i);

  function handleMove(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left - padL) / innerW;
    setHoverI(Math.max(0, Math.min(n - 1, Math.round(rel * (n - 1)))));
  }

  const hp = hoverI != null ? points[hoverI] : null;

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart-svg"
        onMouseMove={n > 0 ? handleMove : undefined}
        onMouseLeave={() => setHoverI(null)}
        onClick={() => hp && onPointClick && onPointClick(hp)}
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={width - padR} y1={yFor(t)} y2={yFor(t)} stroke="var(--viz-border)" strokeWidth="1" />
            <text x={padL - 6} y={yFor(t) + 3} textAnchor="end" fontSize="9" fill="var(--viz-muted)">{t}</text>
          </g>
        ))}
        {SEV_SERIES.map((s) => (
          <path
            key={s.key}
            d={points.map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i)} ${yFor(p[s.key] || 0)}`).join(" ")}
            fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
          />
        ))}
        {SEV_SERIES.map((s) =>
          points.map((p, i) => (
            <circle key={s.key + p.id} cx={xFor(i)} cy={yFor(p[s.key] || 0)} r="4"
              fill={s.color} stroke="var(--viz-panel)" strokeWidth="2" />
          ))
        )}
        {hoverI != null && (
          <line x1={xFor(hoverI)} x2={xFor(hoverI)} y1={padT} y2={height - padB}
            stroke="var(--viz-accent)" strokeWidth="1" opacity="0.5" />
        )}
        {points.map((p, i) => (i === 0 || i === n - 1) && (
          <text key={p.id} x={xFor(i)} y={height - 8}
            textAnchor={i === 0 ? "start" : "end"} fontSize="9" fill="var(--viz-muted)">
            {p.id}
          </text>
        ))}
      </svg>
      {hp && (
        <div className="chart-tooltip" style={{
          left: `${n <= 1 ? 50 : Math.min(85, Math.max(15, (hoverI / (n - 1)) * 100))}%`,
        }}>
          <div className="text-sm font-medium">{hp.id} · {formatCommitDate(hp.epoch)}</div>
          {SEV_SERIES.filter((s) => hp[s.key] > 0).map((s) => (
            <div key={s.key} className="chart-tooltip-row">
              <span className="chart-linekey" style={{ background: s.color }} />
              <span className="text-muted">{s.label}</span>
              <span className="font-medium">{hp[s.key]}</span>
            </div>
          ))}
          {hp.resolved > 0 && (
            <div className="chart-tooltip-row">
              <span className="text-muted">Resolved this commit</span>
              <span className="font-medium">{hp.resolved}</span>
            </div>
          )}
          <div className="text-xs text-muted mt-1">Click to open this commit</div>
        </div>
      )}
      <div className="chart-legend">
        {SEV_SERIES.map((s) => (
          <span key={s.key} className="chart-legend-item">
            <span className="chart-linekey" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Horizontal bar list: magnitude by category, capped with an "Other" bucket. */
function BarList({ rows, colorFor }) {
  const top = rows.slice(0, 7);
  const restCount = rows.slice(7).reduce((n, r) => n + r.count, 0);
  const items = restCount > 0 ? [...top, { name: `Other (${rows.length - 7})`, count: restCount }] : top;
  const max = Math.max(1, ...items.map((r) => r.count));
  if (items.length === 0) return <div className="text-sm text-muted">No data.</div>;
  return (
    <div className="space-y-1">
      {items.map((r) => (
        <div key={r.name} className="bar-row">
          <div className="bar-row-label text-sm truncate" title={r.name}>{r.name}</div>
          <div className="bar-row-track">
            <div className="bar-row-fill" style={{ width: `${(r.count / max) * 100}%`, background: colorFor(r) }} />
          </div>
          <div className="bar-row-value text-sm font-medium">{r.count}</div>
        </div>
      ))}
    </div>
  );
}

function DataTable({ rows, columns }) {
  return (
    <div className="overflow-x-auto">
      <table className="chart-table">
        <thead>
          <tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{columns.map((c) => <td key={c.key}>{c.render ? c.render(r) : r[c.key]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartCard({ title, subtitle, tableColumns, tableRows, children }) {
  const [table, setTable] = useState(false);
  return (
    <section className="chart-card">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">{title}</div>
          {subtitle && <div className="text-sm text-muted">{subtitle}</div>}
        </div>
        <button type="button" className="chip" onClick={() => setTable((t) => !t)}>
          {table ? "Chart view" : "Table view"}
        </button>
      </div>
      <div className="mt-3">
        {table ? <DataTable rows={tableRows} columns={tableColumns} /> : children}
      </div>
    </section>
  );
}

export default function Dashboard({ repos, repo, branch, commit, onSelectCommit, onClose }) {
  const scopedFindings = commit
    ? commit.findings
    : branch
    ? (branch.commits[0]?.findings || [])
    : repo
    ? repo.branches.flatMap((b) => b.commits[0]?.findings || [])
    : repos.flatMap((r) => r.branches.flatMap((b) => b.commits[0]?.findings || []));

  const byAuthor = findingsByAuthor(scopedFindings);
  const byTool = findingsByTool(scopedFindings);
  const bySeverity = findingsBySeverity(scopedFindings);
  const byRepo = !branch
    ? (repo ? [] : repos.map((r) => ({ name: r.name, count: r.findings })))
    : [];
  const trajectory = branch ? trajectoryForBranch(branch) : null;

  const scopeLabel = commit
    ? `${repo?.name} / ${branch?.name} / ${commit.id}`
    : branch
    ? `${repo?.name} / ${branch.name}`
    : repo
    ? repo.name
    : "All repositories";

  return (
    <div className="dashboard-overlay" role="dialog" aria-modal="true">
      <div className="dashboard-panel">
        <div className="dashboard-header">
          <div>
            <div className="text-sm text-muted">Findings dashboard</div>
            <div className="font-medium">{scopeLabel}</div>
          </div>
          <button type="button" className="chip" onClick={onClose}>Close</button>
        </div>

        <div className="dashboard-body scroll">
          {trajectory ? (
            <ChartCard
              title="Findings trajectory"
              subtitle="Active findings by severity, per commit on this branch"
              tableColumns={[
                { key: "id", label: "Commit" },
                { key: "critical", label: "Critical" },
                { key: "high", label: "High" },
                { key: "medium", label: "Medium" },
                { key: "low", label: "Low" },
                { key: "resolved", label: "Resolved" },
              ]}
              tableRows={trajectory}
            >
              <TrajectoryChart
                points={trajectory}
                onPointClick={(p) => onSelectCommit && onSelectCommit(p.id)}
              />
            </ChartCard>
          ) : (
            <div className="viz-callout">
              Select a branch to see its commit-by-commit trajectory. Showing current
              snapshot breakdowns for <strong>{scopeLabel}</strong> below.
            </div>
          )}

          {byRepo.length > 0 && (
            <ChartCard
              title="Findings by repository"
              tableColumns={[{ key: "name", label: "Repository" }, { key: "count", label: "Active findings" }]}
              tableRows={byRepo}
            >
              <BarList rows={byRepo} colorFor={() => ACCENT} />
            </ChartCard>
          )}

          <ChartCard
            title="Findings by author"
            subtitle="Who introduced each active finding — for pinning down responsibility"
            tableColumns={[{ key: "name", label: "Author" }, { key: "count", label: "Findings introduced" }]}
            tableRows={byAuthor}
          >
            <BarList rows={byAuthor} colorFor={() => ACCENT} />
          </ChartCard>

          <div className="dashboard-grid-2">
            <ChartCard
              title="Findings by tool"
              tableColumns={[{ key: "name", label: "Tool" }, { key: "count", label: "Findings" }]}
              tableRows={byTool}
            >
              <BarList rows={byTool} colorFor={() => ACCENT} />
            </ChartCard>

            <ChartCard
              title="Findings by severity"
              tableColumns={[{ key: "name", label: "Severity" }, { key: "count", label: "Findings" }]}
              tableRows={bySeverity}
            >
              <BarList rows={bySeverity} colorFor={(r) => SEV_COLOR[r.name] || ACCENT} />
            </ChartCard>
          </div>
        </div>
      </div>
    </div>
  );
}
