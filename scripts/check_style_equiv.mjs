#!/usr/bin/env node
// Proves the declarative half of "relief off ⇒ identical export": with
// hillshade hidden, `resolveOpenFreeMapStyle()` on 71c600d must hand MapLibre
// the same sources and the same visible layer list, in the same order, as it
// did on 7074a15 (the commit right before the ne2/exaggeration change).
//
// Fully offline: both trees are archived from git into a temp dir and their
// OpenFreeMap style fetches are served from the on-disk tile cache
// (output/.maps/tile-cache), never the network.
//
// Usage: node scripts/check_style_equiv.mjs

import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const BEFORE_SHA = "7074a15";
const AFTER_SHA = "71c600d";
const STYLE_IDS = ["positron", "liberty", "bright", "dark", "fiord", "buildings3d"];
const NE2_ID = "terrarium-ne2";
const HILLSHADE_ID = "hillshade";
const EXPECTED_NE2_STYLES = new Set(["liberty", "buildings3d"]);

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SCRIPT_DIR, "..");
const ESBUILD = join(REPO_ROOT, "dashboard", "node_modules", ".bin", "esbuild");
const TILE_CACHE_ROOT = join(REPO_ROOT, "output", ".maps", "tile-cache");
const TILE_PREFIX = "/api/maps/tiles/";

function cachePathForRel(rel) {
  let clean = decodeURIComponent(rel).replace(/^\/+/, "");
  const hasSuffix = /\.[^/.]+$/.test(clean);
  if (!hasSuffix) clean = `${clean}.json`;
  return join(TILE_CACHE_ROOT, ...clean.split("/"));
}

function installStubs() {
  globalThis.window = { location: { origin: "http://localhost:8765" } };
  globalThis.fetch = async (input) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith(TILE_PREFIX)) {
      throw new Error(`FATAL: fetch stub only serves ${TILE_PREFIX}*, got ${url}`);
    }
    const rel = url.slice(TILE_PREFIX.length);
    const filePath = cachePathForRel(rel);
    let text;
    try {
      text = await readFile(filePath, "utf8");
    } catch {
      throw new Error(`FATAL: missing tile-cache fixture for ${url} -> expected ${filePath}`);
    }
    return { ok: true, status: 200, json: async () => JSON.parse(text) };
  };
}

function archiveTree(sha, destRoot) {
  const dest = join(destRoot, sha);
  mkdirSync(dest, { recursive: true });
  execFileSync("sh", ["-c", `git archive ${sha} dashboard/src/maps | tar -x -C "${dest}"`], {
    cwd: REPO_ROOT,
  });
  return dest;
}

function bundleTree(treeDir, outDir, label) {
  const entry = join(outDir, `${label}.entry.mjs`);
  writeFileSync(entry, `export { resolveOpenFreeMapStyle } from ${JSON.stringify(join(treeDir, "dashboard/src/maps/styles.ts"))};\n`);
  const outfile = join(outDir, `${label}.bundle.mjs`);
  execFileSync(ESBUILD, [entry, "--bundle", "--format=esm", "--platform=neutral", `--outfile=${outfile}`, "--log-level=warning"]);
  return outfile;
}

function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
}

function diffPaths(a, b, prefix = "") {
  if (deepEqual(a, b)) return [];
  const aIsObj = typeof a === "object" && a !== null;
  const bIsObj = typeof b === "object" && b !== null;
  if (!aIsObj || !bIsObj || Array.isArray(a) !== Array.isArray(b)) {
    return [prefix || "(root)"];
  }
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const out = [];
  for (const k of keys) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (!Object.prototype.hasOwnProperty.call(a, k) || !Object.prototype.hasOwnProperty.call(b, k)) {
      out.push(path);
      continue;
    }
    out.push(...diffPaths(a[k], b[k], path));
  }
  return out;
}

function visibleIds(layers) {
  return layers.filter((l) => l.layout?.visibility !== "none").map((l) => l.id);
}

function fail(styleId, detail) {
  console.log(`STYLE-EQUIV: FAIL — ${styleId}: ${detail}`);
  process.exit(1);
}

