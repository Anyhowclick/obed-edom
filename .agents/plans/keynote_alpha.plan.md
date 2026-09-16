# Keynote build preview and transparent animation — implementation handoff

Reviewed 2026-09-16 against the current source and
[`kpf_renderer_probe_2026-09-12.md`](../research/kpf_renderer_probe_2026-09-12.md).
This expands DSK plan item 21; the DSK plan remains authoritative for operator decisions.
Status: **P1 implemented and live-checked 2026-09-16.** Parser had to be taught the
live Keynote 15.3.1 HTML shape (`majorVersion`/`minorVersion`,
`events[].accessibility[].text`, media-filename noise, IWA-only operator notes)
before `Alpha_Wall.key` / `Alpha_DSK.key` would map. Source decks were not
modified. P2/P3 are not implemented.

Live P1 record (fixtures on Desktop, hashes unchanged after every Keynote run):

| deck | sha256 | mtime | inode | size |
| --- | --- | --- | --- | --- |
| `Alpha_Wall.key` | `82f66298805c9dccf4e2d494038c6c8a676398b10397a808040fe9f5eca843dd` | 2026-09-16 11:59:00 | 135441448 | 1952381018 |
| `Alpha_DSK.key` | `d8de34a942806f54fd401acb3ca7070774d1bb13331dc5dc39b200d63f64795c` | 2026-09-16 11:58:07 | 135440387 | 184556673 |

