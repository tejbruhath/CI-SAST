import { useMemo, useState } from "react";
import { SEV_RANK } from "../data/util.js";

export const LEVELS = ["repo", "branch", "commit", "severity", "tool", "file", "line"];

export const LEVEL_NAMES = {
  repo: "Repositories", branch: "Branches", commit: "Commits",
  severity: "Severity", tool: "Tools", file: "Files", line: "Lines",
};

// Dynamic top-bar filter options per level.
export const FILTER_MAP = {
  repo: ["Recent commit", "Most findings", "Highest severity", "Most runs"],
  branch: ["Authors", "Most severity", "Oldest", "Active findings"],
  commit: ["Newest", "Oldest", "Pipeline status", "New findings", "Resolved findings"],
  severity: ["Highest severity", "Type", "Most findings"],
  tool: ["Tool version", "Finding type", "Most findings"],
  file: ["Most findings", "Language", "Path"],
  line: ["Lifecycle", "Rule ID", "Highest severity"],
};

const TOOL_VERSIONS = { gitleaks: "8.18.0", trivy: "0.50.0", sonarqube: "9.9.4" };

const initialState = () => ({
  repo: null, branch: null, commit: null, severity: null,
  tool: null, file: null, line: null,
  search: "", filter: null, resolved: false,
});

export function useExplorer(repos) {
  const [state, setState] = useState(initialState);

  const api = useMemo(() => {
    const repo = () => repos.find((r) => r.id === state.repo);
    const branch = () => repo()?.branches.find((b) => b.id === state.branch);
    const commit = () => branch()?.commits.find((c) => c.id === state.commit);

    const resolvedList = () => commit()?.resolved || [];
    const findings = () =>
      commit() ? [...commit().findings, ...(state.resolved ? resolvedList() : [])] : [];

    function after(level) {
      LEVELS.slice(LEVELS.indexOf(level) + 1).forEach((k) => (state[k] = null));
    }

    function visibleLevels() {
      const out = ["repo"];
      for (let i = 0; i < LEVELS.length - 1; i++) {
        if (state[LEVELS[i]]) out.push(LEVELS[i + 1]);
        else break;
      }
      return out;
    }

    function currentLevel() {
      for (let i = LEVELS.length - 1; i >= 0; i--) {
        if (state[LEVELS[i]]) return LEVELS[Math.min(i + 1, LEVELS.length - 1)];
      }
      return "repo";
    }

    function raw(level) {
      if (level === "repo") {
        return repos.map((x) => ({
          id: x.id, title: x.name, sev: x.sev,
          meta: `${x.findings} findings · ${x.runs} runs`,
          extra: x.path, _findings: x.findings, _runs: x.runs, _epoch: x.updatedEpoch,
        }));
      }
      if (level === "branch") {
        return (repo()?.branches || []).map((x) => ({
          id: x.id, title: x.name, sev: x.sev,
          meta: `${x.findings} active`, extra: x.owner,
          _findings: x.findings, _epoch: x.updatedEpoch,
        }));
      }
      if (level === "commit") {
        return (branch()?.commits || []).map((x) => ({
          id: x.id, title: x.id, meta: x.msg, status: x.status,
          extra: `${x.author} · ${x.resolved.length} resolved`,
          _epoch: x.dateEpoch, _new: x.findings.filter((f) => f.life === "new").length,
          _resolved: x.resolved.length,
        }));
      }
      const fs = findings();
      if (level === "severity") {
        return [...new Set(fs.map((f) => f.sev))]
          .sort((a, b) => SEV_RANK[b] - SEV_RANK[a])
          .map((x) => ({ id: x, title: x, sev: x,
            meta: `${fs.filter((f) => f.sev === x).length} findings`,
            _findings: fs.filter((f) => f.sev === x).length }));
      }
      const a = fs.filter((f) => !state.severity || f.sev === state.severity);
      if (level === "tool") {
        return [...new Set(a.map((f) => f.tool))].map((x) => ({
          id: x, title: x, extra: TOOL_VERSIONS[x],
          meta: `${a.filter((f) => f.tool === x).length} findings`,
          _findings: a.filter((f) => f.tool === x).length }));
      }
      const b = a.filter((f) => !state.tool || f.tool === state.tool);
      if (level === "file") {
        return [...new Set(b.map((f) => f.file))].map((x) => ({
          id: x, title: x, extra: String(x).split(".").pop().toUpperCase(),
          meta: `${b.filter((f) => f.file === x).length} findings`,
          _findings: b.filter((f) => f.file === x).length }));
      }
      // line
      return b
        .filter((f) => !state.file || f.file === state.file)
        .map((f) => ({
          id: f.id, sev: f.sev, finding: f, extra: f.rule,
          title: f.line == null ? "Manifest" : `Line ${f.line}`,
          meta: f.msg,
        }));
    }

    function items(level) {
      let a = raw(level).filter((x) =>
        `${x.title} ${x.meta || ""} ${x.extra || ""}`
          .toLowerCase()
          .includes(state.search.toLowerCase())
      );
      const f = state.filter;
      if (f === "Highest severity" || f === "Most severity")
        a = [...a].sort((x, y) => (SEV_RANK[y.sev] || 0) - (SEV_RANK[x.sev] || 0));
      else if (f === "Most findings" || f === "Active findings")
        a = [...a].sort((x, y) => (y._findings || 0) - (x._findings || 0));
      else if (f === "Most runs")
        a = [...a].sort((x, y) => (y._runs || 0) - (x._runs || 0));
      else if (f === "Recent commit" || f === "Newest")
        a = [...a].sort((x, y) => (y._epoch || 0) - (x._epoch || 0));
      else if (f === "Oldest")
        a = [...a].sort((x, y) => (x._epoch || 0) - (y._epoch || 0));
      else if (f === "New findings")
        a = [...a].sort((x, y) => (y._new || 0) - (x._new || 0));
      else if (f === "Resolved findings")
        a = [...a].sort((x, y) => (y._resolved || 0) - (x._resolved || 0));
      else if (f === "Authors")
        a = [...a].sort((x, y) => String(x.extra).localeCompare(String(y.extra)));
      else if (f === "Path" || f === "Language" || f === "Rule ID")
        a = [...a].sort((x, y) => String(x.extra).localeCompare(String(y.extra)));
      return a;
    }

    return { repo, branch, commit, resolvedList, findings,
             after, visibleLevels, currentLevel, raw, items };
  }, [repos, state]);

  // --- actions ---------------------------------------------------------------
  const select = (level, item) => {
    setState((s) => {
      const next = { ...s, [level]: item.id, search: "", filter: null };
      LEVELS.slice(LEVELS.indexOf(level) + 1).forEach((k) => (next[k] = null));
      if (level === "line") next.line = item.id;
      return next;
    });
  };
  const setSearch = (v) => setState((s) => ({ ...s, search: v }));
  const setFilter = (n) => setState((s) => ({ ...s, filter: s.filter === n ? null : n }));
  const toggleResolved = () =>
    setState((s) => ({ ...s, resolved: !s.resolved,
      severity: null, tool: null, file: null, line: null }));
  const closeDetail = () => setState((s) => ({ ...s, line: null }));
  const reset = () => setState(initialState());

  return { state, api, select, setSearch, setFilter, toggleResolved, closeDetail, reset };
}
