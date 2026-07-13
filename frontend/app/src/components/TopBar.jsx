import React from "react";

export default function TopBar({
  crumb, title, placeholder, searchValue, onSearch,
  filters, activeFilter, onFilter,
  resolvedCount, resolvedActive, onToggleResolved, showResolvedToggle,
  onReset, onRefresh, refreshing,
}) {
  return (
    <header className="top space-y-3 p-3">
      <div className="flex flex-col gap-2 lg-row justify-between" style={{ alignItems: "center" }}>
        <div className="min-w-0">
          <div className="truncate text-sm text-muted">{crumb}</div>
          <div className="font-medium">{title}</div>
        </div>
        <div className="flex gap-2 items-center">
          <span className="viz-badge">Smart delete ON</span>
          <button type="button" className="chip" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button type="button" className="chip" onClick={onReset}>Reset</button>
        </div>
      </div>

      <div className="flex flex-col gap-2 lg-row">
        <label className="flex-1">
          <span className="hidden">Search current level</span>
          <input
            type="search"
            placeholder={placeholder}
            value={searchValue}
            onChange={(e) => onSearch(e.target.value)}
          />
        </label>
        <div className="filters scroll">
          {filters.map((n) => (
            <button
              key={n}
              type="button"
              className={`chip ${activeFilter === n ? "active" : ""}`}
              onClick={() => onFilter(n)}
            >
              {n}
            </button>
          ))}
          {showResolvedToggle && (
            <button
              type="button"
              className={`chip ${resolvedActive ? "active" : ""}`}
              onClick={onToggleResolved}
            >
              Resolved history ({resolvedCount})
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
