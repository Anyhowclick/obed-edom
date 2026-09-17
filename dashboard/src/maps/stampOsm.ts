import { compositePaperGrain } from "./watercolourStyle";
import { creditLine } from "./credits";

let scratch: HTMLCanvasElement | null = null;

function scratchCanvas(width: number, height: number): HTMLCanvasElement {
  if (!scratch) scratch = document.createElement("canvas");
  if (scratch.width !== width || scratch.height !== height) {
    scratch.width = width;
    scratch.height = height;
  }
  return scratch;
}

function paintOsmBar(ctx: CanvasRenderingContext2D, width: number, height: number, terrain = false, styleId?: string): void {
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, height - 18, width, 18);
  ctx.fillStyle = "#fff";
  ctx.font = "11px sans-serif";
  ctx.fillText(creditLine(styleId, terrain), 8, height - 5);
}

export function stampOsmCropOnCanvas(
  source: HTMLCanvasElement,
  x: number,
  y: number,
  width: number,
  height: number,
  mime: string,
  quality: number,
  terrain = false,
  styleId?: string,
  stamp = true
): Promise<Blob> {
  return stampOsmMovieFrame(source, x, y, width, height, width, height, mime, quality, terrain, styleId, stamp);
}

/** Crop `visW×visH` from the map and composite it onto a black `outW×outH` frame.
 * Frame 0 of a centre→FW movie keeps the plate's 3840 viewport; later frames widen. */
export function stampOsmMovieFrame(
  source: HTMLCanvasElement,
  x: number,
  y: number,
  visW: number,
  visH: number,
  outW: number,
  outH: number,
  mime: string,
  quality: number,
  terrain = false,
  styleId?: string,
  stamp = true
): Promise<Blob> {
  const canvas = scratchCanvas(outW, outH);
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new Error("2d context unavailable"));
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, outW, outH);
  const dx = Math.floor((outW - visW) / 2);
  const dy = Math.floor((outH - visH) / 2);
  ctx.drawImage(source, x, y, visW, visH, dx, dy, visW, visH);
  if (styleId === "watercolour") compositePaperGrain(ctx, outW, outH);
  if (stamp) paintOsmBar(ctx, outW, outH, terrain, styleId);
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), mime, quality);
    } catch {
      reject(new Error("Map canvas is tainted (CORS). Cannot export."));
    }
  });
}

export async function stampOsm(blob: Blob, terrain = false, styleId?: string): Promise<Blob> {
  const img = await createImageBitmap(blob);
  const canvas = scratchCanvas(img.width, img.height);
  const ctx = canvas.getContext("2d");
  if (!ctx) return blob;
  ctx.drawImage(img, 0, 0);
  if (styleId === "watercolour") compositePaperGrain(ctx, canvas.width, canvas.height);
  paintOsmBar(ctx, canvas.width, canvas.height, terrain, styleId);
  return new Promise((resolve, reject) => {
    canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), "image/png");
  });
}
