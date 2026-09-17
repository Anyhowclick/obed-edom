# Keynote build preview and transparent animation — implementation handoff

Reviewed 2026-09-16 against the current source and
[`kpf_renderer_probe_2026-09-12.md`](../research/kpf_renderer_probe_2026-09-12.md).
This expands DSK plan item 21; the DSK plan remains authoritative for operator decisions.
Status: **P1 implemented and live-checked 2026-09-16.** Parser had to be taught the
live Keynote 15.3.1 HTML shape (`majorVersion`/`minorVersion`,
`events[].accessibility[].text`, media-filename noise, IWA-only operator notes)
before `Alpha_Wall.key` / `Alpha_DSK.key` would map. Source decks were not
modified. **P2 first capture (2026-09-16) did not pass.** P2.1 treated `#n` as a
slide index; owner correction 2026-09-16: **hash is a scene, not a slide.**
P2.2 is `?currentSlide=N` (exported 1-based → starting scene). P3 is not
implemented.

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

## P2.1 — capture identity, then timing, then composed alpha

Owner rule 2026-09-16: **identity, then timing, then genuine composed alpha**.
Stale leftover textures and opaque ProRes round-trips cannot count as passes.
P3 and DSK Exporter alpha stay off until a slide meets all three gates.

P2 first capture (same `Alpha_DSK.key` fingerprint as the table above): composed
1920×1080 page screenshots were fully opaque (`alpha_min` 255). Slide 3 initial
and click `before` were byte-identical to slide 1 (Matthew 18). After Space the
plate was Genesis with 36 identical holds (LineDraw motion not sampled). Slides
4 and 5 page captures were the Genesis + Elohim leftover, not the photo/movie
(`pdf-rasters/slide-04-page-1.png` is the photo). Object-composites on 4/5 were
leftover slide-3 textures and must not score as alpha. `slide-03-click1.mov`
decoded MAE 0 against opaque sources — not a transparent-video pass. Headless
idle rAF was 0/500 ms.

Gate 1 (must go green first): tear the page down between slides (`about:blank`,
then `index.html` + expected `playerHash`); live hash must match; painted
composed screenshot must not match a previous settled plate and must be closer
to this slide’s PDF raster than to any other live slide (empty-identity photo/
movie included); leftover object-canvas layers fail identity; Space is only a
click proof after Gate 1 on the *current* slide. Hash-only / `{uuid}.json` is
not painted identity. Do not install a `requestAnimFrame` shim to pass identity.
Headed Chrome is an escalation only when the owner says the UI is free.

P2.1 live re-run 2026-09-16 15:00 (same `Alpha_DSK.key` fingerprint): isolated
headless pages made **slides 1 and 3 painted identity pass** (`#0` Matthew,
`#1` Genesis initial). Space on slide 3 changed the player hash to `#2` (not a
same-slide LineDraw). Slides 4–5 still failed identity (closer to the prior
plate / byte-identical leftover). Composed page alpha remained opaque
(`alpha_min` 255). Timing and transparent ProRes did not pass. P3 waits.

Gate 2 (only if Gate 1 passed): idle rAF ≥ 10 in 500 ms; slide 3 LineDraw must
show non-identical intermediate frames at declared 30 fps; `timing_repeatability`
must pass on changing progress, not on identical holds. No private player
functions.

Gate 3 (only if Gates 1–2 passed): score the composed page framebuffer only.
Object-composites never set `supportedStaticAlpha`. Colour-keying remains
forbidden. ProRes 4444 pass requires source frames that already have genuine
alpha *and* decoded alpha MAE within the declared bound. Fixture
`black-content.mov` is codec evidence only.

## P2.2 — `?currentSlide=` control (owner 2026-09-16)

The HTML player hash is a **scene** index. `#n` in the URL wins over query
parameters and selects that scene, not the exported slide. The player expands
each source slide into one or more animation events. Measured Alpha_DSK starting
scenes:

| Source slide | Starting scene | `?currentSlide=` (1-based exported) |
| --- | --- | --- |
| 1 Matthew | 0 | 1 |
| 3 Genesis | 1 | 2 |
| 4 Photo | 3 | 3 |
| 5 Movie | 4 | 4 |

