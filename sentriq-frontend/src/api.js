// API base: optional VITE_API_BASE + always under /api/v1.
const BASE = (import.meta.env.VITE_API_BASE || "") + "/api/v1"; // backend prefix

function getCookie(name) {
  // Read a single cookie by name from document.cookie.
  const value = `; ${document.cookie}`; // pad so split always works
  const parts = value.split(`; ${name}=`); // split on "; name="
  if (parts.length === 2) return parts.pop().split(";").shift(); // value before next cookie
  return null; // cookie missing
}

async function req(path, opts = {}) {
  // Shared fetch helper: JSON, cookies, CSRF, error mapping.
  const csrfToken = getCookie("sentriq_csrftoken"); // Django CSRF cookie name
  const headers = {
    "Content-Type": "application/json", // all bodies are JSON
    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}), // required for unsafe methods
    ...opts.headers, // allow per-call header overrides
  };

  const res = await fetch(BASE + path, {
    credentials: "include", // send session cookie cross-origin if needed
    ...opts, // method, body, etc.
    headers, // merged headers win over opts.headers order above
  });

  if (res.status === 401) {
    // Session expired or not logged in — let App force login.
    const err = new Error("Unauthorized");
    err.status = 401;
    throw err;
  }

  if (!res.ok) {
    // Surface status + body text for UI error banners.
    const body = await res.text();
    const err = new Error(`${res.status} ${path}: ${body}`);
    err.status = res.status;
    throw err;
  }

  return res.status === 204 ? null : res.json(); // no-content vs JSON parse
}

// Ensure the CSRF cookie is set before making state-changing requests.
async function ensureCsrf() {
  if (getCookie("sentriq_csrftoken")) return; // already have cookie
  await fetch(BASE + "/csrf", { credentials: "include" }); // hit endpoint that sets it
}

const realApi = {
  auth: {
    me: () => req("/auth/me"), // current user + profile
    loginWithGitHub: async () => {
      await ensureCsrf(); // cookie before OAuth start
      return req("/auth/github"); // returns authorize URL / starts flow
    },
    logout: () => req("/auth/logout", { method: "POST" }), // clear session
  },
  repos: {
    list: () => req("/repos"), // GitHub repos for picker
  },
  scans: {
    list: (repo) => req("/scans" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")), // optional filter
    create: async ({ pipeline, target, ref, tools, auto_fix_severity }) => {
      await ensureCsrf(); // POST needs CSRF
      return req("/scans", {
        method: "POST",
        body: JSON.stringify({ pipeline, target, ref, tools, auto_fix_severity }), // create body
      });
    },
  },
  queue: {
    status: () => req("/queue"), // depth + active tools
  },
  findings: {
    list: (params = {}) => {
      // Build query string from non-empty filter params.
      const entries = Object.entries(params).filter(([, v]) => v != null && v !== "");
      const q = new URLSearchParams(entries).toString();
      return req("/findings" + (q ? `?${q}` : "")); // list with filters
    },
    get: (id) => req(`/findings/${id}`), // full detail + triage/fixes
    hitl: async (id, action, actor, note, edited_diff) => {
      await ensureCsrf();
      return req(`/findings/${id}/hitl`, {
        method: "POST",
        body: JSON.stringify({ action, actor, note, edited_diff }), // approve/deny/edit
      });
    },
    createPr: async (id) => {
      await ensureCsrf();
      return req(`/findings/${id}/pr`, { method: "POST" }); // single-finding PR
    },
    fixWithAi: async (id) => {
      await ensureCsrf();
      return req(`/findings/${id}/fix`, { method: "POST" }); // on-demand AI fix
    },
    approve: async (id, actor, note = "") => {
      await ensureCsrf();
      return req(`/findings/${id}/hitl`, {
        method: "POST",
        body: JSON.stringify({ action: "approve", actor, note }), // shortcut approve
      });
    },
  },
  // One PR containing every approved fix for a repo — nothing else.
  pr: {
    createBatch: async (repo) => {
      await ensureCsrf();
      return req(`/pr`, { method: "POST", body: JSON.stringify({ repo }) }); // batch PR
    },
  },
  metrics: (repo) => req("/metrics" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")), // dashboard tiles
};

export const api = realApi; // single export used across components
