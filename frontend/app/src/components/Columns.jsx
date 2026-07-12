import React, { useEffect, useRef } from "react";
import { SEV_COLOR } from "../data/util.js";
import { LEVEL_NAMES } from "../hooks/useExplorer.js";

function Item({ item, active, onClick }) {
  return (
    <button type="button" className={`item ${active ? "active" : ""}`} onClick={onClick}>
      <div className="flex items-center gap-2 font-medium">
        {item.sev && (
          <span className="dot" style={{ background: SEV_COLOR[item.sev] }} />
        )}
        <span className="truncate">{item.title}</span>
        {item.status && <span className="viz-badge">{item.status}</span>}
      </div>
      {item.meta && <div className="mt-1 line-clamp-2 text-sm text-muted">{item.meta}</div>}
      {item.extra && <div className="mt-2 truncate text-sm text-muted">{item.extra}</div>}
    </button>
  );
}

export default function Columns({ levels, activeIds, itemsFor, onSelect }) {
  const hostRef = useRef(null);

  // Auto-scroll to reveal the newest (right-most) column as you drill in.
  useEffect(() => {
    const el = hostRef.current;
    if (el) requestAnimationFrame(() => (el.scrollLeft = el.scrollWidth));
  }, [levels.length]);

  return (
    <div className="columns scroll" ref={hostRef}>
      {levels.map((level) => {
        const list = itemsFor(level);
        return (
          <section className="col" key={level}>
            <div className="col-head">
              <div className="text-sm font-medium">{LEVEL_NAMES[level]}</div>
              <div className="text-sm text-muted">{list.length} options</div>
            </div>
            <div className="space-y-1 p-2">
              {list.length === 0 ? (
                <div className="p-3 text-sm text-muted">No matches.</div>
              ) : (
                list.map((x) => (
                  <Item
                    key={x.id}
                    item={x}
                    active={activeIds[level] === x.id}
                    onClick={() => onSelect(level, x)}
                  />
                ))
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
