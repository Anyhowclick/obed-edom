// Two-tier remap read: live (x,y,w,h) for groups, masked/rotated images, and autosize text only.
// Address by bundle id, never by name. Discard a bulk array whose length ≠ count (would shift kindIndex).

if (typeof ObjC !== "undefined") ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

function num(v, fallback) {
  const n = Number(v);
  return isNaN(n) ? fallback : n;
}

function lenOf(v) {
  if (v == null) return 0;
  try {
    let n = v.length;
    if (typeof n === "function") n = n.call(v);
    n = Number(n);
    return isNaN(n) ? 0 : n;
  } catch (e) {
    return 0;
  }
}

function xyFrom(p) {
  if (p == null) return null;
  if (lenOf(p) >= 2) {
    return [num(p[0], 0), num(p[1], 0)];
  }
  let x = NaN;
  let y = NaN;
  try {
    let xv = p.x;
    if (typeof xv === "function") xv = xv.call(p);
    x = Number(xv);
  } catch (eX) {}
  try {
    let yv = p.y;
    if (typeof yv === "function") yv = yv.call(p);
    y = Number(yv);
  } catch (eY) {}
  if (!isNaN(x) && !isNaN(y)) return [x, y];
  return null;
}

function positionOf(obj) {
  const pair = xyFrom(obj.position());
  if (pair) return pair;
  return [0, 0];
}

function widthOf(obj) {
  return num(obj.width(), 0);
}

function heightOf(obj) {
  return num(obj.height(), 0);
}

// Per-collection/bulk-property/item failures are otherwise INVISIBLE: a caught
// exception here just omits that kind (Python sees "bulk-missing" with no reason why).
// Collected here instead, capped, and returned in the JSON as `errors` so the reason
// survives into the offline-inspect sidecar (offline_inspect._finalize_two_tier).
var errors = [];
var errorCount = 0; // uncapped total; `errors` itself is capped at MAX_ERRORS
var MAX_ERRORS = 50;
var notes = []; // informational only (e.g. a bulk-array length drift) -- own cap, never gates
var noteCount = 0;
var MAX_NOTES = 50;
var currentSlideIndex = null;

function pushError(kind, where, e) {
  errorCount += 1;
  if (errors.length >= MAX_ERRORS) return;
  errors.push({ slide: currentSlideIndex, kind: kind, where: where, error: String(e) });
}

function pushNote(kind, where, e) {
  noteCount += 1;
  if (notes.length >= MAX_NOTES) return;
  notes.push({ slide: currentSlideIndex, kind: kind, where: where, error: String(e) });
}

function withItemFallback(fn, kind, i, fallback) {
  try {
    return fn();
  } catch (e) {
    pushError(kind, "item:" + i, e);
    return fallback;
  }
}

// Never zip a short bulk array: a dropped missing value would shift every later kindIndex.
function bulkArray(value, count) {
  if (value == null) return null;
  let n;
  try {
    n = value.length;
    if (typeof n === "function") n = n.call(value);
    n = Number(n);
  } catch (e) {
    return null;
  }
  if (isNaN(n) || n !== count) return null;
  return value;
}

function tryBulk(slide, name, prop, count, kind) {
  var raw;
  try {
    raw = slide[name][prop]();
  } catch (e) {
    pushError(kind, "bulk:" + prop, e);
    return null;
  }
  var result = bulkArray(raw, count);
  // bulkArray rejected a NON-null value (drifted/unreadable length) -- informational,
  // the per-item fallback already covers it; distinct from the exception case above,
  // so it is a NOTE, not an error (never gates, own cap/count).
  if (result === null && raw != null) {
    pushNote(kind, "bulk:" + prop + ":length", "length !== " + count);
  }
  return result;
}

// Same kindIndex order as inspect_keynote.js. Shapes/lines omitted — offline already exact.
var COLLECTIONS = [
  ["textItems", "text"],
  ["images", "image"],
  ["movies", "movie"],
  ["groups", "group"],
];

