const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-save-queue-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/saveQueue.ts"), path.join(root, "src/maps/rebase.ts"), path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { MapsSaveConflictError, MapsSaveBlockedError, MapsSaveQueue } = require(path.join(out, "saveQueue.js"));

const doc = (title = "Old", churches = []) => ({
  defaultStyle: "positron", crop: "center+cg", exportLw: true, exportCg: true, exportDsk: false, hiddenLayers: [], cachedCountries: [], assets: [], links: [],
  slides: [{ id: "s1", title, style: "positron", camera: { lat: 1, lon: 2, zoom: 8, bearing: 0, pitch: 0 }, highlights: [], churches, cgShiftX: 0, cgShiftY: 0, includeSidePanels: false }],
});

test("queue returns the identical active flush promise and rebases an edit made while saving", async () => {
  let live = doc();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const calls = [];
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      calls.push({ sent, revision });
      await gate;
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: live, revision: 0 });
  queue.markDirty();
  const first = queue.flush();
  const second = queue.flush();
  assert.strictEqual(first, second);
  live = doc("Edited during flight");
  queue.markDirty();
  release();
  await first;
  assert.equal(calls.length, 2);
  assert.equal(live.slides[0].title, "Edited during flight");
});

test("queue rebases a structured conflict and preserves a remote landmark", async () => {
  let live = doc("Local");
  let attempts = 0;
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      attempts += 1;
      if (attempts === 1) throw new MapsSaveConflictError({ document: doc("Old", [{ id: "p1", name: "p1", lat: 1, lon: 2, kind: "dot", color: "#fff" }]), revision: revision + 1 });
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: doc(), revision: 0 });
  queue.markDirty();
  await queue.flush();
  assert.equal(attempts, 2);
  assert.equal(live.slides[0].title, "Local");
  assert.equal(live.slides[0].churches[0].id, "p1");
});

test("queue keeps a conflict candidate with unrelated remote additions for explicit retry", async () => {
  let live = doc("Local");
  let conflict;
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async () => {
      throw new MapsSaveConflictError({ document: doc("Remote", [{ id: "p1", name: "p1", lat: 1, lon: 2, kind: "dot", color: "#fff" }]), revision: 1 });
    },
    onConflict: (next) => { conflict = next; },
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: doc(), revision: 0 });
  queue.markDirty();
  await assert.rejects(queue.flush(), /Resolve the map save conflict/);
  assert.ok(conflict);
  assert.equal(conflict.candidate.slides[0].churches[0].id, "p1");
  assert.equal(conflict.candidate.slides[0].title, "Local");
});

test("reset abandons the in-flight save so the next flush starts a fresh request", async () => {
  let live = doc();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const calls = [];
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      calls.push({ sent, revision });
      await gate;
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: live, revision: 0 });
  queue.markDirty();
  const first = queue.flush();
  queue.reset({ document: doc(), revision: 7 });
  queue.markDirty();
  const second = queue.flush();
  assert.notStrictEqual(second, first);
  release();
  await Promise.all([first, second]);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].revision, 7);
});

test("an in-flight save's ack does not clobber a newer base set by a concurrent reconcile", async () => {
  let live = doc("Local");
  const calls = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      calls.push({ sent, revision });
      if (calls.length === 1) {
        await gate;
        return { document: sent, revision: 1 };
      }
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: doc("Local"), revision: 0 });
  queue.markDirty();
  const flushed = queue.flush();

  const withAsset = doc("Local", [{ id: "p1", name: "uploaded", lat: 1, lon: 2, kind: "dot", color: "#fff" }]);
  queue.reconcile({ document: withAsset, revision: 2 });
  assert.equal(live.slides[0].churches[0]?.id, "p1");

  release();
  await flushed;

  assert.equal(calls.length, 2);
  assert.equal(calls[1].revision, 2, "the rebase after the stale ack must resend against the newer base");
  assert.equal(live.slides[0].churches[0]?.id, "p1", "the revision-2 asset must survive the stale ack");
});

test("a stale acknowledgement cannot move the base revision backwards", async () => {
  let live = doc("Current");
  const calls = [];
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      calls.push({ sent, revision });
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => assert.fail(String(error)),
  });
  queue.reset({ document: live, revision: 5 });
  queue.reconcile({ document: doc("Stale"), revision: 3 });
  assert.equal(live.slides[0].title, "Current");
  queue.markDirty();
  await queue.flush();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].revision, 5);
  assert.equal(live.slides[0].title, "Current");
});

test("a transport failure leaves the queue dirty, fires onError, skips publish, and a later flush resends the same document", async () => {
  const live = doc("Local");
  let publishCalls = 0;
  let errorSeen = null;
  const calls = [];
  let failNext = true;
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: () => { publishCalls += 1; },
    transport: async (sent, revision) => {
      calls.push(sent);
      if (failNext) {
        failNext = false;
        throw new Error("network down");
      }
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => assert.fail("unexpected conflict"),
    onError: (error) => { errorSeen = error; },
  });
  queue.setAcknowledged({ document: live, revision: 0 });
  queue.markDirty();
  await assert.rejects(queue.flush(), /network down/);
  assert.equal(publishCalls, 0);
  assert.ok(errorSeen && String(errorSeen).includes("network down"));
  assert.equal(calls.length, 1);
  await queue.flush();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1], calls[0]);
});

test("a blocked queue rejects flush with MapsSaveBlockedError and stays undirty", async () => {
  let live = doc("Local");
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async () => {
      throw new MapsSaveConflictError({ document: doc("Remote"), revision: 1 });
    },
    onConflict: () => undefined,
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: doc(), revision: 0 });
  queue.markDirty();
  await assert.rejects(queue.flush(), MapsSaveBlockedError);
  assert.ok(queue.conflict);
  await assert.rejects(queue.flush(), MapsSaveBlockedError);
});

test("reloadLatest and keepMyChanges clear the conflict so later edits are accepted again", async () => {
  let live = doc("Local");
  let attempts = 0;
  const queue = new MapsSaveQueue({
    document: () => live,
    publish: (next) => { live = next; },
    transport: async (sent, revision) => {
      attempts += 1;
      if (attempts === 1) throw new MapsSaveConflictError({ document: doc("Remote"), revision: 1 });
      return { document: sent, revision: revision + 1 };
    },
    onConflict: () => undefined,
    onError: (error) => assert.fail(String(error)),
  });
  queue.setAcknowledged({ document: doc(), revision: 0 });
  queue.markDirty();
  await assert.rejects(queue.flush(), MapsSaveBlockedError);
  assert.ok(queue.conflict);
  queue.reloadLatest();
  assert.equal(queue.conflict, null);
  assert.equal(live.slides[0].title, "Remote");

  live = doc("Edited again");
  queue.markDirty();
  await queue.flush();
  assert.equal(live.slides[0].title, "Edited again");

  attempts = 0;
  queue.setAcknowledged({ document: doc(), revision: 0 });
  live = doc("Local");
  queue.markDirty();
  await assert.rejects(queue.flush(), MapsSaveBlockedError);
  assert.ok(queue.conflict);
  await queue.keepMyChanges();
  assert.equal(queue.conflict, null);
  assert.equal(live.slides[0].title, "Local");
});
