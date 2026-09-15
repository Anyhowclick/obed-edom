import { chooseFolder } from "../api";

type Props = {
  value: string;
  onChange: (path: string) => void;
  defaultLabel?: string;
  onError?: (message: string) => void;
  /** Render as direct members of the caller's `.actions` row, for sharing it with another button. */
  inline?: boolean;
};

export function ExportDestinationRow({ value, onChange, defaultLabel, onError, inline }: Props) {
  const destination = value || defaultLabel || "output/ (default)";

  return (
    <div className={`export-dest${inline ? " inline" : ""}`}>
      {!inline && <span className="export-dest-label">Export to</span>}
      <button
        className="btn collab"
        type="button"
        onClick={async () => {
          try {
            const chosen = await chooseFolder("Choose an export folder");
            onChange(chosen.path);
          } catch (err) {
            onError?.(err instanceof Error ? err.message : String(err));
          }
        }}
      >
        Export to…
      </button>
      <span className="export-dest-path" title={destination}>
        {destination}
      </span>
      {value && (
        <button className="btn secondary" type="button" onClick={() => onChange("")}>
          Use default
        </button>
      )}
    </div>
  );
}
