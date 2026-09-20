const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").dir;
const { statusLabel } = require(path.join(out, "statusLabel.js"));

const FEATURES = ["generate", "dsk", "maps", "resize", "watercolour", "check", "diff"];

const DONE = {
  generate: "Generated",
  dsk: "Generated",
  maps: "Exported",
  resize: "Resized",
  watercolour: "Rendered",
  check: "Checked",
  diff: "Checked",
};

const RUNNING = {
  generate: "Generating…",
  dsk: "Generating…",
  maps: "Exporting…",
  resize: "Resizing…",
  watercolour: "Rendering…",
  check: "Checking…",
  diff: "Checking…",
};

for (const feature of FEATURES) {
  test(`statusLabel(${feature}, done) is "${DONE[feature]}" with tone ok`, () => {
    assert.deepEqual(statusLabel(feature, "done"), { text: DONE[feature], tone: "ok" });
  });
  test(`statusLabel(${feature}, running) is "${RUNNING[feature]}" with tone busy`, () => {
    assert.deepEqual(statusLabel(feature, "running"), { text: RUNNING[feature], tone: "busy" });
  });
}

test("statusLabel(queued) is Queued regardless of feature", () => {
  assert.deepEqual(statusLabel("maps", "queued"), { text: "Queued", tone: "busy" });
});

test("statusLabel(error) is Failed regardless of feature", () => {
  assert.deepEqual(statusLabel("maps", "error"), { text: "Failed", tone: "err" });
});

test("statusLabel falls back to the generic Done/Working… copy for an unknown feature", () => {
  assert.deepEqual(statusLabel("visual", "done"), { text: "Done", tone: "ok" });
  assert.deepEqual(statusLabel("visual", "running"), { text: "Working…", tone: "busy" });
});
