import { useRef, useState } from "react";
import { IconPlus } from "./icons";
import {
  blankRow,
  validateManualRows,
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
const NOTES: Record<ManualMode, string> = {
  slides: `One entry per slide. A name alone is geocoded and zoomed to fit what it is — a country lands at z4.3, a town at z13. New slides are added at the end of the deck. ${LINK_NOTE}`,
  pins: `One entry per pin on the current view. Pins keep this slide's zoom. ${LINK_NOTE}`,
};

export function ManualEntriesForm({ mode, busy, onDone, onCancel }: Props) {
  const [rows, setRows] = useState<ManualRow[]>([blankRow(0)]);
  const [errors, setErrors] = useState<ManualRowError[]>([]);
  const seq = useRef(1);

  function edit(key: string, patch: Partial<ManualRow>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
    setErrors((current) => current.filter((error) => error.key !== key));
  }

  function remove(key: string) {
    setRows((current) => current.filter((row) => row.key !== key));
    setErrors((current) => current.filter((error) => error.key !== key));
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
        const invalid = errors.some((error) => error.key === row.key) || undefined;
        return (
          <div className="maps-manual-row" key={row.key}>
            <input
              type="text"
              value={row.name}
              disabled={busy}
              aria-label={`Name row ${position}`}
              aria-invalid={invalid}
              placeholder="Singapore"
              onChange={(event) => edit(row.key, { name: event.target.value })}
            />
            <input
              type="text"
              value={row.place}
              disabled={busy}
              aria-label={`Place row ${position}`}
              aria-invalid={invalid}
              placeholder="Bedok, Singapore"
              onChange={(event) => edit(row.key, { place: event.target.value })}
            />
            <input
              type="text"
              value={row.url}
              disabled={busy}
              aria-label={`Google Maps link row ${position}`}
              aria-invalid={invalid}
              placeholder="https://www.google.com/maps/…/@1.35,103.8,13z"
              onChange={(event) => edit(row.key, { url: event.target.value })}
            />
            <input
              type="text"
              inputMode="decimal"
              value={row.lat}
              disabled={busy}
              aria-label={`Latitude row ${position}`}
              aria-invalid={invalid}
              placeholder="1.3521"
              onChange={(event) => edit(row.key, { lat: event.target.value })}
            />
            <input
              type="text"
              inputMode="decimal"
              value={row.lon}
              disabled={busy}
              aria-label={`Longitude row ${position}`}
              aria-invalid={invalid}
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
          disabled={busy}
          aria-label="Add row"
          onClick={() => setRows((current) => [...current, blankRow(seq.current++)])}
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
