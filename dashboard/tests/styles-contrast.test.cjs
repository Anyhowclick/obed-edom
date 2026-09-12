const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const css = fs.readFileSync(path.join(__dirname, "../src/styles.css"), "utf8");

test("no rule block sets both --bg-surface-solid background and --ink-primary color", () => {
  const blocks = css.match(/\{[^{}]*\}/g) || [];
  const offenders = blocks.filter(
    (block) => /background:\s*var\(--bg-surface-solid\)/.test(block) && /color:\s*var\(--ink-primary\)/.test(block)
  );
  assert.deepEqual(offenders, []);
});
