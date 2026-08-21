ObjC.import("Foundation");

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
  if (!positionOnly && spec.fontSize) {
    try {
      obj.objectText.size = spec.fontSize;
    } catch (eF) {}
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

function skipOutsideRange(slides, fromSlide, toSlide) {
  const n = countOf(slides);
  let skipped = 0;
  for (let i = 0; i < n; i++) {
    const hide = i + 1 < fromSlide || i + 1 > toSlide;
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
      continue;
    }
    if (applyGeom(obj, spec, positionOnly)) {
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

function applyCgLayouts(dest, origCount, fromSlide, toSlide) {
  const slides = dest.slides();
  const n = Math.min(countOf(slides), origCount);
  const start = fromSlide ? Math.max(0, fromSlide - 1) : 0;
  const end = toSlide ? Math.min(toSlide, n) : n;
  const applied = [];
  for (let i = start; i < end; i++) {
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
  const Keynote = Application("Keynote");
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
  const range = plan.range || null;
  if (plan.template) {
    let templateDoc = null;
    try {
      templateDoc = Keynote.open(Path(plan.template));
      layoutReport.imported = importCgLayouts(doc, templateDoc, Keynote);
      layoutReport.applied = applyCgLayouts(
        doc,
        origN,
        range ? Number(range[0]) : 1,
        range ? Number(range[1]) : origN
      );
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
  const slides = doc.slides();
  const first = applyTransforms(slides, transforms, collections, missReasons, false);
  if (first.applied === 0) {
    try {
      Keynote.close(doc, { saving: "no" });
    } catch (eAbort) {}
    return JSON.stringify({
      dest: plan.dest,
      applied: 0,
      missed: first.missed,
      width: actualWidth,
      height: actualHeight,
      sizeProp: sizeProp,
      collections: collections,
      missReasons: missReasons,
      layouts: layoutReport,
      saved: false,
    });
  }
  const missAfter = [];
  // Size yanks position to (0,0). Restore x/y only on the second pass.
  const second = applyTransforms(slides, transforms, null, missAfter, true);
  const mapReadback = readMapGeom(slides, transforms);
  let skippedSlides = 0;
  if (range && range.length >= 2) {
    skippedSlides = skipOutsideRange(slides, Number(range[0]), Number(range[1]));
  }
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
    applied: second.applied || first.applied,
    missed: second.missed,
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
