import type { MapsAudience, MapsCamera, MapsDocument } from "./types";

export function withSlideCamera(doc: MapsDocument, slideId: string, audience: MapsAudience, camera: MapsCamera): MapsDocument {
  const slides = doc.slides.map((slide) => {
    if (slide.id !== slideId) return slide;
    return audience === "cg" && slide.cg ? { ...slide, cg: { ...slide.cg, camera } } : { ...slide, camera };
  });
  return { ...doc, slides };
}

export function commitCamera(
  doc: MapsDocument,
  slideId: string,
  audience: MapsAudience,
  camera: MapsCamera,
  gate: { frozen: boolean; previewing: boolean },
): MapsDocument | null {
  if (gate.frozen || gate.previewing) return null;
  return withSlideCamera(doc, slideId, audience, camera);
}
