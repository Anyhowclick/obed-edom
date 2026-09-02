// Full inspect. Address by bundle id, never by name.
// Bulk arrays must length-match the collection — a short zip silently shifts kindIndex.
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

function sizeOf(obj) {
  let w = 0;
  let h = 0;
  try {
    w = num(obj.width(), 0);
  } catch (e) {}
  try {
    h = num(obj.height(), 0);
  } catch (e) {}
  return [w, h];
}

// No per-run style from Keynote scripting (attributeRuns fails; String.prototype.bold is an HTML wrapper). Whole-item font/size/color only.

function kindOf(obj) {
  let raw = "";
  try {
    raw = String(obj.class());
  } catch (e) {}
  const s = raw.toLowerCase();
  if (s.indexOf("text") >= 0) return "text";
  if (s.indexOf("image") >= 0 || s.indexOf("imag") >= 0) return "image";
  if (s.indexOf("movie") >= 0 || s.indexOf("shmv") >= 0) return "movie";
  if (s.indexOf("group") >= 0 || s.indexOf("igrp") >= 0) return "group";
  if (s.indexOf("line") >= 0 || s.indexOf("iwln") >= 0) return "line";
  if (s.indexOf("table") >= 0) return "table";
  if (s.indexOf("chart") >= 0) return "chart";
  if (s.indexOf("audio") >= 0) return "audio";
  if (s.indexOf("shape") >= 0 || s.indexOf("sshp") >= 0) return "shape";
  return s || "item";
}

function fileNameOf(obj) {
  try {
    const n = obj.fileName();
    if (n == null) return "";
    const s = String(n);
    if (s && s !== "[object Object]") return s;
  } catch (e) {}
  try {
    const f = obj.file();
    if (f && f.toString) {
      const s = String(f);
      if (s && s !== "[object Object]") return s;
    }
  } catch (e2) {}
  return "";
}

function describeItem(obj, index, kindHint) {
  const kind = kindHint || kindOf(obj);
  const rec = {
    index: index,
    kind: kind,
    text: "",
    x: 0,
    y: 0,
    w: 0,
    h: 0,
    size: 0,
    font: "",
    color: null,
    fileName: "",
    locked: false,
    rotation: 0,
    buildCount: 0,
  };
  const pos = positionOf(obj);
  rec.x = pos[0];
  rec.y = pos[1];
  const sz = sizeOf(obj);
  rec.w = sz[0];
  rec.h = sz[1];
  rec.fileName = fileNameOf(obj);
  try {
    rec.locked = Boolean(obj.locked());
  } catch (eLock) {}
  try {
    rec.rotation = num(obj.rotation(), 0);
  } catch (eRot) {}
  if (kind === "text" || kind === "shape") {
    try {
      rec.text = String(obj.objectText());
    } catch (e) {}
    try {
      rec.size = num(obj.objectText.size(), 0);
    } catch (eSize) {}
    try {
      rec.font = String(obj.objectText.font());
    } catch (eFont) {}
    try {
      const c = obj.objectText.color();
      if (c && c[0] != null) {
        rec.color = [num(c[0], 0), num(c[1], 0), num(c[2], 0)];
      }
    } catch (eCol) {}
  }
  if (kind === "line") {
    try {
      const pair = xyFrom(obj.startPoint());
      if (pair) rec.start = pair;
    } catch (eS) {}
    try {
      const pair = xyFrom(obj.endPoint());
      if (pair) rec.end = pair;
    } catch (eE) {}
  }
  if (kind === "group") {
    rec.children = [];
    try {
      const kids = obj.iWorkItems();
      rec.childCount = kids.length;
      for (let i = 0; i < kids.length; i++) {
        rec.children.push(describeItem(kids[i], i));
      }
    } catch (eG) {
      rec.childCount = 0;
    }
  }
  return rec;
}

// Bulk: one unevaluated collection specifier per property. Discard if length ≠ count — a short array would shift kindIndex.

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

