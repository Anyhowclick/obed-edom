import type { MapsAudience, MapsCamera, MapsDocument, MapsSlide } from "./types";
import { slideForAudience } from "./types";

export interface ThumbnailGeometry {
  authoredWidth: number;
  surfaceWidth: number;
  crop: unknown;
}

export function thumbnailFingerprint(slideId: string, audience: MapsAudience, view: MapsSlide, geometry: ThumbnailGeometry): string {
  return JSON.stringify({
    id: slideId,
    audience,
    style: view.style,
    camera: view.camera,
    highlights: view.highlights,
    churches: view.churches,
    hiddenLayers: view.hiddenLayers,
    hillshade: view.hillshade,
    isolate: view.isolate ? { mode: view.isolate.mode, strength: view.isolate.strength } : null,
    authoredWidth: geometry.authoredWidth,
    surfaceWidth: geometry.surfaceWidth,
    crop: geometry.crop,
  });
}

export function withSlideCamera(doc: MapsDocument, slideId: string, audience: MapsAudience, camera: MapsCamera): MapsDocument {
  const slides = doc.slides.map((slide) => {
    if (slide.id !== slideId) return slide;
    return audience === "cg" && slide.cg ? { ...slide, cg: { ...slide.cg, camera } } : { ...slide, camera };
  });
  return { ...doc, slides };
}

export function shouldPublishThumb(gate: { frozen: boolean; tokenStillValid: boolean; sameJob: boolean; sameView: boolean }): boolean {
  return !gate.frozen && gate.tokenStillValid && gate.sameJob && gate.sameView;
}

export function shouldReconcileThumb(gate: { frozen: boolean; sameJob: boolean }): boolean {
  return !gate.frozen && gate.sameJob;
}

export function hopPreviewViews(from: MapsSlide, to: MapsSlide, audience: MapsAudience): { during: MapsSlide; landing: MapsSlide } {
  return { during: slideForAudience(from, audience), landing: slideForAudience(to, audience) };
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
