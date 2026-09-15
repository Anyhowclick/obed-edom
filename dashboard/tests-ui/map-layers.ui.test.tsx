import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_HIDDEN_LAYERS } from "../src/maps/types";
import { filterForLayer } from "../src/maps/layers";
import { makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { renderMapsTab } from "./renderMapsTab";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("filterForLayer water names", () => {
  it("splits water body names from place labels", () => {
    expect(filterForLayer({ id: "water_name_point_label", type: "symbol", "source-layer": "water_name" })).toBe("waternames");
    expect(filterForLayer({ id: "water_name_ocean", type: "symbol", "source-layer": "water_name" })).toBe("waternames");
    expect(filterForLayer({ id: "waterway_line_label", type: "symbol", "source-layer": "waterway" })).toBe("waternames");
    expect(filterForLayer({ id: "waterway", type: "line", "source-layer": "waterway" })).toBeNull();
    expect(filterForLayer({ id: "water", type: "fill", "source-layer": "water" })).toBeNull();
    expect(filterForLayer({ id: "label_city", type: "symbol", "source-layer": "place" })).toBe("labels");
  });
});

describe("Water names map layer", () => {
  it("is a toggle independent of Place labels, hidden by default", async () => {
    await renderMapsTab({
      job: makeJob({
        result: {
          ...makeDoc({
            hiddenLayers: [...DEFAULT_HIDDEN_LAYERS],
            slides: [makeSlide({ hiddenLayers: [...DEFAULT_HIDDEN_LAYERS] })],
          }),
          stateRevision: 1,
        },
      }),
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Map layers/ }));
    });

    const water = screen.getByRole("checkbox", { name: "Water names" });
    const places = screen.getByRole("checkbox", { name: "Place labels" });
    expect(water).not.toBeChecked();
    expect(places).not.toBeChecked();

    await act(async () => {
      fireEvent.click(water);
    });
    expect(water).toBeChecked();
    expect(places).not.toBeChecked();
  });
});
