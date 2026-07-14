import ScanCard from "./ScanCard.jsx";

export default function ScansList({ scans, activeScan, onPick }) {
  if (!scans.length) {
    return (
      <div className="border-2 border-outline-variant bg-surface-container p-6 text-center">
        <p className="font-body-md text-body-md text-on-surface-variant">No scans yet.</p>
      </div>
    );
  }

  return (
    <section className="bg-surface border-2 border-outline flex flex-col h-full min-h-[250px]">
      <div className="p-4 border-b-2 border-outline bg-surface-container-low flex justify-between items-center">
        <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase tracking-tight flex items-center gap-2">
          <span className="material-symbols-outlined text-primary">history</span>
          Recent Scans
        </h2>
      </div>
      <div className="p-4 flex flex-col gap-4 overflow-y-auto">
        {scans.map((s) => (
          <ScanCard key={s.id} scan={s} active={activeScan === s.id} onClick={() => onPick(s.id)} />
        ))}
      </div>
    </section>
  );
}