function tryBulkNested(slide, name, prop, sub, count) {
  try {
    return bulkArray(slide[name][prop][sub](), count);
  } catch (e) {
    return null;
  }
}

function fetchBulkArrays(slide, name, kind, count) {
  const bulk = {};
  bulk.position = tryBulk(slide, name, "position", count);
  bulk.width = tryBulk(slide, name, "width", count);
  bulk.height = tryBulk(slide, name, "height", count);
  bulk.locked = tryBulk(slide, name, "locked", count);
  bulk.rotation = tryBulk(slide, name, "rotation", count);
  if (kind === "image" || kind === "movie") {
    bulk.fileName = tryBulk(slide, name, "fileName", count);
  }
  if (kind === "text" || kind === "shape") {
    bulk.text = tryBulk(slide, name, "objectText", count);
    bulk.size = tryBulkNested(slide, name, "objectText", "size", count);
    bulk.font = tryBulkNested(slide, name, "objectText", "font", count);
    bulk.color = tryBulkNested(slide, name, "objectText", "color", count);
  }
  if (kind === "line") {
    bulk.start = tryBulk(slide, name, "startPoint", count);
    bulk.end = tryBulk(slide, name, "endPoint", count);
  }
  return bulk;
}

function fileNameFrom(bulk, i, obj) {
  if (bulk.fileName) {
    const v = bulk.fileName[i];
    if (v != null) {
      const s = String(v);
      if (s && s !== "[object Object]") return s;
    }
  }
  return fileNameOf(obj);
}

function describeItemBulk(obj, index, kindHint, bulk, i) {
  const kind = kindHint || kindOf(obj);
  const rec = {
    index: index,
    kind: kind,
    text: "",
    x: 0,
    y: 0,
    w: 0,
    h: 0,
    size: 0,
    font: "",
    color: null,
    fileName: "",
    locked: false,
    rotation: 0,
    buildCount: 0,
  };
  const pos = bulk.position ? xyFrom(bulk.position[i]) || [0, 0] : positionOf(obj);
  rec.x = pos[0];
  rec.y = pos[1];
  let szCache = null;
  const sizePair = function () {
    if (!szCache) szCache = sizeOf(obj);
    return szCache;
  };
  rec.w = bulk.width ? num(bulk.width[i], 0) : sizePair()[0];
  rec.h = bulk.height ? num(bulk.height[i], 0) : sizePair()[1];
  rec.fileName = fileNameFrom(bulk, i, obj);
  if (bulk.locked) {
    rec.locked = Boolean(bulk.locked[i]);
  } else {
    try {
      rec.locked = Boolean(obj.locked());
    } catch (eLock) {}
  }
  if (bulk.rotation) {
    rec.rotation = num(bulk.rotation[i], 0);
  } else {
    try {
      rec.rotation = num(obj.rotation(), 0);
    } catch (eRot) {}
  }
  if (kind === "text" || kind === "shape") {
    if (bulk.text) {
      rec.text = String(bulk.text[i]);
    } else {
      try {
        rec.text = String(obj.objectText());
      } catch (e) {}
    }
    if (bulk.size) {
      rec.size = num(bulk.size[i], 0);
    } else {
      try {
        rec.size = num(obj.objectText.size(), 0);
      } catch (eSize) {}
    }
    if (bulk.font) {
      rec.font = String(bulk.font[i]);
    } else {
      try {
        rec.font = String(obj.objectText.font());
      } catch (eFont) {}
    }
    if (bulk.color) {
      const c = bulk.color[i];
      if (c && c[0] != null) {
        rec.color = [num(c[0], 0), num(c[1], 0), num(c[2], 0)];
      }
    } else {
      try {
        const c = obj.objectText.color();
        if (c && c[0] != null) {
          rec.color = [num(c[0], 0), num(c[1], 0), num(c[2], 0)];
        }
      } catch (eCol) {}
    }
  }
  if (kind === "line") {
    if (bulk.start) {
      const pair = xyFrom(bulk.start[i]);
      if (pair) rec.start = pair;
    } else {
      try {
        const pair = xyFrom(obj.startPoint());
        if (pair) rec.start = pair;
      } catch (eS) {}
    }
    if (bulk.end) {
      const pair = xyFrom(bulk.end[i]);
      if (pair) rec.end = pair;
    } else {
      try {
        const pair = xyFrom(obj.endPoint());
        if (pair) rec.end = pair;
      } catch (eE) {}
    }
  }
  if (kind === "group") {
    rec.children = [];
    try {
      const kids = obj.iWorkItems();
      rec.childCount = kids.length;
      for (let k = 0; k < kids.length; k++) {
        rec.children.push(describeItem(kids[k], k));
      }
    } catch (eG) {
      rec.childCount = 0;
    }
  }
  return rec;
}

