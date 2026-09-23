// Remap write pass. Address by bundle id, never by name.
// JXA size-before-position yanks to (0,0). Delete highest-index first.
if (typeof ObjC !== "undefined") {
  ObjC.import("Foundation");
  try { ObjC.import("AppKit"); } catch (eAK) {}
}

var TIMING = null;
function _now() {
  return +new Date();
}
var STAGES = {};
function _stage(name, t0) {
  STAGES[name] = (STAGES[name] || 0) + (_now() - t0);
}
function _resetStages() {
  for (const k in STAGES) delete STAGES[k];
}
function _trec(bucket, ms, desc) {
  if (!TIMING) return;
  if (!TIMING.buckets[bucket]) TIMING.buckets[bucket] = { ms: 0, n: 0 };
  TIMING.buckets[bucket].ms += ms;
  TIMING.buckets[bucket].n += 1;
  if (desc && ms >= TIMING.slowMs) {
    desc.ms = Math.round(ms);
    if (TIMING.slow.length < 400) TIMING.slow.push(desc);
  }
}

let KEYNOTE_BUNDLE_ID = "com.apple.Keynote";

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

function kindColName(kind) {
  if (kind === "text") return "textItems";
  if (kind === "image") return "images";
  if (kind === "shape") return "shapes";
  if (kind === "movie") return "movies";
  if (kind === "group") return "groups";
  if (kind === "line") return "lines";
  return "";
}

function countOf(col) {
  if (col == null) return 0;
  try {
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n);
    if (!isNaN(n) && n >= 0) return n;
  } catch (e) {}
  return 0;
}

// Same read as countOf, but a throw or a bad length is reported as -1 ("unmeasured"),
// never folded into a genuine 0. Used only by collectionCounts — countOf's 0 degrade
// stays correct for itemAt/slide counts, which need "absent" and "empty" to look
// the same.
function countOrUnreadable(col) {
  if (col == null) return -1;
  try {
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n);
    if (!isNaN(n) && n >= 0) return n;
  } catch (e) {}
  return -1;
}

function collectionNamed(slide, name) {
  try {
    return slide[name]();
  } catch (e) {}
  try {
    return slide[name];
  } catch (e2) {}
  return null;
}

function collectionOf(slide, name, cache) {
  if (!cache) return collectionNamed(slide, name);
  if (!Object.prototype.hasOwnProperty.call(cache, name)) cache[name] = collectionNamed(slide, name);
  return cache[name];
}

function itemAt(col, index) {
  const n = countOf(col);
  if (index < 0 || index >= n) return null;
  try {
    const obj = col[index];
    if (obj != null) return obj;
  } catch (e) {}
  return null;
}

function getItem(slide, spec, cache) {
  const kind = spec.kind || "";
  const kindIndex = spec.kindIndex != null ? Number(spec.kindIndex) : Number(spec.itemIndex);
  const colName = kindColName(kind);
  if (colName && !isNaN(kindIndex)) {
    const typed = itemAt(collectionOf(slide, colName, cache), kindIndex);
    if (typed) return typed;
  }
  const itemIndex = Number(spec.itemIndex);
  if (!isNaN(itemIndex)) {
    return itemAt(collectionOf(slide, "iWorkItems", cache), itemIndex);
  }
  return null;
}

function collectionCounts(slide) {
  const out = {};
  ["textItems", "images", "shapes", "movies", "groups", "lines", "iWorkItems"].forEach(function (name) {
    out[name] = countOrUnreadable(collectionNamed(slide, name));
  });
  return out;
}

function setPos(obj, x, y) {
  const nx = Number(x);
  const ny = Number(y);
  if (isNaN(nx) || isNaN(ny)) return false;
  const attempts = [
    function () {
      obj.position = [nx, ny];
    },
    function () {
      obj.position = { x: nx, y: ny };
    },
  ];
  for (let i = 0; i < attempts.length; i++) {
    try {
      attempts[i]();
      const got = xyOf(obj);
      if (Math.abs(got[0] - nx) < 2 && Math.abs(got[1] - ny) < 2) return true;
    } catch (e) {}
  }
  let w = 0;
  let h = 0;
  try {
    w = Number(obj.width());
  } catch (eW) {}
  try {
    h = Number(obj.height());
  } catch (eH) {}
  if (w > 0 && h > 0) {
    try {
      obj.position = [nx + w / 2, ny + h / 2];
      const got = xyOf(obj);
      if (Math.abs(got[0] - nx) < 3 && Math.abs(got[1] - ny) < 3) return true;
    } catch (eC) {}
  }
  return false;
}

