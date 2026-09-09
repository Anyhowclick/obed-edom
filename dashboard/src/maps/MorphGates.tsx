import { admin0Name } from "./overlays";
import { STYLE_SWATCHES } from "./styles";
import {
  LAYER_FILTERS,
  MORPH_MAX_DBEARING,
  MORPH_MAX_DZOOM,
  MORPH_MAX_PITCH,
  MORPH_MAX_PLATE_PX,
  appearanceMismatch,
  morphPlatePx,
  bearingDelta,
  captureWidth,
  slideHiddenLayers,
  softMovieFields,
  type MapsLayerFilterId,
  type MapsSlide,
} from "./types";

type Gate = { id: string; label: string; ok: boolean; detail: string; tip: string };

function WarnMark({ className = "" }: { className?: string }) {
  return (
    <span className={`morph-mark soft ${className}`.trim()} aria-hidden="true">
      <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <path d="M8 1.6 14.8 13.6H1.2Z" />
        <path d="M8 6.2v3.6" strokeLinecap="round" />
        <circle cx="8" cy="12" r="0.9" fill="currentColor" stroke="none" />
      </svg>
    </span>
  );
}

function styleLabel(id: MapsSlide["style"]): string {
  return STYLE_SWATCHES.find((item) => item.id === id)?.label || id;
}

function countriesLabel(codes: string[]): string {
  if (!codes.length) return "none";
  return codes.map((code) => admin0Name(code)).join(", ");
}

function layersLabel(ids: MapsLayerFilterId[], relief: boolean): string {
  const base = ids.length ? ids.map((id) => LAYER_FILTERS.find((item) => item.id === id)?.label || id).join(", ") : "none hidden";
  return relief ? `${base} · relief on` : base;
}

function isolateLabel(s: MapsSlide): string {
  return s.isolate ? `${Math.round(s.isolate.strength * 100)}%` : "off";
}

function fmtDeg(n: number): string {
  const rounded = Math.abs(n) < 0.05 ? 0 : n;
  return `${rounded.toFixed(0)}°`;
}

