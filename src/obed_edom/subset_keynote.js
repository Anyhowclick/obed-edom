ObjC.import("Foundation");

function readJSON(path) {
  const data = $.NSData.dataWithContentsOfFile(path);
  const str = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
  return JSON.parse(ObjC.unwrap(str));
}

function run(argv) {
  const plan = readJSON(argv[0]);
  const Keynote = Application("Keynote");
  Keynote.includeStandardAdditions = true;
  const wanted = {};
  const nums = plan.slides || [];
  for (let i = 0; i < nums.length; i++) {
    wanted[Number(nums[i])] = true;
  }
  const doc = Keynote.open(Path(plan.dest));
  const slides = doc.slides();
  for (let i = slides.length - 1; i >= 0; i--) {
    if (!wanted[i + 1]) {
      try {
        slides[i].delete();
      } catch (eDel) {
        try {
          Keynote.delete(slides[i]);
        } catch (eDel2) {}
      }
    }
  }
  try {
    Keynote.save(doc);
  } catch (eSave) {
    Keynote.save(doc, { in: Path(plan.dest) });
  }
  try {
    Keynote.close(doc, { saving: "yes" });
  } catch (eClose) {}
  return JSON.stringify({ dest: plan.dest, kept: nums });
}
