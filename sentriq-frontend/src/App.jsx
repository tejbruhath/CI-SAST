import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import MetricsPanel from "./components/MetricsPanel.jsx";
import ScanForm from "./components/ScanForm.jsx";
import ScansList from "./components/ScansList.jsx";
import FindingsTable from "./components/FindingsTable.jsx";
import FindingDetail from "./components/FindingDetail.jsx";

const POLL_MS = 5000;

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [scans, setScans] = useState([]);
  const [findings, setFindings] = useState([]);
  const [filters, setFilters] = useState({ scan: "", severity: "", tool: "", verdict: "" });
  const [selected, setSelected] = useState(null);   // finding detail (full object)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [m, s, f] = await Promise.all([
        api.metrics(), api.scans(), api.findings(filters),
      ]);
      setMetrics(m); setScans(s); setFindings(f); setErr(null);
    } catch (e) {
      setErr(e.message);
    }
  }, [filters]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const submitScan = async (pipeline, target, ref) => {
    setBusy(true);
    try {
      await api.createScan(pipeline, target, ref);
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openFinding = async (id) => {
    try { setSelected(await api.finding(id)); }
    catch (e) { setErr(e.message); }
  };

  // While a PR is being created, poll the open finding until it lands.
  useEffect(() => {
    const creating = selected?.fixes?.some((f) => f.pr_status === "creating");
    if (!creating) return;
    const t = setInterval(() => openFinding(selected.id), 4000);
    return () => clearInterval(t);
  }, [selected]);

  const doHitl = async (id, action, note) => {
    await api.hitl(id, action, "reviewer", note, null);
    await openFinding(id);   // reload detail
    refresh();
  };

  const doCreatePr = async (id) => {
    await api.createPr(id);
    await openFinding(id);   // reflect pr_status=creating; polling updates to open
  };

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <h1>Sentriq<span className="dot">.</span></h1>
          <span className="tag">AI security remediation · SAST · SCA · DAST</span>
        </div>
        <button className="ghost" onClick={refresh}>Refresh</button>
      </div>

      {err && <div className="err">{err}</div>}

      <MetricsPanel metrics={metrics} />

      <div className="grid">
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="panel">
            <h2>New scan</h2>
            <ScanForm onSubmit={submitScan} busy={busy} />
          </div>
          <div className="panel">
            <h2>Recent scans</h2>
            <ScansList scans={scans} activeScan={filters.scan}
              onPick={(id) => setFilters({ ...filters, scan: filters.scan === id ? "" : id })} />
          </div>
        </div>

        <div className="panel">
          <h2>
            Findings{filters.scan ? " · filtered by scan" : ""}
            <span style={{ float: "right", color: "var(--muted)", fontWeight: 400 }}>
              {findings.length} shown
            </span>
          </h2>
          <FindingsTable findings={findings} filters={filters} setFilters={setFilters}
            onPick={openFinding} selected={selected?.id} />
        </div>
      </div>

      {selected && (
        <FindingDetail finding={selected} onClose={() => setSelected(null)}
          onHitl={doHitl} onCreatePr={doCreatePr} />
      )}
    </div>
  );
}
