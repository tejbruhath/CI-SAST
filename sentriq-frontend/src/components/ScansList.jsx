import ScanCard from "./ScanCard.jsx"; // one card per scan row

export default function ScansList({ scans, activeScan, onPick }) {
  // Vertical list of recent scans; empty state when none.
  if (!scans.length) {
    return (
      <div className="border-2 border-outline-variant bg-surface-container p-6 text-center">
        <p className="font-body-md text-body-md text-on-surface-variant">No scans yet.</p> {/* empty copy */}
      </div>
    );
  }

  return (
    <section className="bg-surface border-2 border-outline flex flex-col h-full min-h-[250px]">
      {/* Section header */}
      <div className="p-4 border-b-2 border-outline bg-surface-container-low flex justify-between items-center">
        <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase tracking-tight flex items-center gap-2">
          <span className="material-symbols-outlined text-primary">history</span> {/* history icon */}
          Recent Scans
        </h2>
      </div>
      {/* Scrollable cards */}
      <div className="p-4 flex flex-col gap-4 overflow-y-auto">
        {scans.map((s) => (
          <ScanCard
            key={s.id} // stable React key
            scan={s} // scan DTO from API
            active={activeScan === s.id} // highlight selected
            onClick={() => onPick(s.id)} // select scan
            onShowFindings={onPick} // same handler for findings button
          />
        ))}
      </div>
    </section>
  );
}
