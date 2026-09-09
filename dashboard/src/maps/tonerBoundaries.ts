import type { LayerSpecification, LineLayerSpecification } from "maplibre-gl";

const COUNTRY_ID = "boundary_country_z0-4";
const STATE_ID = "boundary_state";
const STATE_LOW_ID = "boundary_state_z1-4";

function findLine(layers: LayerSpecification[], id: string): LineLayerSpecification | null {
  const layer = layers.find((candidate) => candidate.id === id);
  return layer && layer.type === "line" ? layer : null;
}

/** Re-gates the boundaries so whole-country views keep their borders; weights stay vendored. */
export function withLowZoomBoundaries(layers: LayerSpecification[]): LayerSpecification[] {
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
    minzoom: 1,
    maxzoom: 5,
    layout: { "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": "rgba(0, 0, 0, 1)",
      "line-dasharray": [2, 2],
      "line-opacity": 1,
      "line-width": 1.2,
    },
  };
  const raisedState: LineLayerSpecification = { ...state, minzoom: 5 };

  return layers.flatMap((layer) => {
    if (layer.id === COUNTRY_ID) return [lowerCountry];
    if (layer.id === STATE_ID) return [lowerState, raisedState];
    return [layer];
  });
}
