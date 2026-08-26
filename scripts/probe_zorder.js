#!/usr/bin/env osascript -l JavaScript
// Can stacking order be read back, and can it be changed?
//
// Builds a throwaway deck with overlapping objects in a known creation order,
// then asks three questions:
//   1. does the mixed `iWork items` collection enumerate at all,
//   2. if it does, does its order correspond to stacking (creation) order,
//   3. is there any command or property that reorders (the sdef shows none).
//
// Run: osascript -l JavaScript scripts/probe_zorder.js
'use strict';

function run() {
  const BUNDLE = 'com.apple.Keynote';
  const app = Application(BUNDLE);
  app.includeStandardAdditions = true;
  const out = { bundleId: BUNDLE, version: app.version() };

  const doc = app.Document().make();
  const slide = doc.slides[0];

  // Three overlapping shapes in a known order, plus a text item, so the mixed
  // collection has more than one class in it.
  const made = [];
  for (let i = 0; i < 3; i += 1) {
    const shape = app.Shape({ position: { x: 100 + i * 40, y: 100 + i * 40 }, width: 200, height: 200 });
    slide.shapes.push(shape);
    made.push('shape' + i);
  }
  const text = app.TextItem({ objectText: 'zprobe', position: { x: 160, y: 160 } });
  slide.textItems.push(text);
  made.push('text');
  out.creationOrder = made;

  // Q1/Q2: the mixed collection.
  try {
    const items = slide.iWorkItems();
    out.mixedCollection = { ok: true, count: items.length };
    out.mixedCollection.classes = items.map((it) => {
      try {
        return String(it.class());
      } catch (e) {
        return 'class() failed: ' + e.message;
      }
    });
    out.mixedCollection.positions = items.map((it) => {
      try {
        const p = it.position();
        return [p.x, p.y];
      } catch (e) {
        return null;
      }
    });
  } catch (e) {
    out.mixedCollection = { ok: false, error: e.message };
  }

  // Per-type collections do enumerate; record their order for comparison.
  try {
    out.shapePositions = slide.shapes().map((s) => {
      const p = s.position();
      return [p.x, p.y];
    });
  } catch (e) {
    out.shapePositions = 'failed: ' + e.message;
  }

  // Q3: is anything reorder-shaped reachable on an item?
  const probes = {};
  const target = slide.shapes[0];
  for (const name of ['zOrder', 'zOrderIndex', 'index', 'stackingOrder', 'layer']) {
    try {
      probes[name] = String(target[name]());
    } catch (e) {
      probes[name] = 'unavailable: ' + e.message;
    }
  }
  for (const verb of ['bringToFront', 'sendToBack', 'bringForward', 'sendBackward']) {
    probes[verb + '()'] = typeof app[verb] === 'function' ? 'exists on app' : 'absent';
  }
  out.reorderProbes = probes;

  doc.close({ saving: 'no' });
  return JSON.stringify(out, null, 2);
}
