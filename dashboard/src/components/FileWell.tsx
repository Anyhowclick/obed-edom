import { useState, type DragEvent } from "react";
import { resolveDroppedFolder, resolveDroppedKeynote } from "../dropPath";

type Props = {
  label: string;
  hint: string;
  accept?: string;
  file?: { path?: string; name: string } | null;
  onFiles?: (files: File[]) => void;
  onChoose?: () => void;
  onPath?: (path: string) => void;
  onError?: (message: string) => void;
  onClear?: () => void;
  multiple?: boolean;
  folder?: boolean;
  tone?: "keynote" | "document";
};

export function FileWell({
  label,
  hint,
  accept,
  file,
  onFiles,
  onChoose,
  onPath,
  onError,
  onClear,
  multiple,
  folder,
  tone,
}: Props) {
  const [over, setOver] = useState(false);
  const inputId = `file-${label.replace(/[^a-z0-9]+/gi, "-")}`;

  async function handleDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (onPath) {
      const resolved = folder ? await resolveDroppedFolder(e.dataTransfer) : await resolveDroppedKeynote(e.dataTransfer);
      if ("path" in resolved) {
        onPath(resolved.path);
        return;
      }
      onError?.(resolved.error);
      return;
    }
    const files = [...e.dataTransfer.files];
    if (files.length && onFiles) onFiles(files);
  }

  return (
    <div className={`col${tone ? ` well-tone-${tone}` : ""}`}>
      <div
        className={`well ${over ? "over" : ""}${tone ? ` ${tone}` : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={handleDrop}
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
          {onClear && file && (
            <button
              className="btn secondary"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onClear();
              }}
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}
