import type { Flag } from "../api";

export function ValidationPanel({ flags, onJump }: { flags: Flag[]; onJump?: (location: string) => void }) {
  if (!flags?.length) {
    return (
      <section className="flags">
        <h2>Validation</h2>
        <p className="note">No flags yet.</p>
      </section>
    );
  }
  const order = { error: 0, warning: 1, info: 2 } as const;
  const sorted = [...flags].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return (
    <section className="flags">
      <h2>Validation</h2>
      <p className="note">{sorted.length} finding{sorted.length === 1 ? "" : "s"}. Files are not modified.</p>
      {sorted.map((flag, i) => (
        <div
          key={`${flag.category}-${i}`}
          className={`flag ${flag.severity}`}
          onClick={() => flag.location && onJump?.(flag.location)}
          role={onJump && flag.location ? "button" : undefined}
        >
          <div className="meta">
            {flag.severity} · {flag.category}
            {flag.location ? ` · ${flag.location}` : ""}
          </div>
          {flag.message}
        </div>
      ))}
    </section>
  );
}
