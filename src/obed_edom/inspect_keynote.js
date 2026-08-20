ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

}

function num(v, fallback) {
  const n = Number(v);
  return isNaN(n) ? fallback : n;
}

function positionOf(obj) {
  try {
    const p = obj.position();
    if (p && p.length >= 2) {
      return [num(p[0], 0), num(p[1], 0)];
    }
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
    runs: [],
    fileName: "",
    locked: false,
    rotation: 0,
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
  }
  if (kind === "line") {
    try {
      const sp = obj.startPoint();
      if (sp && sp.length >= 2) rec.start = [num(sp[0], 0), num(sp[1], 0)];
    } catch (eS) {}
    try {
      const ep = obj.endPoint();
      if (ep && ep.length >= 2) rec.end = [num(ep[0], 0), num(ep[1], 0)];
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
    for (let i = 0; i < col.length; i++) {
      const rec = describeItem(col[i], items.length, kind);
      rec.kindIndex = i;
      kindCounts[kind] = (kindCounts[kind] || 0) + 1;
      items.push(rec);
    }
  } catch (e) {}
}

function collectItems(slide) {
  const items = [];
  try {
    const all = slide.iWorkItems();
    for (let i = 0; i < all.length; i++) {
      const rec = describeItem(all[i], i);
      rec.kindIndex = i;
      items.push(rec);
    }
  } catch (e) {}
  if (items.length) return items;

  const kindCounts = {};
  collectFrom(slide, "textItems", "text", items, kindCounts);
  collectFrom(slide, "images", "image", items, kindCounts);
  collectFrom(slide, "shapes", "shape", items, kindCounts);
  collectFrom(slide, "movies", "movie", items, kindCounts);
  collectFrom(slide, "groups", "group", items, kindCounts);
  collectFrom(slide, "lines", "line", items, kindCounts);
  return items;
}

function run(argv) {
  const plan = readJSON(argv[0]);
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.path));
  const slides = doc.slides();
  let slideWidth = 1920;
  let slideHeight = 1080;
  try {
    slideWidth = doc.slideWidth();
    slideHeight = doc.slideHeight();
  } catch (e) {}

  const range = plan.range || null;
  const start = range ? Math.max(0, range[0] - 1) : 0;
  const end = range ? Math.min(slides.length, range[1]) : slides.length;

  const outSlides = [];
  for (let i = start; i < end; i++) {
    let master = "";
    try {
      master = String(slides[i].baseSlide().name());
    } catch (e2) {}
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
