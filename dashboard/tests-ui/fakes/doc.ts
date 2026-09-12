import type { MapsCamera, MapsDocument, MapsSlide } from "../../src/maps/types";
import type { Job } from "../../src/api";

export function makeCamera(overrides: Partial<MapsCamera> = {}): MapsCamera {
  return { lat: 1.3, lon: 103.8, zoom: 12, bearing: 0, pitch: 0, ...overrides };
}

export function makeSlide(overrides: Partial<MapsSlide> = {}): MapsSlide {
  return {
    id: "slide-1",
    title: "Slide 1",
    style: "positron",
    camera: makeCamera(),
    highlights: [],
    churches: [],
    cgShiftX: 0,
    cgShiftY: 0,
    includeSidePanels: false,
    ...overrides,
  };
}

export function makeDoc(overrides: Partial<MapsDocument> = {}): MapsDocument {
  return {
    defaultStyle: "positron",
    crop: "center+cg",
    exportLw: true,
    exportCg: true,
    exportDsk: false,
    hiddenLayers: [],
    cachedCountries: [],
    assets: [],
    slides: [makeSlide()],
    links: [],
    ...overrides,
  };
}

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    kind: "maps",
    feature: "maps",
    status: "done",
    logs: [],
    result: { ...makeDoc(), stateRevision: 1 },
    createdAt: 0,
    updatedAt: 0,
    ...overrides,
  };
}