export function morphGateList(from: MapsSlide, to: MapsSlide): Gate[] {
  const mismatch = new Set(appearanceMismatch(from, to));
  const fromHi = [...from.highlights].map((h) => h.toUpperCase()).sort();
  const toHi = [...to.highlights].map((h) => h.toUpperCase()).sort();
  const fromLayers = slideHiddenLayers(from).sort();
  const toLayers = slideHiddenLayers(to).sort();
  const fromRelief = from.hillshade === true;
  const toRelief = to.hillshade === true;
  const pitch = Math.max(Math.abs(from.camera.pitch), Math.abs(to.camera.pitch));
  const dBearing = bearingDelta(from.camera.bearing, to.camera.bearing);
  const dZoom = Math.abs(from.camera.zoom - to.camera.zoom);
  const threeD = from.style === "buildings3d" || to.style === "buildings3d" || pitch > MORPH_MAX_PITCH;
  const plate = morphPlatePx(from.camera, to.camera, captureWidth(from), captureWidth(to));
  const plateOk = plate != null && plate.w <= MORPH_MAX_PLATE_PX && plate.h <= MORPH_MAX_PLATE_PX;
  let threeDDetail = "flat";
  if (from.style === "buildings3d" || to.style === "buildings3d") threeDDetail = "3D buildings";
  else if (pitch > MORPH_MAX_PITCH) threeDDetail = `pitch ${fmtDeg(pitch)}`;
  const layersSame = !mismatch.has("hiddenLayers") && !mismatch.has("hillshade");
  return [
    {
      id: "style",
      label: "Same map style",
      ok: !mismatch.has("style"),
      detail: from.style === to.style ? styleLabel(from.style) : `${styleLabel(from.style)} → ${styleLabel(to.style)}`,
      tip: "Positron, Liberty, 3D, and the rest must match on both shots.",
    },
    {
      id: "countries",
      label: "Same region highlights",
      ok: !mismatch.has("highlights"),
      detail:
        fromHi.join(",") === toHi.join(",")
          ? countriesLabel(fromHi)
          : `${countriesLabel(fromHi)} → ${countriesLabel(toHi)}`,
      tip: "Highlighted regions must match on both shots. Panning part of the map off-screen is fine.",
    },
    {
      id: "isolate",
      label: "Same isolate",
      ok: !mismatch.has("isolate"),
      detail: isolateLabel(from) === isolateLabel(to) ? isolateLabel(from) : `${isolateLabel(from)} → ${isolateLabel(to)}`,
      tip: "Isolate country (darken) must match on both shots.",
    },
    {
      id: "layers",
      label: "Same layers",
      ok: layersSame,
      detail: layersSame
        ? layersLabel(fromLayers, fromRelief)
        : `${layersLabel(fromLayers, fromRelief)} → ${layersLabel(toLayers, toRelief)}`,
      tip: "Hidden map layers (roads, POIs, labels…) and relief shading must match on both shots.",
    },
    {
      id: "3d",
      label: "No 3D",
      ok: !threeD,
      detail: threeDDetail,
      tip: "3D buildings or camera pitch need a Movie fly, not Magic Move.",
    },
    {
      id: "bearing",
      label: "Same rotation",
      ok: dBearing <= MORPH_MAX_DBEARING,
      detail:
        dBearing <= MORPH_MAX_DBEARING
          ? fmtDeg(from.camera.bearing)
          : `${fmtDeg(from.camera.bearing)} → ${fmtDeg(to.camera.bearing)} · Δ ${fmtDeg(dBearing)}`,
      tip: "Both cameras may be rotated, but their bearings must match for one shared plate.",
    },
    {
      id: "zoom",
      label: `Zoom Δ ≤ ${MORPH_MAX_DZOOM}`,
      ok: dZoom <= MORPH_MAX_DZOOM,
      detail: `Δ ${dZoom.toFixed(1)}`,
      tip: `The authoring limit is Δ${MORPH_MAX_DZOOM}; the 8192px plate-size check may impose a lower limit for wider outputs.`,
    },
    {
      id: "plate",
      label: "Fits 1 image",
      ok: plateOk,
      detail: plate ? `${Math.round(plate.w)} × ${Math.round(plate.h)}` : "too small",
      tip: "Keynote Magic Move is one PNG that covers both cameras. Over 8192px becomes Movie.",
    },
  ];
}

function gateHint(gates: Gate[]): string {
  if (gates.every((gate) => gate.ok)) return "Keynote can pan this hop on one plate — land leaving the frame is fine.";
  const failed = gates.filter((gate) => !gate.ok);
  if (failed.some((gate) => gate.id === "style" || gate.id === "countries" || gate.id === "layers")) {
    return "Map style, region highlights, or layers changed — that cannot Magic Move. Use Cut or Dissolve.";
  }
  if (failed.every((gate) => gate.id === "plate")) {
    return "The two cameras do not fit on one 8192px plate — Export will use Movie.";
  }
  return "Pitch, a rotation change, 3D, or an oversized zoom jump needs a Movie fly.";
}

export function MorphGates({ from, to }: { from: MapsSlide; to: MapsSlide }) {
  const gates = morphGateList(from, to);
  const allOk = gates.every((gate) => gate.ok);
  return (
    <div
      className={`morph-gates${allOk ? " clear" : " blocked"}`}
      role="status"
      aria-label={allOk ? "Magic Move is clear" : "Magic Move is blocked"}
    >
      <div className="morph-gates-head">
        <span className={`morph-mark ${allOk ? "ok" : "bad"}`} aria-hidden="true">
          {allOk ? "✓" : "✕"}
        </span>
        Magic Move
        <span className="morph-gates-state">{allOk ? "Clear" : "Blocked"}</span>
      </div>
      <ul className="morph-gate-list">
        {gates.map((gate) => (
          <li key={gate.id} className={`morph-gate${gate.ok ? " ok" : " bad"}`} title={gate.tip}>
            <span className={`morph-mark ${gate.ok ? "ok" : "bad"}`} aria-hidden="true">
              {gate.ok ? "✓" : "✕"}
            </span>
            <span className="morph-gate-label">
              <span className="morph-sr">{gate.ok ? "Pass: " : "Fail: "}</span>
              {gate.label}
            </span>
            <span className="morph-gate-detail">{gate.detail}</span>
          </li>
        ))}
      </ul>
      <p className="morph-gates-hint">{gateHint(gates)}</p>
    </div>
  );
}

