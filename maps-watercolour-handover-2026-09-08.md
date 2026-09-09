# Maps + Watercolour handover — 2026-09-08

Implementation is stopped at the user's request. Do not auto-resume this work. This document records the state at the stop point so a future reviewed implementation pass can continue deliberately.

## Workspace and working agreement

- Workspace: `/Users/anyhowclick/Desktop/work/obed-edom-wt-maps-tab`
- Branch: `codex/maps-watercolour-objects`
- The branch has uncommitted work. Do not commit, open a PR, or publish before the remaining implementation and independent reviews are complete.
- `/Users/anyhowclick/Desktop/work/obed-edom` is on an unrelated dirty branch. Never edit it.
- Requested workflow: Astra plans, Sol reviews the plan, Terra is the sole implementation executor, then two Sol final reviews. Root only orchestrates and performs independent QA.

## Current QA context

- Root's current QA server is port `8766`, process `44994`, exec session `44060`.
- Root's browser tab 6 is the active style QA tab. It is on test deck `edec02a6`, titled `Style swatch QA`, at latitude `1.286`, longitude `103.854`, zoom `18.5`, with Watercolour selected. Do not drive the UI without a new explicit request.
- Other QA decks: `94b496dc` and `dae2f886`.
- The last root server restart happened before the newest object-scale and thumbnail code. The current built files are `dashboard/dist/assets/MapsTab-Gbp6I4AA.js` and `dashboard/dist/assets/index-CuSoPKbv.js`; root has not reloaded or verified this build.
- The running server may also hold the pre-no-wobble Python module. The standalone renderer artifacts are verified, but a future agent must rebuild, restart, and reload before judging the live app.

## Completed or substantially implemented

### Watercolour photo renderer

- [x] Local procedural Watercolour conversion exists, including batch history and result download.
- [x] Dark-pigment floor correction was reviewed and implemented. On the supplied Mumbai benchmark, the intended dark shirt's near-paper fraction changed from `67.5%` to `0`; sky luminance delta was `0`. Root visually approved the corrected shirt and warmer domes.
- [x] The approved no-wobble-only correction was implemented. `_wobble` preserves the two original random draws but returns the unwarped wash. Do not change mean-shift, median blending, pigment floor, hue, ink, sky, or alpha as part of that correction.
- [x] Architecture ablation helper: `scripts/watercolour_architecture_ablation.py`. It produced current/no-wobble/no-blotch/both outputs for Mumbai and both supplied church photos in `output/watercolour-architecture-ablation/`.
- [x] Explicit byte verification helper: `scripts/verify_watercolour_no_wobble.py`. Root ran it successfully against Mumbai and both church images. It requires explicit `--reference`, two `--church`, and `--ablation` arguments.
- [x] Final local benchmark: `output/watercolour-final/render.png`.
- [x] Portable Watercolour tests were last reported as seven passing. The real-photo byte gate intentionally moved out of pytest because it depends on user-local clipboard inputs.

### Map styles and camera

- [x] Watercolour vector style is an original OpenFreeMap-compatible transformer with turquoise water, peach land, sage parks, cool ice/glacier, orange/yellow roads, muted labels/boundaries, and thin white water/road casing treatment.
- [x] The synthetic Watercolour diagonal pattern was removed from the builder, registration paths, example, and documentation.
- [x] The MapLibre black-map failure from `line-width: undefined` was fixed. A cached complete Positron transform check now rejects undefined values; root verified Watercolour renders again.
- [x] Portable Watercolour source/glyph overrides remove conflicting inline vector tiles.
- [x] Toner was vendored from MapTiler commit `8688fbd46e1918cae2e9c3d36e607b9d994badfe`; full/background/lines variants and local patterns were working in earlier root QA.
- [x] Closed-form camera flight math and Toner variant checks have executable frontend coverage.

### CAS and document ownership

