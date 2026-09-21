const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").watercolour;
const { floodFill } = require(path.join(out, "floodFill.js"));

function grid(colors) {
  const h = colors.length;
  const w = colors[0].length;
  const rgba = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const [r, g, b] = colors[y][x];
      const offset = (x + y * w) * 4;
      rgba[offset] = r; rgba[offset + 1] = g; rgba[offset + 2] = b; rgba[offset + 3] = 255;
    }
  }
  return { rgba, w, h };
}

test("flood fill covers only the contiguous same-colour region at zero tolerance", () => {
  const black = [0, 0, 0];
  const white = [255, 255, 255];
  const { rgba, w, h } = grid([
    [black, black, white, white],
    [black, black, white, white],
    [white, white, black, black],
    [white, white, black, black],
  ]);
  const filled = floodFill(rgba, w, h, 0, 0, 0);
  assert.deepEqual(Array.from(filled), [
    1, 1, 0, 0,
    1, 1, 0, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
  ]);
});

test("higher tolerance bridges a near-colour neighbour", () => {
  const black = [0, 0, 0];
  const near = [10, 10, 10];
  const white = [255, 255, 255];
  const { rgba, w, h } = grid([
    [black, near, white],
    [black, near, white],
  ]);
  const strict = floodFill(rgba, w, h, 0, 0, 0);
  assert.deepEqual(Array.from(strict), [1, 0, 0, 1, 0, 0]);
  const loose = floodFill(rgba, w, h, 0, 0, 10);
  assert.deepEqual(Array.from(loose), [1, 1, 0, 1, 1, 0]);
});

test("diagonal-only neighbour is not filled (4-connected)", () => {
  const black = [0, 0, 0];
  const white = [255, 255, 255];
  const { rgba, w, h } = grid([
    [black, white],
    [white, black],
  ]);
  const filled = floodFill(rgba, w, h, 0, 0, 0);
  assert.deepEqual(Array.from(filled), [1, 0, 0, 0]);
});
