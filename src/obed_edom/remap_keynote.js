// Remap write pass. Address by bundle id, never by name.
// JXA size-before-position yanks to (0,0). Delete highest-index first.
if (typeof ObjC !== "undefined") ObjC.import("Foundation");

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

function matchesRect(x, y, w, h, rect, tol) {
  const t = tol != null ? Number(tol) : 4;
  return (
    Math.abs(x - Number(rect.x)) <= t &&
    Math.abs(y - Number(rect.y)) <= t &&
    Math.abs(w - Number(rect.w)) <= t &&
    Math.abs(h - Number(rect.h)) <= t
  );
}

// Reuse-donor copies drift; resolve removals by live output rect, not wall kindIndex. tol=4px.
function itemsByGeom(slide, kind, rect, tol) {
  const out = [];
  const col = collectionNamed(slide, kindColName(kind));
  const n = countOf(col);
  const t = tol != null ? Number(tol) : 4;
  for (let i = 0; i < n; i++) {
    const obj = itemAt(col, i);
    if (!obj) continue;
    const p = xyOf(obj);
    const wh = whOf(obj);
    if (matchesRect(p[0], p[1], wh[0], wh[1], rect, t)) {
      out.push({ obj: obj, index: i });
    }
  }
  return out;
}

function getItemByGeom(slide, kind, rect, tol) {
  const hits = itemsByGeom(slide, kind, rect, tol);
  return hits.length ? hits[0].obj : null;
}

function refHasGeom(ref) {
  return ref != null && ref.x != null && ref.y != null && ref.w != null && ref.h != null;
}

