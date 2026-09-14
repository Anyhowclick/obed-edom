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

test("the ＋ menu labels are terse — no trailing ellipsis", () => {
  const text = src("tabs/MapsTab.tsx");
  for (const label of ["Add slides", "Add pins", "Add slides from CSV", "Add pins from CSV", "Replace deck from CSV"]) {
    assert.match(text, new RegExp(`>\\s*${label}\\s*<`), `missing label ${JSON.stringify(label)}`);
  }
  for (const stale of ["Add slides manually…", "Add pins to this view manually…", "Add slides from CSV…", "Add pins to this view from CSV…", "Replace deck from CSV…"]) {
    assert.doesNotMatch(text, new RegExp(`>\\s*${stale}\\s*<`), `stale label ${JSON.stringify(stale)} still present`);
  }
});

test("the highlight list is captioned \"Selected regions\", not \"Orange countries\"", () => {
  const text = src("tabs/MapsTab.tsx");
  assert.match(text, /<InspSection id="regions" title="Selected regions">/);
  assert.doesNotMatch(text, /Orange countries/);
});

test("the export checkboxes no longer carry an audience-colour class", () => {
  const text = src("tabs/MapsTab.tsx");
  assert.doesNotMatch(text, /className="maps-check aud-(lw|cg|dsk)"/);
});

test("the sliding pill is measured (offsetLeft/width), not equal-width CSS vars", () => {
  const maps = src("tabs/MapsTab.tsx");
  assert.match(maps, /<SlidingSeg/);
  assert.doesNotMatch(maps, /"--seg-i":\s*pickRegions/);

  const sliding = src("maps/SlidingSeg.tsx");
  assert.match(sliding, /offsetLeft/);
  assert.match(sliding, /offsetWidth/);
  assert.match(sliding, /style\.transition = "none"/);
  assert.match(sliding, /role="tablist"/);
  assert.match(sliding, /role="tab"/);
  assert.match(sliding, /animUntilRef/);
  assert.match(sliding, /TABS_MS = 250/);

  const bar = blocks().find((b) => b.selector === ".seg.seg-slide");
  assert.ok(bar, ".seg.seg-slide rule not found");
  assert.match(bar.body, /padding:\s*var\(--tabs-pad\)/);
  assert.match(bar.body, /gap:\s*3px/);
  assert.match(bar.body, /width:\s*max-content/);
  assert.doesNotMatch(bar.body, /flex:\s*1/);

  const tab = blocks().find((b) => b.selector === ".seg.seg-slide button");
  assert.ok(tab, ".seg.seg-slide button rule not found");
  assert.doesNotMatch(tab.body, /flex:\s*1 1 0/);

  const ind = blocks().find((b) => b.selector === ".seg-slide-ind");
  assert.ok(ind, ".seg-slide-ind rule not found");
  assert.match(ind.body, /width:\s*0/);
  assert.match(ind.body, /visibility:\s*hidden/);
  assert.doesNotMatch(ind.body, /--seg-n|--seg-i/);
  assert.match(ind.body, /transition:[^}]*transform[^}]*width/);

  const reducedMotion = css.match(/@media \(prefers-reduced-motion: reduce\) \{[^}]*\.seg-slide-ind[^}]*\}[^}]*\}/);
  assert.ok(reducedMotion, "missing reduced-motion rule for .seg-slide-ind");
});
