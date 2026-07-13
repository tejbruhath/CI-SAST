import { useState } from "react";

export default function ScanForm({ onSubmit, busy }) {
  const [pipeline, setPipeline] = useState("static");
  const [target, setTarget] = useState("");
  const [ref, setRef] = useState("HEAD");

  const submit = (e) => {
    e.preventDefault();
    if (!target.trim()) return;
    onSubmit(pipeline, target.trim(), ref.trim() || "HEAD");
  };

  return (
    <form onSubmit={submit}>
      <label className="field">
        <span>Pipeline</span>
        <select value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
          <option value="static">Static — SAST + SCA (gitleaks · semgrep · trivy)</option>
          <option value="dynamic">Dynamic — DAST (ZAP · nuclei)</option>
        </select>
      </label>
      <label className="field">
        <span>{pipeline === "static" ? "Git repository URL" : "Target URL"}</span>
        <input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder={pipeline === "static"
            ? "https://github.com/org/repo.git"
            : "https://staging.example.com"}
        />
      </label>
      {pipeline === "static" && (
        <label className="field">
          <span>Ref (branch / commit)</span>
          <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="HEAD" />
        </label>
      )}
      <button type="submit" disabled={busy}>
        {busy ? "Queuing…" : "Run scan"}
      </button>
    </form>
  );
}