async function main() {
  const work = mkdtempSync(join(tmpdir(), "style-equiv-"));
  try {
    installStubs();

    const beforeTree = archiveTree(BEFORE_SHA, work);
    const afterTree = archiveTree(AFTER_SHA, work);
    const beforeBundle = bundleTree(beforeTree, work, "before");
    const afterBundle = bundleTree(afterTree, work, "after");

    const { resolveOpenFreeMapStyle: resolveBefore } = await import(pathToFileURL(beforeBundle).href);
    const { resolveOpenFreeMapStyle: resolveAfter } = await import(pathToFileURL(afterBundle).href);

    for (const styleId of STYLE_IDS) {
      const before = await resolveBefore(styleId);
      const after = await resolveAfter(styleId);

      if (!deepEqual(after.sources, before.sources)) {
        const paths = diffPaths(before.sources, after.sources).join(", ");
        fail(styleId, `sources differ at sources.${paths}`);
      }

      const ne2Spliced = after.layers.some((l) => l.id === NE2_ID);
      const expectedNe2 = EXPECTED_NE2_STYLES.has(styleId);
      if (ne2Spliced !== expectedNe2) {
        fail(styleId, `ne2Spliced=${ne2Spliced}, expected=${expectedNe2}`);
      }

      const expectedLength = before.layers.length + (ne2Spliced ? 1 : 0);
      if (after.layers.length !== expectedLength) {
        fail(styleId, `layers.length after=${after.layers.length}, expected before.length(${before.layers.length}) + ${ne2Spliced ? 1 : 0} = ${expectedLength}`);
      }

      const afterFiltered = after.layers.filter((l) => l.id !== NE2_ID);
      if (afterFiltered.length !== before.layers.length) {
        fail(styleId, `after (ne2 removed) has ${afterFiltered.length} layers, before has ${before.layers.length}`);
      }
      for (let i = 0; i < before.layers.length; i++) {
        const beforeLayer = before.layers[i];
        const afterLayer = afterFiltered[i];
        if (beforeLayer.id !== afterLayer.id) {
          fail(styleId, `layer order mismatch at index ${i}: before.id=${beforeLayer.id} after.id=${afterLayer.id}`);
        }
        const diffs = diffPaths(beforeLayer, afterLayer);
        if (beforeLayer.id === HILLSHADE_ID) {
          if (diffs.length !== 1 || diffs[0] !== "paint.hillshade-exaggeration") {
            fail(styleId, `layers[${i}] (id="hillshade") differs at [${diffs.join(", ")}], expected exactly ["paint.hillshade-exaggeration"]`);
          }
        } else if (diffs.length !== 0) {
          fail(styleId, `layers[${i}] (id="${beforeLayer.id}") unexpectedly differs at [${diffs.join(", ")}]`);
        }
      }

      const beforeVisible = visibleIds(before.layers);
      const afterVisible = visibleIds(after.layers);
      if (!deepEqual(beforeVisible, afterVisible)) {
        const beforeSet = new Set(beforeVisible);
        const afterSet = new Set(afterVisible);
        const onlyBefore = beforeVisible.filter((id) => !afterSet.has(id));
        const onlyAfter = afterVisible.filter((id) => !beforeSet.has(id));
        let firstDivergence = -1;
        const minLen = Math.min(beforeVisible.length, afterVisible.length);
        for (let i = 0; i < minLen; i++) {
          if (beforeVisible[i] !== afterVisible[i]) {
            firstDivergence = i;
            break;
          }
        }
        if (firstDivergence === -1 && beforeVisible.length !== afterVisible.length) firstDivergence = minLen;
        fail(
          styleId,
          `visible layer id lists differ: onlyBefore=${JSON.stringify(onlyBefore)} onlyAfter=${JSON.stringify(onlyAfter)} firstDivergenceIndex=${firstDivergence}`
        );
      }

      const hillshadeAfter = after.layers.find((l) => l.id === HILLSHADE_ID);
      const hillshadeBefore = before.layers.find((l) => l.id === HILLSHADE_ID);
      if (hillshadeAfter?.layout?.visibility !== "none" || hillshadeBefore?.layout?.visibility !== "none") {
        fail(styleId, `hillshade layout.visibility not "none" as resolved (before=${hillshadeBefore?.layout?.visibility}, after=${hillshadeAfter?.layout?.visibility})`);
      }
      if (ne2Spliced) {
        const ne2Layer = after.layers.find((l) => l.id === NE2_ID);
        if (ne2Layer?.layout?.visibility !== "none") {
          fail(styleId, `terrarium-ne2 layout.visibility not "none" as resolved (got ${ne2Layer?.layout?.visibility})`);
        }
      }

      for (const [label, style] of [["before", before], ["after", after]]) {
        const layersJsonBefore = JSON.stringify(style.layers);
        for (const id of [NE2_ID, HILLSHADE_ID]) {
          const layer = style.layers.find((l) => l.id === id);
          if (layer) {
            layer.layout = layer.layout || {};
            layer.layout.visibility = "none";
          }
        }
        const layersJsonAfter = JSON.stringify(style.layers);
        if (layersJsonBefore !== layersJsonAfter) {
          fail(styleId, `re-setting visibility:"none" on the ${label} style document's terrarium-ne2/hillshade layers changed them (expected already-hidden, no-op)`);
        }
      }
    }

    console.log(
      "STYLE-EQUIV: PASS — 6 style ids / 5 distinct documents (buildings3d reuses liberty's cached style); relief-off visible layer lists identical; deltas confined to hidden 'terrarium-ne2' (liberty, buildings3d) and hidden 'hillshade' paint.hillshade-exaggeration"
    );
    process.exit(0);
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
