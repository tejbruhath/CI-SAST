export default function Header({ repo, user, onLogout }) {
  // Top bar: current repo breadcrumb + user avatar + logout.
  return (
    <header className="h-16 border-b-2 border-outline bg-surface-container-low px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Left: REPOS / owner/name breadcrumb */}
      <div className="flex items-center gap-2 font-code-label text-code-label text-on-surface-variant">
        <span className="material-symbols-outlined text-[18px]">folder</span> {/* folder icon */}
        <span>Repos</span> {/* static label */}
        <span className="text-outline">/</span> {/* path separator */}
        <span className="text-primary font-bold">{repo?.full_name || "unknown"}</span> {/* active repo */}
      </div>
      {/* Right: identity + logout */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3 pl-4 border-l-2 border-outline">
          {user && (
            <>
              <img alt={user.name} className="w-8 h-8 border-2 border-primary object-cover" src={user.avatar_url} /> {/* GitHub avatar */}
              <span className="font-headline-sm text-headline-sm text-on-surface hidden sm:inline">{user.name || user.login}</span> {/* hide name on tiny screens */}
            </>
          )}
          <button onClick={onLogout} className="material-symbols-outlined text-outline hover:text-error transition-colors" title="Logout">
            logout {/* icon font glyph */}
          </button>
        </div>
      </div>
    </header>
  );
}
