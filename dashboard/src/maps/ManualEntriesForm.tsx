import { useEffect, useRef, useState } from "react";
import { IconPlus } from "./icons";
import {
  blankRow,
  validateManualRows,
  MANUAL_MAX_ROWS,
  type ManualMode,
  type ManualPinKind,
  type ManualRow,
  type ManualRowError,
  type MapsBootstrapRow,
} from "./manualRows";

type Props = {
  mode: ManualMode;
  busy: boolean;
  onDone: (payload: MapsBootstrapRow[]) => void;
  onCancel: () => void;
};

const LINK_NOTE =
  "A Google Maps link is only read when it contains @lat,lng (the full desktop URL) — shortened maps.app.goo.gl links are not.";
const SKIP_NOTE = "Blank rows are skipped.";
const NOTES: Record<ManualMode, string> = {
  slides: `One entry per slide. A name alone is geocoded and zoomed to fit what it is — a country lands at z4.3, a town at z13. New slides are added at the end of the deck. ${LINK_NOTE} ${SKIP_NOTE}`,
  pins: `One entry per pin on the current view. Pins keep this slide's zoom. ${LINK_NOTE} A pin still needs a name, a place or coordinates of its own. ${SKIP_NOTE}`,
};

export function ManualEntriesForm({ mode, busy, onDone, onCancel }: Props) {
  const [rows, setRows] = useState<ManualRow[]>([blankRow(0)]);
  const [errors, setErrors] = useState<ManualRowError[]>([]);
  const seq = useRef(1);
  const nameInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const pendingFocus = useRef<string | null>(null);

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    nameInputs.current[key]?.focus();
  }, [rows]);

  function edit(key: string, patch: Partial<ManualRow>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
    setErrors((current) => current.filter((error) => error.key !== key));
  }

  function add() {
    const row = blankRow(seq.current++);
    pendingFocus.current = row.key;
    setRows((current) => [...current, row]);
    setErrors([]);
  }

  function remove(key: string) {
    setRows((current) => current.filter((row) => row.key !== key));
    setErrors([]);
  }

  function done() {
    const checked = validateManualRows(rows, mode);
    setErrors(checked.errors);
    if (!checked.errors.length) onDone(checked.payload);
  }

  return (
    <div
      className={`maps-manual maps-manual-${mode}`}
      role="group"
      aria-label={mode === "slides" ? "Add slides manually" : "Add pins manually"}
    >
      <div className="cap">{mode === "slides" ? "Add slides manually" : "Add pins to this view manually"}</div>
      <p className="note">{NOTES[mode]}</p>
      <div className="maps-manual-head">
        <span>Name</span>
        <span>Place</span>
        <span>Google Maps link</span>
        <span>Lat</span>
        <span>Lon</span>
        {mode === "pins" && <span>Kind</span>}
        <span />
      </div>
      {rows.map((row, index) => {
        const position = index + 1;
        const failed = errors.find((error) => error.key === row.key)?.field;
        return (
          <div className="maps-manual-row" key={row.key}>
            <input
              type="text"
              value={row.name}
              disabled={busy}
              autoFocus={index === 0}
              ref={(el) => {
                nameInputs.current[row.key] = el;
              }}
              aria-label={`Name row ${position}`}
              aria-invalid={failed === "name" || undefined}
              placeholder="Singapore"
              onChange={(event) => edit(row.key, { name: event.target.value })}
            />
            <input
              type="text"
              value={row.place}
              disabled={busy}
              aria-label={`Place row ${position}`}
              aria-invalid={failed === "place" || undefined}
              placeholder="Bedok, Singapore"
              onChange={(event) => edit(row.key, { place: event.target.value })}
            />
            <input
              type="text"
              value={row.url}
              disabled={busy}
              aria-label={`Google Maps link row ${position}`}
              placeholder="https://www.google.com/maps/…/@1.35,103.8,13z"
              onChange={(event) => edit(row.key, { url: event.target.value })}
            />
            <input
              type="text"
              inputMode="decimal"
              value={row.lat}
              disabled={busy}
              aria-label={`Latitude row ${position}`}
              aria-invalid={failed === "lat" || undefined}
              placeholder="1.3521"
              onChange={(event) => edit(row.key, { lat: event.target.value })}
            />
            <input
              type="text"
              inputMode="decimal"
              value={row.lon}
              disabled={busy}
              aria-label={`Longitude row ${position}`}
              aria-invalid={failed === "lon" || undefined}
              placeholder="103.8198"
              onChange={(event) => edit(row.key, { lon: event.target.value })}
            />
            {mode === "pins" && (
              <select
                value={row.kind}
                disabled={busy}
                aria-label={`Kind row ${position}`}
                onChange={(event) => edit(row.key, { kind: event.target.value as ManualPinKind })}
              >
                <option value="dropPin">Drop pin</option>
                <option value="dot">Dot</option>
              </select>
            )}
            <button
              className="btn secondary icon-btn"
              type="button"
              disabled={busy || rows.length < 2}
              aria-label={`Remove row ${position}`}
              title="Remove row"
              onClick={() => remove(row.key)}
            >
              ×
            </button>
          </div>
        );
      })}
      {errors.length > 0 && (
        <div className="maps-manual-errors" role="alert">
          {errors.map((error) => (
            <p key={error.key || "all"}>{error.message}</p>
          ))}
        </div>
      )}
      <div className="maps-manual-actions">
        <button
          className="btn secondary"
          type="button"
          disabled={busy || rows.length >= MANUAL_MAX_ROWS}
          aria-label="Add row"
          title={`Up to ${MANUAL_MAX_ROWS} entries per batch`}
          onClick={add}
        >
          <IconPlus />
          Add row
        </button>
        <span className="spacer" />
        <button className="btn secondary" type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button className="btn" type="button" disabled={busy} onClick={done}>
          Done
        </button>
      </div>
    </div>
  );
}
