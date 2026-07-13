// Minimal unified-diff renderer — colors +/- lines, hunk headers, file meta.
// No dependency; parses the raw diff string line by line.
export default function DiffViewer({ diff }) {
  if (!diff || !diff.trim()) return <div className="spinner">No patch.</div>;
  const lines = diff.split("\n");
  return (
    <pre className="diff">
      {lines.map((ln, i) => {
        let cls = "";
        if (ln.startsWith("+++") || ln.startsWith("---") || ln.startsWith("diff ")) cls = "meta";
        else if (ln.startsWith("@@")) cls = "hunk";
        else if (ln.startsWith("+")) cls = "add";
        else if (ln.startsWith("-")) cls = "del";
        return <span key={i} className={`ln ${cls}`}>{ln || " "}</span>;
      })}
    </pre>
  );
}
