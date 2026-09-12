import { chooseFolder } from "../api";

type Props = {
  value: string;
  onChange: (path: string) => void;
  defaultLabel?: string;
  onError?: (message: string) => void;
  /** Freeze the row read-only, e.g. between a propose and its matching apply. */
  disabled?: boolean;
  /** Render without the "Export to" heading/col wrapper, for sharing a row with another button. */
  inline?: boolean;
};

export function ExportDestinationRow({ value, onChange, defaultLabel, onError, disabled, inline }: Props) {
  const destination = value || defaultLabel || "output/ (default)";

  if (disabled) {
    return inline ? (
      <span className="muted">{destination} · Locked to this destination until applied.</span>
    ) : (
      <div className="col">
        <strong>Export to</strong>
        <p className="muted">{destination}</p>
        <p className="muted">Locked to this destination until applied.</p>
      </div>
    );
  }

  const buttons = (
    <>
      <button
        className={inline ? "btn collab" : "btn secondary"}
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
    </>
  );

  if (inline) {
    return (
      <>
        <span className="muted" title={destination}>{destination}</span>
        {buttons}
      </>
    );
  }

  return (
    <div className="col">
      <strong>Export to</strong>
      <p className="muted">{destination}</p>
      <div className="actions">{buttons}</div>
    </div>
  );
}
