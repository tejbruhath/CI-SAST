const BASE = (import.meta.env.VITE_API_BASE || "") + "/api/v1";

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

async function req(path, opts = {}) {
  const csrfToken = getCookie("sentriq_csrftoken");
  const headers = {
    "Content-Type": "application/json",
    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
    ...opts.headers,
  };

  const res = await fetch(BASE + path, {
    credentials: "include",
    ...opts,
    headers,
  });

  if (res.status === 401) {
    const err = new Error("Unauthorized");
    err.status = 401;
    throw err;
  }

  if (!res.ok) {
    const body = await res.text();
    const err = new Error(`${res.status} ${path}: ${body}`);
    err.status = res.status;
    throw err;
  }

  return res.status === 204 ? null : res.json();
}

// Ensure the CSRF cookie is set before making state-changing requests.
async function ensureCsrf() {
  if (getCookie("sentriq_csrftoken")) return;
  await fetch(BASE + "/csrf", { credentials: "include" });
}

const realApi = {
  auth: {
    me: () => req("/auth/me"),
    loginWithGitHub: async () => {
      await ensureCsrf();
      return req("/auth/github");
    },
    logout: () => req("/auth/logout", { method: "POST" }),
  },
  repos: {
    list: () => req("/repos"),
  },
  scans: {
    list: (repo) => req("/scans" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")),
    create: async ({ pipeline, target, ref, tools, auto_fix_severity }) => {
      await ensureCsrf();
      return req("/scans", {
        method: "POST",
        body: JSON.stringify({ pipeline, target, ref, tools, auto_fix_severity }),
      });
    },
  },
  queue: {
    status: () => req("/queue"),
  },
  findings: {
    list: (params = {}) => {
      const entries = Object.entries(params).filter(([, v]) => v != null && v !== "");
      const q = new URLSearchParams(entries).toString();
      return req("/findings" + (q ? `?${q}` : ""));
    },
    get: (id) => req(`/findings/${id}`),
    hitl: async (id, action, actor, note, edited_diff) => {
      await ensureCsrf();
      return req(`/findings/${id}/hitl`, {
        method: "POST",
        body: JSON.stringify({ action, actor, note, edited_diff }),
      });
    },
    createPr: async (id) => {
      await ensureCsrf();
      return req(`/findings/${id}/pr`, { method: "POST" });
    },
  },
  metrics: () => req("/metrics"),
};

export const api = realApi;
