import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const compositePaperGrain = vi.fn();
vi.mock("../src/maps/watercolourStyle", () => ({
  compositePaperGrain: (...args: unknown[]) => compositePaperGrain(...args),
}));

import { stampOsmCropOnCanvas } from "../src/maps/stampOsm";

function fakeContext() {
  return {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    fillStyle: "",
    font: "",
  } as unknown as CanvasRenderingContext2D;
}

let ctx: ReturnType<typeof fakeContext>;

beforeEach(() => {
  compositePaperGrain.mockClear();
  ctx = fakeContext();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as RenderingContext);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function toBlob(this: HTMLCanvasElement, cb: BlobCallback) {
    cb(new Blob(["fake"], { type: "image/png" }));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("stampOsmCropOnCanvas for the watercolour style", () => {
  it("composites paper grain and skips the attribution bar when stamp is false", async () => {
    const source = document.createElement("canvas");
    await stampOsmCropOnCanvas(source, 0, 0, 100, 100, "image/png", 0.92, false, "watercolour", false);

    expect(compositePaperGrain).toHaveBeenCalledTimes(1);
    expect(ctx.fillText).not.toHaveBeenCalled();
  });

  it("still paints the attribution bar for watercolour when stamp is true", async () => {
    const source = document.createElement("canvas");
    await stampOsmCropOnCanvas(source, 0, 0, 100, 100, "image/png", 0.92, false, "watercolour", true);

    expect(compositePaperGrain).toHaveBeenCalledTimes(1);
    expect(ctx.fillText).toHaveBeenCalled();
  });
});
