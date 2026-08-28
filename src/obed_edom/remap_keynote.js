ObjC.import("Foundation");

// --- write-path timing (OBED_WRITE_TIMING) -------------------------------
// Null unless plan.timing is set. When on, records per-slide/per-phase elapsed
// and the individual objects slower than slowMs, so one run shows exactly which
// slide, phase, and objects eat the geometry-write time. Zero cost when off.
var TIMING = null;
function _now() {
  return +new Date();
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

// Set from the plan in run(). Keynote is addressed by bundle id because 15.x is
// "Keynote Creator Studio" under com.apple.Keynote while 14.x is
// com.apple.iWork.Keynote, and both answer to the name "Keynote".
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

function collectionNamed(slide, name) {
  try {
    return slide[name]();
  } catch (e) {}
  try {
    return slide[name];
  } catch (e2) {}
  return null;
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

function getItem(slide, spec) {
  const kind = spec.kind || "";
  const kindIndex = spec.kindIndex != null ? Number(spec.kindIndex) : Number(spec.itemIndex);
  const colName = kindColName(kind);
  if (colName && !isNaN(kindIndex)) {
    const typed = itemAt(collectionNamed(slide, colName), kindIndex);
    if (typed) return typed;
  }
  const itemIndex = Number(spec.itemIndex);
  if (!isNaN(itemIndex)) {
    return itemAt(collectionNamed(slide, "iWorkItems"), itemIndex);
  }
  return null;
}

function collectionCounts(slide) {
  const out = {};
  ["textItems", "images", "shapes", "movies", "groups", "lines", "iWorkItems"].forEach(function (name) {
    try {
      out[name] = countOf(collectionNamed(slide, name));
    } catch (e) {
      out[name] = -1;
    }
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
  // Some items treat position as the centre. Compensate using current size.
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

// mode selects what applyGeom writes:
//   "full"  — attributes (opacity/font/size/colour) AND geometry (w/h/position).
//             The original positionOnly=false behaviour.
//   "pos"   — position only. The original positionOnly=true behaviour.
//   "attrs" — attributes only, NO geometry. Used by the OBED_AS_GEOMETRY path so
//             the yank-free AppleScript geometry block owns w/h/position and this
//             JXA pass only touches the non-yanking attributes.
function applyGeom(obj, spec, mode) {
  mode = mode || "full";
  const writeAttrs = mode !== "pos"; // opacity/font/size/colour
  const writeSize = mode === "full"; // width/height (yanks in JXA — never in "attrs")
  const writePos = mode !== "attrs"; // position (yanks in JXA — never in "attrs")
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
  // Never set size in a position-only pass. Setting width/height yanks the object to (0,0).
  if (writeSize && spec.w != null) {
    try {
      obj.width = spec.w;
      ok = true;
    } catch (eW) {}
  }
  if (writeSize && spec.h != null) {
    try {
      obj.height = spec.h;
      ok = true;
    } catch (eH) {}
  }
  // Keynote 15.3.1 does not implement a line's endpoints: they read back null
  // even on a line created with them, and *writing* them collapses the line to
  // one unit long. A 383px divider came out at w=1. `width` is the length —
  // Keynote reports it that way whichever direction the line runs — and setting
  // it works, so the size pass above is what places a rule. (AppleScript CAN set
  // a line's start/end points, so the OBED_AS_GEOMETRY block uses those instead.)
  // See scripts/probe_line.js.
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
  if (writePos && spec.role !== "hide" && spec.x != null && spec.y != null) {
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

function deleteRefs(Keynote, slide, refs) {
  const ordered = (refs || []).slice().sort(function (a, b) {
    const ka = String(a.kind || "");
    const kb = String(b.kind || "");
    if (ka !== kb) return ka < kb ? -1 : 1;
    return Number(b.kindIndex) - Number(a.kindIndex);
  });
  let n = 0;
  for (let i = 0; i < ordered.length; i++) {
    if (deleteObj(Keynote, getItem(slide, ordered[i]))) n += 1;
  }
  return n;
}

function textLookup(slide) {
  const map = {};
  const col = collectionNamed(slide, "textItems");
  for (let i = 0; i < countOf(col); i++) {
    const obj = itemAt(col, i);
    if (!obj) continue;
    try {
      const key = String(obj.objectText()).trim();
      if (key && map[key] == null) map[key] = obj;
    } catch (e) {}
  }
  return map;
}

function keystroke(cmd) {
  const SE = Application("System Events");
  SE.keystroke(cmd, { using: "command down" });
}

function applySpec(obj, spec) {
  // The reuse path keeps the JXA geometry writes (full pass, then a position-only
  // restore) regardless of OBED_AS_GEOMETRY: pasted/mutated objects land at the
  // end of their collection, so their live index no longer equals the wall
  // kindIndex the AppleScript block would address. See the summary's reuse note.
  if (!obj || !spec || spec.x == null) return false;
  const a = applyGeom(obj, spec, "full");
  applyGeom(obj, spec, "pos");
  return a;
}

function stripBuildsOf(Keynote, slide, obj) {
  if (!obj) return 0;
  let n = 0;
  for (let guard = 0; guard < 40; guard++) {
    const builds = collectionNamed(slide, "builds");
    let found = null;
    for (let i = countOf(builds) - 1; i >= 0; i--) {
      const b = itemAt(builds, i);
      if (!b) continue;
      try {
        const target = b.object();
        if (target === obj) {
          found = b;
          break;
        }
      } catch (e) {}
    }
    if (!found) break;
    if (deleteObj(Keynote, found)) n += 1;
    else break;
  }
  return n;
}

function stripBuildRefs(Keynote, slide, refs) {
  let n = 0;
  for (let i = 0; i < (refs || []).length; i++) {
    n += stripBuildsOf(Keynote, slide, getItem(slide, refs[i]));
  }
  return n;
}

function runAppleScript(doc, body) {
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
  const ns = $.NSString.stringWithString(script);
  ns.writeToFileAtomicallyEncodingError(
    "/tmp/obed-edom-keynote.applescript",
    true,
    $.NSUTF8StringEncoding,
    null
  );
  const app = Application.currentApplication();
  app.includeStandardAdditions = true;
  app.doShellScript("/usr/bin/osascript /tmp/obed-edom-keynote.applescript");
}

function applyReuse(doc, Keynote, job, missReasons) {
  const from = Number(job.from);
  const to = Number(job.slide);
  let slides = doc.slides();
  if (from < 1 || to < 1 || from > countOf(slides) || to > countOf(slides)) {
    return { ok: false, duplicated: 0, applied: 0, missed: 1 };
  }
  const nBefore = countOf(slides);
  try {
    Keynote.activate();
    runAppleScript(doc, "duplicate slide " + from + " to before slide " + to);
  } catch (eDup) {
    if (missReasons.length < 8) missReasons.push("duplicate slide " + from + " failed: " + eDup);
    return { ok: false, duplicated: 0, applied: 0, missed: 1 };
  }
  slides = doc.slides();
  if (countOf(slides) !== nBefore + 1) {
    return { ok: false, duplicated: 0, applied: 0, missed: 1 };
  }
  // copy sits at `to`; the original wall slide shifted to `to + 1`.
  let copy = slides[to - 1];
  let orig = slides[to];
  const removed = deleteRefs(Keynote, copy, job.remove || []);
  stripBuildRefs(Keynote, copy, job.stripBuilds || []);
  slides = doc.slides();
  copy = slides[to - 1];
  orig = slides[to];
  const add = job.add || [];
  let applied = 0;
  let missed = 0;
  if (add.length) {
    // Rearrange the delta on the original slide (kindIndex from wall inspect),
    // then paste those already-placed objects onto the remapped donor copy.
    for (let i = 0; i < add.length; i++) {
      const spec = add[i];
      const obj = getItem(orig, spec);
      if (!obj || spec.x == null) {
        if (spec.x != null) missed += 1;
        continue;
      }
      if (applySpec(obj, spec)) applied += 1;
      else missed += 1;
    }
    deleteRefs(Keynote, orig, job.strip || []);
    delay(0.3);
    try {
      Keynote.activate();
      doc.currentSlide = orig;
      delay(0.25);
      keystroke("a");
      delay(0.2);
      keystroke("c");
      delay(0.25);
      doc.currentSlide = copy;
      delay(0.25);
      keystroke("v");
      delay(0.6);
    } catch (ePaste) {
      if (missReasons.length < 8) missReasons.push("paste delta slide " + to + ": " + ePaste);
    }
    slides = doc.slides();
    copy = slides[to - 1];
    orig = slides[to];
  }
  const mutate = job.mutate || [];
  if (mutate.length) {
    const byText = textLookup(copy);
    for (let i = 0; i < mutate.length; i++) {
      const spec = mutate[i];
      let obj = spec.matchText ? byText[String(spec.matchText).trim()] : null;
      if (!obj) obj = getItem(copy, spec);
      if (!obj || spec.x == null) {
        if (!obj && spec.x != null) missed += 1;
        continue;
      }
      if (applySpec(obj, spec)) applied += 1;
      else missed += 1;
    }
  }
  try {
    runAppleScript(doc, "delete slide " + (to + 1));
  } catch (eDel) {
    slides = doc.slides();
    const leftover = slides[to];
    if (leftover) deleteObj(Keynote, leftover);
  }
  return { ok: true, duplicated: 1, removed: removed, applied: applied, missed: missed };
}

function slidesInPlan(transforms, reuses) {
  const set = {};
  for (let t = 0; t < transforms.length; t++) {
    const n = Number(transforms[t].slide);
    if (!isNaN(n)) set[n] = true;
  }
  for (let i = 0; i < (reuses || []).length; i++) {
    const n = Number(reuses[i].slide);
    const f = Number(reuses[i].from);
    if (!isNaN(n)) set[n] = true;
    if (!isNaN(f)) set[f] = true;
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
    // Every hidden object is deleted, not left at opacity 0. An invisible leftover
    // still catches clicks, so the operator ends up selecting a zero-opacity ghost
    // instead of the text they want to edit. (A group never honoured opacity anyway,
    // and the canvas shrink would scale a "hidden" grouped inset back on-frame.)
    // Deletion is deferred to deleteHides, after both geometry passes, so removing
    // one never shifts the kindIndex a placed sibling is looked up by here.
    if (spec.role === "hide") continue;
    const obj = getItem(slide, spec);
    if (!obj) {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push(
          "slide " + slideNo + " " + (spec.kind || "item") + "[" + spec.kindIndex + "] missing"
        );
      }
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
    // In "attrs" mode geometry is written by the AppleScript block, not here, so a
    // resolved object counts as applied even when it carries no JXA attribute to
    // set (a map/pin has no opacity/font). Otherwise every geometry-only object
    // would be miscounted as missed and could trip the "moved 0 objects" abort.
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
  // Remove every object marked role="hide", after both geometry passes have read the
  // collection by its original indices. Grouped by (slide, kind) and descending by
  // kindIndex within each, so each deletion leaves the lower indices of the ones
  // still to go — in that same per-kind collection — valid.
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
      // Last resort if Keynote refuses the delete: pin it invisible so a hide that
      // cannot be removed does not reappear on the CG. (No help for a group, which
      // ignores opacity — but those were always delete-or-nothing.)
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
  // Run the Python-built batched geometry block for slide n against the open doc.
  // Built in Python (see remap_keynote.py) so a pytest can lock the string, and
  // safe to address by number because non-reuse slide numbering is stable.
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

function applyNonReuseSlide(doc, Keynote, n, transforms, collectionsOut, missReasons, asGeom) {
  const specs = transformsForSlide(transforms, n);
  let applied = 0;
  let missed = 0;
  // Decide the path PER SLIDE, not on a global flag: use the AppleScript geometry
  // path only when Python built a body for this slide (i.e. every geometry-bearing
  // object on it is AppleScript-addressable). A slide with any unaddressable kind
  // has no body here and falls through to the JXA full path, so no object ever
  // silently loses its geometry. Flag OFF ⇒ asGeom is null ⇒ always the JXA path.
  const asBody = asGeom ? asGeom[n] : null;
  if (asBody) {
    // JXA writes only the non-yanking attributes (opacity/font/size/colour); the
    // batched AppleScript block owns w/h/position and addresses `slide n` — the
    // SAME live slide JXA just resolved, since the reuse path restores slide
    // numbering before the next slide runs, so a non-reuse slide's live index
    // always equals its wall slide number n.
    const _ta = TIMING ? _now() : 0;
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "attrs");
    if (TIMING) _trec("phase:attrs:slide" + n, _now() - _ta, null);
    applied += r.applied;
    missed += r.missed;
    const _tg = TIMING ? _now() : 0;
    runSlideGeomScript(doc, asGeom, n, missReasons);
    if (TIMING) _trec("phase:asGeomScript:slide" + n, _now() - _tg, null);
    // No position-only restore pass: AppleScript geometry does not yank, so the
    // first position write sticks.
  } else {
    const _tf = TIMING ? _now() : 0;
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "full");
    if (TIMING) _trec("phase:jxaFull:slide" + n, _now() - _tf, null);
    applied += r.applied;
    missed += r.missed;
    const _tp = TIMING ? _now() : 0;
    applyTransforms(doc.slides(), specs, null, missReasons, "pos");
    if (TIMING) _trec("phase:jxaPos:slide" + n, _now() - _tp, null);
  }
  const _td = TIMING ? _now() : 0;
  const rd = deleteHides(doc.slides(), Keynote, specs, missReasons);
  if (TIMING) _trec("phase:deleteHides:slide" + n, _now() - _td, null);
  applied += rd.applied;
  missed += rd.missed;
  return { applied: applied, missed: missed };
}

function run(argv) {
  const plan = readJSON(argv[0]);
  TIMING = plan.timing
    ? { buckets: {}, slow: [], slowMs: Number(plan.timing.slowMs) || 150 }
    : null;
  KEYNOTE_BUNDLE_ID = plan.bundleId || KEYNOTE_BUNDLE_ID;
  const Keynote = Application(KEYNOTE_BUNDLE_ID);
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.dest));
  const transforms = plan.transforms || [];
  // OBED_AS_GEOMETRY path: Python passes a per-slide map of pre-built AppleScript
  // geometry bodies (only for slides where every geometry-bearing object is
  // addressable). Absent ⇒ null ⇒ byte-for-byte the JXA geometry behaviour. The
  // per-slide decision lives in applyNonReuseSlide, keyed on asGeom[n].
  const asGeom = plan.asGeom || null;
  const width = Number(plan.width) || 1920;
  const height = Number(plan.height) || 1080;
  const collections = {};
  const missReasons = [];
  const layoutReport = { imported: [], applied: [], extraDeleted: 0, names: [] };
  // Change canvas first. Keynote scale-to-fits into a 1920×270 strip; we then
  // apply the template crop (map may be larger than the slide, with negative x).
  const sizeProp = setSlideSize(doc, width, height);
  let actualWidth = width;
  let actualHeight = height;
  try {
    actualWidth = Number(doc.width()) || width;
    actualHeight = Number(doc.height()) || height;
  } catch (eSz) {}
  const origN = countOf(doc.slides());
  const wanted = wantedFromPlan(plan, origN);
  if (plan.template) {
    let templateDoc = null;
    try {
      templateDoc = Keynote.open(Path(plan.template));
      layoutReport.imported = importCgLayouts(doc, templateDoc, Keynote);
      layoutReport.applied = applyCgLayouts(doc, origN, wanted);
      layoutReport.extraDeleted = deleteTrailingSlides(doc, Keynote, origN);
      layoutReport.names = layoutNames(doc);
    } catch (eLay) {
      layoutReport.error = String(eLay);
    }
    if (templateDoc) {
      try {
        Keynote.close(templateDoc, { saving: "no" });
      } catch (eT) {}
    }
  }
  const reuses = plan.reuses || [];
  const reuseBy = {};
  for (let i = 0; i < reuses.length; i++) {
    reuseBy[Number(reuses[i].slide)] = reuses[i];
  }
  const order = slidesInPlan(transforms, reuses);
  let cloned = 0;
  let appliedFirst = 0;
  let missedFirst = 0;
  for (let i = 0; i < order.length; i++) {
    const n = order[i];
    if (reuseBy[n]) {
      const r = applyReuse(doc, Keynote, reuseBy[n], missReasons);
      if (r.ok) {
        cloned += r.duplicated || 0;
        appliedFirst += r.applied || 0;
        missedFirst += r.missed || 0;
      } else {
        // Reuse failed: fall back to a fresh non-reuse remap of this slide. Its
        // live index is n (the failed reuse duplicated nothing), so the same
        // slide-number guarantee holds and AppleScript geometry is safe here too.
        const rf = applyNonReuseSlide(
          doc, Keynote, n, transforms, collections, missReasons, asGeom
        );
        appliedFirst += rf.applied;
        missedFirst += rf.missed;
      }
      continue;
    }
    const rn = applyNonReuseSlide(
      doc, Keynote, n, transforms, collections, missReasons, asGeom
    );
    appliedFirst += rn.applied;
    missedFirst += rn.missed;
  }
  if (appliedFirst === 0 && cloned === 0) {
    try {
      Keynote.close(doc, { saving: "no" });
    } catch (eAbort) {}
    return JSON.stringify({
      dest: plan.dest,
      cloned: cloned,
      applied: 0,
      missed: missedFirst,
      width: actualWidth,
      height: actualHeight,
      sizeProp: sizeProp,
      collections: collections,
      missReasons: missReasons,
      layouts: layoutReport,
      saved: false,
    });
  }
  const mapReadback = readMapGeom(doc.slides(), transforms);
  let skippedSlides = 0;
  skippedSlides = skipOutsideRange(doc.slides(), wanted);
  try {
    Keynote.save(doc);
  } catch (eSave) {
    try {
      Keynote.save(doc, { in: Path(plan.dest) });
    } catch (eSave2) {}
  }
  try {
    Keynote.close(doc, { saving: "yes" });
  } catch (eClose) {}
  return JSON.stringify({
    dest: plan.dest,
    cloned: cloned,
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
    saved: true,
    timing: TIMING,
  });
}
