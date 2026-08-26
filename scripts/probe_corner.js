#!/usr/bin/env osascript -l JavaScript
// Is a rounded rectangle's corner radius scriptable, and does setting width or
// height keep it? The resizer sets obj.width/obj.height on shapes; a plate that
// comes out with square corners would mean the radius is lost on resize.
'use strict';
function run() {
  const app = Application('com.apple.Keynote');
  app.includeStandardAdditions = true;
  const doc = app.Document().make();
  const slide = doc.slides[0];
  const out = { version: app.version(), steps: [] };

  // Make a shape and see what it is + what properties it exposes.
  let shp;
  try {
    shp = app.Shape().make ? null : null;
  } catch (e) {}
  try {
    shp = app.Shape({ position: [100, 100], width: 300, height: 120 });
    slide.shapes.push(shp);
  } catch (e) {
    out.makeError = String(e);
  }
  if (!shp && slide.shapes.length) shp = slide.shapes[0];

  function dump(obj) {
    const o = {};
    const keys = ['width', 'height', 'cornerRadius', 'corner radius', 'reflectionShowing',
                  'objectType', 'name', 'class'];
    for (const k of keys) {
      try { o[k] = obj[k] ? obj[k]() : obj[k]; } catch (e) { o[k] = 'ERR:' + String(e).slice(0, 40); }
    }
    // full property bag
    try { o._props = Object.keys(obj.properties()); } catch (e) { o._propsErr = String(e).slice(0, 60); }
    return o;
  }

  if (shp) {
    out.steps.push({ when: 'created', props: dump(shp) });
    try { shp.width = 180; } catch (e) { out.widthErr = String(e); }
    try { shp.height = 80; } catch (e) { out.heightErr = String(e); }
    out.steps.push({ when: 'after resize', props: dump(shp) });
  } else {
    out.noShape = true;
    out.shapesCount = slide.shapes.length;
  }
  doc.close({ saving: 'no' });
  return JSON.stringify(out, null, 2);
}