P2.1 loaded `#0,#1,#2,#3`, so photo and movie were the wrong scenes. Genesis
`#1` → `#2` after Space can be the LineDraw/Elohim scene of the same slide, not
a slide exit. Zero idle `requestAnimationFrame` *requests* does not prove a
frozen clock: an idle player may request none. Count **executed** callbacks
under an active heartbeat; ~115 ms screenshot dt is a capture-throughput limit.

Alpha: the player already requests transparent PDF rendering and clears its
animation WebGL surface transparently. Some states then use **full-slide
composite PDF textures** (Genesis: individual layers during the build, full-slide
textures at the final hold). A patch might yield transparency in motion and
opaque holds. Colour-keying and indiscriminately dropping full-size canvases
remain invalid. A limited text/shape alpha route is still worth this bounded
probe; a general faithful exporter remains low-confidence. Stop if full-slide
textures inseparably flatten background and artwork.

Control experiment (this spike), painted identity still independent of hash:

1. Load each live slide via `index.html?currentSlide=N` (no hash). Verify
   Matthew, Genesis, the actual photo, and the movie/poster.
2. Capture Genesis before Space; prove intermediate LineDraw/Elohim frames while
   Genesis remains identifiable (`#2` is allowed).
3. Measure executed frame callbacks with a heartbeat.
4. Only if 1–3 pass: trace initial/moving/final active PDF textures for a
   structurally separable background. Do not colour-key.

P2.2 live 2026-09-16 15:25 (same `Alpha_DSK.key` fingerprint): `?currentSlide=1..4`
(no hash) plus wait-for-paint. Painted identity passed for **Matthew, Genesis,
source 4 media, and source 5 media**. Genesis Space advanced scene `#1` → `#2`
with 20 distinct frames including Elohim, Genesis still identifiable. Heartbeat
executed 31 rAF callbacks in 500 ms (idle requests were 0). Composed page alpha
still opaque. Texture inventory on a second Genesis load saw 4 `img` nodes and
**0 canvases**, so a separable-background PDF patch is **not** yet evidenced.
Timing repeatability still fails (duplicate motion frame / ~115 ms screenshots).
P3 waits.

## P2.3 — img / PDF texture trace (owner 2026-09-16) — **STOP**

Traced live DOM + Genesis PDF under `?currentSlide=2`. Source fingerprint
unchanged.

The four DOM `<img>` nodes are **navigator `thumbnail.jpeg` only** (not stage).
Stage textures are `<canvas id=ASSET_ID>` whose ids match Genesis JSON texture
assets; `asset.index` is the PDF page. Initial/build uses pages 0–7: page 0 is
an opaque black 1920×1080 underlay (`transparentFrac=0`); object pages 2/4/5/6/7
have genuine empty-background alpha. After Space, export event 1 uses **only**
full-slide pages 8–9 — both rasterise `alpha_min=255` with black corners (page 8
has `/SMask` but still no empty background). Opaque background therefore enters
as (1) the page-0 underlay and (2) flattened full-slide composites at the hold.
Page 0 is backdrop-only in structure, but pages 8–9 have **no** separable
backdrop operation left. Colour-keying remains invalid.

**Was STOP (pre-reassessment).** Full-slide rasters flatten at the hold; the PDF
stream still has a separable leading black fill (recovery 2026-09-16). Object-page alpha is not a composed export path. Keep P1 HTML
preview and stage-PNG export. P3 stays off. Samples:
`p2-alpha/output/p2-alpha-spike/img-trace/`.

## Recovery 2026-09-16 — bounded plan executed (P3 still off)

Reassessment `REPORT.md` reopened feasibility. Executed steps 1–5 in `p2-alpha`:

1. **Native UI Movie control (PASS).** Scratch Genesis + opaque black sentinel;
   Movie sheet Format=Apple ProRes 4444 + Export with transparent backgrounds.
   Decoded `yuva444p12le` / `ap4h`, transparentFrac ≈ 0.88, sentinel intact,
   motion present. Scripted `.m4v` without the UI checkbox stays opaque
   (transparentFrac 0) — the UI setting matters. Samples:
   `p2-alpha/output/p2-recovery/movies/`.
2. **Classification.** UI = success (corrected gates: mean empty alpha +
   transparentFrac; emptyPatchAlphaMax alone was a false negative). Scripted =
   opaque_output_after_successful_export.
3. **PDF strip (static PASS).** Removed identified full-canvas black fill from
   Genesis PDF pages 0/8/9 only. Page 8/9 static rasters regain empty-background
   alpha; artwork survives. Samples: `p2-alpha/output/p2-recovery/html-stripped/`.
