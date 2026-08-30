// Slim bulk-geometry Keynote read — the "second tier" of the two-tier offline
// remap read (see obed_edom.offline_inspect.two_tier_wall_payload).
//
// The offline IWA read (offline_inspect.offline_wall_payload) reconstructs the
// whole JXA inspect payload without opening Keynote, and its geometry is EXACT
// for shapes, lines, and plain (unmasked, unrotated) images/text. It DIVERGES
// only for three classes Keynote lays out in ways the IWA graph does not spell
// out: groups (stored frame vs child-union), masked/rotated images, and autosize
// text (stale naturalSize vs the reflowed box). This script reads back ONLY the
// laid-out (x, y, w, h) of those classes, so the caller can overwrite the soft
// offline values with Keynote's own — closing the plan-equivalence gap while
// paying a tiny fraction of the full ~12-minute per-object inspect.
//
// COST — O(slides), never O(objects). Per slide it touches four collections
// (textItems, images, movies, groups); for each it fires at most THREE bulk
// Apple Events off the UNEVALUATED collection specifier — `slide.images.position()`
// returns the whole array of positions in one event, likewise `.width()` and
// `.height()`. That is <= 12 Apple Events per slide regardless of how many objects
// a slide holds. It reads NO objectText / font / colour / fileName / builds, never
// descends into groups, and issues no per-object event on the fast path. The
// per-object fallback below fires only for a single property of a single
// collection whose bulk array drifted — never for the whole read.
//
// This is deliberately a SEPARATE lean script rather than a mode of
// inspect_keynote.js: the two tiers have opposite shapes (this returns bare
// geometry rows keyed by (slide, kind, kindIndex); inspect returns full item
// records), and keeping the bulk read minimal is what guarantees the O(slides)
// bound. The bulk primitives (bulkArray/tryBulk length-guard + per-object
// fallback) mirror inspect_keynote.js so their proven "never slower, never wrong"
// contract carries over verbatim.

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

// A position specifier answers either as a two-element list or as an object with
// x()/y() accessors — normalise to [x, y]. Mirrors inspect_keynote.js xyFrom.
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

// Per-object fallbacks (used only when a bulk array is unavailable / drifted).
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

// Return `value` only when it is an array-like of exactly `count` elements, else
// null (=> per-object fallback for this property). A SHORT array is never zipped:
// Keynote dropping a missing value would shift every subsequent kindIndex and
// silently corrupt the address. Identical contract to inspect_keynote.js.
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

// One bulk fetch off the UNEVALUATED collection specifier, length-guarded.
function tryBulk(slide, name, prop, count) {
  try {
    return bulkArray(slide[name][prop](), count);
  } catch (e) {
    return null;
  }
}

// The four collections whose geometry the offline read cannot reproduce exactly,
// in the SAME order and under the SAME kindIndex numbering the offline addressing
// and inspect_keynote.js use. Shapes and lines are intentionally absent: the
// offline read is already exact for them, so reading them here would be wasted
// Apple Events.
var COLLECTIONS = [
  ["textItems", "text"],
  ["images", "image"],
  ["movies", "movie"],
  ["groups", "group"],
];

// [x, y, w, h] for every element of one collection, by kindIndex. position, width
// and height each come from a single bulk array when it passes the length guard,
// else per-object. Returns null when the collection cannot be evaluated at all
// (so the caller can mark that (slide, kind) missing and fall back granularly),
// or [] for a genuinely empty collection.
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
    // Only kinds that evaluated are emitted; a null (collection unreadable) is
    // simply omitted, and the Python caller treats a missing (slide, kind) as
    // "not confirmed" and falls back for just that slide/kind.
    if (rows !== null) out[kind] = rows;
  }
  return out;
}

function run(argv) {
  const plan = readJSON(argv[0]);
  // By bundle id, never by name (Keynote 15 "Keynote Creator Studio" has a
  // different id and both answer to "Keynote"). Same handshake as inspect.
  const Keynote = Application(plan.bundleId || "com.apple.Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.path));
  const slides = doc.slides();

  // Same slide-selection contract as inspect_keynote.js: an explicit `slides`
  // list wins, else a [start, end] range, else the whole deck. Keys in the
  // returned map are the 0-based DOCUMENT index so the caller lines up rows with
  // offline_wall_payload's slides[].index directly.
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

// Exposed for Node unit tests only; under osascript `module` is undefined so this
// is a no-op and `run` stays the JXA entry point.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    num: num,
    xyFrom: xyFrom,
    bulkArray: bulkArray,
    collectionGeom: collectionGeom,
    slideGeom: slideGeom,
  };
}
