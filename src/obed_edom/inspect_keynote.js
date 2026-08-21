ObjC.import("Foundation");

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

function extractRuns(textItem) {
  const runs = [];
  try {
    const rich = textItem.objectText;
    if (rich && rich.attributeRuns) {
      const ar = rich.attributeRuns();
      for (let i = 0; i < ar.length; i++) {
        const run = ar[i];
        let text = "";
        let color = null;
        let bold = false;
        try {
          text = String(run());
        } catch (e1) {
          try {
            text = String(run.content());
          } catch (e2) {}
        }
        try {
          const c = run.color();
          if (c && c.length >= 3) {
            color = [num(c[0], 0), num(c[1], 0), num(c[2], 0)];
          }
        } catch (e3) {}
        try {
          bold = Boolean(run.bold());
        } catch (e4) {}
        let size = 0;
        try {
          size = num(run.size(), 0);
        } catch (e5) {}
        let font = "";
        try {
          font = String(run.font());
        } catch (eFont) {}
        let smallCaps = false;
        let capitalization = "";
        try {
          capitalization = String(run.capitalization());
        } catch (eCap) {}
        try {
          smallCaps = Boolean(run.smallCaps());
        } catch (eSmall) {}
        if (capitalization && /small/i.test(capitalization)) {
          smallCaps = true;
        }
        if (text) {
          runs.push({
            text: text,
            color: color,
            bold: bold,
            size: size,
            font: font,
            smallCaps: smallCaps,
            capitalization: capitalization,
          });
        }
      }
    }
  } catch (err) {}
  return runs;
}

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
    runs: [],
    fileName: "",
    locked: false,
    rotation: 0,
    buildCount: 0,
    zIndex: null,
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
    rec.runs = extractRuns(obj);
    try {
      rec.size = num(obj.objectText.size(), 0);
    } catch (eSize) {}
    try {
      rec.font = String(obj.objectText.font());
    } catch (eFont) {}
    if (!rec.font && rec.runs && rec.runs[0] && rec.runs[0].font) {
      rec.font = rec.runs[0].font;
    }
    try {
      const c = obj.objectText.color();
      if (c && c[0] != null) {
        rec.color = [num(c[0], 0), num(c[1], 0), num(c[2], 0)];
      }
    } catch (eCol) {}
    if (!rec.color && rec.runs && rec.runs[0] && rec.runs[0].color) {
      rec.color = rec.runs[0].color;
    }
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

function collectFrom(slide, name, kind, items, kindCounts) {
  try {
    const col = slide[name]();
    let n = col.length;
    if (typeof n === "function") n = n.call(col);
    n = Number(n) || 0;
    for (let i = 0; i < n; i++) {
      const rec = describeItem(col[i], items.length, kind);
      rec.kindIndex = i;
      kindCounts[kind] = (kindCounts[kind] || 0) + 1;
      items.push(rec);
    }
  } catch (e) {}
}

function collectItems(slide) {
  const items = [];
  const kindCounts = {};
  collectFrom(slide, "textItems", "text", items, kindCounts);
  collectFrom(slide, "images", "image", items, kindCounts);
  collectFrom(slide, "shapes", "shape", items, kindCounts);
  collectFrom(slide, "movies", "movie", items, kindCounts);
  collectFrom(slide, "groups", "group", items, kindCounts);
  collectFrom(slide, "lines", "line", items, kindCounts);
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
  attachBuildCounts(slide, items);
  attachZOrder(slide, items);
  return items;
}

function attachZOrder(slide, items) {
  let all = null;
  try {
    all = slide.iWorkItems();
  } catch (e) {
    return;
  }
  const n = countOfSafe(all);
  for (let i = 0; i < n; i++) {
    let obj = null;
    try {
      obj = all[i];
    } catch (eO) {}
    if (!obj) continue;
    const hit = matchItemRecord(slide, obj, items);
    if (hit && hit.zIndex == null) hit.zIndex = i;
  }
}

function attachBuildCounts(slide, items) {
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
    const hit = matchItemRecord(slide, obj, items);
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

function matchItemRecord(slide, obj, items) {
  const names = [
    ["textItems", "text"],
    ["images", "image"],
    ["shapes", "shape"],
    ["movies", "movie"],
    ["groups", "group"],
    ["lines", "line"],
  ];
  for (let c = 0; c < names.length; c++) {
    const colName = names[c][0];
    const kind = names[c][1];
    let col = null;
    try {
      col = slide[colName]();
    } catch (e) {
      continue;
    }
    const n = countOfSafe(col);
    for (let i = 0; i < n; i++) {
      try {
        if (col[i] !== obj) continue;
      } catch (e2) {
        continue;
      }
      for (let k = 0; k < items.length; k++) {
        if (items[k].kind === kind && items[k].kindIndex === i) return items[k];
      }
    }
  }
  return null;
}

function canvasSize(doc) {
  // slideWidth() throws "Can't convert types" on current Keynote; width() works.
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

function run(argv) {
  const plan = readJSON(argv[0]);
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.path));
  const slides = doc.slides();
  const size = canvasSize(doc);
  const slideWidth = size[0];
  const slideHeight = size[1];

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
      items: collectItems(slides[i]),
    });
  }

  let exported = false;
  let exportError = "";
  // PNG export is done in Python via AppleScript after this script returns.

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