| check | DSK (`Alpha_DSK.key`) | GW (`Alpha_Wall.key`) |
| --- | --- | --- |
| HTML export | 18 s, 36.7 MB, 4/5 live, skip 2 omitted | 62 s, 454 MB, 9/10 live, skip 4 omitted, 7680×1080, peak RSS 1.1 GB |
| Mapping | 1→#0, 2 skipped, 3→#1, 4→#2, 5→#3 | 1→#0 … 4 skipped … 10→#8 |
| First / middle / last | UI 1 / 3 / 5; Previous disabled on 1, Next disabled on 5 | Player hashes #0 / #4 / #8 assigned; first slide rendered (wall photo) |
| Skipped jump | Slide 2 labelled “2 — skipped”; iframe removed; status explains omit | Same mapping rule; skip 4 has no player index |
| Multi-build | Slide 3 initial Genesis 1 plate rendered | Slide 5 mapped (#3); intra-build step not sampled here |
| Magic Move | none (all `transition: none`) | Slides 1, 3, 8, 9 carry `apple:magic-move-implied-motion-path`; #0 rendered |
| Close / switch | Back to stills leaves zero iframes; jump-to-skipped also disposes | — |
| Build stepping | Real click reached the iframe; Space/ArrowRight did not advance in this hidden Cursor browser (same rAF freeze the 2026-09-12 probe measured) | Hash set to #2/#6/#8; picture stayed on slide 1 in the hidden pane |

P1 is **not merged**: first-slide playback, skip mapping, close/dispose, and
source-fingerprint invariance passed; intra-build stepping and Magic Move
*motion* still need a visible browser (or the probe’s `requestAnimFrame`
setTimeout shim) before the playback gate is green.

## 1. Scope and delivery order

1. **P1: on-demand build preview** in the dashboard's existing deck review flow. Use Apple's
   exported HTML player to review motion; retain still thumbnails for normal browsing.
2. **P2: bounded alpha-capture feasibility spike**, with real output and an evidence report.
   This is a gate, not an assumption that CSS/background removal produces transparent frames.
3. **P3: transparent animation export** in DSK → Exporter, only after P2 passes and the asset
   timing contract below is confirmed. Reuse the same export manifest and renderer adapter.

Live show playback, output hardware, editing/cropping, resuming benched verse resizing, and
checker OCR replacement are outside this work. Do not expose KPF, Chromium or codec plumbing
as normal operator choices. Preview and alpha export must have separate capability states:
successful embedded playback is not evidence that transparent video export works.

## 2. Review findings and corrections

| Finding | Implementation consequence |
| --- | --- |
| HTML export has per-slide PDFs; `assets/global/` was empty | Discover assets from the exported header/slide data. Do not hardcode `global/shared.pdf` or delete a first PDF operation indiscriminately. |
| Player methods exist inside a minified closure, not on `window` | Hash navigation is the measured slide control. Prove keyboard/real browser input for builds; DOM `dispatchEvent(MouseEvent)` failed in the probe. |
| 119/119 tested effect instances had a renderer path | This is encouraging inventory evidence, not pixel fidelity, frame pacing, transparency or universal effect support. |
| Export omits skipped slides | Persist a source-slide-to-export mapping; never equate the player index with the original slide number. |
| Hidden in-app browser froze animation frames | Do not depend on a hidden iframe for capture. Prove the capture browser's clock and rendering behaviour separately. |
| Current stage exporter uses referent `buildChunks`, not raw build count | Click boundaries and effect counts differ. The old `build_count + 1` shorthand in DSK measured facts is insufficient for this work. |
| Native ProRes export had constant opaque alpha | Validate decoded alpha values and composites, not the codec name or pixel format. |

The probe's “few hours of glue” estimate is not an implementation budget: navigation mapping,
player lifecycle, storage, error states and capture remain work. Its timer shim unfreezes
playback; it does not establish deterministic frame capture.

## 3. Reuse and integration boundaries

Read these before implementing; follow the current checkout rather than old worktree recipes:

- `src/obed_edom/dsk_live.py`: `LiveBatch`, scratch-copy lifecycle, source fingerprint,
  Keynote bundle targeting, process ownership, lock and resource watchdog.
- `src/obed_edom/dsk_stage_export.py`: `stage_counts`, alpha statistics, naming and manifests.
  `stage_counts` counts referent chunks and refuses automatic/unresolved chunks. It is useful
  corroboration, not a complete movie timeline oracle.
- `src/obed_edom/iwa_builds.py` and `iwa_runs.py`: effect inventory and original slide order.
- `src/obed_edom/web/app.py`: DSK propose/decisions/apply jobs and asset-serving conventions.
- `dashboard/src/tabs/dsk/DskExporter.tsx`, `DskGenerator.tsx`, and shared preview components:
  extend existing jobs/results and navigation rather than creating another top-level tool.

Keep HTML export/manifest parsing and capture logic outside `web.*`; the dashboard calls the
same backend services that a CLI/probe can call. Introduce small modules as needed, not a
general renderer framework. Native export must participate in the existing Keynote exclusion
mechanism; browser playback of a finished export must not hold the Keynote lock.

Pin Playwright and its matching browser only if required for P2/P3, as an optional dependency.
P1 iframe playback should not acquire a capture-browser dependency. Do not download runtimes
silently during a normal job; report missing prerequisites before expensive export work.

## 4. P1 — dashboard preview

### Export and identity

- Export a scratch copy using Keynote HTML export and retain its relative asset structure.
  Preserve slide order and neighbouring slides for transitions; do not prune slides merely
  to navigate to one of them if that changes transition semantics.
- Initially omit source-skipped slides exactly as the measured exporter does. Show an explicit
  unavailable/skipped state for them. Supporting skipped slides requires a separately proven
  scratch-only unskip path, with mapping tests.
- Record a versioned manifest: source digest, Keynote version, canvas, export/parser version,
  player digest, and ordered entries containing original document ordinal, original slide ID
  where available, skipped status, exported UUID, player index/hash, and asset paths.
- Verify the exported sequence against the source non-skipped sequence. Refuse ambiguous or
  inconsistent mappings. Establish the hash's index base through a fixture/probe, not a guess.
- Bind results to the source digest; reject stale source state between proposal and apply.

### UI and storage

- Add an explicit “Preview builds” action. Show preparation progress, retryable failure, and
  a return to still preview. Navigation labels always use the original deck's slide numbers.
- Use the measured hash channel for slide navigation. For P1, focused native player input is
  sufficient for per-build stepping; custom Next/Previous Build controls need their own proof.
  Do not promise reverse-build or seek semantics the adapter has not demonstrated.
- Clear/dispose the player when switching jobs/decks or closing the preview. Do not keep a
  hidden player advancing audio/video. Report failures without breaking the still preview.
- Export on demand and reuse by digest/version. Expose cleanup and account for disk size;
  measured exports were 95 MB and 637 MB. Avoid automatic export for every job or unbounded
  permanent caching. Never delete another job's active assets during cleanup.
- Serve only files beneath the registered export root, with traversal/symlink escape checks
  consistent with existing file endpoints. Decide the iframe origin/sandbox deliberately:
  the probe's same-origin embed proves functionality, not unrestricted access as a requirement.
  Preserve the supported local player/assets and show external web media as unsupported unless
  explicitly supported; do not silently make capture depend on remote media.

### P1 acceptance

- Real DSK and GW decks: first/middle/last slide navigation, a multi-build slide, and GW Magic
  Move; correct original numbering across skipped slides, including direct jumps.
- Switching/closing previews stops playback; export failure leaves normal review usable.
- Source fingerprint unchanged; Keynote ownership/lock behaviour preserved; cache invalidates
  after source or renderer changes. Browser console/network failures are recorded.
- Unit/API tests cover identity mapping, stale proposals, missing assets, cleanup boundaries
  and manifest compatibility. UI checks cover loading, errors and unavailable skipped slides.

## 5. P2 — alpha and timing feasibility gate

Create a small local probe before wiring an export button. Keep unmodified HTML exports as
reference evidence; patch only a derivative. Report exactly which renderer/player version and
asset changes are required, with a refusal when their expected structure does not match.

### Transparency

Trace where opaque pixels originate: HTML/CSS, canvas/WebGL context or clears, slide background,
PDF textures, layout drawables, and actual authored artwork. Removing black CSS or requesting
transparent screenshots cannot recover alpha already flattened into a texture or framebuffer.
Preserve intentionally black content, white borders, shadows and semitransparent artwork.
Never use colour-keying or blanket full-page-fill removal as the default alpha implementation.
If a safe background distinction cannot be established, mark that slide unsupported.

Capture raw RGBA frames first. Show the same frames composited over black, white and a saturated
colour/checkerboard. Measure known empty-background alpha, known opaque content and edge pixels;
test for premultiplication halos. Include a black-content fixture so “remove black” cannot pass.
Check the encoded-and-decoded ProRes 4444 frames too: passing PNG alpha does not prove the movie.
Do not use a global `alpha_min == 0` check alone; one transparent pixel proves almost nothing.

### Clicks, time and fidelity

- Inventory events/effects and referent/automatic build chunks. Account for the measured
  LineDraw/LineDrawForLine companion pair without treating it as a second operator click.
- Prove actual browser automation inputs advance builds; do not call inaccessible private
  functions by name. Any player instrumentation must be version-checked and fail explicitly.
- Establish readiness (textures/fonts/media loaded), click boundaries, completion detection,
  reset/replay and a stable clock before capture. Arbitrary sleep durations are not an oracle.
- Capture at a declared constant frame rate (proposed 30 fps). Prove animation progress matches
  the output timestamps across repeated runs, with no missing/duplicate motion frames caused
  by screenshot speed. Identical intentional hold frames are valid.
- Test initial state, each settled click state, and intermediate motion. Use native stage PNGs
  as settled-state references where supported; compare motion against native Keynote playback
  or a reference movie. Set explicit numeric comparison tolerances from the fixtures and
  record them before declaring a pass; do not invent a universal tolerance after seeing errors.
- Probe automatic/with-previous/after-previous chains, build-out, Magic Move, character effects,
  line draws, and movie-start separately. Unsupported cases must be explicit per-slide refusals.

### Evidence and stop condition

Deliver a capability matrix, raw and decoded sample frames, composites, timing/alpha statistics,
source fingerprints, console errors, runtime/RSS/disk measurements and a reproducible command.
Use the known mixed movie/overlay slides 11–13 from `DSK_Gen_Export_Input.key` when available,
plus the measured DSK/GW examples. Record unavailable fixtures; do not substitute fabricated
results. A fixture passing static transparency does not pass animated transparency.

P2 may conclude that only a subset is safe. Keep P1 and stage PNG export; describe the blocker
instead of silently falling back to opaque output labelled as transparent.

## 6. P3 — proposed asset contract, requiring owner review before implementation

The existing owner contract says one asset per operator build step. It does not yet specify
initial-state handling, terminal holds, cross-slide transitions or audio for animated assets.
Present concrete samples from P2 and settle these decisions before implementing P3:

- **Proposed initial state:** one transparent PNG for the settled initial state, followed by
  one transparent movie for each click group. Each movie contains the complete composed slide
  state during that group's animation, including previously revealed objects, not just a delta.
- **Proposed click grouping:** one explicit click plus its automatic continuation chain forms
  one asset. The next explicit click is a new asset. No raw effect-count-to-file-count mapping.
- **Proposed end behaviour:** stop on the settled final frame; prove the intended ProPresenter
  import/playback holds that frame until the next cue. Do not assume a fixed five-second hold
  solves this. Check initial/final continuity when switching between assets.
- **Proposed transitions:** cross-slide transitions, especially Magic Move, require both slide
  states and a documented ownership rule. Preview may support them while initial alpha export
  refuses them. Do not claim transition support by exporting isolated slides.
- **Proposed media scope:** retain today's opaque mixed-movie clip behaviour. Transparent
  overlay-only movies, audio, movie loops and synchronized mixed media require separate proof
  and an explicit contract change. Do not activate the unused `overlay_bake` field as a side
  effect of adding alpha export.

Once agreed, add an explicit output choice in DSK → Exporter, preserve PNG defaults and existing
API clients, and validate capability before apply. Reuse propose → review → apply and job
history. Results report supported/exported/refused slides with reasons and original numbers.
Names must sort by original slide and click order; record the initial state distinctly in the
manifest so an initial PNG cannot be mistaken for the first animated click.

Stage output into a job-owned temporary folder, validate all assets, then publish completed
files with a manifest. Avoid overwriting previous successful exports or leaving partial movies
listed as complete. Cancellation/failure must stop only owned browser/encoder processes,
release resources and preserve useful diagnostics. Include encoder settings, dimensions, FPS,
frame count, duration, alpha results and click mapping in the output manifest.

## 7. Verification and handoff

Implement and review P1 separately from P2/P3. For non-trivial implementation, follow the repo's
applicable review workflow. No live Keynote run is needed merely to edit this plan.

Use focused tests for manifest parsing, click mapping, skipped-slide identity, unsupported
structures, stale inputs, subprocess failures and publication. Offline tests must not launch
Keynote. Run the existing DSK regression tests affected by the change. After dashboard source
changes, build using the current package scripts and visually check the actual served build;
consult the current checkout for test commands rather than stale worktree notes.

The implementation handoff should state which phase passed, exact fixture evidence, remaining
unsupported cases and whether the next phase needs an operator decision. Neither a successful
HTML export nor a successful ProRes encode constitutes acceptance of alpha animation.
