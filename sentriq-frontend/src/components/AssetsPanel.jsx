const SEVERITIES = ["critical", "high", "medium", "low"];

const SEV_STYLES = {
  critical: "bg-error text-on-error border-error",
  high: "bg-tertiary-container text-on-tertiary-container border-on-tertiary-container",
  medium: "bg-secondary-container text-on-surface border-outline",
  low: "bg-primary text-on-primary border-primary",
};

function SeverityCount({ severity, count }) {
  return (
    <span
      className={`inline-flex items-center justify-center min-w-[2rem] px-2 py-0.5 border-2 font-code-label text-[10px] uppercase font-bold ${SEV_STYLES[severity]}`}
    >
      {severity.slice(0, 1)}
      <span className="ml-1">{count}</span>
    </span>
  );
}

function formatTimestamp(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AssetsPanel({ repos, scans, findings, selectedRepo, onSelectRepo }) {
  const scanIdToRepo = Object.fromEntries(
    scans
      .map((s) => {
        const repo = repos.find((r) => s.target && s.target.includes(r.full_name));
        return repo ? [s.id, repo.full_name] : null;
      })
      .filter(Boolean)
  );

  const repoScans = (repo) => scans.filter((s) => s.target && s.target.includes(repo.full_name));

  const repoFindings = (repo) =>
    findings.filter((f) => {
      if (f.repo) return f.repo === repo.full_name;
      return scanIdToRepo[f.scan] === repo.full_name;
    });

  return (
    <section className="bg-surface border-2 border-outline flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
      <div className="p-4 border-b-2 border-outline bg-surface-container-low flex items-center justify-between shrink-0">
        <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase tracking-tight flex items-center gap-2">
          <span className="material-symbols-outlined text-primary">inventory_2</span>
          Assets
        </h2>
        <span className="font-code-label text-code-label text-outline uppercase">
          {repos.length} REPO{repos.length === 1 ? "" : "S"}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto">
        <table className="w-full text-left border-collapse font-body-sm text-body-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-surface-container font-code-label text-code-label text-outline uppercase border-b-2 border-outline">
              <th className="p-3 border-r-2 border-outline font-medium">Repository</th>
              <th className="p-3 border-r-2 border-outline font-medium w-28">Scans</th>
              <th className="p-3 border-r-2 border-outline font-medium w-48">Last Scan</th>
              <th className="p-3 font-medium">Severity Rollup</th>
            </tr>
          </thead>
          <tbody className="text-on-surface">
            {repos.length === 0 ? (
              <tr>
                <td colSpan={4} className="p-8 text-center text-on-surface-variant font-body-md">
                  No repositories loaded.
                </td>
              </tr>
            ) : (
              repos.map((repo) => {
                const scansForRepo = repoScans(repo);
                const findingsForRepo = repoFindings(repo);
                const lastScan = scansForRepo
                  .slice()
                  .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0];
                const counts = SEVERITIES.reduce((acc, sev) => {
                  acc[sev] = findingsForRepo.filter((f) => f.severity === sev).length;
                  return acc;
                }, {});
                const isSelected = selectedRepo?.full_name === repo.full_name;

                return (
                  <tr
                    key={repo.full_name}
                    className={`border-b border-outline hover:bg-surface-container-highest transition-colors cursor-pointer ${
                      isSelected ? "bg-surface-container-high" : ""
                    }`}
                    onClick={() => onSelectRepo?.(repo)}
                  >
                    <td className="p-3 border-r-2 border-outline">
                      <div className="font-bold text-on-surface">{repo.full_name}</div>
                      {repo.clone_url && (
                        <div className="text-outline font-code-label text-code-label truncate max-w-xs">
                          {repo.clone_url}
                        </div>
                      )}
                    </td>
                    <td className="p-3 border-r-2 border-outline font-code-label text-code-label">
                      {scansForRepo.length}
                    </td>
                    <td className="p-3 border-r-2 border-outline font-code-label text-code-label text-outline">
                      {lastScan ? formatTimestamp(lastScan.created_at) : "never scanned"}
                    </td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-2">
                        {SEVERITIES.map((sev) => (
                          <SeverityCount key={sev} severity={sev} count={counts[sev]} />
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