function xyOf(obj) {
  try {
    const p = obj.position();
    if (p == null) return [0, 0];
    if (p[0] != null && p[1] != null) return [Number(p[0]), Number(p[1])];
    let x = p.x;
    let y = p.y;
    if (typeof x === "function") x = x.call(p);
    if (typeof y === "function") y = y.call(p);
    return [Number(x) || 0, Number(y) || 0];
  } catch (e) {
    return [0, 0];
  }
}

// Mirror of _child_ops_lines. Never resizes the group: a Keynote group resize is an
// aspect-locked uniform scale about the group's live frame, which after setSlideSize is
// the union of a word-wrapped autosize child — and the resize freezes that child wrapped.
// All-or-nothing: every child must resolve before any write happens, otherwise the
// group's live frame (the union of whatever landed) becomes a phantom straddling both
// the old and new positions with no repair path.
function applyGroupChildren(obj, spec, mode) {
  if (mode === "attrs") return false;
  const kids = spec.children || [];
  const resolved = [];
  for (let i = 0; i < kids.length; i++) {
    const child = getItem(obj, kids[i]);
    if (!child) return false;
    resolved.push(child);
  }
  let wrote = false;
  for (let i = 0; i < kids.length; i++) {
    const c = kids[i];
    const child = resolved[i];
    if (mode === "full" && c.w != null) {
      try { child.width = c.w; wrote = true; } catch (eW) {}
      if (!c.autosize && c.h != null) {
        try { child.height = c.h; wrote = true; } catch (eH) {}
      }
    }
    if (mode !== "attrs" && c.x != null) {
      let y = c.y;
      if (c.autosize && c.cy != null) {
        let ch = 0;
        try { ch = Number(child.height()); } catch (eR) {}
        if (ch > 0) y = Number(c.cy) - ch / 2;
      }
      if (setPos(child, c.x, y)) wrote = true;
    }
  }
  return wrote;
}

function writesAttrs(spec) {
  return (
    spec.opacity != null ||
    Boolean(spec.font) ||
    Boolean(spec.fontSize) ||
    Boolean(spec.color && spec.color.length >= 3) ||
    Boolean(spec.locked)
  );
}

// Never size in a pos-only pass (JXA yank). Line width=length / height=0 — size places the rule.
function applyGeom(obj, spec, mode) {
  mode = mode || "full";
  const writeAttrs = mode !== "pos";
  const writeSize = mode === "full";
  const writePos = mode !== "attrs";
  let ok = false;
  let wasLocked = false;
  try {
    wasLocked = Boolean(obj.locked());
  } catch (eL) {}
  if (wasLocked) {
    try {
      obj.locked = false;
    } catch (eU) {}
  }
  if (writeAttrs && spec.opacity != null) {
    try {
      obj.opacity = spec.opacity;
      ok = true;
    } catch (eO) {}
  }
  const useChildren = spec.kind === "group" && spec.children && spec.children.length > 0;
  if (useChildren && applyGroupChildren(obj, spec, mode)) ok = true;
  if (!useChildren && writeSize && spec.w != null) {
    try {
      obj.width = spec.w;
      ok = true;
    } catch (eW) {}
  }
  if (!useChildren && writeSize && spec.h != null) {
    try {
      obj.height = spec.h;
      ok = true;
    } catch (eH) {}
  }
  if (writeAttrs && spec.font) {
    try {
      obj.objectText.font = spec.font;
    } catch (eFn) {}
  }
  if (writeAttrs && spec.fontSize) {
    try {
      obj.objectText.size = spec.fontSize;
    } catch (eF) {}
  }
  if (writeAttrs && spec.color && spec.color.length >= 3) {
    try {
      obj.objectText.color = spec.color;
    } catch (eC1) {
      try {
        obj.objectText.attributeRuns[0].color = spec.color;
      } catch (eC2) {}
    }
  }
  if (!useChildren && writePos && spec.role !== "hide" && spec.x != null && spec.y != null) {
    if (setPos(obj, spec.x, spec.y)) {
      ok = true;
    }
  }
  if (spec.locked || wasLocked) {
    try {
      obj.locked = true;
    } catch (eK) {}
  }
  return ok;
}