- [x] Maps state saves use a revision envelope, structured stale-state conflict response, recursive three-way document merge, a serialized frontend save queue, and explicit reload/keep conflict controls.
- [x] Asset upload returns a typed asset plus revision/document ACK; asset metadata is server authoritative.
- [x] Fresh deck title/camera edits were rechecked by root and now persist after the queued-to-done queue initialization fix.
- [x] Server validation now checks nonempty unique slide IDs, unique LW/CG object IDs per view, unique links, and valid link endpoints.
- [x] Focused Maps API testing was last reported at 55 passing after these validations. The frontend production rebase/queue/style tests were last reported passing before the newest unreviewed scale/thumbnail edits.

### Current unverified object and thumbnail edits

- [ ] Latest code builds but root has not live-verified it: preview object scale uses preview surface CSS width divided by authored width.
- [ ] The same scale was applied to dots, strokes, landmarks, drop pins, labels, and label halo. Export is intended to remain authored size (`1`).
- [ ] Landmark sizing now records the actual registered, possibly downscaled bitmap width rather than dividing by the original asset width.
- [ ] Map readiness now rejects on timeout/style replacement. Thumbnail capture has a visual fingerprint, token checks, and a debounced auto-refresh attempt.
- [ ] These newest edits have no meaningful focused production tests yet and have not been independently reviewed or live QA'd.

## Remaining work

### Watercolour map visual QA and picker

- [ ] Validate complete Watercolour style through a real MapLibre style validator, pan/zoom across coastlines, and verify no tile seams in top-down and pitched views.
- [ ] Perform a full export visual check for road casing thickness, labels, water/land treatment, and the Watercolour thumbnail.
- [ ] The style picker is currently a native select. Replace it only after real thumbnails are checked in with a keyboard-accessible three-column grid popover: selected state, disabled state, Escape, outside-click close, focus return, ARIA labels, and visible attribution beside the grid.
- [ ] Root captured current candidate thumbnails at `/private/tmp/maps-style-ready-{positron,liberty,bright,dark,fiord,toner,toner-background,toner-lines,watercolour}.png`.
- [ ] Positron and Liberty captures are at zoom 20 and need recapture at the common zoom 18.5. The others are approximately 18.5. A 3D capture is still needed at pitch 45 with visible extrusion.
- [ ] These are 852×120 panoramas. Choose an intentional crop/aspect for picker tiles; keep OSM/MapTiler attribution outside the cropped thumbnail.
- [ ] Do not use `/private/tmp/maps-style-{liberty,bright,dark}.png`: they are invalid stale Positron captures.
- [ ] No real picker PNGs are checked into `dashboard/public` yet.
- [ ] Latest thumbnail capture refresh is unverified. Root previously needed a tiny camera change after style selection to refresh a thumbnail.

### Objects, movies, exports, and Keynote

- [ ] Add meaningful tests for preview scale across all object types, LW/CG, movie transitions, and resize/authored-width changes.
- [ ] Finish thumbnail latest-wins drain tests and verify no stale metadata is posted during style/object edits.
- [ ] Complete Objects wording cleanup: replace residual “Pin” wording, remove duplicate “Show label”, prevent invalid landmark type selection, and finish size/opacity/visibility properties.
- [ ] Finish copy/paste target chooser for selected multi-slide LW/CG destinations, Cmd/Ctrl-C and Cmd/Ctrl-V behavior outside editable inputs, fresh IDs, asset references, and persistence tests.
- [ ] Verify Keynote anchors, aspect ratio, opacity, world-copy/clipping behavior, and split CG output. Native Keynote opacity is deferred; keep the existing derived PNG alpha path until separately approved.
- [ ] `dae2f886` has LW/CG exports with separate PNGs. Only archive preview inspection occurred; editable live-Keynote validation did not. Never touch `A_PATCHED.key`.

### Studio lifecycle and masking

