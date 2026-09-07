const OSM = "© OpenStreetMap contributors";

let scratch: HTMLCanvasElement | null = null;

function scratchCanvas(width: number, height: number): HTMLCanvasElement {
  if (!scratch) scratch = document.createElement("canvas");
  if (scratch.width !== width || scratch.height !== height) {
    scratch.width = width;
    scratch.height = height;
  }
  return scratch;
}

function paintOsmBar(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, height - 18, width, 18);
  ctx.fillStyle = "#fff";
  ctx.font = "11px sans-serif";
  ctx.fillText(OSM, 8, height - 5);
}

export function stampOsmOnCanvas(source: HTMLCanvasElement, mime: string, quality: number): Promise<Blob> {
  const canvas = scratchCanvas(source.width, source.height);
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new Error("2d context unavailable"));
  ctx.drawImage(source, 0, 0);
  paintOsmBar(ctx, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), mime, quality);
    } catch {
      reject(new Error("Map canvas is tainted (CORS). Cannot export."));
    }
  });
}

export function stampOsmCropOnCanvas(
  source: HTMLCanvasElement,
  x: number,
  y: number,
  width: number,
  height: number,
  mime: string,
  quality: number
): Promise<Blob> {
  const canvas = scratchCanvas(width, height);
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new Error("2d context unavailable"));
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(source, x, y, width, height, 0, 0, width, height);
  paintOsmBar(ctx, width, height);
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), mime, quality);
    } catch {
      reject(new Error("Map canvas is tainted (CORS). Cannot export."));
    }
  });
}

export async function stampOsm(blob: Blob): Promise<Blob> {
  const img = await createImageBitmap(blob);
  const canvas = scratchCanvas(img.width, img.height);
  const ctx = canvas.getContext("2d");
  if (!ctx) return blob;
  ctx.drawImage(img, 0, 0);
  paintOsmBar(ctx, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), "image/png");
  });
}
