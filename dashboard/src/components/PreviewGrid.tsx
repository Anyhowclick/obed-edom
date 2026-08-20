export function isPreviewVideo(nameOrUrl: string): boolean {
  return /\.mov(?:$|[?#])/i.test(nameOrUrl);
}

export function LoadingOverlay({ title, logs }: { title: string; logs: string[] }) {
  return (
    <div className="overlay">
      <div className="overlay-card">
        <div className="spinner" />
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        <div className="log">{logs.join("\n") || "Working…"}</div>
      </div>
    </div>
  );
}

export function Lightbox({ src, onClose }: { src: string | null; onClose: () => void }) {
  if (!src) return null;
  return (
    <div className="lightbox" onClick={onClose}>
      {isPreviewVideo(src) ? (
        <video src={src} controls autoPlay muted playsInline onClick={(e) => e.stopPropagation()} />
      ) : (
        <img src={src} alt="" />
      )}
    </div>
  );
}

export function PreviewGrid({
  urls,
  onOpen,
  columns,
}: {
  urls: { src: string; label?: string }[];
  onOpen: (src: string) => void;
  columns?: 1 | 2 | 3;
}) {
  if (!urls.length) return <p className="note">No preview images.</p>;
  return (
    <div className={`thumbs${columns ? ` cols-${columns}` : ""}`}>
      {urls.map((u) => (
        <button
          key={u.src}
          type="button"
          style={{ background: "none", border: 0, padding: 0, color: "inherit" }}
          onClick={() => onOpen(u.src)}
        >
          {isPreviewVideo(u.src) ? (
            <video src={u.src} muted playsInline preload="metadata" />
          ) : (
            <img src={u.src} alt={u.label || ""} />
          )}
          {u.label ? <div className="cap">{u.label}</div> : null}
        </button>
      ))}
    </div>
  );
}