4. **HTML capture.** Identity passes with `?currentSlide=3#1` on stripped export
   (`painted_identity` now fails closed on weak own-raster evidence). Composed
   page screenshot remains opaque (`alpha_min` 255). LineDraw intermediates not
   sampled (identical holds). Samples: `p2-alpha/output/p2-recovery/html-capture/`.
5. **Encoded alpha.** Native UI ProRes proves transparent intermediates. HTML
   ProRes round-trip of opaque page frames is MAE 0 — not a transparent pass.

**Verdict:** native transparent ProRes path is open for this Genesis scratch.
HTML composed-player alpha still fails despite structural PDF repair. Keep P1
preview + stage PNGs. **Do not wire P3 / DSK Exporter alpha** until product
gates for that path are green.


## Recovery follow-up — `.pdfp` load defect (2026-09-16)

**Defect:** strip rewrote `.pdf` only; capture used `file://`. The player loads the
companion `.pdfp` via `window.local_pdf` (base64 PDF). Decoded `.pdfp` for Genesis
is byte-identical to the **unmodified** opaque PDF (`ff87aeae…`), not the stripped
file (`d879ef46…`). Static Quartz and the browser consumed different bytes, so
“static alpha restored / composed page opaque” did **not** test repaired textures.

Native UI transparent ProRes PASS for Genesis is unaffected.

### Next research (in order)

1. **Load repaired bytes in the browser.** Serve over local HTTP and/or rewrite
   `.pdfp` base64 to the stripped PDF. Assert loaded-byte identity before any
   alpha score; require live texture empty-background alpha.
2. **Genuine LineDraw at 30 fps.** Trace event acceptance + animation progress;
   dense capture over the build. Six sparse wall-clock samples are invalid.
   Two-run `timing_repeatability` on changing progress.
3. **Mixed-video fixtures (slides 11–13 / new Alpha_DSK multi-slide clips).**
   Movie-start, overlays during playback, cross-slide Magic Move. Require opaque
   video in footprint, transparent empty canvas, preserved overlays, correct timing.
4. **If alpha disappears:** isolate texture vs effect FB vs DOM vs screenshot;
   targeted correction only. No colour-keying.

P3 / DSK Exporter alpha stay off until these gates pass.

### Follow-up executed 2026-09-17 (P3 still off)

1. **Loaded repaired bytes — PASS.** `.pdfp` rewritten to stripped sha `d879ef46…`;
   HTTP fetch of live `.pdf` matched. Samples:
   `p2-alpha/output/p2-recovery/html-loaded-capture/`.
2. **30 fps LineDraw — FAIL.** Identity PASS at `#1`; hash advanced; progress stuck
   (~0.272); `distinctFrames=1`; timing_repeatability failed (identical holds only).
   Mid-frame / ProRes page frames opaque.
3. **Mixed FW 11–13 — opaque only (narrow).** Prior refuse-by-construction probe on
   `DSK_Gen_Export_Input.key` was invalid as a transparency capability test (FW wall
   has no transparency). Valid observation only: unchanged FW mixed slides produced
   opaque stage PNGs and opaque scripted ProRes; layout/fill not isolated. Samples:
   `p2-alpha/output/p2-recovery/mixed-11-13/` (16 GB dump deleted; reports kept).
4. **Alpha boundary — incomplete.** Page-8 static vs live canvas (asset maps to page 9)
   plus black `body` bg — not yet a proven effect-FB localization. Samples:
   `p2-alpha/output/p2-recovery/alpha-boundary/`.
5. **Mixed Alpha_DSK 6–8 — evidence PASS (native UI transparent).** Retargeted to
   alpha-capable DSK multi-slide clips (not FW). Independent empty ROIs established
   (~80–91% empty); already transparent before No Fill; UI ProRes 4444 + transparent
   backgrounds (`ap4h` / `yuva444p12le`); 8 sparse frames (no full decode). Gates:
   empty canvas + per-movie footprints + text overlays pass on slides 6–8;
   `supportedTransparentMixed=True`. Source unchanged. Samples:
   `p2-alpha/output/p2-recovery/mixed-11-13-transparent/`.
