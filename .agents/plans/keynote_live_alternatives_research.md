# Alternatives to the overlap refusal — research brief (2026-09-20; both peers REPORTED 2026-09-20 evening — see “Results” at the bottom)

Owner ask (2026-09-20 morning): after the WebGL-texture spike died at Q2, get two independent peers to look for
alternative paths. Peer 1 was started and time-boxed to ~7 minutes because the owner had to pause; Peer 2 was NOT
started. Problem statement + measured facts: [`keynote_live_visible_content.plan.md`](keynote_live_visible_content.plan.md)
§5–§7; product baseline: [`keynote_live_baseline.plan.md`](keynote_live_baseline.plan.md).

Rules for both peers: research + measurement only, no repo edits, no product code; HEADLESS Chrome only; never touch
port 9222 / OBS / Keynote or a Chrome you did not start; own cache digest strings; assert the in-page viewport is
1920×1080 at session start (a concurrent headless Chrome can make a window fall back to the laptop display size);
pinned code = `.claude/worktrees/gate-runner` with `PYTHONPATH=<gate-runner>/src`; driver patterns to copy live in the
ignored evidence folder `output/live-visible-content/{diag,spike}/` of the branch worktree. Score results with
`html_alpha_probe.score_visible_slide` (full rect live) AND "green square still in front" (P2 Finding 2).

## Peer 1 — paths that work WITH / INSIDE the player's rendering
1. **GL command-stream capture & replay** (player-agnostic): wrap `WebGLRenderingContext.prototype`, record every GL
   call of the LAST frame the player drew, then at rest re-issue that frame each video frame with the movie texture
   (960×276, identified by upload size) refreshed via `texImage2D(video)`. Measure: reliable frame delimiting; verbatim
   replay = byte-identical screenshot (do programs/buffers/uniforms persist?); live grating with the green square in
   front; flipY/premultiply state; ms per frame at 1080p and an estimate at 1440p; clean hand-back when the player
   tears the canvas down (next slide, a build on the settled slide).
