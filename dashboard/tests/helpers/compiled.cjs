// One tsc build shared by every tests/*.test.cjs that needs compiled src.
// The union of the entry files the tests used to compile individually is built
// once (rootDir src, so the layout mirrors src/: maps/, watercolour/, dsk/, and
// the src root) into node_modules/.cache/maps-tests/<key>.
//
// <key> hashes everything the emit depends on: the CONTENTS of every
// src/**/*.ts(x), this file, the entry list and flags, the TypeScript version and
// package-lock.json. A build directory is therefore immutable: it is compiled in
// a staging dir and published with one atomic rename, never rewritten, so a test
// process that already resolved its directory keeps a consistent generation while
// a source edit simply produces a new key.
//
// Parallelism: `node --test tests/*.test.cjs` starts 41 processes at once. A
// per-key mkdir lock only avoids a thundering herd -- it is never needed for
// correctness and never broken by force: a waiter that outlasts LOCK_WAIT_MS just
// compiles its own copy, and whoever renames second discards theirs.
//
// The key is re-hashed after tsc and the inputs' mtimes compared (an edit undone
// mid-compile restores the hash but not the mtime): on any change the output is
// discarded and the build retried, so a key never names another snapshot's emit.
// Every use touches its generation's mtime; only generations, locks and staging
// dirs untouched for a day are pruned, which no live test process can be reading.

const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..", "..");
const cache = path.join(root, "node_modules", ".cache", "maps-tests");
const LOCK_WAIT_MS = 60000;
const PRUNE_AFTER_MS = 24 * 60 * 60 * 1000;
const FLAGS = ["--module", "commonjs", "--target", "ES2020", "--jsx", "react-jsx", "--skipLibCheck", "true", "--rootDir", "src"];

// vite-env.d.ts declares the `?url` / `?worker&url` virtual modules that
// src/maps/styles.ts and src/maps/maplibreWorker.ts import.
const entries = [
  "src/vite-env.d.ts",
  "src/playlist.ts",
  "src/statusLabel.ts",
  "src/dsk/decisions.ts",
  "src/maps/BandOverlays.tsx",
  "src/maps/adminSync.ts",
  "src/maps/borderlandsFacade.ts",
  "src/maps/borderlandsGeometry.ts",
  "src/maps/borderlandsInkPolicy.ts",
  "src/maps/borderlandsProjection.ts",
  "src/maps/borderlandsStyle.ts",
  "src/maps/captureFly.ts",
  "src/maps/captureIsolateVisibility.ts",
  "src/maps/commit.ts",
  "src/maps/credits.ts",
  "src/maps/darkContrast.ts",
  "src/maps/flight.ts",
  "src/maps/highlight.ts",
  "src/maps/isolate.ts",
  "src/maps/manualRows.ts",
  "src/maps/maritimeBoundaries.ts",
  "src/maps/objects.ts",
  "src/maps/overlays.ts",
  "src/maps/rebase.ts",
  "src/maps/regionPick.ts",
  "src/maps/saveQueue.ts",
  "src/maps/stylePickerNav.ts",
  "src/maps/tonerBuildings.ts",
  "src/maps/types.ts",
  "src/maps/watercolourStyle.ts",
  "src/watercolour/edges.ts",
  "src/watercolour/floodFill.ts",
  "src/watercolour/history.ts",
  "src/watercolour/loupe.ts",
];

function sources(dir, found) {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, item.name);
    if (item.isDirectory()) sources(full, found);
    else if (/\.tsx?$/.test(item.name)) found.push(full);
  }
  return found;
}

function inputs() {
  return [...sources(path.join(root, "src"), []).sort(), __filename, path.join(root, "package-lock.json")];
}

function buildKey() {
  const hash = crypto.createHash("sha256");
  for (const file of inputs()) {
    hash.update(`${path.relative(root, file)}\n`);
    hash.update(fs.readFileSync(file));
  }
  hash.update(require(path.join(root, "node_modules/typescript/package.json")).version);
  hash.update(JSON.stringify([entries, FLAGS]));
  return hash.digest("hex").slice(0, 32);
}

function writeTimes() {
  return inputs().map((file) => `${file}:${fs.statSync(file).mtimeMs}`).join("\n");
}

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function compile(key) {
  const staging = fs.mkdtempSync(path.join(cache, "staging-"));
  const before = writeTimes();
  try {
    const runtime = process.env.CODEX_NODE || process.execPath;
    const compiled = spawnSync(runtime, [
      path.join(root, "node_modules/typescript/bin/tsc"), ...FLAGS, "--outDir", staging,
      ...entries.map((entry) => path.join(root, entry)),
    ], { cwd: root, encoding: "utf8" });
    assert.equal(compiled.status, 0, compiled.stderr || compiled.stdout);
    if (writeTimes() !== before || buildKey() !== key) return false;
    try {
      fs.renameSync(staging, path.join(cache, key));
    } catch (err) {
      if (!fs.existsSync(path.join(cache, key))) throw err;
    }
    return true;
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
}

function prune(keep) {
  for (const item of fs.readdirSync(cache, { withFileTypes: true })) {
    const full = path.join(cache, item.name);
    if (full === keep || !item.isDirectory() || !/^([0-9a-f]{32}(\.lock)?|staging-.+)$/.test(item.name)) continue;
    try {
      if (Date.now() - fs.statSync(full).mtimeMs > PRUNE_AFTER_MS) fs.rmSync(full, { recursive: true, force: true });
    } catch {}
  }
}

function ensure() {
  fs.mkdirSync(cache, { recursive: true });
  for (;;) {
    const key = buildKey();
    const build = path.join(cache, key);
    const lock = `${build}.lock`;
    const deadline = Date.now() + LOCK_WAIT_MS;
    let owned = false;
    while (!fs.existsSync(build) && !owned && Date.now() < deadline) {
      try {
        fs.mkdirSync(lock);
        owned = true;
      } catch (err) {
        if (err.code !== "EEXIST") throw err;
        sleep(50);
      }
    }
    let settled = true;
    try {
      if (!fs.existsSync(build)) settled = compile(key);
    } finally {
      if (owned) fs.rmSync(lock, { recursive: true, force: true });
    }
    if (!settled) continue;
    const now = new Date();
    fs.utimesSync(build, now, now);
    prune(build);
    return build;
  }
}

const build = ensure();

module.exports = {
  dir: build,
  maps: path.join(build, "maps"),
  watercolour: path.join(build, "watercolour"),
  dsk: path.join(build, "dsk"),
};