6. **Dense windows on same movie — PASS (dissolve path).** Coarse 2fps peak find →
   30fps bursts around movie-starts and cuts 6→7 (@44.75s) / 7→8 (@67.25s) plus
   final hold. Empty alpha stable through windows; transition motion + clean
   boundary hints; anchors near settled stage PNGs; final-frame hold True.
   **Still open:** Magic Move during motion (not on this fixture); live Keynote
   playhead compare; continuous in-clip sync beyond bursts. Samples:
   `p2-alpha/output/p2-recovery/mixed-dense-windows/`.

7. **Magic Move 7→8 (nav 5→6) — export-path PASS.** After reconcile (MM into-8),
   slim UI transparent ProRes: dense window through cut shows empty alpha, motion,
   moving overlays, and video; 4s sync segment keeps empty + opaque movie centers.
   Live playhead screen compare blocked in-agent (`screencapture` TCC). Samples:
   `p2-alpha/output/p2-recovery/magic-move-7-8/`.
8. **HTML live dissolve (Minimal Alpha_DSK) — playback FAIL / alpha FAIL.** Fixture
   `Minimal Alpha_DSK.key` (`a3920567…`, 2 slides, dissolve 1.5s on-click into 2,
   automatic movie-starts, across-slides continue). HTTP patched export; delays
   `{0.5,1.5,3.0,5.0}`s; edge-click after auto movie-start settles at `#1` → `#3`.
   Media clock during wait matches delay. Second movie appears after dissolve.
   **Across-slides movie1 remounts at `currentTime≈0` on every dissolve** (position
   not continuous). Page screenshots opaque (`alphaMin` 255). Source unchanged.
   P3 still off. Magic Move HTML extension later. Samples:
   `p2-alpha/output/p2-recovery/html-dissolve-live/`.
9. **Continuity gate fixed + seek-handoff experiment (2026-09-17).** Offline
   counterexample (44× frozen `3.0`) now fails `continuesThroughDissolve`. Gate
   requires advancing media, not just a preserved first post-click position;
   presented-frame times preferred when present. Mid-transition jump
   `3.0→3.05→3.10→5.0` also fails (`noJump` enforced). Magic Move probe no longer
   force-quits Keynote or moves owner `.mov` files from the Desktop folder.
   Seek-handoff inject (`--handoff`): inconclusive — elapsed always hit the 2.5s
   cap; `got:0` without seeked/lifecycle proof. Replaced with lifecycle-only
   instrumentation. Samples: `html-dissolve-handoff/`.
10. **Decoder-preserve experiment — playback PASS (2026-09-17).** `--preserve`
    intercepts teardown before resource loss (src clear / removeAttribute /
    DOM detach), pools the across-slide `<video>` by asset key, and reuses that
    element when `initVideo` creates a replacement (`setAttribute('src')` +
    facade + DOM swap). Four delays `{0.5,1.5,3.0,5.0}`s:
    `successPlayback=True` (position continuous, advancing, noJump, movie2
    playing). HTML composed alpha still opaque / separate until item 11.
    Samples: `p2-alpha/output/p2-recovery/html-dissolve-preserve/`.
11. **PDF bg-strip + preserve dual gate — PASS (2026-09-17).** Surface inventory
    showed first opaque empty pixels come from full-slide PDF black fills
    (same Genesis pattern) plus opaque `body` chrome — present pre-dissolve, not
    dissolve-time WebGL. `--strip-pdf` removes only the identified solo/inline
    `0 1080 m … h f` fills and rewrites companion `.pdfp`; preserve inject forces
    transparent page chrome. Continuity scorer no longer treats wall-paced sparse
    capture gaps as seeks (capture-delta aware). Four delays with
    `--reuse-export --preserve --strip-pdf`: `successPlayback=True`,
    `successAlpha=True`, `success=True`. Pre-click ~99% transparent; empty right
    corners stay α=0 through dissolve; left opaque content retained. P3 still off.
    Samples: `p2-alpha/output/p2-recovery/html-dissolve-preserve-alpha/`.
