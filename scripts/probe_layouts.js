// Can we read a slide layout's contents, and can we place an image from a file?
//
// The cue palette wants a thumbnail and the placeholders for each layout the
// dropped template defines; the image cue wants to insert a file. The dictionary
// suggests both are possible, but it also advertises attributeRuns(), which
// raises "Can't convert types." at runtime — so nothing here is believed until
// probed. Errors are surfaced rather than swallowed.
//
//   osascript -l JavaScript scripts/probe_layouts.js "/path/to/scratch.key" [imageFile] [bundleId]
//
// The deck is modified (an image is pushed onto a new slide), so pass a scratch
// copy, never a template or a gold deck. bundleId defaults to Keynote 15.

ObjC.import("Foundation");

function err(e) {
  try {
    return String(e && e.message ? e.message : e);
  } catch (x) {
    return "unprintable error";
  }
}

function attempt(label, fn) {
  try {
    return { label: label, ok: true, value: fn() };
  } catch (e) {
    return { label: label, ok: false, error: err(e) };
  }
}

function countOf(label, fn) {
  return attempt(label, function () {
    const v = fn();
    return v === null || v === undefined ? null : v.length;
  });
}

function probeZOrder(slides) {
  // The 14.5 finding is that this reports 0 on slides holding real objects, which
  // is why stacking is a policy rather than something read back.
  const out = [];
  for (let i = 0; i < Math.min(slides.length, 3); i++) {
    const slide = slides[i];
    out.push({
      slide: i + 1,
      iWorkItems: countOf("iWorkItems()", function () {
        return slide.iWorkItems();
      }),
      textItems: countOf("textItems()", function () {
        return slide.textItems();
      }),
      images: countOf("images()", function () {
        return slide.images();
      }),
      shapes: countOf("shapes()", function () {
        return slide.shapes();
      }),
    });
  }
  return out;
}

function probeLayouts(doc) {
  const result = {
    slideLayouts: countOf("doc.slideLayouts()", function () {
      return doc.slideLayouts();
    }),
    masterSlides: countOf("doc.masterSlides()", function () {
      return doc.masterSlides();
    }),
    names: attempt("layout names", function () {
      const lays = doc.slideLayouts();
      const names = [];
      for (let i = 0; i < lays.length; i++) names.push(String(lays[i].name()));
      return names;
    }),
    contents: [],
  };
  // The real question: does a layout expose its placeholders the way a slide does?
  let lays = null;
  try {
    lays = doc.slideLayouts();
  } catch (e) {
    result.contentsError = err(e);
    return result;
  }
  for (let i = 0; i < Math.min(lays.length, 4); i++) {
    const lay = lays[i];
    result.contents.push({
      index: i + 1,
      name: attempt("name()", function () {
        return String(lay.name());
      }),
      textItems: countOf("textItems()", function () {
        return lay.textItems();
      }),
      images: countOf("images()", function () {
        return lay.images();
      }),
      shapes: countOf("shapes()", function () {
        return lay.shapes();
      }),
      firstText: attempt("first text", function () {
        const items = lay.textItems();
        return items.length ? String(items[0].objectText()).slice(0, 60) : "";
      }),
    });
  }
  return result;
}

function probeImageInsert(Keynote, doc, imageFile) {
  if (!imageFile) return { skipped: "no image file given" };
  const out = {};
  out.newSlide = attempt("make new slide", function () {
    const slide = Keynote.Slide();
    doc.slides.push(slide);
    return doc.slides().length;
  });
  if (!out.newSlide.ok) return out;
  const slide = doc.slides()[doc.slides().length - 1];

  out.constructWithFile = attempt("Keynote.Image({file})", function () {
    const img = Keynote.Image({ file: Path(imageFile) });
    slide.images.push(img);
    return slide.images().length;
  });
  if (out.constructWithFile.ok) {
    out.readBack = attempt("placed image geometry", function () {
      const img = slide.images()[slide.images().length - 1];
      return {
        file: String(img.fileName ? img.fileName() : ""),
        x: img.position().x,
        y: img.position().y,
        w: img.width(),
        h: img.height(),
      };
    });
    out.reposition = attempt("set position and size", function () {
      const img = slide.images()[slide.images().length - 1];
      img.position = { x: 100, y: 120 };
      img.width = 640;
      return { x: img.position().x, y: img.position().y, w: img.width() };
    });
  }
  out.constructMovie = attempt("Keynote.Movie({file}) accepts a still", function () {
    const mov = Keynote.Movie({ file: Path(imageFile) });
    slide.movies.push(mov);
    return slide.movies().length;
  });
  return out;
}

function run(argv) {
  const path = argv[0];
  const imageFile = argv.length > 1 && argv[1] !== "-" ? argv[1] : null;
  const bundleId = argv.length > 2 ? argv[2] : "com.apple.Keynote";
  const Keynote = Application(bundleId);
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(path));
  const slides = doc.slides();

  const report = {
    path: path,
    bundleId: bundleId,
    keynoteVersion: Keynote.version(),
    slideCount: slides.length,
    zOrder: probeZOrder(slides),
    layouts: probeLayouts(doc),
    imageInsert: probeImageInsert(Keynote, doc, imageFile),
  };
  try {
    Keynote.close(doc, { saving: "no" });
  } catch (eClose) {
    report.closeError = err(eClose);
  }
  return JSON.stringify(report, null, 1);
}