function deleteObj(Keynote, obj) {
  if (!obj) return false;
  try {
    Keynote.delete(obj);
    return true;
  } catch (e) {
    try {
      obj.delete();
      return true;
    } catch (e2) {
      return false;
    }
  }
}

function whOf(obj) {
  let w = 0;
  let h = 0;
  try {
    w = Number(obj.width());
  } catch (eW) {}
  try {
    h = Number(obj.height());
  } catch (eH) {}
  return [w, h];
}

function tempScriptPath(dir, uniq) {
  const base = dir.charAt(dir.length - 1) === "/" ? dir : dir + "/";
  return base + "obed-edom-keynote-" + uniq + ".applescript";
}

function runAppleScript(doc, body) {
  // Named document, not front. Script file is per-user temp dir, unique per call, removed on success, kept on failure.
  let target = "front document";
  try {
    target =
      'document "' + String(doc.name()).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  } catch (eN) {}
  const script =
    'tell application id "' +
    KEYNOTE_BUNDLE_ID +
    '"\ntell ' +
    target +
    "\n" +
    body +
    "\nend tell\nend tell\n";
  const dir = ObjC.unwrap($.NSTemporaryDirectory());
  const uniq = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  const path = tempScriptPath(dir, uniq);
  const ns = $.NSString.stringWithString(script);
  ns.writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, null);
  const app = Application.currentApplication();
  app.includeStandardAdditions = true;
  try {
    app.doShellScript("/usr/bin/osascript '" + path + "'");
  } catch (e) {
    throw new Error(String(e) + " (script kept: " + path + ")");
  }
  $.NSFileManager.defaultManager.removeItemAtPathError(path, null);
}

function slidesInPlan(transforms) {
  const set = {};
  for (let t = 0; t < transforms.length; t++) {
    const n = Number(transforms[t].slide);
    if (!isNaN(n)) set[n] = true;
  }
  return Object.keys(set)
    .map(Number)
    .sort(function (a, b) {
      return a - b;
    });
}

function transformsForSlide(transforms, slideNo) {
  const out = [];
  for (let t = 0; t < transforms.length; t++) {
    if (Number(transforms[t].slide) === slideNo) out.push(transforms[t]);
  }
  return out;
}

function setSlideSize(doc, width, height) {
  try {
    doc.width = width;
    doc.height = height;
    return "width";
  } catch (e1) {}
  try {
    doc.slideWidth = width;
    doc.slideHeight = height;
    return "slideWidth";
  } catch (e2) {}
  return "";
}

function wantedSet(nums) {
  const set = {};
  for (let i = 0; i < (nums || []).length; i++) set[Number(nums[i])] = true;
  return set;
}

function wantedFromPlan(plan, fallbackN) {
  if (plan.slides && plan.slides.length) {
    return plan.slides.map(Number).filter(function (n) {
      return n >= 1;
    });
  }
  if (plan.range && plan.range.length >= 2) {
    const a = Number(plan.range[0]);
    const b = Number(plan.range[1]);
    const out = [];
    for (let n = a; n <= b; n++) out.push(n);
    return out;
  }
  const out = [];
  for (let n = 1; n <= fallbackN; n++) out.push(n);
  return out;
}

function skipOutsideRange(slides, wanted) {
  const set = wantedSet(wanted);
  const n = countOf(slides);
  let skipped = 0;
  for (let i = 0; i < n; i++) {
    const hide = !set[i + 1];
    try {
      slides[i].skipped = hide;
      if (hide) skipped += 1;
    } catch (e) {}
  }
  return skipped;
}