2. **Force the player's NON-WebGL renderer**: make `getContext('webgl'…)` return null before the player loads. Does the
   Magic Move still animate, does the DOM layer tree paint on the settled slide, is an in-layer `<video>` visible with
   correct z-order, what fidelity is lost, and why does the host refuse this mode today ("Player fell back from the
   authored build renderer" in `live_host.py`)?
3. **Keep the player drawing**: wrap the `requestAnimFrame` alias BEFORE load, capture the player's frame callback, and
   test whether re-invoking it at rest produces draw calls (no minified names).

## Peer 2 — compositing OUTSIDE the player (NOT STARTED)
1. **Static occluder cut-out**: keep the stage-level `<video>` overlay and lay a 2D canvas over it holding the pixels
   of the settled WebGL frame, inside the movie rect, that belong to later-authored artwork. Two ways to get them:
   (a) pixel difference between the settled frame and the poster texture the player uploaded (both readable: wrap
   `texImage2D` to keep the poster source; read the canvas via `drawImage(#0-canvas)` — check `preserveDrawingBuffer`,
   else capture inside the last drawn frame); (b) geometry from the export's draw slots (`baseLayer.layers` above the
   movie slot: rect + opacity; exact for opaque rects, approximate for shapes/text). Measure on the fixture's slide 2
   (green square α?, black box is BEHIND the movie): pixel match vs the raw settled frame outside the movie, full-rect
   liveness inside, green in front; translucent artwork error (slide 1's green is α0.29).
2. **Hole-punch instead of overlay**: put the `<video>` BEHIND `#0-canvas` and punch the movie region out of the canvas
   with CSS `mask-image`/`clip-path` on the canvas ELEMENT (no redraw needed), the mask = movie rect minus occluder
   shapes. Does a CSS mask on a WebGL canvas composite correctly in headless Chrome and in OBS's CEF (Chrome 127)?
3. **Lifecycle**: what happens on a BUILD on the settled slide (slide 2 has three build-in squares — does the player
   redraw `#0-canvas`, replace it, or switch to the DOM tree?), and on the next transition — the cut-out/mask must be
   rebuilt or dropped at those moments; find the observable signal (the hash changes without `hashchange`; GL draw
   calls resume). Scaled stage: everything in authored px mapped through the stage map.
4. Fidelity table + fail-closed rule: when can the cut-out be trusted (opaque, static artwork) and when must the
   baseline refusal still apply (translucent over the movie, animated artwork, masks)?

## Deliverable (each peer, ≤ 110 lines)
Per path: what was measured (numbers, screenshots looked at), verdict ALIVE / ALIVE-WITH-CAVEATS / DEAD, fidelity
table (z-order, translucency, masks, easing, builds, scaled stage), fragility vs the pinned player sha, size, the gate
that would qualify it; ranked recommendation + the single next experiment.

## Status log
- 2026-09-20 07:05 — Peer 1 launched, time-boxed to ~7 min (owner pause). Peer 2 NOT started (brief above is ready).
- 2026-09-20 07:12 — **Peer 1 headline: GL command-stream replay is ALIVE** (headless 1920×1080, raw player, fixture
  slide 2). Measured: 245 GL prototype methods wrapped; the 1→2 move = 8168 calls, 92 frames delimited by
  `clearColor`+`clear`, **every frame exactly 88 calls** (5 `drawElements` = the 5 slide objects); the player's frames are
  NOT rAF-driven (16 rAF callbacks vs 455 draws, zero GL inside rAF; re-invoking the captured rAF callback draws
  nothing ⇒ "keep the player drawing" via rAF is dead). Replaying the LAST 88-call frame at rest is **pixel-exact**
  (screenshot sha identical after 1 and after 10 replays, GL error 0) at **0.03 ms/frame** — programs, buffers, uniforms
  and textures persist. Re-uploading a live `<video>` into the movie's texture (identified by its upload signature:
  canvas source 960×276, RGBA/UNSIGNED_BYTE, `UNPACK_FLIP_Y` + `PREMULTIPLY_ALPHA` true) and replaying shows the **live
  grating across the full movie rect WITH the green square still in front**; a second shot 1 s later shows the grating
  advanced. No minified names touched; both structural assumptions (uniform `clear`-delimited frames; a poster upload of
  the movie's size) are assertable at runtime ⇒ can fail closed to the baseline `retire`.
  NOT measured (the real work): hand-back when the player draws again (next transition; a BUILD on the settled slide —
  slide 2 has three), restoring the poster texture before yielding, what actually schedules the player's frames, two
  movies on one slide, scaled stage / 2560×1440, OBS CEF (Chrome 127). Path 2 (non-WebGL renderer): code-read only — the
  host's "fell back from the authored build renderer" error is a SCENE-COUNT mismatch (the fallback collapses builds),
  low prior. **Next experiment:** a `requestVideoFrameCallback`-driven replay loop on settled slide 2 for ~5 s, then
  (a) advance to slide 3 and (b) fire a build on slide 2 — detect the player's first own GL call, stand down within one
  frame, restore the poster texture, and compare slide 3 byte-for-byte with a control run without the loop.
  Harness to resume from (ignored): `output/live-visible-content/alt-inplayer/replay.py` (+ `replay.json`, shots A–F).
- 2026-09-20 ~17:30 — Owner: run item 3 (the hand-back experiment + Peer 2) **next session**. A hand-back peer was
  launched and stopped by the owner before it measured anything; nothing to salvage. Ready-to-launch brief below.

## Hand-back peer — brief to launch next session (Opus, research only, headless, scratch scripts only)
Extend a COPY of `output/live-visible-content/alt-inplayer/replay.py` (worktree `friendly-sammet-32dab4`, git-ignored).
Use `continuity="off"` + a fresh `<video muted autoplay loop playsinline>` on the same asset (the product baseline now
refuses the 1→2 carry). Pinned code = `.claude/worktrees/gate-runner` (detached on the #158 tip). Fixture scenes: slide 1
= 0,1 (1 = the 1→2 Magic Move) · slide 2 = 2–5 (three build-ins, then the 2→3 dissolve at 5) · slide 3 = 6,7 · slide 4 = 8,9.
Measure, in order:
1. rVFC-driven replay loop on settled slide 2 for ~5 s: iterations, ms p50/p95, GL errors, dropped video frames; score
   with `score_visible_slide` (12-shot burst, rect (109.35,795.04,951.54,267.62), 40×40 corner control) and check a pixel
   inside the green square stays green and static.
2. Detect the player's own GL activity: flag calls issued by our replay; any unflagged call is the player's. Latency and
   shape of the player's drawing for (a) a BUILD on slide 2 (redraws `#0-canvas`? new canvas? DOM tree? does the frame
   length change?), (b) the 2→3 dissolve (draws at all, or just tears the canvas down — when?), (c) a go-to.
3. Stand-down inside the wrapper on the first unflagged call: stop the loop and synchronously restore the ORIGINAL poster
   into the movie texture (recorded pixel-store flags; restore the player's bindings) BEFORE the player's call proceeds.
   Compare with a CONTROL run without the loop at the same settled points (after the first build, after all builds,
   settled slide 3, settled slide 4): sha256; where different, max delta outside movie rects must be 0.
4. Re-arm after a build: re-record the new last frame and resume; look at the screenshot.
5. Stretch: keep the texture fresh WHILE the player draws the move (upload once per player frame from the `clear`
   wrapper) — does the movie play live through the move with the player's own easing?
6. Failure modes: context loss, `texImage2D` cost per frame, bounded memory (keep only the last frame), video not ready
   (replay with the poster, never a blank), taint.
Deliverable: per item numbers + screenshots looked at; hand-back verdict CLEAN / CLEAN-WITH-CAVEATS / NOT CLEAN; a
stand-down state machine (≤ 12 lines); fail-closed conditions (when to fall back to `retire`); what stays unmeasured
(two movies / equal-size posters, scaled stage, OBS CEF Chrome 127); the single next experiment.
Run Peer 2 (section above) alongside it; both must assert the 1920×1080 viewport in-page and use their own cache digests.

## Results — hand-back peer + Peer 2 (2026-09-20 evening, Opus, headless, research only)
Full reports live only in the session transcript (subagents could not write files); scripts + evidence (git-ignored) in
worktree `friendly-sammet-32dab4`: `output/live-visible-content/alt-handback/` and `…/alt-outside/`.

**The problem is narrower than we thought (both peers, independently).** On a BUILD and on the 2→3 dissolve the player
issues ZERO GL calls: in one mutation batch it removes `#0-canvas` (and any `#stage` child of ours) and the DOM layer tree
paints at opacity 1, where an in-layer `<video>` is natively live. The invisible-movie window is ONLY
[Magic-Move settle, next build/transition). The only hand-back signal is the removal of `#0-canvas`
(MutationObserver: same batch; rVFC watchdog: 139 ms after a build, 2490 ms after the dissolve command). The next Magic
Move uses a NEW WebGL context. Renderer disagreement: the settled WebGL frame paints the α0.2947 green square flat OPAQUE
(29,177,0); the DOM path paints it translucent — so at rest the player itself is not faithful to the authored opacity.

**Hand-back peer — GL replay: CLEAN-WITH-CAVEATS.** rVFC loop on settled slide 2: ≈29 Hz, p50 0.8–1.3 ms, p95 2.5–5.2 ms,
GL errors 0, 4–8 % of decoded frames unserviced; green pixel max Δ 0. Three armed runs vs two controls at five settled
points: max Δ OUTSIDE the movie rects = 0 everywhere (in-rect Δ = playback phase, reproduced control-vs-control). Poster
restore (`readPixels` at arm → re-upload) + replay = identical sha. Re-arm after a build: impossible and unnecessary.
**Stretch ALIVE: uploading the live video once per player `clear` during the 1→2 move — 91 uploads, 0 errors, movie plays
live with the player's OWN easing, green in front, seamless into the at-rest loop.** Caveat: the 12-shot CDP burst read a
demonstrably live replay as dead in 1 of 3 sessions (liveFrac 0.004) ⇒ needs an in-page `readPixels` liveness read.
State machine: IDLE →(poster upload seen, MM settles) ARM (snapshot poster, record last frame) → LIVE (per rVFC: canvas
disconnected / unflagged GL call / context lost / frame length changed / error ⇒ STANDDOWN, else upload+replay) →
STANDDOWN (stop, restore poster) → RETIRED (no re-arm on this slide) →(next MM, fresh context) ARM.

**Peer 2 — outside the player.** Enablers: `#0-canvas` is `preserveDrawingBuffer:false` (reads empty at rest) but
replay-then-read in the same task yields the settled frame (0.2–1.0 ms); the poster is drawn 1:1 at AUTHORED
(105,791,960,276) — registered there 79.1 % of the rect is byte-identical to the poster and the 20.7 % rest IS the occluder
(registering at the screen rect over-cuts to 48.6 %); at 1600×1000 the canvas keeps a 1920×1080 backing store ⇒ build
cut-outs in authored px. The live DOM tree on the settled slide is the SOURCE slide's ⇒ geometry must come from the export.
- A. cut-out by pixel diff: **ALIVE** — verdict true, liveFrac 0.799, green Δ 0 over 12 shots, outside-rect Δ on 9e-6 px.
- B. cut-out by export draw-slot rect: **ALIVE-WITH-CAVEATS** — +0.44 % over-cut (export rect ≈2 % larger than painted);
  bbox only for shapes/text/rotation.
- C. CSS `clip-path: path(evenodd…)` hole-punch on the WebGL canvas, video behind: **ALIVE-WITH-CAVEATS** — verdict true,
  zero readback/replay; the run had a bug (occluder not intersected with the hole ⇒ 3.09 % of outside pixels changed) —
  the failure mode is silent and global. OBS CEF (Chrome 127) `clip-path: path()` UNMEASURED.
Proposed fail-closed rule: poster upload found and reproduced byte-identically outside the cut-out; every overlapping
later slot an axis-aligned OPAQUE, unmasked, unrotated, un-animated rect (the fixture's α0.2947 green would be REFUSED);
`#0-canvas` present with the layer tree at opacity 0; observer armed before mounting. Harness caveat: the overlay used
the first `<video>`'s `currentSrc` — a product gate must bind the asset.

**Coordinator synthesis (recommendation, owner decides).** In-player GL (replay at rest + per-`clear` upload during the
move) is the only path that keeps z-order, translucency-as-the-player-paints-it and native easing with no geometry
assumptions, and its hand-back is pixel-clean; Peer 2's paths refuse this very fixture. Rank: (1) in-player GL; (2) Path A
as an independent pixel VERIFIER and Path C as the no-GL fallback; (3) baseline `retire` whenever any assertion fails.
**Next experiment:** per-`clear` upload through the move + hold at rest until `#0-canvas` is removed (MutationObserver,
not GL), at 1920×1080 / 2560×1440 / 1600×1000, scored by an in-page `readPixels` liveness read; then OBS CEF.
Still unmeasured: two movies / equal-size posters, a MOVING movie (3→4), go-to jumps, a settled slide with no builds,
masks, OBS CEF, the video-not-ready branch.

## Opacity disagreement — explained offline (2026-09-20 evening, Opus code-read, no browser; confidence HIGH)
The DOM path is right; the player's WebGL effect renderer DROPS WRAPPER OPACITY. Export: the green square carries opacity
0.29468… on a WRAPPER layer on both slides (slide 1 `b.4`, slide 2 `b.6.0`; leaf opacity 1; the 1→2 move animates opacity
1→1, only scale/translation); the texture PDFs are a flat opaque fill `0.1137 0.6941 0` = exactly the measured (29,177,0),
no `/ExtGState`/`/SMask`. Player `main.js`: the shader is fine (`gl_FragColor = vec4(Opacity) * texColor`, blend
`ONE, ONE_MINUS_SRC_ALPHA`), but `renderFrameWithContext` (offset ≈2190382) sets `Opacity = parentOpacity × leaf opacity`
and `textureInfoFromEffect` (≈2263358) seeds `parentOpacity` once from the stage root (1) and passes it down unchanged —
intermediate wrapper opacities are never multiplied in; `singleTextureOpacity` is never read. The generic GL branch
(≈2192670) has the same defect ⇒ every GL-rendered effect whose object has wrapper opacity paints it opaque, and the
settled frame keeps it until the next build.
Consequences: (1) GL replay reproduces a genuine PLAYER error faithfully — pixel-correct vs the player, wrong vs the deck,
with or without our loop; (2) Peer 2's "opaque only" rule must be judged on EXPORT opacity, never painted pixels (a fixed
player would silently invalidate a pixel-trusted cut-out); a cut-out's source stays the settled frame's own pixels.
Confirming measurement (not run): in the recorded 88-call frame the `uniform1f` for `Opacity` before the green square's
`drawElements` should be exactly 1.0; re-issuing the frame with it patched to 0.29468 should blend the square over the
movie. Coordinator note: that patch would make our replay MORE faithful to the deck than the player — an owner decision
(it changes the look at the first build boundary from opaque→translucent pop to continuous), not a default.
Scratch: `output/live-visible-content/alt-opacity/dump.py`.

## Per-`clear` upload qualification (2026-09-20 night, Opus, headless; evidence `output/live-visible-content/alt-perclear/`)
**Verdict: QUALIFIED-WITH-CAVEATS on the geometry-static 1→2 move, at 1920×1080 / 2560×1440 / letterboxed 1600×1000.**
- **In-page liveness instrument** (same task as the replay: one `readPixels` over the movie rect → 16×8 band means + 40×40
  corner control + green patch, with `currentTime`/rVFC `mediaTime`). Occluded bands are MEASURED, not assumed: swap a
  black then a white marker into the movie texture, replay, sample — a band that does not move is covered (20/128 = the
  green square, identical at every viewport). Controls: null (no upload) DEAD · positive LIVE (min band range 12.3) ·
  paused DEAD (rVFC fired 0) · rVFC loop LIVE (6.95); control + green static in all. Cost p50 3.5 ms / p95 4.0 ms (8-strip
  variant 2.4 / 3.5 ms).
- **The CDP burst flake is reproduced on demand:** at 2560×1440 the 12-shot burst scored liveFrac 0.0044 while the in-page
  read said LIVE in the same session; a 1-px DOM style poke before each shot → 0.805. Hypothesis: with WebGL-only
  changes and no DOM/compositor commit, `Page.captureScreenshot` is served from a stale composited surface. ⇒ the CDP
  burst is NOT a trustworthy liveness oracle over a replayed canvas.
- **Full flow** (per-`clear` upload through the move → record last frame → rVFC upload+replay+sample → MutationObserver
  stand-down → poster restore): 90–91 move uploads, LIVE at rest, loop p50 4.3–4.4 / p95 4.7–5.1 ms incl. the read,
  0 unserviced, 0/234 dropped, 0 GL errors; stand-down `mutation:canvas-removed` **1.7–1.8 ms** after the mutation batch;
  zero unflagged GL calls at the build. Armed vs control at four settled points × three viewports: max |Δ| outside the
  movie rects = 0 (slide 3 needs its SECOND movie rect masked, + 1–2 px dilation for the export-vs-painted ~2 % rect).
- The canvas backing store is 1920×1080 at EVERY viewport ⇒ buffer-space numbers are viewport-independent.
- Frame lengths during the move are NOT uniform: `{88:60, 89:28, 93:1, 125:1}` — "every frame exactly 88 calls" holds only
  for the recorded settle frame; the fail-closed assertion must be on the recorded last frame, not the whole move.
- The 960×276 poster signature is NOT unique (three such textures per slide); disambiguated by which one was
  canvas-uploaded + measured liveness. Bind the `<video>` by the export's `assets[assetId].url.web`, never "first video".
- **3→4 (the movie itself moves/scales): there is NO invisible window** — a new WebGL context draws the move, and at
  settle both canvases are detached and the DOM tree paints at opacity 1 (consistent with the product gate's green V on
  slide 4). The carried poster uploads at the DESTINATION size 1274×364. Per-`clear` upload there gave a ghosted double
  exposure (the move cross-fades whole-slide 1920×1080 snapshot textures) ⇒ NOT QUALIFIED and not needed.
  UNRESOLVED: the peer reports the asset that moves across 3→4 as `VID-20250608-WA0125.mp4`, whereas our records say
  movie1 `Untitled.mov` is the one that moves/scales (960×276 → 1274×364) and WA0125 is the slide-3-only retiring clip —
  verify before relying on either. Also unmeasured: WHY slide 2 stays on WebGL at rest while slide 4 returns to the DOM
  (pending builds on slide 2? transition type?) — this decides how common the invisible window is in real decks.
- Coordinator correction to the peer's caveat: occluded bands being dead is the CORRECT z-order (artwork in front), so the
  flow DOES turn the refused 1→2 carry into a visible one; what it cannot do is more than the player paints (see the
  opacity defect above).
**Next step toward product:** make the in-page read (`sample()` + measured occluder mask) the scorer behind the
visible-content gate for WebGL-settled slides, replacing/augmenting the 12-shot CDP burst; arming work comes after.

## Go-to jumps + hole-punch re-run (2026-09-20 night, Opus, headless; evidence `output/live-visible-content/alt-goto/`)
Go-to driven exactly as the host does (`LiveOutputHost.execute("goTo")` → index digits + Enter), raw player,
`continuity="off"`, per-context GL attribution + `getContext` hook + MutationObserver installed before any context existed.
- **Every go-to destination is painted by the DOM tree** (layer opacity 1): 1→goTo 2, 1→goTo 4, and from the settled
  WebGL slide 2 → goTo 4 / 1 / 3. Zero GL calls, no new context. Leaving the WebGL window: `#0-canvas` + old layer removed
  and the new layer added in ONE mutation batch, 108–263 ms after the command (build: 105 ms); never a GL call on the old
  context afterwards. ⇒ **`#0-canvas` removal is a COMPLETE stand-down signal for every measured exit** (builds, dissolve,
  go-to forward/back/skip) and cannot race the player's drawing.
- **ARM signal is safe:** no go-to path produces a poster upload or a context, so ARM never fires falsely. But a boundary
  does NOT imply a WebGL window: after goTo back to slide 1, `advance` did NOT replay the 1→2 move through WebGL (no
  canvas, no context, no upload) — ARM must stay a measured precondition, never an inference from the plan.
- **NEW, product-relevant, UNVERIFIED in the product path:** on every go-to destination `document.querySelectorAll('video')`
  was EMPTY — the movie is a static poster `<canvas>` (slide 2: at authored 105,791,960,276, visible) and still static
  6.5 s later, including goTo BACK to slide 1 whose movies were live before; `<video>`s return only after the next
  `advance`. Measured on the raw player with continuity off — must be re-checked with the presenter/runtime v4 before
  drawing product conclusions (does the host's goTo leave movies frozen on air?). Owner-relevant if confirmed.
- **Hole-punch (occluder ∩ hole, video bound to the slide's own export copy): ALIVE-WITH-CAVEATS.** 1920×1080: outside-rect
  change 0.0 %, max Δ 0; green probe Δ 0; movie probe Δ 244; 1-px antialias fringe inside the rect. 1600×1000: 0.016 %
  (one column on the hole's edge, Δ ≤ 64). After build 1 the whole frame equals the control (Δ 0); the player removes our
  `#stage` child + the canvas in the same batch ⇒ no teardown needed. **Scaled-stage rule: `#stage` is scaled by an ancestor
  TRANSFORM — `clip-path` and child layout are in UNTRANSFORMED (authored) px; scaling the path by
  `getBoundingClientRect` leaked 4.9 % of outside pixels (max Δ 255).** Still paints the occluder as WebGL does (opaque).
- **Third independent reproduction of the CDP burst defect:** the 12-shot burst read the live punch DEAD at both viewports
  (liveFrac 0.005); 8 shots spaced 0.35 s read 0.795–0.797 pass. Rapid `captureScreenshot` bursts are untrustworthy here.
Unmeasured: OBS CEF `clip-path: path()`, 2560×1440 for the punch, go-to mid-move (rejected as busy), whether the missing
`<video>` after go-to is a player behaviour or an authoring setting (movies "start on click"?).

## Follow-up probes P1–P4 (2026-09-20 late, Opus; evidence `output/live-visible-content/alt-followup/`)
- **P1 (offline) — RESOLVED: `Untitled.mov` is the asset that moves/scales across 3→4** (scale ×1.327/×1.319, translation
  (285.9, −44.0), `contents` cross-fade to slide 4's 1274×364 texture). `VID-20250608-WA0125.mp4` is NOT on slide 4 at all:
  the move fades it `opacity 1→0` over 0.5 s then hides it. The per-`clear` peer's E4 "correct binding" was wrong; its
  ghosting result at 3→4 should be read as "uploaded the wrong clip" — moot, since 3→4 has no invisible window.
- **P2 — the RULE for the invisible window (player `main.js` code-read, offsets 2292003 / 2312893 / 2316990 / 2357683 /
  2368201).** A closed list of effects renders through WebGL (`apple:magic-move-implied-motion-path`, `apple:wipe-iris`,
  the BUK/KLN set — Anvil, Twist, Flop, ColorPlanes, Flame, Confetti, Diffuse, Fireworks, Shimmer, Sparkle — and
  `ca-text-shimmer`/`-sparkle`). The effect sets the DOM layer to opacity 0 and NEVER tears its canvas down; the canvas
  dies only when the NEXT event is rendered. After the transition the player fires the next event by itself iff it has
  `automaticPlay: true`. Slide 4's first event is an auto `apple:movie-start` ⇒ heals at settle; slide 2's first event
  is a click-driven build ⇒ WebGL for the whole dwell. **Prevalence: any WebGL-listed transition onto a slide whose first
  pending event is click-driven (or that has no further events) — the common case in a build-driven deck, unbounded in
  time.** Corollary: the baseline's overlap refusal and the invisible-movie defect apply only to such slides.
- **P3 — opacity confirmed, with a correction.** The settled 88-call frame contains NO `Opacity` call (only `mixFactor` and
  two `MVPMatrix`); Opacity is persistent PROGRAM state set during the move. `getUniform(prog,'Opacity')` at rest: green
  square's draw (idx 83, tex 6) = exactly 1.0 (one other draw = 0). Injecting `uniform1f(Opacity, 0.29468…)` before draw 83
  gives green centre (29,177,0) → (184,228,176) = the exact arithmetic blend over (249,249,249); grating reads through
  the square, square still in front. CAVEAT: restoring the poster does NOT undo it — the value stays in program state and
  must be written back to 1.0 explicitly. Owner decision 2026-09-20 (relayed): no opacity patch in GL-replay v1; plan the
  general per-draw fix ("G2") next.
- **P4 — ON-AIR ISSUE CONFIRMED in the product path (continuity qualified, runtime v4): after ANY go-to the destination's
  movies are frozen posters until the next `advance`.** Identical with continuity off: 0 `<video>` at +1 s and +6 s,
  liveFrac 0.000 (8 shots × 0.35 s) for goTo 2 / 3 / 4 from slide 1 and goTo 1 back from slide 3; after one `advance`
  the videos appear and read 0.991–0.9999 live. The picture looks normal (a detailed still), it just never moves. Cause:
  the player's go-to lands at the slide's INITIAL state, BEFORE the auto `apple:movie-start` build, and does not auto-fire
  it (host snapshot: `goToSemantics "restart-at-initial-state"`, `playerState "IdleAtInitialState"`). Not
  fixture-specific: every auto-starting movie is exported as such a build. The host has no `previous` — backward
  navigation IS a go-to. Unexercised lead: the player's `jumpToSlide` takes an `automaticPlay` argument (offset ≈2361129).
  Candidate fixes (unplanned): host follows a go-to with the auto-play builds the player skipped (must not consume an
  operator-visible click-driven build) · use the `automaticPlay` path · presenter warns "movies idle until next advance".

## Paint-oracle E0, headless part (2026-09-20 late, Opus; evidence `output/live-visible-content/alt-oracle/`)
**CORRECTION to the sections above:** the three "12-shot CDP burst reads live content DEAD" reproductions all used
UNSPACED back-to-back captures. That is NOT the product gate's profile: `BURST_OFFSETS_MS` spreads its 12 shots over
2.36 s `(0,130,290,500,770,1000,1190,1430,1650,1910,2110,2360)`. Measured separately, the gate's real profile is sound.
- 6 arms × 2 stimuli (S-GL = per-`clear` upload + replay loop on settled slide 2; S-DOM = DOM-painted live movie on
  slide 3 reached by normal advances) × 3 viewports × 3 fresh sessions; 216 scored bursts, thresholds untouched.
- Positives, sessions passed of 3 (S-GL 1920 / 2560 / 1600): gate profile 3/3/3 · unspaced rapid 3/**0**/3 · A (8 shots,
  ≥360 ms) 3/3/3 · A+`fromSurface` 3/3/3 · rapid+DOM poke 3/3/3 · rapid+`fromSurface` **2/0/3**. S-DOM: every arm 3/3
  at every viewport (liveFrac 0.987–0.991). In-page `readPixels` said LIVE in 18/18 S-GL bursts incl. every failing one.
- Controls held everywhere: S-GL null DEAD 54/54, S-GL paused-video DEAD 54/54, S-DOM paused DEAD 54/54 (max liveFrac 0).
- **(i) Today's gate verdicts on slides 1/3/4 were never at risk:** 0/54 S-DOM bursts misread in any arm; the defect
  needs (WebGL-only repaint) × (unspaced captures) and the gate has neither.
- **Mechanism (hypothesis, fits all evidence):** `captureScreenshot` over a canvas changed only by GL draws is served
  from a composited surface refreshed lazily and TILE-PARTIALLY — in a failing burst consecutive shots differ only in an
  81×34 px patch at the rect's corner while ~364k px stay byte-identical; full-rect updates resume from ≈290 ms. Spacing
  ≥ ~300 ms or a DOM poke fixes it; `fromSurface` does not; in-page `readPixels` is NOT what rescues it (`noSample` arm).
  **`uniqueShas` is not a flake detector** — a fully misread burst still has 12/12 unique shas (dead controls: 1/12).
- **Recommendation:** profile A `(0,360,730,1090,1460,1820,2190,2550)` ms, default capture flags, +0.2 s/slide; keep the
  DOM poke behind an off-by-default flag; drop `fromSurface`. The current gate profile passes 9/9 but its first gap
  (130 ms) sits inside the stale window and survives only via max−min over later shots — A adds margin, it does not fix
  a broken gate. NOT to land as the default until the OBS attach arm is measured (needs the owner's OBS). Screencast
  arm not run (unnecessary).

## Pooled decoder as texture source + stand-down hand-off (2026-09-20 night, Opus, headless; evidence `output/live-visible-content/alt-pooled/`)
- **Q0 — YES, with the product's existing pool, unchanged.** 60 s each at 1920×1080: never-attached LIVE; attached then
  REMOVED with no keep-warm **DEAD at once** (removing a playing `<video>` pauses it; rVFC never fires again); **the
  runtime's own pooling (detached, held in a Map, `play()` re-tried every 200 ms) LIVE** — rVFC 29–31 Hz flat, 1/1859
  dropped, uploads non-black and changing, whole-frame Δ 0 on screen; `display:none`, 1×1 offscreen and
  `visibility:hidden` also LIVE. Null (no upload) and paused controls DEAD. The 200 ms keep-warm sweep is what makes the
  pooled decoder usable — it must not be weakened; the ≤200 ms pause gap after a detach is unmeasured at frame resolution.
- **Q0b — hand-off with the REAL runtime (plan minus its 1→2 `retire`, scratch copy of the core JS holding the remount;
  texture fed by the PLAYER'S OWN slide-1 element): CLEAN-WITH-CAVEATS.** At rest: pooled, not in the document, zero
  `remount-*`, no painting `<video>`, in-page LIVE (108/128 bands, 20 = the green square). Stand-down 1.7–2.1 ms after the
  mutation batch. **The player creates NO `<video>` at build 1** ⇒ `reuse-decoder` cannot fire there; the hand-off goes
  through `tryRemount` (`remount-into-authored-layer` — the returning DOM tree is a NEW one). Burnt-in counter strictly
  increasing across the stand-down in 2 runs, `currentTime` continuous on the same element, exactly one painting
  `<video>` afterwards, max Δ outside the movie rects = 0 vs the fallback control.
  Caveats: (1) the pool is keyed by ASSET, not instance — slide 1's second same-asset element is pooled too, and an
  unmodified hand-back remounted BOTH onto one footprint (double grating); clean only after retiring the sibling ⇒ needs an
  instance-scoped retire; (2) the remount lands on the SOURCE-slide footprint (109,795,952,268) while the replay painted
  the slide-2 rect (105,791,960,276) ⇒ ~4 px pop; the footprint must come from the destination rect; (3) green square pops
  opaque→translucent at the swap (player opacity defect); (4) the ~2 ms swap is below the ~95 ms shot cadence; (5) n = 2,
  1920×1080 only, no OBS CEF.
- **Fallback is worse than assumed:** under today's `retire` there is NO `<video>` on slide 2 before or after build 1 —
  the export's static poster for the whole dwell, not "a restart at build 1".
- Runtime v4 functions the arming would touch: `preserveAllowedFor`, `scheduleRemount`, `sweepRetireZone` /
  `retireZoneEnd` / `inRetireZone`, `stash()`, `tryRemount`, `retireDecoder` (instance-scoped), the pool keying.

## Real OBS (CEF) qualification (2026-09-20 night, Opus, attached to the owner's OBS 32.2.2 / Chrome 127.0.6533.120; evidence `output/live-visible-content/alt-cef/`)
Environment: 1920×1080, dpr 1, **ANGLE Metal (Apple M1 Pro)** — a real GPU; WebGL/WebGL2, `requestVideoFrameCallback`,
`clip-path: path(evenodd…)` all present; `Page.captureScreenshot` p50 ≈166 ms; H.264 plays, HEVC `canPlayType ""`;
host output `fill-key`, alpha true, transparent background. Page returned to `about:blank#program`, OBS left running.
- **C1 paint-oracle attach arm (DOM stimulus, settled slide 3): GREEN.** 4 sessions: the gate's `BURST_OFFSETS_MS` LIVE 4/4
  (0.9914), profile A LIVE 4/4, paused-video null DEAD 4/4 (0.000) in every arm ⇒ paint-oracle gate (iv) / D-d satisfied
  for the DOM stimulus; profile A may land. Caveat: an UNSPACED burst cannot be produced in CEF (166 ms per shot), so the
  stale-surface defect could be neither reproduced nor excluded there; a WebGL-only stimulus scored by screenshots in
  CEF is unmeasured.
- **C2 GL replay in CEF: FEASIBLE.** Prototype wrapping survives (installed after `show`, before the move — pre-navigation
  injection not exercised); the move renders through WebGL into `#0-canvas`; 42–46 per-`clear` uploads (CEF renders the
  move in about half the frames of headless); settle frame 88 calls, histogram `{88:30, 89:11–15, 93:1, 125:1}`; occluder
  mask 20/128 (identical to headless); rVFC loop 10 s: p50 6.9–7.5 / p95 10.1–11.3 ms, 0 GL errors; null DEAD, positive
  LIVE, paused DEAD (`rvfcFired 0`), resumed LIVE — 3/3 sessions; stand-down 1.4–3.9 ms after the mutation batch; after
  build 1 the DOM movie returns with no residue. `droppedVideoFrames` is NOT a health metric for an uncomposited decoder
  (reads 20–98 % dropped while rVFC + band change are healthy).
- **C3 decoder hosting in CEF:** never-attached LIVE 3/3; `display:none` LIVE; offscreen 1×1 LIVE; **attached-then-removed
  DEAD 3/3** (frozen at the removal instant). RECONCILIATION with the headless Q0: same result there for a bare removal,
  but the PRODUCT pool (detached + `play()` re-tried every 200 ms) was LIVE headless. **The product pool's keep-warm was
  NOT tested in CEF** — that single variant is the open item before G3; if it fails in CEF the pool must host decoders
  attached-but-unpainted instead.
- **C4 hole-punch in CEF: ALIVE, pixel-clean** — liveFrac 0.992, 0 outside pixels changed (cleaner than headless), whole
  frame Δ 0 vs control after build 1.
- **C5 go-to freeze CONFIRMED in the real output path:** goTo 3 and goTo 1-back ⇒ 0 `<video>`, liveFrac 0.000 at +1 s and
  +6 s, 1/8 unique shas (a fully static frame); one advance ⇒ 0.991 live.

## Paint-oracle A12 re-measurement + re-qualification (2026-09-22, Fable; raw evidence pruned 2026-09-24, see git history)
The owner chose 12 shots at ≥360 ms (`(0,360,730,1090,1460,1820,2190,2550,2920,3280,3650,4010)`, plan §14) over E0's
8-shot A. A12 measured with gate12 and A alongside as controls (all matched their E0 numbers):
- Headless S-GL, 3 viewports × 3 sessions: positive LIVE 9/9 (liveFrac 0.805–0.806; in-page readPixels LIVE 9/9),
  paused-video DEAD 9/9, null DEAD 9/9. Headless S-DOM: positive LIVE 9/9, null DEAD 9/9. Burst wall ≈4.05 s.
- OBS 32 CEF attach, 1920×1080, S-DOM, 4 sessions: positive LIVE 4/4 (0.9913), paused null DEAD 4/4. Wall ≈4.2 s.
- Full re-qualification on `feat/paint-oracle` 4256de38: host pass ×3 viewports (V/Voff all met; refused 1→2), P2 fast
  14/14, bridge-off 13/14 (only `continueThroughMovingMagicMove3to4` red), slow 14/14. Invariance vs a `main` (76daff4a)
  before-artifact: every pre-existing verdict/expect/label/rect/stray/status/refused field identical at all three
  viewports; in-page oracle n/a on every rect; only additive `burstProfile` + per-rect `oracles`.
- Residual (pre-existing, run-to-run): `instanceCheck.painting` on slide 3 lists 1 or 2 painting videos depending on the
  run — seen on `main` alone (3 runs at 1920×1080: 2/1, 2/2, 2/2 for V/Voff); `instanceCheck.verdict` True throughout.
- Harness note: `alt-oracle/common.py` FIXTURE repointed from the removed `friendly-sammet` worktree to the durable
  `output/p2-recovery/` copy; A12 harness variants are new files (`oracle_a12.py`, `c1_a12.py`).
