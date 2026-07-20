import { describe, it, expect } from "vitest";
import { matchesFixAllFilters } from "./FixAllDialog.jsx";

const f = (overrides) => ({ severity: "high", tool: "semgrep", verdict: "real", fix: null, ...overrides });

describe("matchesFixAllFilters", () => {
  it("default scope (critical_high, all tools, real) matches a real high finding", () => {
    expect(matchesFixAllFilters(f({}), { severity: "critical_high", tool: "all", verdict: "real" })).toBe(true);
  });

  it("excludes medium severity from critical_high", () => {
    expect(matchesFixAllFilters(f({ severity: "medium" }), { severity: "critical_high", tool: "all", verdict: "real" })).toBe(false);
  });

  it("excludes findings that already have a non-failed fix", () => {
    const finding = f({ fix: { status: "proposed" } });
    expect(matchesFixAllFilters(finding, { severity: "all", tool: "all", verdict: "all" })).toBe(false);
  });

  it("includes findings whose last fix attempt failed (retry)", () => {
    const finding = f({ fix: { status: "failed" } });
    expect(matchesFixAllFilters(finding, { severity: "all", tool: "all", verdict: "all" })).toBe(true);
  });

  it("filters by tool and verdict", () => {
    const finding = f({ tool: "gitleaks", verdict: "noise" });
    expect(matchesFixAllFilters(finding, { severity: "all", tool: "semgrep", verdict: "all" })).toBe(false);
    expect(matchesFixAllFilters(finding, { severity: "all", tool: "gitleaks", verdict: "noise" })).toBe(true);
  });
});
