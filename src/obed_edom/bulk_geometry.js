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
  try {
    const pair = xyFrom(obj.position());
    if (pair) return pair;
  } catch (e) {}
  return [0, 0];
}

function widthOf(obj) {
  try {
    return num(obj.width(), 0);
  } catch (e) {
    return 0;
  }
}

function heightOf(obj) {
  try {
    return num(obj.height(), 0);
  } catch (e) {
    return 0;
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

function tryBulk(slide, name, prop, count) {
  try {
    return bulkArray(slide[name][prop](), count);
  } catch (e) {
    return null;
  }
}

// Same kindIndex order as inspect_keynote.js. Shapes/lines omitted — offline already exact.
var COLLECTIONS = [
  ["textItems", "text"],
  ["images", "image"],
  ["movies", "movie"],
  ["groups", "group"],
];

function collectionGeom(slide, name) {
  var col;
  try {
    col = slide[name]();
  } catch (e) {
    return null;
  }
  var n;
  try {
    n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n);
  } catch (e2) {
    return null;
  }
  if (isNaN(n) || n < 0) return null;
  if (n === 0) return [];
  var positions = tryBulk(slide, name, "position", n);
  var widths = tryBulk(slide, name, "width", n);
  var heights = tryBulk(slide, name, "height", n);
  var rows = [];
  for (var i = 0; i < n; i++) {
    var xy = positions ? xyFrom(positions[i]) : null;
    if (!xy) xy = positionOf(col[i]);
    var w = widths ? num(widths[i], 0) : widthOf(col[i]);
    var h = heights ? num(heights[i], 0) : heightOf(col[i]);
    rows.push([xy[0], xy[1], w, h]);
  }
  return rows;
}

function slideGeom(slide) {
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
  const plan = readJSON(argv[0]);
  const Keynote = Application(plan.bundleId || "com.apple.Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.path));
  const slides = doc.slides();

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
    geometry[i] = slideGeom(slides[i]);
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
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    num: num,
    xyFrom: xyFrom,
    bulkArray: bulkArray,
    collectionGeom: collectionGeom,
    slideGeom: slideGeom,
  };
}
