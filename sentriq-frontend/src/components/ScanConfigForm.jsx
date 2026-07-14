import { useState, useEffect } from "react";

const STATIC_TOOLS = [
  { id: "gitleaks", label: "gitleaks" },
  { id: "semgrep", label: "semgrep" },
  { id: "trivy", label: "trivy" },
];

const DYNAMIC_TOOLS = [
  { id: "zap", label: "zap" },
  { id: "nuclei", label: "nuclei" },
];

// "None" first and default: patches are opt-in per finding, not per scan.
const SEVERITY_OPTIONS = [
  { value: "none", label: "None — fix on demand (default)" },
  { value: "critical", label: "Critical only" },
  { value: "high", label: "High and above" },
  { value: "medium", label: "Medium and above" },
  { value: "low", label: "Low and above" },
];

export default function ScanConfigForm({ repo, onSubmit, busy }) {
  const [pipeline, setPipeline] = useState("static");
  const [ref, setRef] = useState(repo?.default_branch || "main");
  const [dynamicTarget, setDynamicTarget] = useState("https://staging.example.com");
  const [selectedTools, setSelectedTools] = useState(STATIC_TOOLS.map((t) => t.id));
  // Default "none": a scan triages everything but never writes patches on its
  // own. Fixes are requested per-finding with "Fix with AI".
  const [autoFixSeverity, setAutoFixSeverity] = useState("none");

  useEffect(() => {
    setRef(repo?.default_branch || "main");
  }, [repo]);

  useEffect(() => {
    setSelectedTools(pipeline === "static" ? STATIC_TOOLS.map((t) => t.id) : DYNAMIC_TOOLS.map((t) => t.id));
  }, [pipeline]);

  const isValidUrl = (url) => /^https?:\/\//.test(url);

  const tools = pipeline === "static" ? STATIC_TOOLS : DYNAMIC_TOOLS;

  const toggleTool = (toolId) => {
    setSelectedTools((prev) => (prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (selectedTools.length === 0) return;
    if (pipeline === "dynamic" && !isValidUrl(dynamicTarget)) return;
    onSubmit({
      pipeline,
      target: pipeline === "static" ? repo?.clone_url : dynamicTarget,
      ref,
      tools: selectedTools,
      auto_fix_severity: autoFixSeverity,
    });
  };

  return (
    <section className="bg-surface border-2 border-outline p-5 flex flex-col gap-5 relative group">
      <div className="absolute inset-0 border-2 border-primary opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
      <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase tracking-tight flex items-center gap-2">
        <span className="material-symbols-outlined text-primary">settings</span>
        Scan Configuration
      </h2>

      {/* Selected repo */}
      <div className="bg-surface-container-low border-2 border-outline p-3 flex items-center gap-3">
        <span className="material-symbols-outlined text-primary">folder</span>
        <div className="min-w-0">
          <div className="font-code-label text-code-label text-on-surface truncate">{repo?.full_name}</div>
          <div className="font-body-sm text-body-sm text-on-surface-variant">{repo?.default_branch}</div>
        </div>
      </div>

      {/* Pipeline segmented control */}
      <div className="flex border-2 border-outline font-code-label text-code-label uppercase">
        <button
          type="button"
          onClick={() => setPipeline("static")}
          className={`flex-1 py-2 text-center border-r-2 border-outline transition-colors ${
            pipeline === "static" ? "bg-primary text-on-primary font-bold hover:bg-inverse-primary hover:text-white" : "bg-surface text-on-surface hover:bg-surface-container-highest"
          }`}
        >
          STATIC
        </button>
        <button
          type="button"
          onClick={() => setPipeline("dynamic")}
          className={`flex-1 py-2 text-center transition-colors ${
            pipeline === "dynamic" ? "bg-primary text-on-primary font-bold hover:bg-inverse-primary hover:text-white" : "bg-surface text-on-surface hover:bg-surface-container-highest"
          }`}
        >
          DYNAMIC
        </button>
      </div>

      {/* Tools grid */}
      <div className="space-y-2">
        <label className="font-code-label text-code-label text-outline uppercase block">Select Tools</label>
        <div className="grid grid-cols-2 gap-2 font-code-label text-code-label">
          {tools.map((tool) => {
            const checked = selectedTools.includes(tool.id);
            return (
              <label
                key={tool.id}
                className={`flex items-center gap-2 p-2 border-2 cursor-pointer transition-colors ${
                  checked ? "border-primary bg-primary/10 text-primary" : "border-outline-variant bg-surface-container text-on-surface hover:border-primary"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleTool(tool.id)}
                  className="accent-primary w-4 h-4 bg-background border-2 border-outline rounded-none"
                />
                {tool.label}
              </label>
            );
          })}
        </div>
      </div>

      {pipeline === "static" ? (
        /* Branch input */
        <div className="space-y-2">
          <label className="font-code-label text-code-label text-outline uppercase block">Target Branch</label>
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-2.5 text-outline text-[18px]">call_split</span>
            <input
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              className="w-full bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-2 pl-9 pr-3 focus:outline-none focus:border-primary focus:ring-0 transition-colors"
              type="text"
            />
          </div>
        </div>
      ) : (
        /* Dynamic target URL */
        <div className="space-y-2">
          <label className="font-code-label text-code-label text-outline uppercase block">Target URL</label>
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-2.5 text-outline text-[18px]">language</span>
            <input
              value={dynamicTarget}
              onChange={(e) => setDynamicTarget(e.target.value)}
              className="w-full bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-2 pl-9 pr-3 focus:outline-none focus:border-primary focus:ring-0 transition-colors"
              type="text"
              placeholder="https://staging.example.com"
            />
          </div>
        </div>
      )}

      {/* Auto-fix */}
      <div className="space-y-2">
        <label className="font-code-label text-code-label text-outline uppercase block">Auto-fix Policy</label>
        <div className="relative">
          <select
            value={autoFixSeverity}
            onChange={(e) => setAutoFixSeverity(e.target.value)}
            className="w-full bg-background border-2 border-outline-variant text-on-surface font-code-label text-code-label py-2 px-3 focus:outline-none focus:border-primary focus:ring-0 appearance-none rounded-none"
          >
            {SEVERITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <span className="material-symbols-outlined absolute right-3 top-2.5 text-outline pointer-events-none">expand_more</span>
        </div>
      </div>

      {/* HITL note */}
      <div className="bg-error-container border-2 border-error p-3 flex gap-3 items-start">
        <span className="material-symbols-outlined text-error text-[20px] mt-0.5">warning</span>
        <p className="font-code-label text-[11px] text-error leading-tight uppercase">
          HITL REQUIRED: No patch is ever written or opened as a PR without your explicit approval.
        </p>
      </div>

      <button
        type="button"
        onClick={handleSubmit}
        disabled={busy || selectedTools.length === 0 || (pipeline === "dynamic" && !isValidUrl(dynamicTarget))}
        className="mt-2 w-full bg-primary text-on-primary border-2 border-primary font-headline-sm text-headline-sm py-3 uppercase hover:bg-inverse-primary hover:text-white transition-all active:translate-y-1 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {busy ? "QUEUING..." : "RUN SCAN"}
      </button>
    </section>
  );
}