function collectFromBulk(slide, name, kind, items, kindCounts, identity) {
  try {
    const col = slide[name]();
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n) || 0;
    const bulk = fetchBulkArrays(slide, name, kind, n);
    const objs = [];
    for (let i = 0; i < n; i++) {
      let rec;
      try {
        rec = describeItemBulk(col[i], items.length, kind, bulk, i);
      } catch (eItem) {
        rec = describeItem(col[i], items.length, kind);
      }
      rec.kindIndex = i;
      kindCounts[kind] = (kindCounts[kind] || 0) + 1;
      items.push(rec);
      objs.push(col[i]);
    }
    if (identity) identity.push({ kind: kind, objs: objs });
  } catch (e) {}
}

function collectFrom(slide, name, kind, items, kindCounts, identity) {
  try {
    const col = slide[name]();
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n) || 0;
    const objs = [];
    for (let i = 0; i < n; i++) {
      const rec = describeItem(col[i], items.length, kind);
      rec.kindIndex = i;
      kindCounts[kind] = (kindCounts[kind] || 0) + 1;
      items.push(rec);
      objs.push(col[i]);
    }
    if (identity) identity.push({ kind: kind, objs: objs });
  } catch (e) {}
}

// Text-bearing shapes appear in both textItems and shapes; mark the shape copy. kindIndex must keep matching Keynote's collections.
function markDuplicateShapes(items) {
  const texts = [];
  for (let i = 0; i < items.length; i++) {
    if (items[i].kind === "text" && items[i].text) texts.push(items[i]);
  }
  let found = 0;
  for (let i = 0; i < items.length; i++) {
    const rec = items[i];
    if (rec.kind !== "shape" || !rec.text) continue;
    for (let t = 0; t < texts.length; t++) {
      const twin = texts[t];
      if (twin.text !== rec.text) continue;
      if (Math.round(twin.x) !== Math.round(rec.x)) continue;
      if (Math.round(twin.y) !== Math.round(rec.y)) continue;
      if (Math.round(twin.w) !== Math.round(rec.w)) continue;
      if (Math.round(twin.h) !== Math.round(rec.h)) continue;
      rec.duplicateOf = { kind: "text", kindIndex: twin.kindIndex };
      found++;
      break;
    }
  }
  return found;
}

