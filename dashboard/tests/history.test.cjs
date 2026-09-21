const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").watercolour;
const { createHistory, push, undo, redo, canUndo, canRedo } = require(path.join(out, "history.js"));

test("push/undo/redo round-trip", () => {
  let h = createHistory(0);
  h = push(h, 1);
  h = push(h, 2);
  assert.equal(h.present, 2);
  h = undo(h);
  assert.equal(h.present, 1);
  h = undo(h);
  assert.equal(h.present, 0);
  assert.equal(canUndo(h), false);
  h = redo(h);
  assert.equal(h.present, 1);
  h = redo(h);
  assert.equal(h.present, 2);
  assert.equal(canRedo(h), false);
});

test("a push after undo clears future", () => {
  let h = createHistory(0);
  h = push(h, 1);
  h = push(h, 2);
  h = undo(h);
  assert.equal(canRedo(h), true);
  h = push(h, 3);
  assert.equal(h.present, 3);
  assert.equal(canRedo(h), false);
  assert.deepEqual(h.past, [0, 1]);
});

test("history is capped at 50 past entries", () => {
  let h = createHistory(0);
  for (let i = 1; i <= 60; i++) h = push(h, i);
  assert.equal(h.past.length, 50);
  assert.equal(h.past[0], 10);
  assert.equal(h.present, 60);
});
