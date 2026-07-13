import { useState } from "react";
import { SeverityBadge, VerdictBadge, ToolBadge } from "./Badge.jsx";
import DiffViewer from "./DiffViewer.jsx";

export default function FindingDetail({ finding, onClose, onHitl, onCreatePr }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  if (!finding) return null;

  const fix = finding.fixes && finding.fixes[0];
  const triage = finding.triage;

  const act = async (action) => {
    setBusy(true);
    try {
      await onHitl(finding.id, action, note);
    } finally {
      setBusy(false);
    }
  };

  const createPr = async () => {
    setBusy(true);
    try {
      await onCreatePr(finding.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="drawer">
        <button className="close" onClick={onClose}>×</button>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <SeverityBadge severity={finding.severity} />
          <ToolBadge tool={finding.tool} />
          <span className="badge tool">{finding.type}</span>
        </div>
        <h3>{finding.message}</h3>

        <div className="kv">
          <div className="k">Rule</div><div className="mono">{finding.rule_id}</div>
          <div className="k">Location</div>
          <div className="mono">
            {finding.file ? (finding.line ? `${finding.file}:${finding.line}` : finding.file) : "—"}
          </div>
          {finding.url && (
            <>
              <div className="k">Reference</div>
              <div><a href={finding.url} target="_blank" rel="noreferrer"
                style={{ color: "var(--accent)" }}>{finding.url}</a></div>
            </>
          )}
        </div>

        <div className="section">
          <h4>Triage</h4>
          {triage ? (
            <div className="rationale">
              <div style={{ marginBottom: 6 }}>
                <VerdictBadge verdict={triage.verdict} />
                <span style={{ color: "var(--muted)", marginLeft: 8 }}>
                  confidence {(triage.confidence * 100).toFixed(0)}% · {triage.model}
                </span>
              </div>
              {triage.rationale || <span className="spinner">no rationale</span>}
            </div>
          ) : <div className="spinner">Not triaged.</div>}
        </div>

        <div className="section">
          <h4>Suggested Fix</h4>
          {fix ? (
            <>
              <DiffViewer diff={fix.diff} />
              {fix.explanation && (
                <div className="rationale" style={{ marginTop: 8 }}>{fix.explanation}</div>
              )}
              <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 6 }}>
                status: {fix.status}
              </div>
            </>
          ) : <div className="spinner">No fix generated.</div>}
        </div>

        {fix && (
          <div className="section">
            <h4>Human Review (HITL Gate)</h4>
            <textarea rows={2} placeholder="Review note (optional)"
              value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="hitl-actions">
              <button className="ok" disabled={busy} onClick={() => act("approve")}>Approve</button>
              <button className="danger" disabled={busy} onClick={() => act("deny")}>Deny</button>
              <button className="ghost" disabled={busy} onClick={() => act("edit")}>Mark edited</button>
            </div>
            {finding.hitl_actions && finding.hitl_actions.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
                Last: {finding.hitl_actions[0].action} by {finding.hitl_actions[0].actor}
              </div>
            )}

            {/* Create-PR action: enabled once the fix is approved */}
            <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              {fix.pr_status === "open" && fix.pr_url ? (
                <a href={fix.pr_url} target="_blank" rel="noreferrer">
                  <button className="ok" type="button">View pull request ↗</button>
                </a>
              ) : fix.pr_status === "creating" ? (
                <span className="spinner">Opening pull request…</span>
              ) : (
                <button type="button" disabled={busy || fix.status !== "approved"}
                  onClick={createPr}
                  title={fix.status !== "approved" ? "Approve the fix first" : ""}>
                  Create pull request
                </button>
              )}
              {fix.status !== "approved" && fix.pr_status !== "open" && (
                <span style={{ marginLeft: 10, fontSize: 12, color: "var(--muted)" }}>
                  approve the fix to enable
                </span>
              )}
              {fix.pr_status === "failed" && (
                <div className="err" style={{ marginTop: 10 }}>
                  PR failed: {fix.pr_error || "unknown error"}
                </div>
              )}
              {fix.branch && (
                <div style={{ marginTop: 6, fontSize: 12, color: "var(--muted)" }}>
                  branch: <span className="mono">{fix.branch}</span>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="section">
          <h4>Raw details</h4>
          <pre className="details">{JSON.stringify(finding.details, null, 2)}</pre>
        </div>
      </div>
    </>
  );
}
