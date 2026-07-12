import React from "react";
import { SEV_COLOR } from "../data/util.js";

function Field({ label, value }) {
  if (value == null || value === "") return null;
  return (
    <div className="rounded-box">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 break-words text-sm font-medium">{String(value)}</div>
    </div>
  );
}

function recommendation(f) {
  if (f.tool === "trivy")
    return `Upgrade ${f.package || "the dependency"}${f.fixed ? ` to ${f.fixed} or later` : ""}, then re-run the pipeline.`;
  if (f.tool === "gitleaks")
    return "Revoke and rotate the exposed credential, purge it from git history, then re-run the scan.";
  return "Fix the flagged code path, add a regression test, and verify it clears on the next scan.";
}

export default function DetailPanel({ finding, onClose }) {
  if (!finding) return null;
  const f = finding;
  const manifest = f.line == null;

  return (
    <aside className="detail" aria-live="polite">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex wrap items-center gap-2">
              <span className="dot" style={{ background: SEV_COLOR[f.sev] }} />
              <span className="font-medium">{f.sev.toUpperCase()}</span>
              <span className="viz-badge">{f.life}</span>
              <span className="viz-badge">{f.tool}</span>
              <span className="viz-badge">{f.type}</span>
            </div>
            <h2 className="mt-2 font-medium">{f.msg}</h2>
            <div className="mt-1 text-sm text-muted">
              {f.file}{manifest ? " · dependency manifest" : ` · line ${f.line}`}
            </div>
          </div>
          <button type="button" className="chip" onClick={onClose}>Close</button>
        </div>

        <div className="detail-grid">
          <Field label="Rule" value={f.rule} />
          <Field label="Fingerprint" value={f.id} />
          <Field label="Type" value={f.type} />
          <Field label="Lifecycle" value={f.life} />
          <Field label="Package" value={f.package} />
          <Field label="Installed version" value={f.installed} />
          <Field label="Fixed version" value={f.fixed} />
          <Field label="CVSS" value={f.cvss} />
          <Field label="Effort" value={f.effort != null ? `${f.effort} min` : null} />
          <Field label="Entropy" value={f.entropy} />
        </div>

        {f.tags && f.tags.length > 0 && (
          <div className="flex wrap gap-2">
            {f.tags.map((t) => <span key={t} className="viz-badge">{t}</span>)}
          </div>
        )}

        <section className="rounded-box">
          <div className="font-medium">Recommended action</div>
          <p className="mt-2 text-sm">{recommendation(f)}</p>
          <div className="mt-3 flex wrap gap-2">
            {f.url && (
              <a className="chip" href={f.url} target="_blank" rel="noreferrer">
                View in source tool ↗
              </a>
            )}
            <button type="button" className="chip">Assign</button>
            <button type="button" className="chip">Create issue</button>
            <button type="button" className="chip">Accept risk</button>
          </div>
        </section>

        {f.life === "resolved" && (
          <div className="viz-callout">
            This finding was present in an earlier commit but is absent from the
            selected commit. It was auto-removed from the active tree (smart delete)
            and is shown here from resolved history only.
          </div>
        )}
      </div>
    </aside>
  );
}
