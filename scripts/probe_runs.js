// Why does inspect_keynote.js report runs: [] on every text item?
//
// extractRuns() wraps every property in a bare catch and drops a run whose text
// it cannot read, so a total failure is indistinguishable from unstyled text.
// This probe surfaces the errors instead of swallowing them.
//
//   osascript -l JavaScript scripts/probe_runs.js "/path/to/deck.key" [maxSlides]

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

function probeTextItem(item) {
  const out = { routes: [] };

  out.routes.push(
    attempt("objectText() as string", function () {
      return String(item.objectText()).slice(0, 60);
    })
  );

  // The route extractRuns() actually uses.
  out.routes.push(
    attempt("objectText.attributeRuns() length", function () {
      return lenOf(item.objectText.attributeRuns());
    })
  );
  out.routes.push(
    attempt("objectText().attributeRuns() length", function () {
      return lenOf(item.objectText().attributeRuns());
    })
  );
  out.routes.push(
    attempt("objectText.paragraphs() length", function () {
      return lenOf(item.objectText.paragraphs());
    })
  );
  out.routes.push(
    attempt("objectText.characters() length", function () {
      return lenOf(item.objectText.characters());
    })
  );
  out.routes.push(
    attempt("objectText.words() length", function () {
      return lenOf(item.objectText.words());
    })
  );

  // If any run collection is reachable, can we read style off run 0?
  const runProbes = [];
  const collections = ["attributeRuns", "paragraphs", "characters"];
  for (let c = 0; c < collections.length; c++) {
    const name = collections[c];
    const got = attempt(name + "[0] style", function () {
      const coll = item.objectText[name]();
      if (lenOf(coll) < 1) throw new Error("empty collection");
      const r = coll[0];
      const style = {};
      style.callValue = attempt("call", function () {
        return String(r()).slice(0, 40);
      });
      style.content = attempt("content()", function () {
        return String(r.content()).slice(0, 40);
      });
      style.color = attempt("color()", function () {
        const c2 = r.color();
        return c2 && c2.length >= 3 ? [Number(c2[0]), Number(c2[1]), Number(c2[2])] : null;
      });
      style.size = attempt("size()", function () {
        return Number(r.size());
      });
      style.font = attempt("font()", function () {
        return String(r.font());
      });
      style.bold = attempt("bold()", function () {
        return Boolean(r.bold());
      });
      style.smallCaps = attempt("smallCaps()", function () {
        return Boolean(r.smallCaps());
      });
      style.capitalization = attempt("capitalization()", function () {
        return String(r.capitalization());
      });
      return style;
    });
    runProbes.push(got);
  }
  out.runProbes = runProbes;
  return out;
}

function run(argv) {
  const path = argv[0];
  const maxSlides = argv.length > 1 ? Number(argv[1]) : 6;
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(path));
  const slides = doc.slides();

  const report = { path: path, slideCount: slides.length, samples: [] };
  const limit = Math.min(slides.length, maxSlides);

  for (let i = 0; i < limit && report.samples.length < 3; i++) {
    const slide = slides[i];
    let texts = [];
    try {
      texts = slide.textItems();
    } catch (e) {
      continue;
    }
    for (let t = 0; t < lenOf(texts) && report.samples.length < 3; t++) {
      const item = texts[t];
      let content = "";
      try {
        content = String(item.objectText());
      } catch (e) {}
      if (!content.trim()) continue;
      report.samples.push({
        slide: i + 1,
        textItem: t,
        preview: content.slice(0, 50),
        probe: probeTextItem(item),
      });
    }
  }

  try {
    doc.close({ saving: "no" });
  } catch (e) {}

  return JSON.stringify(report, null, 2);
}
