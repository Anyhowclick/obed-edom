const OSM = "© OpenStreetMap contributors";

function paintOsmBar(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, height - 18, width, 18);
  ctx.fillStyle = "#fff";
  ctx.font = "11px sans-serif";
  ctx.fillText(OSM, 8, height - 5);
}

export function stampOsmOnCanvas(source: HTMLCanvasElement, mime: string, quality: number): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = source.width;
  canvas.height = source.height;
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

export async function stampOsm(blob: Blob): Promise<Blob> {
  const img = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = img.width;
  canvas.height = img.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return blob;
  ctx.drawImage(img, 0, 0);
  paintOsmBar(ctx, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((next) => (next ? resolve(next) : reject(new Error("toBlob failed"))), "image/png");
  });
}
