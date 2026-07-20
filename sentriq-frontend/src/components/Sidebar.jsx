export default function Sidebar({ user, activeTab = "dashboard", onNavigate, onLogout, onCreatePr, canFixAll, onFixAll }) {
  // Left nav: tabs + primary actions + logout.
  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: "dashboard" }, // main overview
    { id: "config", label: "Scan Config", icon: "settings_input_component" }, // start scan form
    { id: "history", label: "Recent Scans", icon: "history" }, // scan list
    { id: "assets", label: "Assets", icon: "inventory_2" }, // repo assets panel
  ];

  return (
    <nav className="fixed left-0 top-0 h-full flex flex-col border-r-4 border-primary bg-surface z-40 w-64">
      {/* Brand block */}
      <div className="p-6 border-b-2 border-outline">
        <h1 className="font-headline-md font-black text-2xl text-primary uppercase tracking-tighter">SENTRIQ</h1>
        <p className="font-code-label text-code-label text-outline mt-1 uppercase">v2.4.0-PRO</p> {/* cosmetic version */}
      </div>

      {/* Nav buttons */}
      <div className="flex-1 py-4 flex flex-col gap-2 overflow-y-auto px-2">
        {navItems.map((item) => {
          const isActive = activeTab === item.id; // highlight current tab
          return (
            <button
              key={item.id}
              type="button"
              aria-current={isActive ? "page" : undefined} // a11y current page
              onClick={() => onNavigate?.(item.id)} // parent switches view
              className={`flex items-center p-3 font-black transition-transform active:scale-95 text-left ${
                isActive
                  ? "bg-primary-fixed text-primary border-2 border-primary" // selected style
                  : "text-primary border-2 border-transparent hover:border-primary hover:bg-surface-container-highest" // idle style
              }`}
            >
              <span className={`material-symbols-outlined mr-3 ${isActive ? "material-symbols-filled" : ""}`}>{item.icon}</span>
              <span className="font-body-sm font-bold uppercase text-sm">{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Primary CTAs */}
      <div className="p-4 border-t-2 border-outline flex flex-col gap-2">
        <button
          onClick={() => onNavigate?.("config")} // jump to scan form
          className="w-full bg-primary text-on-primary border-2 border-primary font-code-label font-bold py-2 uppercase hover:bg-inverse-primary hover:text-white transition-colors"
        >
          START NEW SCAN
        </button>
        <button
          onClick={onFixAll} // bulk-queue AI fixes for matching findings
          disabled={!canFixAll}
          className="w-full bg-primary text-on-primary border-2 border-primary font-code-label font-bold py-2 uppercase hover:bg-inverse-primary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          FIX ALL WITH AI
        </button>
        <button
          onClick={onCreatePr} // always opens; dialog tells you to approve a fix first if none are approved yet
          className="w-full bg-primary text-on-primary border-2 border-primary font-code-label font-bold py-2 uppercase hover:bg-inverse-primary hover:text-white transition-colors"
        >
          CREATE PR
        </button>
      </div>

      {/* Footer links */}
      <div className="px-2 pb-4 pt-2 border-t-2 border-outline flex flex-col gap-1">
        <a href="https://github.com/tejbruhath/CI-SAST/tree/main/docs" target="_blank" rel="noreferrer" className="text-outline flex items-center p-2 border-2 border-transparent hover:border-outline transition-all text-xs font-code-label uppercase">
          <span className="material-symbols-outlined mr-2 text-[18px]">description</span> Docs
        </a>
        <button
          onClick={onLogout} // clear session
          className="w-full text-left text-error flex items-center p-2 border-2 border-transparent hover:border-error transition-all text-xs font-code-label uppercase"
        >
          <span className="material-symbols-outlined mr-2 text-[18px]">logout</span> Logout
        </button>
      </div>
    </nav>
  );
}
