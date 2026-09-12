import { chooseFolder } from "../api";

type Props = {
  value: string;
  onChange: (path: string) => void;
  defaultLabel?: string;
  onError?: (message: string) => void;
};

export function ExportDestinationRow({ value, onChange, defaultLabel, onError }: Props) {
  return (
    <div className="col">
      <strong>Export to</strong>
      <p className="muted">{value || defaultLabel || "output/ (default)"}</p>
      <div className="actions">
        <button
          className="btn secondary"
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
        {value && (
          <button className="btn secondary" type="button" onClick={() => onChange("")}>
            Use default
          </button>
        )}
      </div>
    </div>
  );
}
