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

test("component input overrides are prefixed with `input` and ordered after the base input rules", () => {
  const blockRe = /([^{}]+)\{([^{}]*)\}/g;
  const blocks = [];
  let match;
  while ((match = blockRe.exec(css))) {
    blocks.push({ selector: match[1].trim(), index: match.index });
  }

  const selectorHasPart = (block, re) => block.selector.split(",").some((part) => re.test(part.trim()));

  const baseBlock = blocks.find((b) => selectorHasPart(b, /^input:not\(\[type\]\)$/));
  const baseFocusBlock = blocks.find((b) => selectorHasPart(b, /^input:not\(\[type\]\):focus$/));
  assert.ok(baseBlock, "base input rule not found");
  assert.ok(baseFocusBlock, "base input :focus rule not found");

  const jobNameBlock = blocks.find((b) => selectorHasPart(b, /^input\.job-name-input$/));
  const jobNameFocusBlock = blocks.find((b) => selectorHasPart(b, /^input\.job-name-input:focus$/));
  const mapsThumbFocusBlock = blocks.find((b) => selectorHasPart(b, /^input\.maps-thumb-title-input:focus$/));

  assert.ok(jobNameBlock, ".job-name-input rule not found or not prefixed with `input`");
  assert.ok(jobNameFocusBlock, ".job-name-input:focus rule not found or not prefixed with `input`");
  assert.ok(mapsThumbFocusBlock, ".maps-thumb-title-input:focus rule not found or not prefixed with `input`");

  assert.ok(jobNameBlock.index > baseFocusBlock.index, "input.job-name-input must come after the base input:focus block");
  assert.ok(jobNameFocusBlock.index > baseFocusBlock.index, "input.job-name-input:focus must come after the base input:focus block");
  assert.ok(mapsThumbFocusBlock.index > baseFocusBlock.index, "input.maps-thumb-title-input:focus must come after the base input:focus block");

  const selectors = css.match(/[^{}]+(?=\{)/g) || [];
  const offenders = selectors.filter((selector) =>
    selector
      .split(",")
      .some(
        (part) =>
          /\.(maps-thumb-title-input|job-name-input)\b/.test(part) && !/\binput\.(maps-thumb-title-input|job-name-input)\b/.test(part)
      )
  );
  assert.deepEqual(offenders, []);
});
