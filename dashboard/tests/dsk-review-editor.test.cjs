const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").dsk;
const { contiguousCategories, dskEditorReducer, editorState, effectiveFrame, editableReview } = require(path.join(out, "decisions.js"));

function review() {
  return {
    schemaVersion: 2, revision: 4, source: { fingerprint: "digest" }, canvas: { width: 1920, height: 1080 }, safeArea: { left: 43, right: 1877, bottom: 1065 },
    defaults: { viewport: { width: 935, height: 263, aspectLocked: true }, alignment: "centre" },
    compositions: [
      { id: "slide:1", sourceSlides: [1], layoutSlide: 1, category: "movie", capabilities: { mask: true, videoOnly: true }, warnings: [], media: [{ occurrenceId: "one", assetId: "one", kind: "movie", sourceSlide: 1, sourceItem: { kind: "movie", kindIndex: 0, archiveId: "one" }, sourceModes: ["lw", "fw"], slot: { x: 0, y: 0, width: 1, height: 1 } }], previewLayers: [], decision: { include: true, alignment: "inherit", viewport: null, source: "lw", contentMode: "full", masks: {} } },
      { id: "slide:2", sourceSlides: [2], layoutSlide: 2, category: "mixed", mediaLayout: "stacked", capabilities: { mask: true }, warnings: [], media: [], previewLayers: [], decision: { include: true, alignment: "centre", viewport: null, source: "lw", contentMode: "full", masks: {} } },
      { id: "slide:3", sourceSlides: [3], layoutSlide: 3, category: "movie", capabilities: {}, warnings: [], media: [], previewLayers: [], decision: { include: true, alignment: "inherit", viewport: null, source: "lw", contentMode: "full", masks: {} } },
    ],
  };
}

test("v2 selector preserves source order and repeats contiguous category headings", () => {
  const groups = contiguousCategories(review().compositions);
  assert.deepEqual(groups.map((group) => group.label), ["Movie", "Mixed", "Movie"]);
});

test("global defaults flow through inherited composition and a reset restores inheritance", () => {
  let state = editorState(review());
  state = dskEditorReducer(state, { type: "defaults", viewport: { width: 1000 } });
  assert.equal(effectiveFrame(state).width, 1000);
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { width: 800 } });
  assert.equal(effectiveFrame(state).width, 800);
  state = dskEditorReducer(state, { type: "resetViewport", id: "slide:1" });
  assert.equal(effectiveFrame(state).width, 1000);
});

test("v2 serialization sends only editable decisions and clamps mask edits", () => {
  let state = editorState(review());
  state = dskEditorReducer(state, { type: "mask", id: "slide:1", occurrenceId: "one", mask: { zoom: 0, panX: 5, panY: -5 } });
  const payload = editableReview(state);
  assert.deepEqual(Object.keys(payload), ["schemaVersion", "sourceFingerprint", "defaults", "decisions"]);
  assert.deepEqual(payload.decisions[0].masks.one, { zoom: 1, panX: 1, panY: -1 });
  assert.equal("media" in payload.decisions[0], false);
});

test("locked dimensions retain their original ratio across incremental typing", () => {
  let state = editorState(review());
  state = dskEditorReducer(state, { type: "defaults", viewport: { width: 9 } });
  state = dskEditorReducer(state, { type: "defaults", viewport: { width: 93 } });
  state = dskEditorReducer(state, { type: "defaults", viewport: { width: 935 } });
  assert.deepEqual(state.review.defaults.viewport, { width: 935, height: 263, aspectLocked: true });
});

test("reset restores the inherited ratio and safe-area clamping preserves it", () => {
  let state = editorState(review());
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { aspectLocked: false, width: 800, height: 600 } });
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { aspectLocked: true } });
  state = dskEditorReducer(state, { type: "resetViewport", id: "slide:1" });
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { width: 5000 } });
  const viewport = state.review.compositions[0].decision.viewport;
  assert.equal(viewport.width, 1834);
  assert.ok(Math.abs(viewport.width / viewport.height - 935 / 263) < 0.01);
});

test("a new override keeps the latest inherited ratio on later edits", () => {
  let state = editorState(review());
  state = dskEditorReducer(state, { type: "defaults", viewport: { aspectLocked: false, width: 1000, height: 500 } });
  state = dskEditorReducer(state, { type: "defaults", viewport: { aspectLocked: true } });
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { width: 800 } });
  state = dskEditorReducer(state, { type: "viewport", id: "slide:1", viewport: { width: 600 } });
  assert.deepEqual(state.review.compositions[0].decision.viewport, { width: 600, height: 300, aspectLocked: true });
});