function collectItems(slide, bulkRead) {
  const items = [];
  const kindCounts = {};
  const identity = [];
  // Kind collect order is load-bearing — kindIndex is assigned in this sequence.
  const collect = bulkRead === false ? collectFrom : collectFromBulk;
  collect(slide, "textItems", "text", items, kindCounts, identity);
  collect(slide, "images", "image", items, kindCounts, identity);
  collect(slide, "shapes", "shape", items, kindCounts, identity);
  collect(slide, "movies", "movie", items, kindCounts, identity);
  collect(slide, "groups", "group", items, kindCounts, identity);
  collect(slide, "lines", "line", items, kindCounts, identity);
  if (!items.length) {
    try {
      const all = slide.iWorkItems();
      let n = all.length;
      if (typeof n === "function") n = n.call(all);
      n = Number(n) || 0;
      for (let i = 0; i < n; i++) {
        const rec = describeItem(all[i], i);
        rec.kindIndex = i;
        items.push(rec);
      }
    } catch (e) {}
  }
  const byKindIndex = {};
  for (let k = 0; k < items.length; k++) {
    byKindIndex[items[k].kind + ":" + items[k].kindIndex] = items[k];
  }
  attachBuildCounts(slide, items, identity, byKindIndex);
  markDuplicateShapes(items);
  return items;
}

// No z-order from iWorkItems (reports 0 on real slides). Remap stacking is role_order, not recovered z.

function attachBuildCounts(slide, items, identity, byKindIndex) {
  let builds = null;
  try {
    builds = slide.builds();
  } catch (e) {
    return;
  }
  const n = countOfSafe(builds);
  for (let i = 0; i < n; i++) {
    let obj = null;
    try {
      obj = builds[i].object();
    } catch (eO) {}
    if (!obj) continue;
    const hit = matchItemRecord(identity, byKindIndex, obj);
    if (hit) hit.buildCount = (hit.buildCount || 0) + 1;
  }
}

function countOfSafe(col) {
  try {
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n);
    return isNaN(n) ? 0 : n;
  } catch (e) {
    return 0;
  }
}

function matchItemRecord(identity, byKindIndex, obj) {
  if (!identity || !identity.length) return null;
  for (let c = 0; c < identity.length; c++) {
    const objs = identity[c].objs;
    const kind = identity[c].kind;
    for (let i = 0; i < objs.length; i++) {
      try {
        if (objs[i] !== obj) continue;
      } catch (e2) {
        continue;
      }
      return byKindIndex[kind + ":" + i] || null;
    }
  }
  return null;
}

function exportImages(Keynote, doc, exportDir) {
  const folder = Path(exportDir);
  try {
    Keynote.export(doc, {
      to: folder,
      as: "slide images",
      withProperties: { imageFormat: "PNG", skippedSlides: false },
    });
    return true;
  } catch (err1) {
    try {
      doc.export({
        to: folder,
        as: "slide images",
        withProperties: { imageFormat: "PNG" },
      });
      return true;
    } catch (err2) {
      return false;
    }
  }
}

function canvasSize(doc) {
  // slideWidth() throws; width() works.
  try {
    const w = Number(doc.width());
    const h = Number(doc.height());
    if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) return [w, h];
  } catch (e) {}
  try {
    const w = Number(doc.slideWidth());
    const h = Number(doc.slideHeight());
    if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) return [w, h];
  } catch (e2) {}
  return [1920, 1080];
}


const COLLECTION_FOR = {
  text: "textItems",
  image: "images",
  shape: "shapes",
  movie: "movies",
  group: "groups",
  line: "lines",
};

// Before kindIndex: live collection count must match expected (text allows trailing empty placeholders). Drift → whole slide unreadable.
function readSlideItems(slide, entries, kindCounts, slack) {
  const byKind = {};
  for (let e = 0; e < entries.length; e++) {
    const k = entries[e].kind;
    if (!byKind[k]) byKind[k] = [];
    byKind[k].push(entries[e]);
  }
  const records = [];
  for (const kind in byKind) {
    if (!byKind.hasOwnProperty(kind)) continue;
    const name = COLLECTION_FOR[kind];
    if (!name) return { unreadable: true, items: [] };
    let col = null;
    try {
      col = slide[name]();
    } catch (eCol) {
      return { unreadable: true, items: [] };
    }
    if (col == null) return { unreadable: true, items: [] };
    const n = lenOf(col);
    const expected =
      kindCounts && kindCounts[kind] != null ? Number(kindCounts[kind]) : null;
    if (expected != null) {
      const drift =
        kind === "text" ? n < expected || n - expected > slack : n !== expected;
      if (drift) return { unreadable: true, items: [] };
    }
    const wanted = byKind[kind];
    for (let w = 0; w < wanted.length; w++) {
      const ki = Number(wanted[w].kindIndex);
      if (isNaN(ki) || ki < 0 || ki >= n) return { unreadable: true, items: [] };
      const rec = describeItem(col[ki], ki, kind);
      rec.kindIndex = ki;
      records.push(rec);
    }
  }
  return { unreadable: false, items: records };
}

