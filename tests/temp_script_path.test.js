// Unit test for the tempScriptPath pure helper (W0.1). Pure JS — no Keynote, no
// Apple Events, no filesystem writes. Run with:
//
//     node tests/temp_script_path.test.js

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");
const tempScriptPath = m.tempScriptPath;

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

test("distinct uniq values give distinct paths", function () {
  const a = tempScriptPath("/tmp/", "abc");
  const b = tempScriptPath("/tmp/", "xyz");
  assert.notStrictEqual(a, b);
});

test("suffix is .applescript", function () {
  const p = tempScriptPath("/tmp/", "abc");
  assert.strictEqual(p.slice(-".applescript".length), ".applescript");
});

test("dir with trailing slash yields exactly one slash before the basename", function () {
  const p = tempScriptPath("/tmp/", "abc");
  assert.strictEqual(p, "/tmp/obed-edom-keynote-abc.applescript");
});

test("dir without trailing slash yields exactly one slash before the basename", function () {
  const p = tempScriptPath("/tmp", "abc");
  assert.strictEqual(p, "/tmp/obed-edom-keynote-abc.applescript");
});

test("result never equals the old fixed path", function () {
  const p1 = tempScriptPath("/tmp/", "abc");
  const p2 = tempScriptPath("/tmp", "abc");
  assert.notStrictEqual(p1, "/tmp/obed-edom-keynote.applescript");
  assert.notStrictEqual(p2, "/tmp/obed-edom-keynote.applescript");
});

test("basename starts with obed-edom-keynote-", function () {
  const p = tempScriptPath("/var/folders/xyz/T/", "abc-123");
  const basename = p.slice(p.lastIndexOf("/") + 1);
  assert.strictEqual(basename.indexOf("obed-edom-keynote-"), 0);
});

test("uniq appears verbatim in the basename", function () {
  const p = tempScriptPath("/x/", "abc-123");
  assert.strictEqual(p.slice(-"obed-edom-keynote-abc-123.applescript".length), "obed-edom-keynote-abc-123.applescript");
});

console.log("\n" + passed + " passing");
