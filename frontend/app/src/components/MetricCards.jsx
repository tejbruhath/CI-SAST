import React from "react";

const CARDS = [
  ["active", "Active"],
  ["critical", "Critical"],
  ["resolved", "Auto-resolved"],
  ["runs", "Runs"],
];

export default function MetricCards({ metrics }) {
  return (
    <div className="metrics-grid">
      {CARDS.map(([key, label]) => (
        <div className="metric-card" key={key}>
          <div className="text-sm text-muted">{label}</div>
          <div className="viz-stat-value">{metrics[key] ?? 0}</div>
        </div>
      ))}
    </div>
  );
}
