ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

function fillTextItems(slide, textItems) {
  if (!textItems) {
    return;
  }
  const items = slide.textItems();
  Object.keys(textItems)
    .map(function (k) {
      return parseInt(k, 10);
    })
    .sort(function (a, b) {
      return a - b;
    })
    .forEach(function (oneBased) {
      const value = textItems[String(oneBased)];
      if (value === undefined || value === null) {
        return;
      }
      const idx = oneBased - 1;
      if (idx < 0 || idx >= items.length) {
        return;
      }
      try {
        items[idx].objectText = String(value);
      } catch (err) {
        // Some items are not writable; skip.
      }
    });
}

function findMaster(doc, name) {
  const masters = doc.masterSlides();
  for (let i = 0; i < masters.length; i++) {
    if (masters[i].name() === name) {
      return masters[i];
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

function applyOverlays(doc, overlays, slideWidth, slideHeight) {
  overlays.forEach(function (overlay) {
    const slides = doc.slides();
    const index = overlay.slideIndex;
    if (index < 0 || index >= slides.length) {
      return;
    }
    const slide = slides[index];
    const shape = KeynoteShape(slide, overlay, slideWidth, slideHeight);
    if (!shape) {
      return;
    }
  });
}

function KeynoteShape(slide, overlay, slideWidth, slideHeight) {
  try {
    const Keynote = Application("Keynote");
    const x = (overlay.x || 0) * slideWidth;
    const y = (overlay.y || 0.45) * slideHeight;
    const w = (overlay.w || 1) * slideWidth;
    const h = (overlay.h || 0.55) * slideHeight;
    const shape = Keynote.Shape({
      shapeType: "rectangle",
      position: [x, y],
      width: w,
      height: h,
    });
    slide.shapes.push(shape);
    const added = slide.shapes()[slide.shapes().length - 1];
    try {
      added.fillType = "color fill";
    } catch (e1) {}
    try {
      added.fillColor = [0, 0, 0];
    } catch (e2) {}
    try {
      added.opacity = overlay.opacity || 45;
    } catch (e3) {}
    try {
      added.objectDescription = "contrast-gradient";
    } catch (e4) {}
    return added;
  } catch (err) {
    return null;
  }
}

function run(argv) {
  const planPath = argv[0];
  const plan = readJSON(planPath);
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;

  const doc = Keynote.open(Path(plan.output));
  const originalCount = doc.slides().length;
  const missingMasters = [];
  const created = [];

  plan.slides.forEach(function (spec) {
    const master = findMaster(doc, spec.master);
    if (!master) {
      missingMasters.push(spec.master);
      return;
    }
    doc.slides.push(Keynote.Slide({ baseSlide: master }));
    const slides = doc.slides();
    const slide = slides[slides.length - 1];
    fillTextItems(slide, spec.textItems || {});
    created.push(spec.master);
  });

  for (let i = 0; i < originalCount; i++) {
    doc.slides[0].delete();
  }

  let slideWidth = 1920;
  let slideHeight = 1080;
  try {
    slideWidth = doc.slideWidth();
    slideHeight = doc.slideHeight();
  } catch (e) {}

  if (plan.overlays && plan.overlays.length) {
    applyOverlays(doc, plan.overlays, slideWidth, slideHeight);
  }

  Keynote.save(doc);

  let exported = false;
  if (plan.exportDir) {
    exported = exportImages(Keynote, doc, plan.exportDir);
  }

  if (plan.close) {
    Keynote.close(doc, { saving: "yes" });
  }

  return JSON.stringify({
    ok: missingMasters.length === 0,
    slideCount: doc.slides().length,
    created: created,
    missingMasters: missingMasters,
    exported: exported,
    slideWidth: slideWidth,
    slideHeight: slideHeight,
  });
}