function readMapGeom(slides, transforms) {
  for (let t = 0; t < transforms.length; t++) {
    const spec = transforms[t];
    if (spec.role !== "map") continue;
    const slideNo = Number(spec.slide) || 1;
    if (slideNo < 1 || slideNo > countOf(slides)) return null;
    const obj = getItem(slides[slideNo - 1], spec);
    if (!obj) return null;
    const pos = xyOf(obj);
    let w = 0;
    let h = 0;
    try {
      w = Number(obj.width());
    } catch (eW) {}
    try {
      h = Number(obj.height());
    } catch (eH) {}
    return { x: pos[0], y: pos[1], w: w, h: h, planned: { x: spec.x, y: spec.y, w: spec.w, h: spec.h } };
  }
  return null;
}

function applyTransforms(slides, transforms, collectionsOut, missReasons, mode) {
  mode = mode || "full";
  let applied = 0;
  let missed = 0;
  const cache = mode === "attrs" ? {} : null;
  for (let t = 0; t < transforms.length; t++) {
    const spec = transforms[t];
    const slideNo = Number(spec.slide) || 1;
    if (slideNo < 1 || slideNo > countOf(slides)) {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push("slide " + slideNo + " out of range (" + countOf(slides) + ")");
      }
      continue;
    }
    const slide = slides[slideNo - 1];
    if (collectionsOut && !Object.keys(collectionsOut).length) {
      const counts = collectionCounts(slide);
      Object.keys(counts).forEach(function (k) {
        collectionsOut[k] = counts[k];
      });
    }
    // Hides are deleted, not opacity 0 (ghosts still catch clicks). Defer to deleteHides after geometry so kindIndex lookups stay valid.
    if (spec.role === "hide") continue;
    const obj = getItem(slide, spec, cache && (cache[slideNo] || (cache[slideNo] = {})));
    if (!obj) {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push(
          "slide " + slideNo + " " + (spec.kind || "item") + "[" + spec.kindIndex + "] missing"
        );
      }
      continue;
    }
    if (mode === "attrs" && !writesAttrs(spec)) {
      applied += 1;
      continue;
    }
    const _t0 = TIMING ? _now() : 0;
    const wrote = applyGeom(obj, spec, mode);
    if (TIMING) {
      _trec("apply:" + mode, _now() - _t0, {
        op: "apply:" + mode,
        slide: slideNo,
        kind: spec.kind,
        kindIndex: spec.kindIndex,
        role: spec.role || "",
        x: Math.round(Number(spec.x) || 0),
        y: Math.round(Number(spec.y) || 0),
      });
    }
    if (wrote || mode === "attrs") {
      applied += 1;
    } else {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push("slide " + slideNo + " " + (spec.kind || "item") + " geom failed");
      }
    }
  }
  return { applied: applied, missed: missed };
}

function deleteHides(slides, Keynote, transforms, missReasons) {
  // deleteHides after both geometry passes, grouped by (slide, kind), descending kindIndex so remaining indices stay valid.
  const hides = [];
  for (let t = 0; t < transforms.length; t++) {
    const spec = transforms[t];
    if (spec.role !== "hide") continue;
    const slideNo = Number(spec.slide) || 1;
    if (slideNo >= 1 && slideNo <= countOf(slides)) hides.push(spec);
  }
  hides.sort(function (a, b) {
    if (Number(a.slide) !== Number(b.slide)) return Number(b.slide) - Number(a.slide);
    const ka = String(a.kind || "");
    const kb = String(b.kind || "");
    if (ka !== kb) return ka < kb ? -1 : 1;
    return Number(b.kindIndex) - Number(a.kindIndex);
  });
  let applied = 0;
  let missed = 0;
  for (let i = 0; i < hides.length; i++) {
    const slide = slides[Number(hides[i].slide) - 1];
    const obj = getItem(slide, hides[i]);
    const _t0 = TIMING ? _now() : 0;
    const _okDel = deleteObj(Keynote, obj);
    if (TIMING) {
      _trec("deleteHide", _now() - _t0, {
        op: "deleteHide",
        slide: Number(hides[i].slide),
        kind: hides[i].kind,
        kindIndex: hides[i].kindIndex,
        role: "hide",
        x: Math.round(Number(hides[i].x) || 0),
        y: Math.round(Number(hides[i].y) || 0),
      });
    }
    if (_okDel) {
      applied += 1;
    } else {
      if (obj) {
        try {
          obj.opacity = 0;
        } catch (eHideFallback) {}
      }
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push("slide " + hides[i].slide + " hide delete failed");
      }
    }
  }
  return { applied: applied, missed: missed };
}

