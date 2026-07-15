import { useState } from "react"; // imported for future local form state (unused now)

export default function LoginPage({ onLogin, loading }) {
  // Unauthenticated landing: brand card + GitHub OAuth button + 3-step pitch.
  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden px-4">
      <div className="scanline-overlay absolute inset-0 z-0" /> {/* decorative CRT scanlines */}

      <main className="relative z-10 w-full max-w-md">
        {/* Central Brand Card */}
        <div className="bg-surface-container border-2 border-outline p-8 mb-8 relative shadow-[8px_8px_0px_0px_#151922]">
          {/* Decorative Corners */}
          <div className="absolute top-0 left-0 w-2 h-2 border-t-2 border-l-2 border-primary -mt-[2px] -ml-[2px]" /> {/* NW corner accent */}
          <div className="absolute top-0 right-0 w-2 h-2 border-t-2 border-r-2 border-primary -mt-[2px] -mr-[2px]" /> {/* NE */}
          <div className="absolute bottom-0 left-0 w-2 h-2 border-b-2 border-l-2 border-primary -mb-[2px] -ml-[2px]" /> {/* SW */}
          <div className="absolute bottom-0 right-0 w-2 h-2 border-b-2 border-r-2 border-primary -mb-[2px] -mr-[2px]" /> {/* SE */}

          <div className="flex flex-col items-center text-center space-y-6">
            {/* Logo/Brand */}
            <div className="flex flex-col items-center">
              <div className="w-16 h-16 border-2 border-primary bg-surface-container-high flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-primary text-4xl material-symbols-filled">security</span> {/* shield icon */}
              </div>
              <h1 className="font-display-lg text-display-lg text-on-surface uppercase mb-1">SENTRIQ</h1> {/* product name */}
              <span className="font-code-label text-code-label text-primary bg-primary-fixed/10 px-2 py-1 border border-primary/30">
                SEC_OPS_TERMINAL v2.4 {/* cosmetic subtitle */}
              </span>
            </div>

            <div className="w-full border-t border-outline-variant my-2" /> {/* divider */}

            {/* Login Action */}
            <div className="w-full space-y-4">
              <p className="font-body-sm text-body-sm text-on-surface-variant mb-4">
                Authenticate to access the security console and automated PR scanning environment.
              </p>
              <button
                onClick={onLogin} // parent starts GitHub OAuth
                disabled={loading} // prevent double-click while redirecting
                className="w-full bg-primary hover:bg-inverse-primary text-black font-headline-sm text-headline-sm uppercase py-4 border-2 border-primary flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="material-symbols-outlined mr-2">login</span>
                {loading ? "Authenticating..." : "LOGIN WITH GITHUB"} {/* loading label swap */}
              </button>
              <p className="font-body-sm text-body-sm text-on-surface-variant text-center opacity-70 mt-4">
                Requires read/write permissions for repository cloning and PR automation.
              </p>
            </div>
          </div>
        </div>

        {/* 3-Step How it Works */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-surface-container-low border-2 border-outline p-4 flex flex-col items-center text-center">
            <span className="font-code-label text-code-label text-primary mb-2">01</span>
            <span className="material-symbols-outlined text-on-surface-variant mb-2">dataset_linked</span>
            <span className="font-headline-sm text-headline-sm text-on-surface text-sm uppercase">Connect Repo</span>
          </div>
          <div className="bg-surface-container-low border-2 border-outline p-4 flex flex-col items-center text-center">
            <span className="font-code-label text-code-label text-primary mb-2">02</span>
            <span className="material-symbols-outlined text-on-surface-variant mb-2">troubleshoot</span>
            <span className="font-headline-sm text-headline-sm text-on-surface text-sm uppercase">Run Scan</span>
          </div>
          <div className="bg-surface-container-low border-2 border-outline p-4 flex flex-col items-center text-center">
            <span className="font-code-label text-code-label text-primary mb-2">03</span>
            <span className="material-symbols-outlined text-on-surface-variant mb-2">build_circle</span>
            <span className="font-headline-sm text-headline-sm text-on-surface text-sm uppercase">Auto-Fix</span>
          </div>
        </div>
      </main>
    </div>
  );
}
