# Alternatives to the overlap refusal — research brief (2026-09-20, QUEUED FOR THE NEXT SESSION — resume from here)

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
