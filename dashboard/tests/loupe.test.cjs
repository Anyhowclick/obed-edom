const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").watercolour;
const { loupeCorner } = require(path.join(out, "loupe.js"));

const W = 400;
const H = 200;

test("cursor in each quadrant docks the loupe to the opposite corner", () => {
  assert.equal(loupeCorner(10, 10, W, H), "br");
  assert.equal(loupeCorner(W - 10, 10, W, H), "bl");
  assert.equal(loupeCorner(10, H - 10, W, H), "tr");
  assert.equal(loupeCorner(W - 10, H - 10, W, H), "tl");
});

test("exact centre ties toward the top-left quadrant's opposite corner", () => {
  assert.equal(loupeCorner(W / 2, H / 2, W, H), "br");
});