function findLayout(doc, want) {
  if (!want) return null;
  try {
    const lays = doc.slideLayouts();
    for (let i = 0; i < countOf(lays); i++) {
      try {
        if (String(lays[i].name()) === want) return lays[i];
      } catch (e) {}
    }
  } catch (e2) {}
  return null;
}

function layoutNames(doc) {
  const out = [];
  try {
    const lays = doc.slideLayouts();
    for (let i = 0; i < countOf(lays); i++) {
      try {
        out.push(String(lays[i].name()));
      } catch (e) {}
    }
  } catch (e2) {}
  return out;
}

function cgLayoutName(name) {
  const n = String(name || "");
  if (!n) return "";
  if (/\(16:9\)\s*$/.test(n)) return n;
  return n + " (16:9)";
}

function findSlideWithLayout(doc, name) {
  const slides = doc.slides();
  for (let i = 0; i < countOf(slides); i++) {
    try {
      if (String(slides[i].baseLayout().name()) === name) return slides[i];
    } catch (e) {}
  }
  return null;
}

function importCgLayouts(dest, tmpl, Keynote) {
  const imported = [];
  let tLays;
  try {
    tLays = tmpl.slideLayouts();
  } catch (e) {
    return imported;
  }
  for (let i = 0; i < countOf(tLays); i++) {
    let name = "";
    try {
      name = String(tLays[i].name());
    } catch (eN) {
      continue;
    }
    if (findLayout(dest, name)) {
      imported.push(name);
      continue;
    }
    let donor = findSlideWithLayout(tmpl, name);
    if (!donor) {
      try {
        tmpl.slides.push(Keynote.Slide({ baseLayout: tLays[i] }));
        donor = tmpl.slides()[countOf(tmpl.slides()) - 1];
      } catch (e2) {
        try {
          tmpl.slides.push(Keynote.Slide({ baseSlide: tLays[i] }));
          donor = tmpl.slides()[countOf(tmpl.slides()) - 1];
        } catch (e3) {
          continue;
        }
      }
    }
    try {
      Keynote.move(donor, { to: dest });
      imported.push(name);
    } catch (e4) {}
  }
  return imported;
}

function applyCgLayouts(dest, origCount, wanted) {
  const slides = dest.slides();
  const n = Math.min(countOf(slides), origCount);
  const set = wantedSet(wanted);
  const applied = [];
  for (let i = 0; i < n; i++) {
    if (!set[i + 1]) continue;
    try {
      const cur = String(slides[i].baseLayout().name());
      const want = cgLayoutName(cur);
      const lay = findLayout(dest, want);
      if (!lay) continue;
      slides[i].baseLayout = lay;
      applied.push({ slide: i + 1, from: cur, to: String(slides[i].baseLayout().name()) });
    } catch (e) {}
  }
  return applied;
}

function deleteTrailingSlides(dest, Keynote, keepCount) {
  let deleted = 0;
  while (countOf(dest.slides()) > keepCount) {
    const slides = dest.slides();
    const last = slides[countOf(slides) - 1];
    try {
      Keynote.delete(last);
    } catch (e) {
      try {
        last.delete();
      } catch (e2) {
        break;
      }
    }
    deleted += 1;
    if (deleted > 80) break;
  }
  return deleted;
}

