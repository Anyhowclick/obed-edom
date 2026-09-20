const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const Module = require("node:module");
const { createElement } = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const root = path.resolve(__dirname, "..");
const runtime = process.env.CODEX_NODE || process.execPath;
const out = require("./helpers/compiled.cjs").maps;

const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, main, options) {
  if (request === "react" || request === "react/jsx-runtime" || request === "react-dom/server") {
    return resolve.call(this, request, parent, main, { ...options, paths: [root] });
  }
  return resolve.call(this, request, parent, main, options);
};

const { BandOverlays } = require(path.join(out, "BandOverlays.js"));

const noop = () => {};

function render(overrides = {}) {
  const props = {
    splitCg: false,
    fullWall: false,
    exportCg: true,
    cgLeft: 25,
    cgWidth: 50,
    cgSnapped: false,
    box: { x: 400, y: 300, w: 80, h: 120 },
    k: 0.25,
    bandTop: 100,
    onCgPointerDown: noop,
    onCgPointerMove: noop,
    onCgPointerUp: noop,
    onHandlePointerDown: () => noop,
    onHandlePointerMove: noop,
    onHandlePointerUp: noop,
    ...overrides,
  };
  return renderToStaticMarkup(createElement(BandOverlays, props));
}

test("BandOverlays: object layer is later in the DOM than the crop overlay (paints above it)", () => {
  const markup = render();
  const cropIdx = markup.indexOf("maps-crop-overlay");
  const objectIdx = markup.indexOf("maps-object-layer");
  assert.ok(cropIdx >= 0, "missing maps-crop-overlay");
  assert.ok(objectIdx >= 0, "missing maps-object-layer");
  assert.ok(objectIdx > cropIdx, "object layer must come after the crop overlay in DOM order");
});

test("BandOverlays: crop overlay and CG drag frame precede the object layer; object box is not inside the crop overlay", () => {
  const markup = render();
  const cgIdx = markup.indexOf("maps-crop-cg");
  const objectIdx = markup.indexOf("maps-object-layer");
  assert.ok(cgIdx >= 0 && cgIdx < objectIdx);
  const cropSlice = markup.slice(markup.indexOf("maps-crop-overlay"), objectIdx);
  assert.ok(!cropSlice.includes("maps-object-box"));
  const afterObjectLayer = markup.slice(objectIdx);
  for (const corner of ["nw", "ne", "sw", "se"]) {
    assert.ok(afterObjectLayer.includes(`maps-object-handle ${corner}`), `missing handle ${corner}`);
  }
});

test("BandOverlays: box style is k/bandTop-mapped band-local coords (matches objectBoxStyle)", () => {
  const markup = render();
  assert.match(markup, /left:100px/);
  assert.match(markup, /top:50px/);
  assert.match(markup, /width:20px/);
  assert.match(markup, /height:30px/);
});

test("BandOverlays: center (LW) frame renders an LW label", () => {
  const markup = render({ splitCg: false, fullWall: false });
  assert.ok(markup.includes('class="maps-crop-frame center"'));
  assert.ok(markup.includes('class="maps-crop-lw-label">LW</span>'));
});

test("BandOverlays: FW frame renders an FW label, not LW", () => {
  const markup = render({ splitCg: false, fullWall: true });
  assert.ok(markup.includes('class="maps-crop-frame fw"'));
  assert.ok(markup.includes('class="maps-crop-fw-label">FW</span>'));
  assert.ok(!markup.includes("maps-crop-lw-label"));
});

test("BandOverlays: no box means no object layer at all", () => {
  const markup = render({ box: null });
  assert.ok(!markup.includes("maps-object-layer"));
});

test("BandOverlays: snap guide renders only while cgSnapped is true", () => {
  assert.ok(!render({ cgSnapped: false }).includes("maps-snap-guide"));
  assert.ok(render({ cgSnapped: true }).includes("maps-snap-guide"));
});

test("BandOverlays: snap guide is absent when splitCg is true even if cgSnapped", () => {
  assert.ok(!render({ cgSnapped: true, splitCg: true }).includes("maps-snap-guide"));
});

test("BandOverlays: CG frame defaults to select and can switch to move", () => {
  assert.match(render(), /class="maps-crop-cg select"/);
  assert.match(render({ cgInteract: "move" }), /class="maps-crop-cg move"/);
});