function readPlanItems(doc, plan) {
  const slides = doc.slides();
  const counts = plan.counts || {};
  let slack = Number(plan.textPlaceholderSlack);
  if (isNaN(slack)) slack = 0;
  const bySlide = {};
  for (let a = 0; a < plan.items.length; a++) {
    const it = plan.items[a];
    const key = String(Number(it.slide));
    if (!bySlide[key]) bySlide[key] = [];
    bySlide[key].push(it);
  }
  const out = {};
  for (const sKey in bySlide) {
    if (!bySlide.hasOwnProperty(sKey)) continue;
    const i = Number(sKey) - 1;
    const key0 = String(i);
    if (i < 0 || i >= slides.length) {
      out[key0] = { unreadable: true, items: [] };
      continue;
    }
    out[key0] = readSlideItems(slides[i], bySlide[sKey], counts[sKey] || null, slack);
  }
  return out;
}

function closeDoc(Keynote, doc) {
  try {
    Keynote.close(doc, { saving: "no" });
  } catch (e3) {
    try {
      doc.close({ saving: "no" });
    } catch (e4) {}
  }
}

function run(argv) {
  const plan = readJSON(argv[0]);
  const Keynote = Application(plan.bundleId || "com.apple.Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.path));
  if (plan.items) {
    const itemsBySlide = readPlanItems(doc, plan);
    closeDoc(Keynote, doc);
    return JSON.stringify({ path: plan.path, itemsBySlide: itemsBySlide });
  }
  const slides = doc.slides();
  const size = canvasSize(doc);
  const slideWidth = size[0];
  const slideHeight = size[1];

  const bulkRead = plan.bulkRead !== false;

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

  const outSlides = [];
  for (let s = 0; s < indices.length; s++) {
    const i = indices[s];
    let master = "";
    try {
      master = String(slides[i].baseLayout().name());
    } catch (e2) {
      try {
        master = String(slides[i].baseSlide().name());
      } catch (e3) {}
    }
    let skipped = false;
    try {
      skipped = Boolean(slides[i].skipped());
    } catch (eSkip) {
      try {
        skipped = Boolean(slides[i].skipped);
      } catch (eSkip2) {}
    }
    outSlides.push({
      index: i,
      number: i + 1,
      master: master,
      skipped: skipped,
      items: collectItems(slides[i], bulkRead),
    });
  }

  let exported = false;
  let exportError = "";
  if (plan.exportDir) {
    try {
      exported = exportImages(Keynote, doc, plan.exportDir);
      if (!exported) exportError = "Keynote export as slide images failed.";
    } catch (eExp) {
      exportError = String(eExp);
    }
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
    slideWidth: slideWidth,
    slideHeight: slideHeight,
    slideCount: slides.length,
    exported: exported,
    exportError: exportError,
    slides: outSlides,
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    num: num,
    xyFrom: xyFrom,
    kindOf: kindOf,
    positionOf: positionOf,
    sizeOf: sizeOf,
    fileNameOf: fileNameOf,
    describeItem: describeItem,
    describeItemBulk: describeItemBulk,
    bulkArray: bulkArray,
    fileNameFrom: fileNameFrom,
    COLLECTION_FOR: COLLECTION_FOR,
    readSlideItems: readSlideItems,
    readPlanItems: readPlanItems,
  };
}
