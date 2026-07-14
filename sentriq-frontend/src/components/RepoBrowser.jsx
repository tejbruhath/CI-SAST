import { useState, useMemo } from "react";

function RepoCard({ repo, selected, onSelect }) {
  return (
    <div
      className={`bg-[#151922] flex flex-col h-full transition-colors ${
        selected ? "border-2 border-primary relative overflow-hidden" : "border-2 border-outline-variant hover:border-[#424753]"
      }`}
    >
      {selected && (
        <div className="absolute top-0 right-0 w-16 h-16 bg-primary-fixed/10 -translate-y-1/2 translate-x-1/2 rotate-45 border-l-2 border-b-2 border-primary" />
      )}
      <div className="p-5 flex-1 flex flex-col gap-4">
        <div className="flex justify-between items-start">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 border-2 border-outline-variant bg-[#0b0d12] flex items-center justify-center shrink-0">
              <span className="material-symbols-outlined text-on-surface-variant">folder</span>
            </div>
            <div className="min-w-0">
              <h3 className={`font-headline-sm text-headline-sm break-all ${selected ? "text-primary" : "text-on-surface"}`}>
                {repo.full_name}
              </h3>
              <div className="flex items-center gap-2 mt-1">
                <span className="material-symbols-outlined text-[14px] text-on-surface-variant">call_split</span>
                <span className="font-code-label text-code-label text-on-surface-variant">{repo.default_branch}</span>
              </div>
            </div>
          </div>
          <span
            className={`font-code-label text-code-label px-2 py-1 border-2 shrink-0 ${
              repo.private ? "bg-primary text-on-primary border-primary" : "bg-surface-variant text-on-surface border-outline-variant"
            }`}
          >
            {repo.private ? "PRIVATE" : "PUBLIC"}
          </span>
        </div>
        {repo.description && (
          <p className="font-body-sm text-body-sm text-on-surface-variant line-clamp-2">{repo.description}</p>
        )}
      </div>
      <div className={`border-t-2 p-4 ${selected ? "border-primary bg-primary-fixed/5" : "border-outline-variant"}`}>
        <button
          onClick={() => onSelect(repo)}
          disabled={selected}
          className={`w-full py-2 font-headline-sm text-headline-sm uppercase tracking-wide flex items-center justify-center gap-2 transition-colors ${
            selected
              ? "bg-primary text-on-primary border-2 border-primary hover:bg-primary-container"
              : "bg-transparent text-primary border-2 border-outline-variant hover:border-primary"
          } disabled:opacity-70`}
        >
          {selected ? (
            <>
              <span className="material-symbols-outlined">check_circle</span>
              Selected
            </>
          ) : (
            "Select"
          )}
        </button>
      </div>
    </div>
  );
}

function RepoSkeleton() {
  return (
    <div className="bg-[#151922] border-2 border-outline-variant flex flex-col h-full">
      <div className="p-5 flex-1 flex flex-col gap-4">
        <div className="flex justify-between items-start">
          <div className="flex items-center gap-3 w-full">
            <div className="w-10 h-10 shimmer border-2 border-outline-variant" />
            <div className="flex-1 space-y-2">
              <div className="h-5 w-3/4 shimmer" />
              <div className="h-3 w-1/4 shimmer" />
            </div>
          </div>
        </div>
        <div className="space-y-2 mt-4">
          <div className="h-3 w-full shimmer" />
          <div className="h-3 w-5/6 shimmer" />
        </div>
      </div>
      <div className="border-t-2 border-outline-variant p-4">
        <div className="w-full h-10 shimmer border-2 border-outline-variant" />
      </div>
    </div>
  );
}

export default function RepoBrowser({ repos, loading, user, onSelectRepo, onLogout }) {
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter((r) => r.full_name.toLowerCase().includes(q));
  }, [repos, filter]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Navigation */}
      <header className="flex justify-between items-center w-full px-6 py-4 z-50 bg-surface border-b-4 border-primary shadow-[4px_4px_0px_0px_rgba(26,26,26,1)] sticky top-0">
        <div className="flex items-center gap-4">
          <div className="font-headline-md text-headline-md text-primary bg-primary-fixed px-2 border-2 border-primary uppercase tracking-tighter">
            SENTRIQ
          </div>
        </div>
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-4">
            <button className="text-on-surface-variant font-bold hover:text-primary transition-colors">
              <span className="material-symbols-outlined">notifications</span>
            </button>
            <button className="text-on-surface-variant font-bold hover:text-primary transition-colors">
              <span className="material-symbols-outlined">settings</span>
            </button>
          </div>
          <div className="flex items-center gap-3 pl-6 border-l-2 border-outline-variant">
            {user && (
              <>
                <img alt={user.name} className="w-8 h-8 border-2 border-primary object-cover" src={user.avatar_url} />
                <span className="font-headline-sm text-headline-sm text-on-surface hidden sm:inline">{user.name || user.login}</span>
              </>
            )}
            <button onClick={onLogout} className="ml-2 text-on-surface-variant hover:text-error transition-colors p-1" title="Logout">
              <span className="material-symbols-outlined">logout</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex flex-col w-full max-w-7xl mx-auto px-6 py-8 gap-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-end justify-between border-b-2 border-outline-variant pb-6">
          <div>
            <h1 className="font-display-lg text-display-lg text-on-surface tracking-tighter">Select a repository to scan</h1>
            <p className="font-body-md text-body-md text-on-surface-variant mt-2 max-w-2xl">
              Choose a repository to initiate SAST, SCA, or DAST scanning pipelines. Only repositories you have admin access to are
              displayed.
            </p>
          </div>
          <div className="w-full md:w-96 relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant z-10">search</span>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full bg-[#0b0d12] text-on-surface border-2 border-outline-variant focus:border-primary focus:ring-0 pl-10 pr-4 py-3 font-code-label text-code-label transition-colors outline-none"
              placeholder="Filter repositories..."
              type="text"
            />
          </div>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <RepoSkeleton />
            <RepoSkeleton />
            <RepoSkeleton />
            <RepoSkeleton />
            <RepoSkeleton />
            <RepoSkeleton />
          </div>
        ) : filtered.length === 0 ? (
          <div className="border-2 border-outline-variant bg-surface-container p-12 text-center">
            <span className="material-symbols-outlined text-4xl text-on-surface-variant mb-4">folder_off</span>
            <h3 className="font-headline-sm text-headline-sm text-on-surface uppercase">No repositories found</h3>
            <p className="font-body-md text-body-md text-on-surface-variant mt-2">
              {filter ? "Try a different search term." : "No repositories available for this account."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map((repo) => (
              <RepoCard key={repo.id} repo={repo} selected={false} onSelect={onSelectRepo} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