function deleteRefs(Keynote, slide, refs, flags, tally) {
  const all = refs || [];
  const indexRefs = [];
  const geomRefs = [];
  for (let i = 0; i < all.length; i++) {
    if (refHasGeom(all[i])) geomRefs.push(all[i]);
    else indexRefs.push(all[i]);
  }
  let n = 0;
  // Index-addressed deletes: highest kindIndex first so lower live indices stay valid.
  const ordered = indexRefs.slice().sort(function (a, b) {
    const ka = String(a.kind || "");
    const kb = String(b.kind || "");
    if (ka !== kb) return ka < kb ? -1 : 1;
    return Number(b.kindIndex) - Number(a.kindIndex);
  });
  for (let i = 0; i < ordered.length; i++) {
    if (deleteObj(Keynote, getItem(slide, ordered[i]))) {
      n += 1;
      if (tally) {
        const k = String(ordered[i].kind || "item");
        tally[k] = (tally[k] || 0) + 1;
      }
    }
  }
  // Geometry-addressed reuse removals: delete only when live match count equals ref count; else fail loud, never guess.
  const groups = {};
  const order = [];
  for (let i = 0; i < geomRefs.length; i++) {
    const r = geomRefs[i];
    const key =
      String(r.kind || "") +
      "|" +
      Math.round(Number(r.x)) +
      "|" +
      Math.round(Number(r.y)) +
      "|" +
      Math.round(Number(r.w)) +
      "|" +
      Math.round(Number(r.h));
    if (!groups[key]) {
      groups[key] = [];
      order.push(key);
    }
    groups[key].push(r);
  }
  const snapByKind = {};
  function snapshotFor(kind) {
    if (snapByKind[kind]) return snapByKind[kind];
    const snap = [];
    const col = collectionNamed(slide, kindColName(kind));
    const cnt = countOf(col);
    for (let i = 0; i < cnt; i++) {
      const obj = itemAt(col, i);
      if (!obj) continue;
      const p = xyOf(obj);
      const wh = whOf(obj);
      snap.push({ obj: obj, index: i, x: p[0], y: p[1], w: wh[0], h: wh[1] });
    }
    snapByKind[kind] = snap;
    return snap;
  }
  for (let g = 0; g < order.length; g++) {
    const key = order[g];
    const grp = groups[key];
    const r0 = grp[0];
    const snap = snapshotFor(r0.kind);
    const hits = [];
    for (let s = 0; s < snap.length; s++) {
      const e = snap[s];
      if (e.deleted) continue;
      if (matchesRect(e.x, e.y, e.w, e.h, r0, 4)) {
        hits.push({ obj: e.obj, index: e.index, entry: e });
      }
    }
    if (hits.length === grp.length) {
      hits.sort(function (a, b) {
        return b.index - a.index;
      });
      for (let i = 0; i < hits.length; i++) {
        if (deleteObj(Keynote, hits[i].obj)) {
          n += 1;
          hits[i].entry.deleted = true;
          if (tally) {
            const k = String(r0.kind || "item");
            tally[k] = (tally[k] || 0) + 1;
          }
        }
      }
    } else if (flags && flags.length < 8) {
      flags.push(
        "reuse remove geom split: " +
          grp.length +
          " ref(s) vs " +
          hits.length +
          " live match(es) for " +
          r0.kind +
          " @ " +
          key +
          " — kept, no delete (fail loud)"
      );
    }
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
  // Reuse keeps JXA geometry: paste appends, so live index ≠ wall kindIndex the AppleScript block would use.
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

function stripBuildRefs(Keynote, slide, refs, flags) {
  const list = refs || [];
  if (list.length && flags && flags.length < 8) {
    flags.push(
      "stripBuilds non-empty (" +
        list.length +
        " ref(s)) on slide reuse: still wall-index addressed on the drifted copy — deferred (f) build work, verify before trusting"
    );
  }
  let n = 0;
  for (let i = 0; i < list.length; i++) {
    n += stripBuildsOf(Keynote, slide, getItem(slide, list[i]));
  }
  return n;
}

function runAppleScript(doc, body) {
  // Named document, not front. Script file is /tmp; never open a .key under /private/tmp.
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

function removeShortfallOf(refs, tally) {
  const list = refs || [];
  const expected = {};
  for (let i = 0; i < list.length; i++) {
    const k = String(list[i].kind || "item");
    expected[k] = (expected[k] || 0) + 1;
  }
  const removed = tally || {};
  const out = {};
  const keys = Object.keys(expected);
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    const got = Number(removed[k] || 0);
    out[k] = { expected: expected[k], removed: got, shortfall: expected[k] - got };
  }
  return out;
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
  let copy = slides[to - 1];
  let orig = slides[to];
  const removedByKind = {};
  const removed = deleteRefs(Keynote, copy, job.remove || [], missReasons, removedByKind);
  stripBuildRefs(Keynote, copy, job.stripBuilds || [], missReasons);
  slides = doc.slides();
  copy = slides[to - 1];
  orig = slides[to];
  const add = job.add || [];
  let applied = 0;
  let missed = 0;
  if (add.length) {
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
  return {
    ok: true,
    duplicated: 1,
    removed: removed,
    removeShortfall: removeShortfallOf(job.remove || [], removedByKind),
    applied: applied,
    missed: missed,
  };
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
    // Hides are deleted, not opacity 0 (ghosts still catch clicks). Defer to deleteHides after geometry so kindIndex lookups stay valid.
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
    const _ta = TIMING ? _now() : 0;
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "attrs");
    if (TIMING) _trec("phase:attrsSuppressed:slide" + n, _now() - _ta, null);
    applied += r.applied;
    missed += r.missed;
  } else if (path === "as") {
    const _ta = TIMING ? _now() : 0;
    const r = applyTransforms(doc.slides(), specs, collectionsOut, missReasons, "attrs");
    if (TIMING) _trec("phase:attrs:slide" + n, _now() - _ta, null);
    applied += r.applied;
    missed += r.missed;
    const _tg = TIMING ? _now() : 0;
    runSlideGeomScript(doc, asGeom, n, missReasons);
    if (TIMING) _trec("phase:asGeomScript:slide" + n, _now() - _tg, null);
    // AppleScript geometry does not yank, so the first position write sticks.
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
    ? { buckets: {}, slow: [], slowMs: Number(plan.timing.slowMs) || 120 }
    : null;
  KEYNOTE_BUNDLE_ID = plan.bundleId || KEYNOTE_BUNDLE_ID;
  const Keynote = Application(KEYNOTE_BUNDLE_ID);
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.dest));
  const transforms = plan.transforms || [];
  const asGeom = plan.asGeom || null;
  const suppressGeometry = plan.suppressGeometry || null;
  const width = Number(plan.width) || 1920;
  const height = Number(plan.height) || 1080;
  const collections = {};
  const missReasons = [];
  const layoutReport = { imported: [], applied: [], extraDeleted: 0, names: [] };
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
  const removeShortfalls = [];
  for (let i = 0; i < order.length; i++) {
    const n = order[i];
    if (reuseBy[n]) {
      const r = applyReuse(doc, Keynote, reuseBy[n], missReasons);
      if (r.ok) {
        cloned += r.duplicated || 0;
        appliedFirst += r.applied || 0;
        missedFirst += r.missed || 0;
        if (r.removeShortfall) removeShortfalls.push({ slide: n, byKind: r.removeShortfall });
      } else {
        const rf = applyNonReuseSlide(
          doc, Keynote, n, transforms, collections, missReasons, asGeom, suppressGeometry
        );
        appliedFirst += rf.applied;
        missedFirst += rf.missed;
      }
      continue;
    }
    const rn = applyNonReuseSlide(
      doc, Keynote, n, transforms, collections, missReasons, asGeom, suppressGeometry
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
      removeShortfalls: removeShortfalls,
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
    removeShortfalls: removeShortfalls,
    skippedSlides: skippedSlides,
    mapReadback: mapReadback,
    layouts: layoutReport,
    saved: true,
    timing: TIMING,
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    geometryPathForSlide: geometryPathForSlide,
    itemsByGeom: itemsByGeom,
    getItemByGeom: getItemByGeom,
    deleteRefs: deleteRefs,
    removeShortfallOf: removeShortfallOf,
  };
}
