ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
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
        if (text) {
          runs.push({ text: text, color: color, bold: bold });
        }
      }
    }
  } catch (err) {}
  return runs;
}

function collectItems(slide) {
  const items = [];

  function add(kind, obj) {
    const rec = {
      kind: kind,
      text: "",
      x: 0,
      y: 0,
      w: 0,
      h: 0,
      runs: [],
    };
    const pos = positionOf(obj);
    rec.x = pos[0];
    rec.y = pos[1];
    const sz = sizeOf(obj);
    rec.w = sz[0];
    rec.h = sz[1];
    if (kind === "text") {
      try {
        rec.text = String(obj.objectText());
      } catch (e) {}
      rec.runs = extractRuns(obj);
    }
    items.push(rec);
  }

  try {
    const tis = slide.textItems();
    for (let i = 0; i < tis.length; i++) {
      add("text", tis[i]);
    }
  } catch (e) {}
  try {
    const imgs = slide.images();
    for (let i = 0; i < imgs.length; i++) {
      add("image", imgs[i]);
    }
  } catch (e) {}
  try {
    const shs = slide.shapes();
    for (let i = 0; i < shs.length; i++) {
      add("shape", shs[i]);
    }
  } catch (e) {}
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
    outSlides.push({
      index: i,
      number: i + 1,
      master: master,
      items: collectItems(slides[i]),
    });
  }

  let exported = false;
  if (plan.exportDir) {
    exported = exportImages(Keynote, doc, plan.exportDir);
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
    slides: outSlides,
  });
}
