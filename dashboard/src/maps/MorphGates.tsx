import { admin0Name } from "./overlays";
import { STYLE_SWATCHES } from "./styles";
import {
  DEFAULT_HIDDEN_LAYERS,
  LAYER_FILTERS,
  MORPH_MAX_DBEARING,
  MORPH_MAX_DZOOM,
  MORPH_MAX_PITCH,
  MORPH_MAX_PLATE_PX,
  morphPlatePx,
  bearingDelta,
  captureWidth,
  type MapsLayerFilterId,
  type MapsSlide,
} from "./types";

type Gate = { id: string; label: string; ok: boolean; detail: string; tip: string };

function styleLabel(id: MapsSlide["style"]): string {
  return STYLE_SWATCHES.find((item) => item.id === id)?.label || id;
}

function countriesLabel(codes: string[]): string {
  if (!codes.length) return "none";
  return codes.map((code) => admin0Name(code)).join(", ");
}

function layersLabel(ids: MapsLayerFilterId[]): string {
  if (!ids.length) return "none hidden";
  return ids.map((id) => LAYER_FILTERS.find((item) => item.id === id)?.label || id).join(", ");
}

function fmtDeg(n: number): string {
  const rounded = Math.abs(n) < 0.05 ? 0 : n;
  return `${rounded.toFixed(0)}°`;
}

export function morphGateList(from: MapsSlide, to: MapsSlide): Gate[] {
  const fromHi = [...from.highlights].map((h) => h.toUpperCase()).sort();
  const toHi = [...to.highlights].map((h) => h.toUpperCase()).sort();
  const fromLayers = [...(from.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS)].sort();
  const toLayers = [...(to.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS)].sort();
  const pitch = Math.max(Math.abs(from.camera.pitch), Math.abs(to.camera.pitch));
  const dBearing = bearingDelta(from.camera.bearing, to.camera.bearing);
  const dZoom = Math.abs(from.camera.zoom - to.camera.zoom);
  const threeD = from.style === "buildings3d" || to.style === "buildings3d" || pitch > MORPH_MAX_PITCH;
  const plate = morphPlatePx(from.camera, to.camera, captureWidth(from), captureWidth(to));
  const plateOk = plate != null && plate.w <= MORPH_MAX_PLATE_PX && plate.h <= MORPH_MAX_PLATE_PX;
  let threeDDetail = "flat";
  if (from.style === "buildings3d" || to.style === "buildings3d") threeDDetail = "3D buildings";
  else if (pitch > MORPH_MAX_PITCH) threeDDetail = `pitch ${fmtDeg(pitch)}`;
  return [
    {
      id: "style",
      label: "Same map style",
      ok: from.style === to.style,
      detail: from.style === to.style ? styleLabel(from.style) : `${styleLabel(from.style)} → ${styleLabel(to.style)}`,
      tip: "Positron, Liberty, 3D, and the rest must match on both shots.",
    },
    {
      id: "countries",
      label: "Same region highlights",
      ok: fromHi.join(",") === toHi.join(","),
      detail:
        fromHi.join(",") === toHi.join(",")
          ? countriesLabel(fromHi)
          : `${countriesLabel(fromHi)} → ${countriesLabel(toHi)}`,
      tip: "Highlighted regions must match on both shots. Panning part of the map off-screen is fine.",
    },
    {
      id: "layers",
      label: "Same layers",
      ok: fromLayers.join(",") === toLayers.join(","),
      detail:
        fromLayers.join(",") === toLayers.join(",")
          ? layersLabel(fromLayers)
          : `${layersLabel(fromLayers)} → ${layersLabel(toLayers)}`,
      tip: "Hidden map layers (roads, POIs, labels…) must match on both shots.",
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
