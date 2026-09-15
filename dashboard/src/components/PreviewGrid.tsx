export function isPreviewVideo(nameOrUrl: string): boolean {
  return /\.mov(?:$|[?#])/i.test(nameOrUrl);
}

export type OverlayProgress = {
  label: string;
  value: number;
  max: number;
  detail?: string;
  note?: string;
};

export function LoadingOverlay({
  title,
  logs,
  onCancel,
  progress,
}: {
  title: string;
  logs: string[];
  onCancel?: () => void;
  progress?: OverlayProgress | null;
}) {
  const pct = progress ? Math.min(100, Math.max(0, (progress.value / Math.max(1, progress.max)) * 100)) : 0;
  return (
    <div className="overlay">
      <div className="overlay-card">
        <div className="spinner" />
        <h2>{title}</h2>
        {progress ? (
          <div className="progress">
            <div className="progress-head">
              <span>{progress.label}</span>
              <span>{Math.round(pct)}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${pct}%` }} />
            </div>
            {progress.detail ? <div className="progress-detail">{progress.detail}</div> : null}
            {progress.note ? <div className="progress-note">{progress.note}</div> : null}
          </div>
        ) : null}
        <div className="log">{logs.join("\n") || "Working…"}</div>
        {onCancel ? (
          <button className="btn secondary" type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
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
          className="thumb-btn"
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
