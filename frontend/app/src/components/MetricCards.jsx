import React from "react";

const CARDS = [
  ["active", "Active"],
  ["critical", "Critical"],
  ["resolved", "Auto-resolved"],
  ["runs", "Runs"],
];

export default function MetricCards({ metrics, onOpenDashboard }) {
  return (
    <div className="metrics-grid">
      {CARDS.map(([key, label]) => (
        <button type="button" className="metric-card metric-card-button" key={key} onClick={onOpenDashboard}>
          <div className="text-sm text-muted">{label}</div>
          <div className="viz-stat-value">{metrics[key] ?? 0}</div>
        </button>
      ))}
    </div>
  );
}
