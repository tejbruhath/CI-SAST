import React, { useEffect, useMemo, useState } from "react";
import { loadArtifacts } from "./data/loadArtifacts.js";
import { globalMetrics } from "./data/smartDelete.js";
import { useExplorer, LEVEL_NAMES, FILTER_MAP } from "./hooks/useExplorer.js";
import MetricCards from "./components/MetricCards.jsx";
import TopBar from "./components/TopBar.jsx";
import Columns from "./components/Columns.jsx";
import DetailPanel from "./components/DetailPanel.jsx";

export default function App() {
  const [state, setState] = useState({ status: "loading", repos: [], error: null });

  useEffect(() => {
    let alive = true;
    loadArtifacts()
      .then((res) => {
        if (!alive) return;
        setState({
          status: res.count > 0 ? "ready" : "empty",
          repos: res.repos,
          error: null,
        });
      })
      .catch((err) => {
        if (!alive) return;
        setState({ status: "error", repos: [], error: err.message });
      });
    return () => { alive = false; };
  }, []);

  if (state.status === "loading") {
    return (
      <main className="app-shell">
        <div className="flex items-center gap-2 text-muted">
          <span className="spinner" /> Loading artifacts…
        </div>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="app-shell">
        <div className="banner">
          Could not reach the findings API at <code>/artifacts/</code>: {state.error}.
          Check that ci-utils is running and nginx is proxying <code>/artifacts/</code>
          to it, then reload.
        </div>
      </main>
    );
  }

  if (state.status === "empty") {
    return (
      <main className="app-shell">
        <div className="viz-callout">
          No scans have completed yet. Once a pipeline run finishes, its
          findings will appear here automatically.
        </div>
      </main>
    );
  }

  return <Explorer repos={state.repos} />;
}

function Explorer({ repos }) {
  const { state, api, select, setSearch, setFilter, toggleResolved, closeDetail, reset } =
    useExplorer(repos);

  const lineOpen = !!state.line;
  const currentLevel = lineOpen ? "line" : api.currentLevel();

  const detailFinding = useMemo(
    () => (state.line ? api.findings().find((f) => f.id === state.line) : null),
    [state, api]
  );

  // breadcrumb + title
  const parts = [
    api.repo()?.name, api.branch()?.name, api.commit()?.id,
    state.severity, state.tool, state.file,
    state.line ? "finding detail" : null,
  ].filter(Boolean);
  const crumb = parts.length ? `Repositories / ${parts.join(" / ")}` : "Repositories";
  const title = parts.at(-1) || "All repositories";

  // metrics (scoped to selected commit if any)
  const metrics = useMemo(() => {
    const c = api.commit();
    if (c) {
      return {
        active: c.findings.length,
        critical: c.findings.filter((f) => f.sev === "critical").length,
        resolved: c.resolved.length,
        runs: api.repo()?.runs ?? 0,
      };
    }
    return globalMetrics(repos);
  }, [state, api, repos]);

  const resolvedCount = api.resolvedList().length;
  const syncNote =
    api.commit() && resolvedCount
      ? `${resolvedCount} parent fingerprint(s) are absent in this commit and were removed from the active tree (smart delete).`
      : null;

  return (
    <main className="app-shell">
      <section className={`space-y-4 ${lineOpen ? "line-open" : ""}`}>
        <MetricCards metrics={metrics} />

        <div className="frame">
          <TopBar
            crumb={crumb}
            title={title}
            placeholder={`Search ${LEVEL_NAMES[currentLevel].toLowerCase()}…`}
            searchValue={state.search}
            onSearch={setSearch}
            filters={FILTER_MAP[currentLevel] || []}
            activeFilter={state.filter}
            onFilter={setFilter}
            resolvedCount={resolvedCount}
            resolvedActive={state.resolved}
            onToggleResolved={toggleResolved}
            showResolvedToggle={!!api.commit()}
            onReset={reset}
          />

          {syncNote && <div className="sync-note">{syncNote}</div>}

          <div className="work">
            <Columns
              levels={api.visibleLevels()}
              activeIds={state}
              itemsFor={api.items}
              onSelect={select}
            />
            {lineOpen && <DetailPanel finding={detailFinding} onClose={closeDetail} />}
          </div>
        </div>

        <div className="viz-callout">
          Default behaviour: only fingerprints present in the selected commit stay
          active. Fingerprints that a later commit no longer reports are removed
          from the active tree and kept in resolved history only.
        </div>
      </section>
    </main>
  );
}
