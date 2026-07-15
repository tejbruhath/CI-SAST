export default function DiffViewer({ diff, filename = "patch" }) {
  // Render a unified diff with color-coded add/del/hunk lines.
  if (!diff || !diff.trim()) return <div className="text-on-surface-variant font-body-sm">No patch.</div>; // empty state

  const lines = diff.split("\n"); // one row per diff line
  let lineNumber = 0; // approximate new-file line counter

  const rendered = lines.map((ln, i) => {
    let type = "context"; // default unchanged context line
    if (ln.startsWith("---") || ln.startsWith("+++") || ln.startsWith("diff ")) type = "meta"; // file headers
    else if (ln.startsWith("@@")) type = "hunk"; // hunk header
    else if (ln.startsWith("+")) type = "add"; // added line
    else if (ln.startsWith("-")) type = "del"; // removed line

    if (type === "add" || type === "context") lineNumber++; // count new-file lines

    return { key: i, type, text: ln || " ", lineNumber: type !== "meta" && type !== "hunk" ? lineNumber : null }; // display model
  });

  const displayFilename = filename || "patch"; // header label

  return (
    <div className="border-2 border-outline-variant bg-surface-container font-code-label text-code-label overflow-x-auto">
      <div className="flex bg-surface-container-high border-b-2 border-outline-variant px-4 py-2">
        <span className="text-on-surface-variant">{displayFilename}</span> {/* file name bar */}
      </div>
      <div className="flex flex-col whitespace-pre">
        {rendered.map(({ key, type, text, lineNumber: ln }) => {
          const rowBase = "flex w-full hover:bg-surface-variant"; // shared row layout
          const rowClass = {
            meta: `${rowBase} text-on-surface-variant`, // grey headers
            hunk: `${rowBase} text-primary`, // highlight hunk markers
            add: `${rowBase} bg-primary/10 hover:bg-primary/20 border-l-4 border-primary`, // green-ish add
            del: `${rowBase} bg-error-container/20 hover:bg-error-container/30 border-l-4 border-error`, // red del
            context: `${rowBase} text-on-surface-variant`, // muted context
          }[type];

          const numClass = "w-12 text-right pr-4 py-1 select-none border-r-2 border-outline-variant bg-surface text-outline"; // gutter
          const textClass = "px-4 py-1"; // code cell padding
          const textColor = {
            meta: "text-on-surface-variant",
            hunk: "text-primary",
            add: "text-primary",
            del: "text-error",
            context: "text-on-surface-variant",
          }[type];

          return (
            <div key={key} className={rowClass}>
              <div className={numClass}>{ln ?? (type === "hunk" ? "@@" : "")}</div> {/* line # or @@ */}
              <div className={`${textClass} ${textColor}`}>{text}</div> {/* raw diff text */}
            </div>
          );
        })}
      </div>
    </div>
  );
}