- [x] FileWell chooser/reset, batch mask clearing, source-alpha submission, and transparent-only Add to map were implemented, but need full end-to-end QA.
- [ ] Build the actual mask correction UX: pointer brush strokes, visible keep/remove overlay, checkerboard result preview, preview endpoint, reset behavior, and bounded feather control.
- [ ] Validate mask JSON bounds and malformed/out-of-bounds/nonfinite correction handling. Cover duplicate filename/index semantics.
- [ ] Fix queued cancellation staging cleanup, submit-failure cleanup, running cancellation retained results/statuses, and atomic original/result writes with rollback.
- [ ] Verify alpha preservation and eliminate any remaining double-feather/transparent-fringe issues.
- [ ] Add active-tab refresh for Maps destinations because Watercolour remains mounted while hidden.
- [ ] Finish Add-to-map ACK reconciliation, network error handling, atomic asset/object rollback, and corresponding end-to-end tests.

### CAS backend completion and review

- [ ] **Priority confirmed by Sol2:** `_seed_result` still lacks `stateRevision: 0`; the fresh-deck UI persistence result does not prove the first CAS save works.
- [ ] **Priority confirmed by Sol2:** queue reset retains an old in-flight promise. A flush for a new job can attach to the old job and leave the new document dirty and unsaved.
- [ ] **Priority confirmed by Sol2:** older out-of-order ACKs can move the acknowledged base revision backward.
- [ ] **Priority confirmed by Sol2:** conflict freeze is incomplete; MapView gestures/callback paths remain active despite locked form controls.
- [ ] **Priority confirmed by Sol2:** session assets/previews are installed and backup removal occurs before document commit, preventing reliable rollback.
- [ ] **Priority confirmed by Sol2:** mutations do not yet share one atomic contract with job completion, CSV/export, history relocation, and the session status/commit window.
- [ ] **Priority confirmed by Sol2:** `flushAndSave` schedules a save rather than awaiting its completion.
- [ ] Migrate remaining backend Maps writers, session/import paths, export metadata paths, and file publication through the shared mutation/lock contract.
- [ ] Add rollback for failed atomic file/document publication and tests for it.
- [ ] Add real concurrent races: Studio append vs stale state save, two appends, stale thumbnail writer after append, asset revision handoff, session import vs stale save, and delete/edit conflict.
- [x] Sol2 confirmed source fixes for local array appends, queued-to-done document initialization dependencies, upload captured target/latest document, form-control locking, and server IDs/endpoints validation.
- [ ] Sol2's pre-stop review found the priority blockers above. It ran 12 production Node tests and 11 focused API tests with 44 deselected, but this does not approve the current branch or replace final review.

## Useful commands

Run frontend commands from `dashboard`; use the bundled Node runtime because system Node may be too old for Vite:

```sh
(
  cd dashboard
  export PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
  npm install
  npm run build
  npm run test:maps
)
```

Focused Python checks:

```sh
.venv/bin/python -m pytest tests/test_maps_api.py -q
.venv/bin/python -m pytest tests/test_watercolour.py -q
.venv/bin/python -m pytest tests/test_maps_api.py tests/test_maps_geo.py tests/test_maps_tiles.py tests/test_maps_keynote.py tests/test_maps_movie.py -q
```

Restart the dashboard from the worktree root after a verified build:

```sh
.venv/bin/python -m obed_edom dashboard --no-browser --port 8766
```

Explicit local no-wobble verification:

```sh
.venv/bin/python scripts/verify_watercolour_no_wobble.py \
  --reference /path/to/mumbai-reference.png \
  --church /path/to/church-one.png \
  --church /path/to/church-two.png \
  --ablation output/watercolour-architecture-ablation
```

## Final stop condition

The user explicitly stopped implementation and requested this handover. Do not resume automatically. When work resumes, begin with a fresh Astra plan/Sol review for the next bounded package, preserve this branch's uncommitted state, run the relevant tests and root QA, obtain two independent Sol final reviews, then commit only verified work. Do not open a PR or publish.