function runSlideGeomScript(doc, asGeom, n, missReasons) {
  if (!asGeom) return;
  const body = asGeom[n];
  if (!body) return;
  try {
    runAppleScript(doc, body);
  } catch (eGeom) {
    if (missReasons.length < 8) {
      missReasons.push("slide " + n + " AppleScript geometry failed: " + eGeom);
    }
  }
}

// "attrs" wins over asGeom: without suppress, empty-asGeom falls through to JXA full path.
function geometryPathForSlide(n, asGeom, suppressGeometry) {
  if (suppressGeometry && suppressGeometry.indexOf(n) !== -1) return "attrs";
  if (asGeom && asGeom[n]) return "as";
  return "jxa";
}

function applyNonReuseSlide(
  doc, Keynote, n, transforms, collectionsOut, missReasons, asGeom, suppressGeometry
) {
  const specs = transformsForSlide(transforms, n);
  let applied = 0;
  let missed = 0;
  const path = geometryPathForSlide(n, asGeom, suppressGeometry);
  if (path === "attrs") {
    const _ta = _now();
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "attrs");
    _stage("attrs", _ta);
    if (TIMING) _trec("phase:attrsSuppressed:slide" + n, _now() - _ta, null);
    applied += r.applied;
    missed += r.missed;
  } else if (path === "as") {
    const _ta = _now();
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "attrs");
    _stage("attrs", _ta);
    if (TIMING) _trec("phase:attrs:slide" + n, _now() - _ta, null);
    applied += r.applied;
    missed += r.missed;
    const _tg = _now();
    runSlideGeomScript(doc, asGeom, n, missReasons);
    _stage("asScript", _tg);
    if (TIMING) _trec("phase:asGeomScript:slide" + n, _now() - _tg, null);
    // AppleScript geometry does not yank, so the first position write sticks.
  } else {
    const _tf = _now();
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "full");
    _stage("attrs", _tf);
    if (TIMING) _trec("phase:jxaFull:slide" + n, _now() - _tf, null);
    applied += r.applied;
    missed += r.missed;
    const _tp = _now();
    applyTransforms(doc.slides(), specs, null, missReasons, "pos");
    _stage("attrs", _tp);
    if (TIMING) _trec("phase:jxaPos:slide" + n, _now() - _tp, null);
  }
  const _td = _now();
  const rd = deleteHides(doc.slides(), Keynote, specs, missReasons);
  _stage("hides", _td);
  if (TIMING) _trec("phase:deleteHides:slide" + n, _now() - _td, null);
  applied += rd.applied;
  missed += rd.missed;
  return { applied: applied, missed: missed };
}

