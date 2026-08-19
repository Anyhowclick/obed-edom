import { useState } from "react";

type Props = {
  label: string;
  hint: string;
  accept?: string;
  file?: { path?: string; name: string } | null;
  onFiles?: (files: File[]) => void;
  onChoose?: () => void;
  onPath?: (path: string) => void;
  multiple?: boolean;
};

export function FileWell({ label, hint, accept, file, onFiles, onChoose, onPath, multiple }: Props) {
  const [over, setOver] = useState(false);
  const [path, setPath] = useState("");
  const inputId = `file-${label.replace(/[^a-z0-9]+/gi, "-")}`;
  return (
    <div className="col">
      <div
        className={`well ${over ? "over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const files = [...e.dataTransfer.files];
          if (files.length && onFiles) onFiles(files);
        }}
        onClick={() => {
          if (onChoose) {
            onChoose();
            return;
          }
          if (onFiles) {
            document.getElementById(inputId)?.click();
          }
        }}
      >
        <strong>{label}</strong>
        <p>{file?.name || file?.path || hint}</p>
        {onFiles && (
          <input
            type="file"
            accept={accept}
            multiple={multiple}
            style={{ display: "none" }}
            id={inputId}
            onChange={(e) => {
              const files = e.target.files ? [...e.target.files] : [];
              if (files.length) onFiles(files);
            }}
          />
        )}
      </div>
      {onFiles && (
        <div className="actions">
          <button
            className="btn secondary"
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              document.getElementById(inputId)?.click();
            }}
          >
            Browse files
          </button>
        </div>
      )}
      {onChoose && (
        <div className="actions">
          <button className="btn secondary" type="button" onClick={onChoose}>
            Choose on this Mac
          </button>
        </div>
      )}
      {onPath && (
        <label className="field">
          Or paste a path
          <input
            type="text"
            value={path}
            placeholder="/Users/…/deck.key"
            onChange={(e) => setPath(e.target.value)}
            onBlur={() => path.trim() && onPath(path.trim())}
            onKeyDown={(e) => {
              if (e.key === "Enter" && path.trim()) onPath(path.trim());
            }}
          />
        </label>
      )}
    </div>
  );
}
