ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

function applyGeom(obj, spec) {
  let wasLocked = false;
  try {
    wasLocked = Boolean(obj.locked());
  } catch (eL) {}
  if (wasLocked) {
    try {
      obj.locked = false;
    } catch (eU) {}
  }
  try {
    obj.position = [spec.x, spec.y];
  } catch (eP) {}
  if (spec.w != null) {
    try {
      obj.width = spec.w;
    } catch (eW) {}
  }
  if (spec.h != null) {
    try {
      obj.height = spec.h;
    } catch (eH) {}
  }
  if (spec.start && spec.start.length >= 2) {
    try {
      obj.startPoint = spec.start;
    } catch (eS) {}
  }
  if (spec.end && spec.end.length >= 2) {
    try {
      obj.endPoint = spec.end;
    } catch (eE) {}
  }
  if (spec.fontSize) {
    try {
      obj.objectText.size = spec.fontSize;
    } catch (eF) {}
  }
  if (spec.locked || wasLocked) {
    try {
      obj.locked = true;
    } catch (eK) {}
  }
}

function run(argv) {
  const plan = readJSON(argv[0]);
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;
  const doc = Keynote.open(Path(plan.dest));
  const slides = doc.slides();
  const transforms = plan.transforms || [];
  let applied = 0;
  let missed = 0;
  for (let t = 0; t < transforms.length; t++) {
    const spec = transforms[t];
    const slideNo = Number(spec.slide) || 1;
    const itemIndex = Number(spec.itemIndex);
    if (slideNo < 1 || slideNo > slides.length) {
      missed += 1;
      continue;
    }
    const slide = slides[slideNo - 1];
    let obj = null;
    try {
      const items = slide.iWorkItems();
      if (itemIndex >= 0 && itemIndex < items.length) {
        obj = items[itemIndex];
      }
    } catch (eItems) {}
    if (!obj) {
      missed += 1;
      continue;
    }
    applyGeom(obj, spec);
    applied += 1;
  }
  const width = Number(plan.width) || 1920;
  const height = Number(plan.height) || 1080;
  try {
    doc.width = width;
  } catch (eW) {}
  try {
    doc.height = height;
  } catch (eH) {}
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
  return JSON.stringify({ dest: plan.dest, applied: applied, missed: missed, width: width, height: height });
}
