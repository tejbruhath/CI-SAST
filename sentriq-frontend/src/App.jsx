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
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [queue, setQueue] = useState({ queue_depth: 0, active_tasks: 0 });

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

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
    setSelectedFinding(null);
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
      const [s, f, q] = await Promise.all([
        api.scans.list(repoName),
        api.findings.list({ ...filters, repo: repoName }),
        api.queue.status(),
      ]);
      setScans(s);
      setFindings(f);
      setQueue(q);
      setErr(null);

      // Refresh selected finding if drawer is open
      if (selectedFinding) {
        const updated = f.find((x) => x.id === selectedFinding.id);
        if (updated) setSelectedFinding(updated);
      }
    } catch (e) {
      setErr(e.message);
    }
  }, [selectedRepo, filters, selectedFinding?.id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

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
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openFinding = async (id) => {
    try {
      const f = await api.findings.get(id);
      setSelectedFinding(f);
    } catch (e) {
      setErr(e.message);
    }
  };

  const doHitl = async (id, action, note) => {
    try {
      await api.findings.hitl(id, action, user?.login || "reviewer", note, null);
      await refresh();
      if (selectedFinding?.id === id) {
        const f = await api.findings.get(id);
        setSelectedFinding(f);
      }
    } catch (e) {
      setErr(e.message);
    }
  };

  const doCreatePr = async (id) => {
    try {
      await api.findings.createPr(id);
      await refresh();
      if (selectedFinding?.id === id) {
        const f = await api.findings.get(id);
        setSelectedFinding(f);
      }
    } catch (e) {
      setErr(e.message);
    }
  };

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

  return (
    <div className="min-h-screen flex bg-background text-on-background font-body-md text-body-md relative overflow-hidden">
      <div className="scanline-overlay absolute inset-0 z-0" />
      <div
        className="absolute inset-0 pointer-events-none opacity-20 z-0"
        style={{
          backgroundImage: "radial-gradient(circle at center, #8c909f 1px, transparent 1px)",
          backgroundSize: "8px 8px",
        }}
      />

      <Sidebar user={user} activeTab="dashboard" onLogout={logout} />

      <main className="flex-1 flex flex-col min-w-0 pl-64 z-10 relative">
        <Header repo={selectedRepo} user={user} onLogout={logout} />

        {err && (
          <div className="mx-6 mt-6 bg-error-container border-2 border-error text-on-error-container p-3 font-body-md">
            {err}
          </div>
        )}

        <div className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-3 gap-6 overflow-auto">
          {/* Left column */}
          <div className="col-span-1 flex flex-col gap-6">
            <ScanConfigForm repo={selectedRepo} onSubmit={submitScan} busy={busy} />
            <ScansList
              scans={scans}
              activeScan={filters.scan}
              onPick={(id) => setFilters({ ...filters, scan: filters.scan === id ? "" : id })}
            />
          </div>

          {/* Right column */}
          <div className="col-span-1 lg:col-span-2 flex flex-col gap-6">
            <QueueStatus queue={queue} />
            <FindingsTable
              findings={findings}
              filters={filters}
              setFilters={setFilters}
              onPick={openFinding}
              selected={selectedFinding?.id}
              onCreatePr={doCreatePr}
              busy={busy}
            />
          </div>
        </div>
      </main>

      {selectedFinding && (
        <FindingDetail
          finding={selectedFinding}
          onClose={() => setSelectedFinding(null)}
          onHitl={doHitl}
          onCreatePr={doCreatePr}
          busy={busy}
        />
      )}
    </div>
  );
}
