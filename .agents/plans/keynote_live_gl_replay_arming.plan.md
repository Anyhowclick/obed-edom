# GL-replay arming v1 — turn the refused 1→2 carry into a VISIBLE live movie

DRAFT for owner review — written 2026-09-20 by Opus (read-only); nothing implemented.
Parents: [`keynote_live_baseline.plan.md`](keynote_live_baseline.plan.md) (the `retire` this replaces at ONE
boundary), [`keynote_live_paint_oracle.plan.md`](keynote_live_paint_oracle.plan.md) (§4.2–4.4 in-page GL oracle —
owner answered D-b land now / D-c inconclusive-and-fail / D-d attach first / D-e full re-qualification), and the
results at the bottom of [`keynote_live_alternatives_research.md`](keynote_live_alternatives_research.md).
Every measured fact below is cited from those results and is NOT re-derived here.
Reference flow (git-ignored): `output/live-visible-content/alt-perclear/{js,e2}.py`.

## 1. Scope and non-goals

**In scope — exactly one new boundary class.** A boundary keeps today's `retire` unless ALL of:
(a) the transition effect is in the player's closed WebGL list (P2 code-read: `apple:magic-move-implied-motion-path`,
`apple:wipe-iris`, the BUK/KLN set, `ca-text-shimmer`/`-sparkle`);
(b) exactly ONE carried movie, geometry-static across the boundary (identical authored rect on both slides);
(c) the destination's first pending event is click-driven or absent (⇒ the WebGL window persists; P2);
(d) no mask (baseline §2's interim rule, unchanged), and the movie node passes the closed vocabulary.
Such a boundary derives `action: "glReplay"` instead of `retire`. Everything else — overlap refusals on
non-WebGL transitions, multi-movie boundaries, masks, unreadable slot shapes — is byte-unchanged.

**Non-goals for v1.** ~~No opacity patch~~ — SUPERSEDED 2026-09-21: the owner wants the wrapper-opacity fix IN v1,
without modifying `main.js` (see "Owner decisions — ANSWERED" below). No 3→4 /
moving-movie arming (measured: no invisible window there, auto `movie-start` heals it, per-`clear` upload ghosts).
No two-movie slide, no masked movie, no go-to arming (go-to destinations are DOM-painted; the separate P4
frozen-poster-after-go-to defect is NOT fixed here and must be stated in the capability report). No hole-punch /
cut-out path (Peer 2's paths refuse this very fixture). No arming of the DOM-painted slides 1/3/4.

## 2. Plan ↔ runtime contract

**Runtime boundary entry:** `{atScene, action: "glReplay", movieKey, fallback: "retire"}`. `fallback` is literal and
asserted by the runtime at parse time: an entry it cannot fully satisfy degrades to the existing retire code path,
never to "carry anyway". `to_runtime()` guards mirror `retire`'s exactly (at most one; before the first restart and
any bridge; any other refusal ⇒ whole-deck `Unsupported`). `retireZoneEnd`/`inRetireZone`/`preserveAllowedFor`
treat `glReplay` as a retire boundary for every DOM decision — the only difference is §3.

**`derive_plan` must prove OFFLINE (any failure ⇒ `retire`, with the existing refusal reason plus
`glReplay: false, glReplayReason`):** effect name of the boundary transition ∈ the closed list; the destination's
first event `automaticPlay` is false / no further event; exactly one movie instance carried; src and dst
`_movie_rect` equal within `_GEOMETRY_TOLERANCE`; mask/vocabulary checks pass; the overlapping later-authored slots
exist (an overlap is what makes arming *worth* it, but arming is also legal with none — those boundaries stay
`pin` and never reach here).

**Only the runtime can assert (each failure ⇒ stand down to `retire`, note + `notCarried` reason):**
`glReplayUnavailable` (no `WebGLRenderingContext`, wrapper not installed before player load) ·
`canvasShape` (the context's canvas is not `#<transitionObjectID>-canvas`, not a child of `#stage`, not connected) ·
`posterAmbiguous` (the poster upload signature — canvas source at the authored movie size, RGBA/UNSIGNED_BYTE,
flipY+premultiply — does not resolve to exactly ONE texture after the canvas-uploaded + liveness disambiguation;
the signature is NOT unique, three per slide) · `frameNotDelimited` (the last segment is not `clearColor`+`clear`
bounded, or is empty; frame lengths during the move are NOT uniform — assert the RECORDED settle frame only) ·
`contextLost` · `rvfcUnavailable` · `videoNotReady` (`readyState < 2`) · `assetUnbound` (no
`assets[assetId].url.web` match — never "first video") · `occlusionTooHigh` (>50 % measured occluded bands, §5).

**Allowlist.** The runtime JSON shape moves ⇒ `QUALIFIED_PLAN_SHA256` is **replaced**, not appended (baseline §1
rule), in the same commit as the P2 injected plan, the pinned test literal and the signature test.
`CONTINUITY_VERSION` 4→5. The GL arming JS is a SEPARATE module with its own `GL_REPLAY_VERSION` + `js_sha256`,
so a change there does not silently ride on the continuity sha.

## 3. State machine and the pooled decoder's lifecycle

`IDLE → ARM-PRE → ARM-POST → LIVE → STANDDOWN → RETIRED` (no re-arm on the same slide; the next Magic Move gets a
NEW context and re-enters at ARM-PRE).

- **IDLE.** Wrapper installed (pass-through), MutationObserver on `#stage` **armed before anything else** (measured:
  arming after is a race). ARM is a *measured* precondition — after a go-to + advance the 1→2 move did not go
  through WebGL at all, so the plan alone never implies ARM.
- **ARM-PRE** (hash enters `atScene − 1`, the move's scene): a WebGL context exists whose canvas matches §2, and a
  poster upload of the movie's authored size is seen. The movie is **pooled** by the existing `stash()` path (same
  element, same clock ⇒ P2's identity/clock guarantees hold) and the src-clear hook swallows the clear as in the
  `pin` path. The element is **never** mounted: no overlay, no in-layer remount, `data-obed-preserved` stays off
  the DOM-visible path. From the player's and the screenshot's point of view this is indistinguishable from
  `retire`. Per-`clear` `texImage2D(video)` starts here ⇒ the movie plays through the move with the player's own
  easing (measured 90–91 uploads, 0 errors).
- **ARM-POST** (the move settles): record the last clear-delimited frame; run the black/white marker swap to
  measure the occluder mask; restore the poster; take the `readPixels` baseline. Any assertion false ⇒ STANDDOWN.
- **LIVE.** One rVFC tick = upload the pooled decoder into the movie texture, replay the recorded frame, take one
  `sample()` (measured p50 4.4 ms incl. the read, 0 dropped frames). Our calls are flagged (§4); any *unflagged*
  GL call, a context loss, a changed frame length or a GL error ⇒ STANDDOWN.
- **STANDDOWN.** Triggered by `#0-canvas` removal from `#stage` (the COMPLETE signal for build, dissolve, go-to
  fwd/back/skip; 1.7–1.8 ms), or by any LIVE guard. Stop the loop, restore the poster texture synchronously, then
  **hand the pooled decoder to the existing remount path** — the DOM tree is now at opacity 1, so `tryRemount`'s
  authored-parent branch places the same, never-paused decoder where the player's fresh `<video>` would be, and
  the src-clear/reuse hooks make the player's own element adopt it (`reuse-decoder`) instead of starting a new
  one. No restart, no seek. If the remount cannot find a trustworthy target, `retireDecoder` — worst case is the
  raw player's restart, which is exactly today's `retire`.
- **RETIRED.** Pool entry dropped; wrapper back to pass-through.

## 4. GL wrapping strategy

Wrap `WebGLRenderingContext.prototype` (and `WebGL2RenderingContext.prototype` when present) **once**, plus
`HTMLCanvasElement.prototype.getContext` to attribute contexts — prototype, not instance, so a context created
before we look is still covered. Injected by `live_host` through the SAME
`Page.addScriptToEvaluateOnNewDocument` mechanism as `PRESERVE_CORE_JS`, **ordered before it and before the
player loads**; no minified player names anywhere. Idle cost: each wrapper is `if (!state.recording && !state.armed)
return orig.apply(...)` — one boolean test per GL call, and the player draws only during a move. Our own calls set
a `replaying` depth counter, so a nested call is never mistaken for the player's; the same counter suppresses
recording during replay. Memory is bounded by construction: a ring buffer of the current segment plus ONE retained
segment (the recorded settle frame); recording stops at ARM-POST, and any segment exceeding a hard call cap ⇒
`frameNotDelimited` ⇒ stand down. Argument capture keeps only values, plus texture identity through a `WeakMap`.

## 5. Gates

- **Probe V/Voff.** Slide 2's expectation flips from *dead-as-expected* to **live**, per rect, derived from the
  plan (`rect_expectations`/`visible_expectations`), with the measured occluder bands excluded — occluded bands
  being dead IS the correct z-order. Voff stays *dead-as-expected* (raw export) and remains the raw reference.
  `refused1to2` is replaced by `armed1to2`: a positive verdict = a `glreplay-live` note for `movie1` at scene ≥ 2,
  a non-zero sample window with the in-page verdict LIVE, and STILL zero painting `<video>`s overlapping the movie
  rect (`PAINTING_VIDEOS_JS`) — the movie is visible through the canvas, not through a DOM overlay.
- **Two oracles.** Screenshot burst profile A (8 shots ≥360 ms) + the in-page GL oracle from the paint-oracle plan;
  disagreement ⇒ inconclusive-and-fail (D-c). This is the first slide where the in-page oracle is applicable.
- **Finding 2 stays where it is.** Green square in front + static (Δ ≤ 1.0 on the green patch) is now a *positive*
  assertion of the arming, not of a refusal. `BLACK_BEHIND_ROI` must be re-confirmed, never re-tuned.
- **Hand-back.** Armed vs a no-arming control at all four settled points × three viewports: max |Δ| **outside**
  the movie rects = 0 (slide 3 needs its second movie rect masked + 1–2 px dilation). Stand-down latency recorded
  and asserted ≤ 50 ms after the mutation batch.
- **Fail-closed arm.** A forced-failure arm that drives each runtime assertion of §2 false **in turn** (a debug-only
  switch, never a product path) and asserts the resulting artifacts equal today's `retire` artifacts field by
  field — only the notes stream may differ, and only by `glreplay-standdown{reason}`.
- **P2.** `refusedCarry1to2` becomes `glReplayCarry1to2`: the injected plan carries the `glReplay` entry;
  `preserve-refused`/`retire-boundary` are replaced by `glreplay-arm`/`glreplay-live`; **zero** `remount-*` events
  for `movie1` while LIVE; the pool census shows exactly one pooled, never-mounted decoder; identity and clock
  continuity across the boundary are asserted on THAT decoder (unchanged mechanism). The burnt-in counter: the
  `readPixels` buffer is drawing-buffer px and the backing store is 1920×1080 at every viewport, so
  `index_patch_roi_for`'s authored ROI maps 1:1 — feed the GL read to the existing decoder and require the counter
  to progress; keep the screenshot decode as the second, independent reading. `preserveDidNotBlockRestart`'s
  never-pooled clause must be re-scoped to "pooled but never mounted, and retired/remounted at stand-down".
- Controls in every applicable arm: null (no upload ⇒ DEAD), positive, paused decoder (⇒ DEAD, rVFC fires 0).
  Three viewports (incl. letterboxed 1600×1000) + one real-OBS attach pass.

## 6. Qualification BEFORE any product code

**Q1 — OBS CEF (Chrome 127), blocking everything else.** In the owner's real OBS attach path: does prototype
wrapping survive, does `requestVideoFrameCallback` exist, does `texImage2D(video)` + replay produce the live
movie, and what is the per-frame cost? **If rVFC is missing but replay works**, fall back to a timer at the
video's frame rate and re-qualify liveness; **if replay itself fails**, v1 ships as a headless/HDMI-only capability
with the master flag defaulting off and OBS capture explicitly documented as unarmed (the boundary then stays
`retire` under attach — the runtime already knows this at ARM-PRE and falls back per §3).
**Q2 — paint-oracle D-d:** the DOM stimulus in attach mode, before any burst-offset change lands.
**Q3 — long-run:** 20 min armed on one slide; memory, GL errors, dropped frames, context loss injected.
**Q4 (needs decks) — owner-authored tomorrow, 1920×1080, the existing grating-with-counter movie:**
 (i) *no-build destination*: S1 movie + one shape behind it → geometry-static Magic Move → S2 with **no builds and
   no further events** (tests "destination's first pending event absent" — does the window persist?);
 (ii) *two movies, one slide*: both carried across a geometry-static Magic Move, different sizes;
 (iii) *equal-size posters*: two movies with the SAME authored rect (the disambiguation's worst case — must refuse);
 (iv) *masked movie*: one movie with a shape mask crossing a Magic Move (also serves baseline §5(ii));
 (v) *positive control* (baseline §5(i)) if not yet authored — it is also the only deck that proves the
   stand-down hand-back where the destination has nothing above the movie.
(ii)/(iii) may only *refuse* in v1; they exist to prove the refusal is measured, not assumed.

**Q4 status 2026-09-22 (owner-authored, exported to `output/gl-decks/`, checked offline via `derive_plan`):**
(i) = `Minimal Alpha_DSK` S4→S5, plans `pin`. "No further events" is NOT authorable: Keynote always emits a Start
Movie build for a movie, so the destination's Start Movie is set to **On Click** (click-driven first event, no other
builds). An **After Transition** start on a carried movie exports as an automatic first event and heals the window
(3→4 behaviour) — this is a backend condition `derive_plan` already reads; the operator-facing side is a
validation warning (see §7 follow-up). (ii) = S6→S7, both movies at identical rects, plans `pin` per movie; the
opacity computation refuses on an unmeasured `transform.rotation.z` (allowed here). (iii) = S8→S9, two movie
objects at the identical rect on both slides: **measured refusal** `ambiguous ownership … 4 geometry-equal pairs`
(a whole-deck refusal, so 4→5 and 6→7 are gated as sub-decks with the rest skipped). (iv) is **MOOT**: Keynote
cannot mask movies (menu disabled), and a DSK-generator "mask" is a pre-cropped video file exported at the final
dimensions — a plain movie node with ordinary geometry. The baseline's `possible mask` refusal stays as the
closed-vocabulary guard with nothing to measure it against. (v) = `Positive Control.key`, 4 slides, plans
`pin` / `bridge` / `restart`, no refusals.
**Follow-up (§7):** a sermon-validation warning — movie carried through a Magic Move whose destination Start Movie
is After Transition ⇒ "will restart on the destination; set On Click / After Build N". The DSK generator authors
its own decks and should set the build start directly rather than warn.

## 7. Work split, tests, rollout

| # | Files (disjoint) | Work |
|---|---|---|
| G0 | none (scratch under `output/live-visible-content/alt-cef/`) | Q1–Q3. **Blocks G1–G5.** |
| G1 | `src/obed_edom/live_continuity.py` + `tests/test_live_continuity.py` | `glReplay` derivation (§2 offline proofs), `glReplay`/`glReplayReason` on the refusal record, `to_runtime` guards, new allowlist sha |
| G2 | `src/obed_edom/live_gl_replay_js.py` (new) + `tests/test_live_gl_replay_js.py` | wrapper, recorder, marker swap, rVFC loop, `sample()`, MutationObserver stand-down, `GL_REPLAY_VERSION`/sha. Node-sandbox tests with a fake GL context |
| G3 | `src/obed_edom/live_continuity_js.py` + tests | `glReplay` zone: pool-but-never-mount, stand-down remount handoff, notes, `CONTINUITY_VERSION` 5 |
| G4 | `src/obed_edom/live_host.py` + tests | inject G2 before the core script, master flag, `continuity.glReplay` surface in `output()` |
| G5 | `scripts/live_continuity_probe.py`, `src/obed_edom/html_alpha_probe.py` + tests | live-expectation flip, `armed1to2`, occluder mask wiring, two-oracle record |
| G6 | `scripts/p2_recovery_html_adversarial.py` | `glReplayCarry1to2`, census re-scope, counter-from-GL |

Order: G0 → (G1 ∥ G2) → G3 → G4 → G5 → G6 → full re-qualification (D-e) → Codex. One integration PR.
**Rollout flag:** `OBED_LIVE_GL_REPLAY` env + `LiveOutputHost(gl_replay=…)`, values `off|auto`, **default off**, a
single master switch like the resizer's; with it off nothing is injected and every byte of behaviour is today's.
**Commands:** unit suite as the handover lists plus the two new test files; gates via
`run_gates.sh <gate-worktree> <outdir>` from `gate-runner`, three viewports + V/Voff, P2 fast/slow/bridge-off.
**Codex review brief — outline.** (1) Can any runtime assertion failure end anywhere but the retire path?
(2) Can the pooled decoder ever paint in the DOM while LIVE? (3) Is the MutationObserver always armed before the
first upload, and is stand-down synchronous w.r.t. the poster restore? (4) Can a flagged/unflagged mix-up let the
player's own call pass unnoticed? (5) Is the occluder mask measured in the same armed state as the samples?
(6) Any unbounded buffer, any minified player name, any threshold not traceable to a measurement?
(7) Does `off` inject or evaluate anything at all?

## 8. Risks, and what is genuinely the owner's

**Risks.** (1) OBS CEF may not support the flow ⇒ headless/HDMI-only (Q1 decides first). (2) The in-page oracle
measures the canvas, not the composited element — mitigated by requiring the canvas to pass `checkVisibility` and
by keeping the screenshot oracle authoritative for element-level occlusion. (3) The marker swap writes into the
player's texture; it must run only in an armed state we own. (4) Arming makes the deck depend on the pinned player
sha far more tightly than the baseline does — a player update invalidates the settle-frame assumption, and the
assertions must catch it (they are structural, not name-based). (5) `glReplay` reproduces the player's opacity
defect (a α0.29 square painted opaque) — a *known wrong* pixel that G2-the-follow-up would change. (6) The pooled,
never-mounted decoder is a new lifecycle state in runtime v4; every byte there costs a ~45 min re-qualification.
(7) P4's frozen-movies-after-go-to defect is untouched and will now sit next to a slide that IS live — more
visible, not worse.

**Owner decisions.** (D1) Ship v1 headless/HDMI-only if Q1 fails in OBS, or hold the whole feature until CEF
works? (D2) Is reproducing the player's opacity defect acceptable on air for v1, or must G2 land first? (D3) Do
(ii)/(iii) (two movies / equal-size posters) have to be authored and *measured-refusing* before v1 ships, or is
the structural refusal enough? (D4) Accept that the fail-closed arm's artifacts differ from today's by the
`glreplay-standdown` notes (they cannot be byte-identical and still be provable)? (D5) Does arming default to
`auto` for the owner's own HDMI runs once qualified, or stay `off` until a second deck is qualified?

**Owner decisions — ANSWERED 2026-09-21.** D1 moot (GL replay measured FEASIBLE in real OBS CEF 127; G3 still waits on
the pool keep-warm-inside-CEF measurement). D2: NOT acceptable as the target — the opacity fix ships with v1 if it can be
done WITHOUT editing `main.js` (a patched player is a dependency that breaks on a Keynote update). Measured route
(research doc P3): in OUR replay, `uniform1f(Opacity, <export wrapper-opacity product>)` before the affected draw gives the
exact blend; `Opacity` is persistent program state ⇒ write 1.0 back on stand-down. New v1 stage "G2": first todo =
MEASURE a provable draw→export-object mapping (fixture: draw idx 83 / tex 6); assert the `Opacity` uniform exists; when
the mapping cannot be proven for a boundary, replay with the player's own (opaque) look and emit a presenter note — do
not refuse the carry. D3: the two-movie and equal-size-poster decks must be authored and MEASURED refusing before v1
ships. D4: accepted. D5: arming stays `off` by default until a second deck is qualified.

## 9. Coordinator review (2026-09-20) — amendments before this plan is approved
- **Q0 (new, blocks everything, headless, no decks needed): the POOLED decoder as the texture source is UNMEASURED.**
  Every research run fed the texture from a FRESH `<video>` that the harness attached itself. §3 needs the runtime's
  pooled, NEVER-MOUNTED element: measure whether a detached (or pooled-offscreen) `<video>` keeps decoding, keeps firing
  `requestVideoFrameCallback`, and uploads non-black frames via `texImage2D` for ≥ 60 s in headless Chrome AND OBS CEF.
  If a detached element stalls, the design needs a mounted-but-unpainted host (and then "zero painting `<video>`s" in §5
  must be asserted by pixels/visibility, not by DOM absence).
- **Q0b: the stand-down hand-off is also unmeasured.** On the fixture the player creates its own `<video>` when the DOM
  tree returns at build 1. Whether `reuse-decoder` adopts the pooled decoder there without a restart or a one-frame
  double image must be shown on pixels + the burnt-in counter (no backward step across the stand-down) before G3 is
  written. Fallback if it cannot: `retireDecoder` at stand-down = a visible restart at the first build — an owner call.
- §5 "stand-down latency ≤ 50 ms" is not traceable to a measurement (measured 1.7–1.8 ms). Set the bound from the
  qualification run with a stated margin, or make it report-only in v1.
- The freeze-control re-bracket (`p2_freeze_control_3to4.plan.md`) and this plan both edit
  `scripts/p2_recovery_html_adversarial.py`; G6 starts only after that PR has merged.
- The go-to repair (`keynote_live_goto_autoplay.plan.md`) changes what follows a go-to; §3's "after a go-to + advance
  the move does not go through WebGL" must be re-measured once that lands.


## 10. Q0 / Q0b measured headless (2026-09-20 night) — amends §3
Numbers: "Pooled decoder as texture source" in the research doc. Q0 PASS: the runtime's existing pool (200 ms keep-warm
`play()`) is a live texture source; no mounted host needed; "zero painting `<video>`s" may stay a DOM assertion.
§3 STANDDOWN is WRONG as written: the player creates no `<video>` at build 1, so `reuse-decoder` never fires — the hand-off
is `tryRemount` → `remount-into-authored-layer` into a NEW DOM tree, and it is pixel/counter clean only if (a) same-asset
sibling decoders are retired per INSTANCE (the pool is asset-keyed) and (b) the remount footprint comes from the
DESTINATION rect (today: source rect ⇒ ~4 px pop). Both are new v1 work items in G3. D1/D5 should be decided against the
real fallback: a static poster for the whole dwell, not a restart. Still open: OBS CEF (Q1), 2 other viewports, n = 2.

## 11. G1 plan (2026-09-22 evening, Fable planner M) — `glReplay` derivation, offline only

**Measured before planning** (real exports): P2 1→2 = `pin` + overlap refusal (slot 6), transition
`apple:magic-move-implied-motion-path`, slide-2 `events[0].automaticPlay == False`, `effect_opacity_overrides` ⇒ one
override (slot 4, α 0.29468628764152527, 178×157). Minimal (i) S4→S5 = `pin`, NO refusal (nothing above the movie),
overrides `[]`; (ii) S6→S7 = two pins, one refusal, S7 first event automatic, opacity refuses on `transform.rotation.z`;
(iii) = whole-deck ambiguous-ownership `Unsupported`. Positive Control unchanged. The committed four-slide fixture
lacks `automaticPlay` and the full slide-1 transition tree — fixture work is part of G1.

**Derivation** (inside `derive_plan`, only for a pin that received an overlap refusal — §2 "those boundaries stay
`pin` and never reach here"; first failure keeps `retire` and records `glReplay: false, glReplayReason`):
1. transition name ∈ `_GL_REPLAY_TRANSITIONS = {"apple:magic-move-implied-motion-path"}` (the only measured name);
2. exactly one continuing movie at the boundary; 3. that movie's action is `pin` (geometry-static);
4. destination `events[0].automaticPlay is False` (absent / True / non-bool ⇒ refuse: "no further event" is not authorable);
5. `effect_opacity_overrides(transition)` returns a result (an `Unsupported` propagates as the reason, never raises);
6. masks are already a whole-deck refusal upstream.
Runtime entry: `{atScene, action: "glReplay", movieKey, fallback: "retire", slotSizes, slotRects, opacityOverrides}`;
`slotRects` exact floats; `excluded` is note-only. `to_runtime` treats `retire` and `glReplay` as one retire-class
(same guards, same messages) plus an unreadable-override-table guard.

**Decisions taken under stated assumptions (owner may overrule, each is a one-condition switch):**
- **A. Deck (i) plans `pin`, not `glReplay`.** The handover's "(i) glReplay" contradicts §2 and the Q4 status line
  ("plans `pin`"); §2 wins. Consequence worth an owner look: a click-driven WebGL pin with nothing above the movie is
  still inside the invisible window and G1 does not arm it.
- **B. Flag-gated derivation, not an allowlist replacement.** `derive_plan(..., gl_replay=False)`; off ⇒ every byte
  is today's (old sha, P2 injected plan and `p2_verdict.py` untouched — the rollout-flag rule in §7). On ⇒ the
  `glReplay` entry and a NEW sha. `QUALIFIED_PLAN_SHA256` therefore holds two entries until G3 (which bumps
  `CONTINUITY_VERSION` 4→5 and replaces the list); without this, runtime v4 — which filters boundaries by literal
  action — would receive a plan with no retire zone and carry the movie into the overlap ("carry anyway").
- **C. Operator warning is a follow-up PR** in the sermon-validation family (reads `.key`, not exports). Note for
  that follow-up: the DSK generator's rule 2 (`dsk_assemble.py:_clip_timing_for_slide`) sets continuity clips to
  After Transition — exactly rule 4's refusal — so generated DSK decks can never arm until one side moves.

**Tests:** fixture 1→2 ⇒ `glReplay` with the slot-4 override (flag on) and byte-identical to today (flag off);
mutation negatives per rule 1/2/4/5 (each asserts the reason string and that the flag-on runtime is unqualified);
`to_runtime` guards; real-export parity; new `tests/test_live_continuity_decks.py` on sanitized deck fixtures
(`minimal_alpha_dsk/` S4–S9, `positive_control/`) asserting (i) pin/no refusal, (ii) refuse rule 2, (iii) ambiguous,
Positive Control unchanged; `REAL`-gated parity vs `output/gl-decks/`.
