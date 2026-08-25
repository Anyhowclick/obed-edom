ObjC.import("Foundation");

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

function applyGeom(obj, spec, positionOnly) {
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
  if (!positionOnly && spec.opacity != null) {
    try {
      obj.opacity = spec.opacity;
      ok = true;
    } catch (eO) {}
  }
  // Never set size in a position-only pass. Setting width/height yanks the object to (0,0).
  if (!positionOnly && spec.w != null) {
    try {
      obj.width = spec.w;
      ok = true;
    } catch (eW) {}
  }
  if (!positionOnly && spec.h != null) {
    try {
      obj.height = spec.h;
      ok = true;
    } catch (eH) {}
  }
  if (!positionOnly && spec.start && spec.start.length >= 2) {
    try {
      obj.startPoint = spec.start;
      ok = true;
    } catch (eS) {}
  }
  if (!positionOnly && spec.end && spec.end.length >= 2) {
    try {
      obj.endPoint = spec.end;
      ok = true;
    } catch (eE) {}
  }
  if (!positionOnly && spec.font) {
    try {
      obj.objectText.font = spec.font;
    } catch (eFn) {}
  }
  if (!positionOnly && spec.fontSize) {
    try {
      obj.objectText.size = spec.fontSize;
    } catch (eF) {}
  }
  if (!positionOnly && spec.color && spec.color.length >= 3) {
    try {
      obj.objectText.color = spec.color;
    } catch (eC1) {
      try {
        obj.objectText.attributeRuns[0].color = spec.color;
      } catch (eC2) {}
    }
  }
  if (spec.role !== "hide" && spec.x != null && spec.y != null) {
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

function lineEnds(obj) {
  const out = {};
  try {
    const p = obj.startPoint();
    out.start = [Number(p[0]), Number(p[1])];
  } catch (eS) {}
  try {
    const p = obj.endPoint();
    out.end = [Number(p[0]), Number(p[1])];
  } catch (eE) {}
  return out;
}

function debugInteresting(spec) {
  return (
    spec.fontSize ||
    spec.role === "title" ||
    spec.kind === "text" ||
    spec.kind === "line" ||
    spec.kind === "group" ||
    (spec.kind === "image" && Number(spec.itemIndex) === 3)
  );
}

function applySpec(obj, spec) {
  if (!obj || !spec || spec.x == null) return false;
  const a = applyGeom(obj, spec, false);
  let afterSize = null;
  try {
    afterSize = { w: Number(obj.width()), h: Number(obj.height()), pos: xyOf(obj), ends: lineEnds(obj) };
  } catch (eMid) {}
  applyGeom(obj, spec, true);
  let afterPos = null;
  try {
    afterPos = { w: Number(obj.width()), h: Number(obj.height()), pos: xyOf(obj), ends: lineEnds(obj) };
  } catch (eEnd) {}
  // #region agent log
  if (debugInteresting(spec)) {
    try {
      const app = Application.currentApplication();
      app.includeStandardAdditions = true;
      const line =
        JSON.stringify({
          sessionId: "6310d1",
          runId: "pre-fix",
          hypothesisId: spec.kind === "line" ? "H22" : spec.kind === "group" ? "H23" : "H19",
          location: "remap_keynote.js:applySpec",
          message: "geom after size then position pass",
          data: {
            role: spec.role,
            kind: spec.kind,
            idx: spec.itemIndex,
            ki: spec.kindIndex,
            planned: {
              x: spec.x,
              y: spec.y,
              w: spec.w,
              h: spec.h,
              fontSize: spec.fontSize,
              start: spec.start || null,
              end: spec.end || null,
            },
            afterSize: afterSize,
            afterPos: afterPos,
          },
          timestamp: Date.now(),
        }) + "\n";
      app.doShellScript(
        "printf %s " +
          JSON.stringify(line) +
          " >> " +
          JSON.stringify("/Users/anyhowclick/Desktop/work/obed-edom/.cursor/debug-6310d1.log")
      );
    } catch (eLog) {}
  }
  // #endregion
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

function applyTransforms(slides, transforms, collectionsOut, missReasons, positionOnly) {
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
    const obj = getItem(slide, spec);
    if (!obj) {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push(
          "slide " + slideNo + " " + (spec.kind || "item") + "[" + spec.kindIndex + "] missing"
        );
      }
      // #region agent log
      if (debugInteresting(spec)) {
        try {
          const app = Application.currentApplication();
          app.includeStandardAdditions = true;
          const line =
            JSON.stringify({
              sessionId: "6310d1",
              runId: "pre-fix",
              hypothesisId: spec.kind === "line" ? "H22" : spec.kind === "group" ? "H20" : "H24",
              location: "remap_keynote.js:applyTransforms",
              message: "getItem missed",
              data: {
                role: spec.role,
                kind: spec.kind,
                idx: spec.itemIndex,
                ki: spec.kindIndex,
                positionOnly: !!positionOnly,
                planned: { x: spec.x, y: spec.y, w: spec.w, h: spec.h, start: spec.start || null, end: spec.end || null },
              },
              timestamp: Date.now(),
            }) + "\n";
          app.doShellScript(
            "printf %s " +
              JSON.stringify(line) +
              " >> " +
              JSON.stringify("/Users/anyhowclick/Desktop/work/obed-edom/.cursor/debug-6310d1.log")
          );
        } catch (eMiss) {}
      }
      // #endregion
      continue;
    }
    if (applyGeom(obj, spec, positionOnly)) {
      applied += 1;
      // #region agent log
      if (debugInteresting(spec)) {
        try {
          const got = {
            w: Number(obj.width()),
            h: Number(obj.height()),
            pos: xyOf(obj),
            ends: lineEnds(obj),
          };
          const app = Application.currentApplication();
          app.includeStandardAdditions = true;
          const line =
            JSON.stringify({
              sessionId: "6310d1",
              runId: "pre-fix",
              hypothesisId: spec.kind === "line" ? "H22" : spec.kind === "group" ? "H23" : "H19",
              location: "remap_keynote.js:applyTransforms",
              message: "readback after geom pass",
              data: {
                role: spec.role,
                kind: spec.kind,
                idx: spec.itemIndex,
                ki: spec.kindIndex,
                positionOnly: !!positionOnly,
                planned: {
                  x: spec.x,
                  y: spec.y,
                  w: spec.w,
                  h: spec.h,
                  fontSize: spec.fontSize,
                  start: spec.start || null,
                  end: spec.end || null,
                },
                got: got,
              },
              timestamp: Date.now(),
            }) + "\n";
          app.doShellScript(
            "printf %s " +
              JSON.stringify(line) +
              " >> " +
              JSON.stringify("/Users/anyhowclick/Desktop/work/obed-edom/.cursor/debug-6310d1.log")
          );
        } catch (eLog) {}
      }
      // #endregion
    } else {
      missed += 1;
      if (missReasons.length < 8) {
        missReasons.push("slide " + slideNo + " " + (spec.kind || "item") + " geom failed");
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

function run(argv) {
  const plan = readJSON(argv[0]);
  KEYNOTE_BUNDLE_ID = plan.bundleId || KEYNOTE_BUNDLE_ID;
  const Keynote = Application(KEYNOTE_BUNDLE_ID);
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.dest));
  const transforms = plan.transforms || [];
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
        const r2 = applyTransforms(
          doc.slides(),
          transformsForSlide(transforms, n),
          collections,
          missReasons,
          false
        );
        appliedFirst += r2.applied;
        missedFirst += r2.missed;
        applyTransforms(doc.slides(), transformsForSlide(transforms, n), null, missReasons, true);
      }
      continue;
    }
    const r = applyTransforms(
      doc.slides(),
      transformsForSlide(transforms, n),
      collections,
      missReasons,
      false
    );
    appliedFirst += r.applied;
    missedFirst += r.missed;
    applyTransforms(doc.slides(), transformsForSlide(transforms, n), null, missReasons, true);
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
  });
}