function kindForName(name) {
  for (var c = 0; c < COLLECTIONS.length; c++) {
    if (COLLECTIONS[c][0] === name) return COLLECTIONS[c][1];
  }
  return name;
}

function collectionGeom(slide, name) {
  var kind = kindForName(name);
  var col;
  try {
    col = slide[name]();
  } catch (e) {
    pushError(kind, "collection", e);
    return null;
  }
  var n;
  try {
    n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n);
  } catch (e2) {
    pushError(kind, "collection", e2);
    return null;
  }
  if (isNaN(n) || n < 0) {
    pushError(kind, "count", "count is " + n);
    return null;
  }
  if (n === 0) return [];
  var positions = tryBulk(slide, name, "position", n, kind);
  var widths = tryBulk(slide, name, "width", n, kind);
  var heights = tryBulk(slide, name, "height", n, kind);
  var rows = [];
  for (var i = 0; i < n; i++) {
    var xy = positions ? xyFrom(positions[i]) : null;
    if (!xy) xy = withItemFallback(function () { return positionOf(col[i]); }, kind, i, [0, 0]);
    var w = widths ? num(widths[i], 0) : withItemFallback(function () { return widthOf(col[i]); }, kind, i, 0);
    var h = heights ? num(heights[i], 0) : withItemFallback(function () { return heightOf(col[i]); }, kind, i, 0);
    rows.push([xy[0], xy[1], w, h]);
  }
  return rows;
}

function slideGeom(slide, index) {
  currentSlideIndex = index === undefined ? null : index;
  var out = {};
  for (var c = 0; c < COLLECTIONS.length; c++) {
    var name = COLLECTIONS[c][0];
    var kind = COLLECTIONS[c][1];
    var rows = collectionGeom(slide, name);
    if (rows !== null) out[kind] = rows;
  }
  return out;
}

function run(argv) {
  errors = [];
  errorCount = 0;
  notes = [];
  noteCount = 0;
  currentSlideIndex = null;

  const plan = readJSON(argv[0]);
  const Keynote = Application(plan.bundleId || "com.apple.Keynote");
  Keynote.includeStandardAdditions = true;

  var doc, slides;
  try {
    doc = Keynote.open(Path(plan.path));
    slides = doc.slides();
  } catch (eOpen) {
    var openMsg = String(eOpen);
    if (!openMsg) openMsg = "Keynote.open/doc.slides() failed with no message";
    return JSON.stringify({ path: plan.path, error: openMsg });
  }

  const range = plan.range || null;
  const wanted = plan.slides && plan.slides.length ? plan.slides : null;
  const start = range ? Math.max(0, range[0] - 1) : 0;
  const end = range ? Math.min(slides.length, range[1]) : slides.length;
  const indices = [];
  if (wanted) {
    for (let w = 0; w < wanted.length; w++) {
      const i = Number(wanted[w]) - 1;
      if (i >= 0 && i < slides.length) indices.push(i);
    }
  } else {
    for (let i = start; i < end; i++) indices.push(i);
  }

  const geometry = {};
  for (let s = 0; s < indices.length; s++) {
    const i = indices[s];
    geometry[i] = slideGeom(slides[i], i);
  }

  try {
    Keynote.close(doc, { saving: "no" });
  } catch (e3) {
    try {
      doc.close({ saving: "no" });
    } catch (e4) {}
  }

  return JSON.stringify({
    path: plan.path,
    slideCount: slides.length,
    geometry: geometry,
    errors: errors,
    errorCount: errorCount,
    notes: notes,
    noteCount: noteCount,
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    num: num,
    xyFrom: xyFrom,
    bulkArray: bulkArray,
    collectionGeom: collectionGeom,
    slideGeom: slideGeom,
    getErrors: function () { return errors; },
    getErrorCount: function () { return errorCount; },
    getNotes: function () { return notes; },
    getNoteCount: function () { return noteCount; },
    resetErrors: function () { errors = []; errorCount = 0; notes = []; noteCount = 0; },
  };
}
