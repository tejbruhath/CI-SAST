import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";

// Mutable store so tests can control the per-id deferreds returned by
// api.findings.get. vi.hoisted() runs before vi.mock's factory is hoisted,
// so the binding exists by the time the factory closes over it.
const findingDeferreds = vi.hoisted(() => new Map());

vi.mock("./api.js", () => {
  function makeDeferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  const user = { id: 1, login: "testuser", name: "Test User", avatar_url: "https://example.com/avatar.png" };

  const repo = {
    id: 1,
    full_name: "owner/repo",
    default_branch: "main",
    clone_url: "https://github.com/owner/repo.git",
    private: false,
    description: "Test repo",
  };

  const listFindingA = {
    id: "finding-a",
    severity: "high",
    tool: "semgrep",
    file: "src/app.js",
    line: 10,
    message: "Hardcoded secret in source",
    verdict: "real",
    fix: null,
  };

  const listFindingB = {
    id: "finding-b",
    severity: "critical",
    tool: "gitleaks",
    file: "src/config.js",
    line: 20,
    message: "API key leaked in config",
    verdict: "real",
    fix: null,
  };

  const metrics = {
    totals: { findings: 2, scans: 0, fixes_proposed: 0, fixes_approved: 0 },
    by_severity: { critical: 1, high: 1 },
  };

  return {
    api: {
      auth: {
        me: vi.fn(() => Promise.resolve(user)),
        loginWithGitHub: vi.fn(() => Promise.resolve({ url: "https://github.com/login" })),
        logout: vi.fn(() => Promise.resolve()),
      },
      repos: {
        list: vi.fn(() => Promise.resolve([repo])),
      },
      scans: {
        list: vi.fn(() => Promise.resolve([])),
        create: vi.fn(() => Promise.resolve({ id: 1 })),
      },
      findings: {
        list: vi.fn(() => Promise.resolve([listFindingA, listFindingB])),
        get: vi.fn((id) => {
          if (!findingDeferreds.has(id)) {
            findingDeferreds.set(id, makeDeferred());
          }
          return findingDeferreds.get(id).promise;
        }),
        hitl: vi.fn(() => Promise.resolve({})),
        createPr: vi.fn(() => Promise.resolve({})),
        fixWithAi: vi.fn(() => Promise.resolve({})),
        approve: vi.fn(() => Promise.resolve({})),
      },
      queue: {
        status: vi.fn(() => Promise.resolve({ queue_depth: 0, active_tasks: 0 })),
      },
      pr: {
        createBatch: vi.fn(() => Promise.resolve({})),
      },
      metrics: vi.fn(() => Promise.resolve(metrics)),
    },
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  findingDeferreds.clear();
});

function detailShape(id, message, overrides = {}) {
  return {
    id,
    severity: "high",
    tool: "semgrep",
    file: "src/app.js",
    line: 10,
    message,
    type: "security",
    details: {},
    triage: { verdict: "real", confidence: 0.95, rationale: "Test rationale" },
    fixes: [],
    scan: 1,
    ...overrides,
  };
}

describe("App", () => {
  it("drops stale finding detail responses when selection changes", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Wait for the repo card itself (not just the static heading, which
    // renders before repos.list() resolves) then select the only repo.
    await user.click(await screen.findByRole("button", { name: "Select" }));
    await waitFor(() => {
      expect(screen.getByText("Live Findings")).toBeInTheDocument();
    });

    // Select finding A. This triggers the [selectedId] effect and starts an
    // in-flight api.findings.get('finding-a') call.
    await user.click(screen.getByText("Hardcoded secret in source"));
    await waitFor(() => {
      expect(findingDeferreds.has("finding-a")).toBe(true);
    });

    // Before A's detail resolves, switch to finding B. The previous effect's
    // cleanup flips `alive` to false, so A's eventual response must be ignored.
    await user.click(screen.getByText("API key leaked in config"));
    await waitFor(() => {
      expect(findingDeferreds.has("finding-b")).toBe(true);
    });

    // Resolve A first — this would show the wrong finding if the guard failed.
    findingDeferreds.get("finding-a").resolve(
      detailShape("finding-a", "Hardcoded secret in source")
    );

    // Resolve B second — this should be the only response that updates detail.
    findingDeferreds.get("finding-b").resolve(
      detailShape("finding-b", "API key leaked in config", {
        severity: "critical",
        tool: "gitleaks",
        file: "src/config.js",
        line: 20,
        type: "secret",
      })
    );

    // The detail dialog should appear and show B, not A.
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("API key leaked in config");
    expect(dialog).not.toHaveTextContent("Hardcoded secret in source");
  });

  it("routes to a different tab via the Sidebar navigation", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Select" }));
    await waitFor(() => {
      expect(screen.getByText("Live Findings")).toBeInTheDocument();
    });

    // Click the non-default tab in the sidebar. Accessible name includes the
    // material-icon ligature text ("settings_input_component"), so match
    // loosely rather than on the exact visible label.
    await user.click(screen.getByRole("button", { name: /Scan Config/i }));

    // The Scan Config tab panel should render.
    await waitFor(() => {
      expect(screen.getByText("Scan Configuration")).toBeInTheDocument();
    });

    // The previous dashboard tab panel should no longer render.
    expect(screen.queryByText("Live Findings")).not.toBeInTheDocument();
  });
});