12. **Adversarial HTML gate — alpha HOLD / playback FAIL (2026-09-17).** Owner-edited
    `Minimal Alpha_DSK.key` (`1c86a3db…`, 4 slides, No Fill): opaque black art,
    green MM 1→2 (authored interior α=75/255 ≈29.4%; ROI mean ≈82 averages white
    border), dual Untitled crops, across-slides continue 1→2, deliberate restart
    intent 2→3. Gate `scripts/p2_recovery_html_adversarial.py` with preserve + strip:
    - **Alpha holds:** empty corners clear; black sentinel opaque; green partial α.
    - **Playback:** composed Magic Move movie ROI stays pixel-identical while
      `currentTime` advances — **audio-only clock**. `Untitled.mov` in the export
      is **HEVC Main 10**; Chrome advances AAC/`currentTime` with `videoWidth=0`.
      Reattaching the preserved element did not restore pixels.
    - **Gate corrections:** (1) visible motion now requires sustained changing
      adjacent pairs (early+late), not one mid-window cut; (2) nav drains to
      `#6+`; (3) restart samples continuously through the drain with sceneHash +
      per-movie rows — late first obs → **inconclusive**, not conclusive fail;
      preserve `note()` carries `sceneHash`. Pool-clear alone is not a pass.
    Samples: `p2-alpha/output/p2-recovery/html-adversarial/`.
13. **Disposable H.264 decode probe — decode yes / “fully green” no (2026-09-17).**
    `scripts/p2_recovery_html_decode_probe.py` clones the adversarial HTML export
    (no Keynote), replaces HEVC `Untitled.mov*` with H.264 testsrc under the same
    filenames. **Established:** browser decode (`videoWidth>0` + changing
    `sampleFrame`) and visible moving pixels *after* remount-after-detach.
    Owner reproduction of the MM failure still stands: colour bars play before Magic
    Move; during MM both `<video>` leave the DOM; afterward the street **poster**
    remains. Remount is an overlay workaround, not Keynote restoring the layer.
    **Owner blocking findings (not green):**
    - Restart gate falsely passes on uninterrupted playback that starts pre-boundary
      (`0.297s` on `#5` → `1.958s` on `#6`). Near-zero must be tied to the target
      slide’s Start Movie, not any earlier hash.
    - Hardcoded remount slots + max z-index break authored composition (~55% of black
      rect covered, green obscured, extra movie upper-left) —
      `html-decode-probe/runs/primary/after-1to2.png`.
    - Dense “through MM” capture starts after `#1→#2` settle + remount + 0.35s — cannot
      prove uninterrupted visibility *during* the transition.
    Gate hardenings that remain valid: fixed `EXPECTED_MOVIE_KEYS`, mandatory decoded
    width, wall/media-spaced progression, `w>0` over null-width dupes,
    `preserveGeneration` on clear. Samples:
    `p2-alpha/output/p2-recovery/html-decode-probe/`.
    Handover: `.agents/handovers/keynote-alpha-html-2026-09-17.md` (OPEN 1).

**Stop line:** native UI transparent ProRes is proven for Genesis **and** Alpha_DSK
mixed clips 6–8. On Minimal Alpha_DSK HTML, PDF bg-strip restores empty-canvas
alpha; authored black/green survive. **HEVC Untitled.mov = audio-only clocks.**
Disposable H.264 decodes; remount shows post-transition colour motion — but restart
scoring, overlay composition, and during-transition capture are still red under
owner review. **Do not wire P3.**

**Next (OPEN 1):** preserve authored movie placement / layering / lifetime; restart
tied to Start Movie on the target boundary; capture that covers the Magic Move
itself — see handover.

## P2.4 — native PNG mid-frame probe (2026-09-16) — **no intermediate frames**

Question: can Keynote’s transparent PNG path evaluate an arbitrary animation
time, not only settled build stages?

**Sdef:** `export … as slide images` + `all stages` (= each settled build stage).
`show next` advances one build in play mode. No build class, playhead, scrub,
current time, or animation-time parameter.

**Live (Alpha_DSK Genesis / slide 3 scratch):** `all stages:true` emitted **2**
settled PNGs (initial + post-click). Both pass `validate_alpha`
(`transparentFrac` ≈ 0.88). Chunk oracle with `allow_automatic` said 4 — it
over-counts companions relative to PNG emission. Native ProRes re-check this
run failed on `.mov` destination (error 6); prior plan measurement still stands
for opaque movie alpha.

**Verdict:** settled native stage PNGs remain the working alpha path. There is
**no scriptable intermediate animation frame** on that renderer. P3 animated
transparent movies stay blocked. Samples:
`p2-alpha/output/p2-native-midframe/`.

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

P2.1 scoring: leftover textures and opaque ProRes round-trips are hard fails.
`supportedStaticAlpha` / `supportedAnimatedAlpha` require identity, then (for
motion) timing, then composed page alpha. Do not score object-composites as
slide-level alpha.

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
