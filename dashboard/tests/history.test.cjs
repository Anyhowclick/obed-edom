const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "wash-history-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/watercolour/history.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
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
