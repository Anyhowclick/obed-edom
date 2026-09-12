const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const src = (file) => fs.readFileSync(path.join(__dirname, "../src", file), "utf8");
const css = src("styles.css").replace(/\/\*[\s\S]*?\*\//g, "");

function blocks() {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let match;
  while ((match = re.exec(css))) out.push({ selector: match[1].trim(), body: match[2] });
  return out;
}

test("a control reads its height from the container tier and never declares one", () => {
  const all = blocks();
  const btn = all.find((b) => b.selector === ".btn");
  const iconBtn = all.find((b) => b.selector === ".icon-btn");
  assert.ok(btn, ".btn rule not found");
  assert.ok(iconBtn, ".icon-btn rule not found");
  assert.match(btn.body, /min-height:\s*var\(--ctl-h\)/);
  assert.match(iconBtn.body, /height:\s*var\(--ctl-h\)/);

  const offenders = all
    .filter((b) => /\.btn\b|\.icon-btn\b|\.seg\s+button\b/.test(b.selector))
    .filter((b) => /--ctl-h\s*:/.test(b.body))
    .map((b) => b.selector);
  assert.deepEqual(offenders, []);
});

test("no bare .icon rule — .maps-pin-hidden.icon is a span, not an svg", () => {
  const offenders = blocks()
    .map((b) => b.selector)
    .filter((selector) => selector.split(",").some((part) => /(^|\s)\.icon$/.test(part.trim())));
  assert.deepEqual(offenders, []);
});

test("every control that opens a menu renders exactly one caret", () => {
  for (const file of ["tabs/MapsTab.tsx", "maps/CountryCache.tsx", "maps/StylePicker.tsx"]) {
    const text = src(file);
    const triggers = (text.match(/aria-haspopup/g) || []).length;
    const carets = (text.match(/<IconCaret\s*\/>/g) || []).length;
    assert.equal(carets, triggers, `${file}: ${triggers} menu triggers but ${carets} carets`);
  }
});
