import type { LayerSpecification, LineLayerSpecification, Map as MapLibreMap } from "maplibre-gl";

const COUNTRY_ID = "boundary_country_z0-4";
const STATE_ID = "boundary_state";
const STATE_LOW_ID = "boundary_state_z1-4";
const PROVINCE_AUTHORED_MIN = 4;
const PROVINCE_AUTHORED_MAX = 5;

const shift = (z: number, offset: number) => Math.min(24, Math.max(0, z + offset));

function findLine(layers: LayerSpecification[], id: string): LineLayerSpecification | null {
  const layer = layers.find((candidate) => candidate.id === id);
  return layer && layer.type === "line" ? layer : null;
}

/** Re-gates the boundaries so whole-country views keep their borders; weights stay vendored. */
export function withLowZoomBoundaries(
  layers: LayerSpecification[],
  zoomOffset = 0,
): LayerSpecification[] {
  const country = findLine(layers, COUNTRY_ID);
  const state = findLine(layers, STATE_ID);
  if (!country || !state) return layers;

  const lowerCountry: LineLayerSpecification = { ...country, minzoom: 0 };
  const lowerState: LineLayerSpecification = {
    id: STATE_LOW_ID,
    type: "line",
    source: state.source,
    "source-layer": state["source-layer"],
    filter: state.filter,
    minzoom: shift(PROVINCE_AUTHORED_MIN, zoomOffset),
    maxzoom: shift(PROVINCE_AUTHORED_MAX, zoomOffset),
    layout: { "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": "rgba(80, 80, 80, 1)",
      "line-opacity": 1,
      "line-width": 1.2,
    },
  };
  const raisedPaint = { ...state.paint };
  delete raisedPaint["line-dasharray"];
  const raisedState: LineLayerSpecification = {
    ...state,
    minzoom: shift(PROVINCE_AUTHORED_MAX, zoomOffset),
    paint: raisedPaint,
  };

  return layers.flatMap((layer) => {
    if (layer.id === COUNTRY_ID) return [lowerCountry];
    if (layer.id === STATE_ID) return [lowerState, raisedState];
    return [layer];
  });
}

/** Converts the authored zoom gate into the preview map's shifted zoom range. */
export function applyBoundaryZoomOffset(map: MapLibreMap, zoomOffset: number): void {
  if (map.getLayer(STATE_LOW_ID)) {
    map.setLayerZoomRange(
      STATE_LOW_ID,
      shift(PROVINCE_AUTHORED_MIN, zoomOffset),
      shift(PROVINCE_AUTHORED_MAX, zoomOffset),
    );
  }
  if (map.getLayer(STATE_ID)) {
    map.setLayerZoomRange(STATE_ID, shift(PROVINCE_AUTHORED_MAX, zoomOffset), 14);
  }
}
