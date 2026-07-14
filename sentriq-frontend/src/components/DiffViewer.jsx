export default function DiffViewer({ diff, filename = "patch" }) {
  if (!diff || !diff.trim()) return <div className="text-on-surface-variant font-body-sm">No patch.</div>;

  const lines = diff.split("\n");
  let lineNumber = 0;

  const rendered = lines.map((ln, i) => {
    let type = "context";
    if (ln.startsWith("---") || ln.startsWith("+++") || ln.startsWith("diff ")) type = "meta";
    else if (ln.startsWith("@@")) type = "hunk";
    else if (ln.startsWith("+")) type = "add";
    else if (ln.startsWith("-")) type = "del";

    if (type === "add" || type === "context") lineNumber++;

    return { key: i, type, text: ln || " ", lineNumber: type !== "meta" && type !== "hunk" ? lineNumber : null };
  });

  const displayFilename = filename || "patch";

  return (
    <div className="border-2 border-outline-variant bg-surface-container font-code-label text-code-label overflow-x-auto">
      <div className="flex bg-surface-container-high border-b-2 border-outline-variant px-4 py-2">
        <span className="text-on-surface-variant">{displayFilename}</span>
      </div>
      <div className="flex flex-col whitespace-pre">
        {rendered.map(({ key, type, text, lineNumber: ln }) => {
          const rowBase = "flex w-full hover:bg-surface-variant";
          const rowClass = {
            meta: `${rowBase} text-on-surface-variant`,
            hunk: `${rowBase} text-primary`,
            add: `${rowBase} bg-primary/10 hover:bg-primary/20 border-l-4 border-primary`,
            del: `${rowBase} bg-error-container/20 hover:bg-error-container/30 border-l-4 border-error`,
            context: `${rowBase} text-on-surface-variant`,
          }[type];

          const numClass = "w-12 text-right pr-4 py-1 select-none border-r-2 border-outline-variant bg-surface text-outline";
          const textClass = "px-4 py-1";
          const textColor = {
            meta: "text-on-surface-variant",
            hunk: "text-primary",
            add: "text-primary",
            del: "text-error",
            context: "text-on-surface-variant",
          }[type];

          return (
            <div key={key} className={rowClass}>
              <div className={numClass}>{ln ?? (type === "hunk" ? "@@" : "")}</div>
              <div className={`${textClass} ${textColor}`}>{text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
