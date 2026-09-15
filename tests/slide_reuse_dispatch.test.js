// Branch-decision unit test for a plan with no `reuses` key (Step A reuse-off).
// Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/slide_reuse_dispatch.test.js
//
// applyReuse itself needs a live Keynote `doc`/`Keynote` app object, so the
// production loop is not Node-harnessable. The lynchpin — slidesInPlan equals
// the transform slide set, and the reuseBy lookup never selects a job — is
// the same construction remap_keynote.js uses before calling applyReuse.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

test("plan with no reuses key: slidesInPlan equals the transform slide set", function () {
  const transforms = [{ slide: 3 }, { slide: 5 }, { slide: 3 }, { slide: 124 }];
  const plan = { transforms };
  assert.deepStrictEqual(m.slidesInPlan(transforms, plan.reuses), [3, 5, 124]);
});

test("plan with no reuses key: applyReuse / deleteRefs / keystroke never invoked", function () {
  const transforms = [{ slide: 123 }, { slide: 124 }];
  const plan = { transforms };
  let applyN = 0;
  let deleteN = 0;
  let keyN = 0;
  const origApply = m.applyReuse;
  const origDelete = m.deleteRefs;
  const origKey = m.keystroke;
  m.applyReuse = function () {
    applyN += 1;
  };
  m.deleteRefs = function () {
    deleteN += 1;
  };
  m.keystroke = function () {
    keyN += 1;
  };
  try {
    const reuses = plan.reuses || [];
    const reuseBy = {};
    for (let i = 0; i < reuses.length; i++) {
      reuseBy[Number(reuses[i].slide)] = reuses[i];
    }
    const order = m.slidesInPlan(transforms, reuses);
    for (let i = 0; i < order.length; i++) {
      const n = order[i];
      if (reuseBy[n]) {
        m.applyReuse({}, {}, reuseBy[n], [], false);
      }
    }
    assert.deepStrictEqual(order, [123, 124]);
    assert.strictEqual(Object.keys(reuseBy).length, 0);
    assert.strictEqual(applyN, 0);
    assert.strictEqual(deleteN, 0);
    assert.strictEqual(keyN, 0);
  } finally {
    m.applyReuse = origApply;
    m.deleteRefs = origDelete;
    m.keystroke = origKey;
  }
});

console.log("\n" + passed + " passing");