function run(argv) {
  _resetStages();
  const tRun = _now();
  const plan = readJSON(argv[0]);
  TIMING = plan.timing
    ? { buckets: {}, slow: [], slowMs: Number(plan.timing.slowMs) || 120 }
    : null;
  KEYNOTE_BUNDLE_ID = plan.bundleId || KEYNOTE_BUNDLE_ID;
  const Keynote = Application(KEYNOTE_BUNDLE_ID);
  Keynote.includeStandardAdditions = true;
  let t0 = _now();
  const doc = Keynote.open(Path(plan.dest));
  _stage("open", t0);
  const transforms = plan.transforms || [];
  const asGeom = plan.asGeom || null;
  const suppressGeometry = plan.suppressGeometry || null;
  const width = Number(plan.width) || 1920;
  const height = Number(plan.height) || 1080;
  const collections = {};
  const missReasons = [];
  const layoutReport = { imported: [], applied: [], extraDeleted: 0, names: [] };
  t0 = _now();
  const sizeProp = setSlideSize(doc, width, height);
  let actualWidth = width;
  let actualHeight = height;
  try {
    actualWidth = Number(doc.width()) || width;
    actualHeight = Number(doc.height()) || height;
  } catch (eSz) {}
  _stage("slideSize", t0);
  const origN = countOf(doc.slides());
  const wanted = wantedFromPlan(plan, origN);
  if (plan.template) {
    let templateDoc = null;
    try {
      t0 = _now();
      try {
        templateDoc = Keynote.open(Path(plan.template));
      } finally {
        _stage("templateOpen", t0);
      }
      t0 = _now();
      try {
        layoutReport.imported = importCgLayouts(doc, templateDoc, Keynote);
      } finally {
        _stage("layoutImport", t0);
      }
      t0 = _now();
      try {
        layoutReport.applied = applyCgLayouts(doc, origN, wanted);
      } finally {
        _stage("layoutApply", t0);
      }
      t0 = _now();
      try {
        layoutReport.extraDeleted = deleteTrailingSlides(doc, Keynote, origN);
        layoutReport.names = layoutNames(doc);
      } finally {
        _stage("trailingDelete", t0);
      }
    } catch (eLay) {
      layoutReport.error = String(eLay);
    }
    if (templateDoc) {
      t0 = _now();
      try {
        Keynote.close(templateDoc, { saving: "no" });
      } catch (eT) {}
      _stage("templateClose", t0);
    }
  }
  const order = slidesInPlan(transforms);
  let appliedFirst = 0;
  let missedFirst = 0;
  for (let i = 0; i < order.length; i++) {
    const n = order[i];
    const rn = applyNonReuseSlide(
      doc, Keynote, n, transforms, collections, missReasons, asGeom, suppressGeometry
    );
    appliedFirst += rn.applied;
    missedFirst += rn.missed;
  }
  if (appliedFirst === 0) {
    try {
      Keynote.close(doc, { saving: "no" });
    } catch (eAbort) {}
    _stage("total", tRun);
    return JSON.stringify({
      dest: plan.dest,
      applied: 0,
      missed: missedFirst,
      width: actualWidth,
      height: actualHeight,
      sizeProp: sizeProp,
      collections: collections,
      missReasons: missReasons,
      layouts: layoutReport,
      saved: false,
      stages: STAGES,
      saveRetried: false,
      saveFirstError: null,
    });
  }
  t0 = _now();
  const mapReadback = readMapGeom(doc.slides(), transforms);
  let skippedSlides = 0;
  skippedSlides = skipOutsideRange(doc.slides(), wanted);
  _stage("finish", t0);
  let saved = true;
  let saveError = null;
  let saveRetried = false;
  let saveFirstError = null;
  t0 = _now();
  try {
    Keynote.save(doc);
  } catch (eSave) {
    saveRetried = true;
    saveFirstError = String(eSave);
    try {
      Keynote.save(doc, { in: Path(plan.dest) });
    } catch (eSave2) {
      saved = false;
      saveError = String(eSave2);
    }
  }
  _stage("save", t0);
  let closed = true;
  let closeError = null;
  t0 = _now();
  try {
    Keynote.close(doc, { saving: "yes" });
    if (!saved) {
      saved = true;
    }
  } catch (eClose) {
    closed = false;
    closeError = String(eClose);
  }
  _stage("close", t0);
  _stage("total", tRun);
  return JSON.stringify({
    dest: plan.dest,
    applied: appliedFirst,
    missed: missedFirst,
    width: actualWidth,
    height: actualHeight,
    sizeProp: sizeProp,
    collections: collections,
    missReasons: missReasons,
    skippedSlides: skippedSlides,
    mapReadback: mapReadback,
    layouts: layoutReport,
    saved: saved,
    saveError: saveError,
    closed: closed,
    closeError: closeError,
    timing: TIMING,
    stages: STAGES,
    saveRetried: saveRetried,
    saveFirstError: saveFirstError,
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    geometryPathForSlide: geometryPathForSlide,
    collectionCounts: collectionCounts,
    countOrUnreadable: countOrUnreadable,
    tempScriptPath: tempScriptPath,
    applyGeom: applyGeom,
    applyGroupChildren: applyGroupChildren,
    applyTransforms: applyTransforms,
    writesAttrs: writesAttrs,
    slidesInPlan: slidesInPlan,
    applyNonReuseSlide: applyNonReuseSlide,
    _stage: _stage,
    _resetStages: _resetStages,
    STAGES: STAGES,
    setTiming: function (t) {
      TIMING = t;
    },
  };
}
