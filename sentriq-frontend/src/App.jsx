import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";

import LoginPage from "./components/LoginPage.jsx";
import RepoBrowser from "./components/RepoBrowser.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Header from "./components/Header.jsx";
import ScanConfigForm from "./components/ScanConfigForm.jsx";
import ScansList from "./components/ScansList.jsx";
import QueueStatus from "./components/QueueStatus.jsx";
import FindingsTable from "./components/FindingsTable.jsx";
import FindingDetail from "./components/FindingDetail.jsx";
import AssetsPanel from "./components/AssetsPanel.jsx";
import MetricsPanel from "./components/MetricsPanel.jsx";
import CreatePrDialog from "./components/CreatePrDialog.jsx";
import FixAllDialog from "./components/FixAllDialog.jsx";

const POLL_MS = 3000;

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState(null);

  const [repos, setRepos] = useState([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [selectedRepo, setSelectedRepo] = useState(null);

  const [scans, setScans] = useState([]);
  const [findings, setFindings] = useState([]);
  const [filters, setFilters] = useState({ scan: "", severity: "", tool: "", verdict: "" });
  // Only the id is selection state. The detail object is fetched from it, so a
  // late/stale response can never resurrect a closed or replaced dialog.
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [queue, setQueue] = useState({ queue_depth: 0, active_tasks: 0 });
  const [metrics, setMetrics] = useState(null);
  const [tab, setTab] = useState("dashboard");

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [fixingIds, setFixingIds] = useState(new Set());
  const [prOpen, setPrOpen] = useState(false);
  const [prResult, setPrResult] = useState(null);
  const [prBusy, setPrBusy] = useState(false);
  // Frozen at request time: `approvedFindings` drops these once refresh() sees
  // pr_status flip to "open", so the live list can't be used to render the
  // post-result dialog (it would read as "nothing approved").
  const [prSnapshot, setPrSnapshot] = useState([]);
  const [fixAllOpen, setFixAllOpen] = useState(false);
  const [fixAllBusy, setFixAllBusy] = useState(false);

  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const loginStatus = params.get("login");
    if (loginStatus === "success") {
      // OAuth callback redirected back here; clear the query string and refresh.
      window.history.replaceState({}, "", window.location.pathname);
    }

    api.auth
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  const login = async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const data = await api.auth.loginWithGitHub();
      if (data?.url) {
        window.location.href = data.url;
        return;
      }
      // Mock mode returns the user directly.
      setUser(data);
    } catch (e) {
      setAuthError(e.message);
      setAuthLoading(false);
    }
  };

  const logout = async () => {
    await api.auth.logout();
    setUser(null);
    setSelectedRepo(null);
    setSelectedId(null);
    setScans([]);
    setFindings([]);
    setRepos([]);
  };

  // -------------------------------------------------------------------------
  // Repos
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!user) return;
    setReposLoading(true);
    api.repos
      .list()
      .then(setRepos)
      .catch((e) => setErr(e.message))
      .finally(() => setReposLoading(false));
  }, [user]);

  // -------------------------------------------------------------------------
  // Dashboard data refresh
  // -------------------------------------------------------------------------
  const refresh = useCallback(async () => {
    if (!selectedRepo) return;
    try {
      const repoName = selectedRepo.full_name;
      const [s, f, q, m] = await Promise.all([
        api.scans.list(repoName),
        api.findings.list({ ...filters, repo: repoName }),
        api.queue.status(),
        api.metrics(repoName),
      ]);
      setScans(s);
      setFindings(f);
      setQueue(q);
      setMetrics(m);
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
    // NB: never write selection state here. The list rows come from
    // FindingListSerializer, which has no `triage`/`details` — merging one into
    // the open dialog is what made a triaged finding read "Not triaged yet".
  }, [selectedRepo, filters]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // -------------------------------------------------------------------------
  // Open finding detail — owned solely by selectedId.
  // `alive` is the whole trick: when you close the dialog or click another row,
  // this effect tears down and any in-flight response is dropped instead of
  // being written back (which reopened the dialog / showed the previous row).
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let alive = true;
    // Switching rows: drop the previous row's data immediately so it can never
    // flash in the new dialog. Same id (the 3s poll) keeps it — no flicker.
    setDetail((cur) => (cur?.id === selectedId ? cur : null));
    const load = async () => {
      try {
        const d = await api.findings.get(selectedId);
        if (alive) setDetail(d);
      } catch (e) {
        if (alive) setErr(e.message);
      }
    };
    load();
    // Keep the open finding live (triage/fix land asynchronously mid-scan).
    const t = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [selectedId]);

  // Once a queued AI fix lands in the polled list, stop showing the spinner.
  useEffect(() => {
    setFixingIds((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of prev) {
        if (findings.some((f) => f.id === id && f.fix)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [findings]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------
  const submitScan = async ({ pipeline, target, ref, tools, auto_fix_severity }) => {
    setBusy(true);
    try {
      const actualTarget = pipeline === "static" ? selectedRepo?.clone_url : target || "https://staging.example.com";
      await api.scans.create({
        pipeline,
        target: actualTarget,
        ref,
        tools,
        auto_fix_severity,
      });
      await refresh();
      setTab("history");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Re-read the open finding after an action, but only if it's still the open
  // one — same guard as the poll.
  const reloadDetail = async (id) => {
    const d = await api.findings.get(id);
    setDetail((cur) => (cur?.id === id ? d : cur));
  };

  const doCreatePr = async (id) => {
    try {
      await api.findings.createPr(id);
      await refresh();
      if (selectedId === id) await reloadDetail(id);
    } catch (e) {
      setErr(e.message);
    }
  };

  // Approving is the gate: only approved fixes are ever included in a PR.
  const doApprove = async (id) => {
    try {
      await api.findings.approve(id, user?.login || "reviewer");
      await refresh();
      if (selectedId === id) await reloadDetail(id);
    } catch (e) {
      setErr(e.message);
    }
  };

  const doDeny = async (id) => {
    try {
      await api.findings.hitl(id, "deny", user?.login || "reviewer");
      await refresh();
      if (selectedId === id) await reloadDetail(id);
    } catch (e) {
      setErr(e.message);
    }
  };

  const doEdit = async (id, editedDiff) => {
    try {
      await api.findings.hitl(id, "edit", user?.login || "reviewer", "", editedDiff);
      await refresh();
      if (selectedId === id) await reloadDetail(id);
    } catch (e) {
      setErr(e.message);
    }
  };

  // Every approved fix for this repo that has not already gone into a PR.
  const approvedFindings = findings.filter(
    (f) => f.fix && ["approved", "edited"].includes(f.fix.status) && f.fix.pr_status === "none"
  );

  const doCreateBatchPr = async () => {
    setPrBusy(true);
    setPrSnapshot(approvedFindings);
    try {
      const res = await api.pr.createBatch(selectedRepo.full_name);
      setPrResult(res);
      await refresh();
    } catch (e) {
      setErr(e.message);
      setPrOpen(false);
    } finally {
      setPrBusy(false);
    }
  };

  const doFixWithAi = async (id) => {
    setFixingIds((prev) => new Set(prev).add(id));
    try {
      await api.findings.fixWithAi(id);
      await refresh();
    } catch (e) {
      setErr(e.message);
      setFixingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleCreatePr = () => {
    setPrResult(null);
    setPrOpen(true);
  };

  const canFixAll = findings.length > 0;

  const doFixAll = async (ids) => {
    setFixAllBusy(true);
    try {
      await Promise.all(ids.map((id) => doFixWithAi(id)));
      setFixAllOpen(false);
    } finally {
      setFixAllBusy(false);
    }
  };

  // The detail serializer returns `scan` as an id, so enrich it with the scan
  // target so the detail panel can build deep links into github.dev.
  const detailFinding = detail
    ? { ...detail, scan_target: scans.find((s) => s.id === detail.scan)?.target }
    : null;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background text-on-surface">
        <div className="flex flex-col items-center gap-4">
          <span className="material-symbols-outlined text-4xl text-primary animate-spin">sync</span>
          <span className="font-code-label text-code-label uppercase">Loading security console...</span>
        </div>
      </div>
    );
  }

  if (!user) {
      return (
        <LoginPage
          onLogin={login}
          loading={authLoading}
        />
      );
  }

  if (!selectedRepo) {
    return <RepoBrowser repos={repos} loading={reposLoading} user={user} onSelectRepo={setSelectedRepo} onLogout={logout} />;
  }

  // h-screen + overflow-hidden: the page itself never scrolls. Every child in
  // the chain needs min-h-0 so the findings list is the one thing that does.
  return (
    <div className="h-screen flex bg-background text-on-background font-body-md text-body-md relative overflow-hidden">
      <div className="scanline-overlay absolute inset-0 z-0 pointer-events-none" />
      <div
        className="absolute inset-0 pointer-events-none opacity-20 z-0"
        style={{
          backgroundImage: "radial-gradient(circle at center, #8c909f 1px, transparent 1px)",
          backgroundSize: "8px 8px",
        }}
      />

      <Sidebar user={user} activeTab={tab} onNavigate={setTab} onLogout={logout} onCreatePr={handleCreatePr} canFixAll={canFixAll} onFixAll={() => setFixAllOpen(true)} />

      <main className="flex-1 flex flex-col min-w-0 min-h-0 pl-64 z-10 relative">
        <Header repo={selectedRepo} user={user} onLogout={logout} />

        {err && (
          <div className="mx-6 mt-6 shrink-0 bg-error-container border-2 border-error text-on-error-container p-3 font-body-md">
            {err}
          </div>
        )}

        <div className="flex-1 min-h-0 p-6 flex flex-col gap-6">
          {tab === "dashboard" && (
            <>
              <MetricsPanel metrics={metrics} />
              <QueueStatus queue={queue} triagingScan={scans.find((s) => s.triaging)} />
              <FindingsTable
                findings={findings}
                filters={filters}
                setFilters={setFilters}
                onPick={setSelectedId}
                selected={selectedId}
                onFixWithAi={doFixWithAi}
                onApprove={doApprove}
                fixingIds={fixingIds}
                busy={busy}
              />
            </>
          )}

          {tab === "config" && (
            <div className="flex-1 min-h-0 overflow-y-auto max-w-2xl w-full">
              <ScanConfigForm repo={selectedRepo} onSubmit={submitScan} busy={busy} />
            </div>
          )}

          {tab === "history" && (
            <div className="flex-1 min-h-0 overflow-y-auto max-w-3xl w-full">
              <ScansList
                scans={scans}
                activeScan={filters.scan}
                onPick={(id) => {
                  setFilters({ ...filters, scan: filters.scan === id ? "" : id });
                  setTab("dashboard");
                }}
              />
            </div>
          )}

          {tab === "assets" && (
            <AssetsPanel
              repos={repos}
              scans={scans}
              findings={findings}
              selectedRepo={selectedRepo}
              onSelectRepo={setSelectedRepo}
            />
          )}
        </div>
      </main>

      {prOpen && (
        <CreatePrDialog
          approved={prResult ? prSnapshot : approvedFindings}
          repoSlug={selectedRepo?.full_name}
          result={prResult}
          busy={prBusy}
          onConfirm={doCreateBatchPr}
          onClose={() => { setPrOpen(false); setPrResult(null); }}
        />
      )}

      {fixAllOpen && (
        <FixAllDialog
          findings={findings}
          busy={fixAllBusy}
          onConfirm={doFixAll}
          onClose={() => setFixAllOpen(false)}
        />
      )}

      {detail && (
        <FindingDetail
          finding={detailFinding}
          onClose={() => setSelectedId(null)}
          onFixWithAi={doFixWithAi}
          onCreatePr={doCreatePr}
          onApprove={doApprove}
          onDeny={doDeny}
          onEdit={doEdit}
          busy={busy}
          fixing={fixingIds.has(detail.id)}
        />
      )}
    </div>
  );
}