test("styles.css: .maps-object-layer sits above the crop overlay and stays click-through except its handles", () => {
  const css = fs.readFileSync(path.join(root, "src/styles.css"), "utf8");
  const block = (selector) => {
    const m = css.match(new RegExp(selector.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}"));
    assert.ok(m, `missing ${selector} block`);
    return m[1];
  };
  const objectLayer = block(".maps-object-layer");
  assert.match(objectLayer, /z-index:\s*\d+/);
  assert.match(objectLayer, /pointer-events:\s*none/);
  const zIndexOf = (blockText) => {
    const m = blockText.match(/z-index:\s*(-?\d+)/);
    return m ? Number(m[1]) : null;
  };
  const cropOverlay = block(".maps-crop-overlay");
  const cropZ = zIndexOf(cropOverlay);
  const layerZ = zIndexOf(objectLayer);
  assert.ok(cropZ === null || cropZ < layerZ, "crop overlay must not out-rank the object layer");
  const handle = block(".maps-object-handle");
  assert.match(handle, /pointer-events:\s*auto/);
});

test("styles.css: .maps-snap-guide is click-through and ordered above the crop overlay", () => {
  const css = fs.readFileSync(path.join(root, "src/styles.css"), "utf8");
  const block = (selector) => {
    const m = css.match(new RegExp(selector.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}"));
    assert.ok(m, `missing ${selector} block`);
    return m[1];
  };
  const zIndexOf = (blockText) => {
    const m = blockText.match(/z-index:\s*(-?\d+)/);
    return m ? Number(m[1]) : null;
  };
  const guide = block(".maps-snap-guide");
  assert.match(guide, /pointer-events:\s*none/);
  const cropOverlay = block(".maps-crop-overlay");
  const cropZ = zIndexOf(cropOverlay);
  const guideZ = zIndexOf(guide);
  assert.ok(cropZ === null || guideZ === null || cropZ <= guideZ, "crop overlay must not out-rank the snap guide");
});

test("styles.css: FW crop frame/label are neutral white, LW stays --aud-lw, CG stays plum", () => {
  const css = fs.readFileSync(path.join(root, "src/styles.css"), "utf8");
  const block = (selector) => {
    const m = css.match(new RegExp(selector.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}"));
    assert.ok(m, `missing ${selector} block`);
    return m[1];
  };
  assert.match(block(".maps-crop-frame.fw"), /border-color:\s*rgba\(255,\s*255,\s*255,\s*0\.75\)/);
  assert.match(block(".maps-crop-fw-label"), /color:\s*#FFFFFF/);
  assert.match(block(".maps-crop-frame"), /border:\s*2px solid var\(--aud-lw\)/);
  assert.match(block(".maps-crop-frame.cg"), /border-color:\s*var\(--plum\)/);
  const cgLabelOverride = css.match(/\.maps-crop-cg-label\s*\{\s*top:\s*8px;[^}]*\}/);
  assert.ok(cgLabelOverride, "missing .maps-crop-cg-label colour override block");
  assert.match(cgLabelOverride[0], /color:\s*var\(--plum\)/);
});

test("styles.css: select mode lets map clicks through the CG frame; move mode captures them", () => {
  const css = fs.readFileSync(path.join(root, "src/styles.css"), "utf8");
  const block = (selector) => {
    const m = css.match(new RegExp(selector.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}"));
    assert.ok(m, `missing ${selector} block`);
    return m[1];
  };
  assert.match(block(".maps-crop-cg.select"), /pointer-events:\s*none/);
  assert.match(block(".maps-crop-cg.move"), /pointer-events:\s*auto/);
  const mode = block(".maps-cg-mode");
  assert.match(mode, /z-index:\s*5/);
  assert.match(mode, /bottom:\s*10px/);
});

test("styles.css: .maps-manual-pins tints gold, .maps-manual stays teal", () => {
  const css = fs.readFileSync(path.join(root, "src/styles.css"), "utf8");
  const block = (selector) => {
    const m = css.match(new RegExp(selector.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}"));
    assert.ok(m, `missing ${selector} block`);
    return m[1];
  };
  const manual = block(".maps-manual");
  assert.match(manual, /rgba\(0, 229, 255/);
  const manualPins = block(".maps-manual-pins");
  assert.match(manualPins, /rgba\(255, 199, 44/);
  assert.match(manualPins, /background:/);
  assert.match(manualPins, /border:/);
  const done = block(".maps-manual-pins .btn.maps-manual-done");
  assert.match(done, /var\(--accent-collab\)/);
});

test("MapView.tsx: uses previewLayout from ./types and no longer computes inner height as 1080 * scale", () => {
  const src = fs.readFileSync(path.join(root, "src/maps/MapView.tsx"), "utf8");
  assert.match(src, /import\s*\{[^}]*\bpreviewLayout\b[^}]*\}\s*from\s*"\.\/types"/);
  assert.ok(!/1080\s*\*\s*scale/.test(src), "found a leftover 1080 * scale inner-height expression");
});

test("MapView.tsx: inner transform translates by -bandTop*k then scales by k", () => {
  const src = fs.readFileSync(path.join(root, "src/maps/MapView.tsx"), "utf8");
  assert.ok(
    src.includes("`translateY(${-L.bandTop * L.k}px) scale(${L.k})`"),
    "expected the inner element's transform template literal to translate by -bandTop*k then scale by k"
  );
});

test("MapView.tsx: wheel over the CG overlay is forwarded to MapLibre scrollZoom", () => {
  const src = fs.readFileSync(path.join(root, "src/maps/MapView.tsx"), "utf8");
  assert.match(src, /addEventListener\("wheel", onFrameWheel/);
  assert.match(src, /scrollZoom\.wheel\(event\)/);
  assert.match(src, /getCanvasContainer\(\)\.contains\(target\)/);
});
