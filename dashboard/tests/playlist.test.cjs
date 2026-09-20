const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").dir;
const { MAX_COMBINED_RIGHTS, combineNext, canCombineNext } = require(path.join(out, "playlist.js"));

function slotsFor(rightCount) {
  const slots = [{ leftIndex: 0, rightIndex: 0, rightIndexes: [0] }];
  for (let i = 1; i <= rightCount; i++) {
    slots.push({ leftIndex: null, rightIndex: i, rightIndexes: [i] });
  }
  return slots;
}

test("combineNext folds DSK slides into one row up to MAX_COMBINED_RIGHTS", () => {
  assert.equal(MAX_COMBINED_RIGHTS, 5);
  let slots = slotsFor(MAX_COMBINED_RIGHTS - 1);
  for (let step = 0; step < MAX_COMBINED_RIGHTS - 1; step++) {
    assert.equal(canCombineNext(slots, 0), true);
    slots = combineNext(slots, 0);
  }
  assert.deepEqual(slots[0].rightIndexes, [0, 1, 2, 3, 4]);
});

test("combineNext refuses to exceed MAX_COMBINED_RIGHTS", () => {
  const full = { leftIndex: 0, rightIndex: 0, rightIndexes: [0, 1, 2, 3, 4] };
  const next = { leftIndex: null, rightIndex: 5, rightIndexes: [5] };
  const slots = [full, next];
  assert.equal(canCombineNext(slots, 0), false);
  assert.equal(combineNext(slots, 0), slots);
});