export function MovieAppearanceGate({
  from,
  to,
  crossAudience,
  disabled,
  onMatch,
}: {
  from: MapsSlide;
  to: MapsSlide;
  crossAudience: boolean;
  disabled: boolean;
  onMatch: () => void;
}) {
  const destIsolated = !!(to.isolate && to.highlights.length);
  const sourceIsolated = !!from.isolate && !destIsolated;
  const softFields = softMovieFields(from, to);
  const allRows = morphGateList(from, to).filter(
    (gate) => (gate.id === "style" || gate.id === "countries" || gate.id === "isolate" || gate.id === "layers") && !gate.ok,
  );
  const isSoftRow = (gate: Gate) =>
    (gate.id === "countries" && softFields.has("highlights")) || (gate.id === "isolate" && softFields.has("isolate"));
  const hardRows = allRows.filter((gate) => !isSoftRow(gate));
  const softRows = allRows.filter(isSoftRow);
  const hasHard = hardRows.length > 0 || crossAudience;

  if (!hasHard && !softRows.length && !destIsolated && !sourceIsolated) return null;

  const showMatchButton = hardRows.some((gate) => gate.id === "layers");
  return (
    <div className="morph-gates warn" role="status" aria-label={hasHard ? "Movie appearance mismatch" : "Movie appearance heads-up"}>
      <div className="morph-gates-head">
        {hasHard ? (
          <span className="morph-mark bad" aria-hidden="true">
            ✕
          </span>
        ) : (
          <WarnMark />
        )}
        Movie appearance
        <span className="morph-gates-state">{hasHard ? "Mismatch" : "Heads-up"}</span>
      </div>
      {(hardRows.length > 0 || softRows.length > 0) && (
        <ul className="morph-gate-list">
          {hardRows.map((gate) => (
            <li key={gate.id} className="morph-gate bad" title={gate.tip}>
              <span className="morph-mark bad" aria-hidden="true">
                ✕
              </span>
              <span className="morph-gate-label">
                <span className="morph-sr">Fail: </span>
                {gate.label}
              </span>
              <span className="morph-gate-detail">{gate.detail}</span>
            </li>
          ))}
          {softRows.map((gate) => (
            <li key={gate.id} className="morph-gate soft" title={gate.tip}>
              <WarnMark />
              <span className="morph-gate-label">
                <span className="morph-sr">Heads-up: </span>
                {gate.label}
              </span>
              <span className="morph-gate-detail">{gate.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {hasHard && (
        <p className="morph-gates-hint">
          The fly renders entirely in the source shot's appearance, so these differences pop at the cut to the next
          slide. Style, highlight, or isolate mismatches are not auto-copied — use "Reset hop" to re-suggest a hop kind instead.
        </p>
      )}
      {crossAudience && (
        <p className="morph-gates-hint">The other audience also mismatches on this hop and must be fixed by switching audiences.</p>
      )}
      {destIsolated && <p className="morph-gates-hint">Lands on the plain view, then dissolves into the isolated view.</p>}
      {sourceIsolated && <p className="morph-gates-hint">The fly stays darkened, then cuts to the plain view.</p>}
      {showMatchButton && (
        <button
          type="button"
          className="btn secondary"
          disabled={disabled}
          onClick={onMatch}
          title={`Copy hidden layers and relief from "${to.title}" onto "${from.title}".`}
        >
          Match layers to destination
        </button>
      )}
    </div>
  );
}
