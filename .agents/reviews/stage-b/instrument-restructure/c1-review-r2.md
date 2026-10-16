# C1 code review r2 (Opus 5.5 high; code and tests lenses, self-refuted; target `d8725e5b`, r1 target `b77ae598`)

Confirmed 15 (0 blocker, 3 major, 5 medium, 7 minor). r2 folds every severity. Scratch:
`/private/tmp/claude-501/c1-review-r2/` (code) and `/private/tmp/claude-501/c1-review-r2-tests/` (mutants; the proposed
test diff is `proposed-test.diff`, 39 passed, lifecycle mutants 46/26 → 57/15 killed/survived, every survivor justified).

## r1 verdicts
Fixed: S1, S3, S4, S5, D1 (disclosure; gate-2 obligations open), D2 (0/50k OBS differences), D3, D4, D6, T2, T3, T4, T5,
T7, T8. Partial: S2 (geometry exact; kernel unproven, cost regression), D5 (`dataBits: 12.0`), T1 (counter final ≡
reference; hand-back and late-mount scenes lost), T6 (`no_frozen_return`, `no_cancel_raf` regressed).

## Code
**C1 medium · GL cell reads scan the whole read box per cell (20–50× CPU inside the product's draw call).** `cellMean`
(`scripts/mm_feed_instrument.py:185`) loops `read.rect` per cell. Counter read 3.3 ms (1:1), 11.8 ms (DSF 2), 65 ms (30°)
vs 0.09–1.2 ms at b77ae598. Fix: iterate each cell's own bounding box clipped to the read rect (verified identical on 22
harness cases; 0.34–1.41 ms).

**C2 medium · S2 kernel equality unproven.** GL side box-averages each projected cell; the source side is the browser's
`drawImage` downscale, which repo evidence records as plain bilinear for video (`keynote_live_dissolve_crossfade.plan.md:518,
:632`). Box-vs-bilinear model: 52 % false reds at 1920×540 σ=3. Fix: measure the `drawImage`→192 kernel once in headless
Chrome 155 on a video source, then match the GL side (box, or a bilinear point at the exact cell centre). Record it in the
C1 gate record before the separation re-proof.

**C3 minor · `counterSafe` checks block centres ±2 px; the read is the whole cell.** A later draw covering a cell edge
reads `ambiguous` instead of `covered` (`cover.js`). Fix: test the same cell polygons the read uses.

**C4 minor · sub-pixel cell fallback reads a 2×2 block offset ½ px.** Fix: the single pixel at `floor(cx), floor(cy)`.

**C5 minor · D5 `dataBits: 12.0` divergence still open (vector moved to 12.5).** Unreachable in the pipeline. Fix: Python
accepts integral floats (not bool); add a `12.0` row.

**C6 minor · simplify.** `decode_counter`'s `counter_layout` becomes required; `meanAt` radius is always 0 (single-pixel
read, fixes C4); one `cellQuad` helper for `vectorFromGl`, `counterFromGl`, `safeUv` and `counterSafe` (fixes C3).

## Tests
**T9 major · hand-back assertion vacuous** (`tests/test_mm_feed_instrument.py:280`: no context closes, `handbacks == []`).
`handback_two_frames`, `dom_gated_by_pixels` survive. Fix: close the killed move context and present 45–47; assert
`[("carry-killed", True, 3)]`.

**T10 major · counter final always equals reference** (`counter_final_is_reference` survives). Fix: present the counter
decoder one frame ahead of the uploaded texture once (n == 3).

**T11 major · late mount (the production order) never exercised** (`no_late_mount_resolve`). Fix: decoders appear after
the plan is assigned.

**T12 medium · UNPACK_FLIP_Y never exercised; production is 100 % flip=true** (277,926 stored rows). Fix: the fake records
`pixelStorei(UNPACK_FLIP_Y)` per upload, `paintSource` honours it, flip on around the counter upload.

**T13 medium · S2 kernel unpinned** (`s2_wide_kernel` survives). Fix: assert clean carry-alpha reads `dVideo < 2`.

**T14 minor · second `report()` identity dropped** (`no_frozen_return`). Fix: `report() === finalReport` in `frozen`.

**T15 minor · rAF cancel unobservable** (`no_cancel_raf`): the Video fake's cancel also pushes to `cancelled`. Fix: drop
that push.

**T16 minor · S4 fallback unpinned** (`s4_no_fallback`). Fix: one failed small `readPixels` at n == 2.

**T17 minor · redundant contract tests.** Delete `test_v2_replay_without_counter_layout_keeps_the_legacy_contract`; the
co-land test uses `_strict_setup` and its `referenceLevels` pop becomes a table row.

## Noted, not findings
`makeGl` resets module-level fake state per context (make it per-context before interleaving scenes); the fake's pixel
pattern repeats every 10 frames; the label scene's slope margin is .0058 (fragile; scorer owner).
