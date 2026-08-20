import type { Flag } from "../api";

export type SlideTarget = { deck: "lw" | "dsk"; index: number };

export function parseSlideTarget(location?: string): SlideTarget | null {
  if (!location) return null;
  const tagged = /(?:^|\b)(LW|DSK)\s+slide\s+(\d+)/i.exec(location);
  if (tagged) {
    return { deck: tagged[1].toLowerCase() as "lw" | "dsk", index: Number(tagged[2]) };
  }
  const plain = /(?:^|\b)slide\s+(\d+)/i.exec(location);
  if (!plain) return null;
  return { deck: "lw", index: Number(plain[1]) };
}

export function ValidationPanel({ flags, onJump }: { flags: Flag[]; onJump?: (location: string) => void }) {
  const visible = (flags || []).filter((flag) => flag.severity !== "success");
  if (!visible.length) {
    return (
      <section className="flags">
        <h2>Validation</h2>
        <p className="note">No flags yet.</p>
      </section>
    );
  }
  const order = { error: 0, warning: 1, info: 2 } as const;
  const sorted = [...visible].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return (
    <section className="flags">
      <h2>Validation</h2>
      <p className="note">{sorted.length} finding{sorted.length === 1 ? "" : "s"}. Files are not modified.</p>
      {sorted.map((flag, i) => {
        const slideHit = Boolean(onJump && (flag.severity === "error" || flag.severity === "warning") && parseSlideTarget(flag.location));
        const heading = `${flag.severity} · ${flag.category}${flag.location ? ` · ${flag.location}` : ""}`;
        return (
          <div key={`${flag.category}-${i}`} className={`flag ${flag.severity}`}>
            {slideHit ? (
              <button type="button" className="meta jump" onClick={() => onJump!(flag.location!)}>
                {heading}
              </button>
            ) : (
              <div className="meta">{heading}</div>
            )}
            {flag.message}
          </div>
        );
      })}
    </section>
  );
}
