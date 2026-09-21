# Visible-content gate — trustworthy paint oracle: fix the screenshot burst, add an in-page GL read

Status: DRAFT for owner review — no code written; E0 headless part DONE 2026-09-20 (see §12), OBS attach arm pending. Drafted 2026-09-20 by Opus (read-only) from the results at the bottom of
[`keynote_live_alternatives_research.md`](keynote_live_alternatives_research.md) ("Per-`clear` upload
qualification", "Go-to jumps") and the gate as it stands in
[`keynote_live_visible_content.plan.md`](keynote_live_visible_content.plan.md) §1.
Fail-closed throughout; no existing threshold is loosened and no verdict on today's fixture may move.

## 1. Problem statement — proven vs hypothesised

**Proven (3 independent reproductions, headless, research harness).** A rapid 12-shot
`Page.captureScreenshot` burst over a canvas whose ONLY change is WebGL drawing reads demonstrably live
content as dead: liveFrac 0.004–0.005 at 1920×1080 and 2560×1440, while an in-page `readPixels` taken in
the same session says LIVE (min judged band range 6.95–12.3, control and green-patch ranges ≤ 1.0).
Two cheap variants read the SAME content as live: 8 shots spaced ≥ 0.35 s → 0.795–0.797; a 1-px DOM style
poke before each shot → 0.805. Third reproduction: the `clip-path` hole-punch (`alt-goto`).

**Hypothesised (mechanism, unmeasured).** With WebGL-only changes and no DOM/compositor commit,
`captureScreenshot` is served from a stale composited surface; the poke and the spacing both force a commit.
The `noSample` arm in `alt-perclear/e1.py` was designed to separate "readPixels forces a flush" from
"time forces a commit" — read its result before choosing a fix, it is the one datum that discriminates.

**Unmeasured and load-bearing.** Whether the defect touches DOM-painted slides at all. TODAY the product has
no settled slide whose live pixels come from WebGL: slide 2 is refused/`retire` and expected DEAD; slides
1/3/4 paint through the DOM layer tree at opacity 1 where the movie is a real `<video>`. So the defect has
plausibly never fired inside the gate — and equally plausibly costs us a rare flaky RED. Measure before
changing anything.

**What an in-page read can and cannot attest.**
- WebGL-settled slide, `readPixels` in the SAME task as a draw/replay: attests the canvas's own content —
  what the compositor will show, modulo compositing of the canvas ELEMENT (opacity/transform/occlusion by
  later DOM). Strong, but not a full paint oracle.
- DOM slide: GL `readPixels` does not exist there. `drawImage(video)` / rVFC `mediaTime` read the DECODER,
  not the composite — exactly the confusion the gate was created to eliminate (§0 of the gate plan: decoder
  live ≠ painted). **An in-page read must never be allowed to score a DOM slide.**
⇒ Screenshots remain the only paint oracle for 1/3/4, and the only oracle that sees element-level occlusion
anywhere. Fixing them is mandatory; the GL read is an addition, not a replacement.

## 2. Instrument options

| # | Option | Cost | Verdict |
|---|---|---|---|
| A | Spaced burst: 8 shots at ≥ 350 ms, keep unequal gaps | 2.45 s/slide vs today's 2.36 s ⇒ ~free | **recommend** |
| B | 1-px DOM poke before each shot | +1 evaluate/shot; mutates the page under test | fallback / diagnostic |
| C | `captureScreenshot(fromSurface=true)`, `captureBeyondViewport=false` | free if it works | test in E0, cheap win |
| D | `Page.startScreencast` frames | new frame plumbing in `live_host`/transport | only if A+C fail |
| E | `HeadlessExperimental.beginFrame` | headless-only ⇒ cannot serve the OBS attach arm | reject as the gate's oracle |
| F | In-page `readPixels` scorer | ~4 ms/sample | **add, WebGL-settled only** |

**Recommendation: A (+C if it measures clean) for ALL slides and both passes, plus F as a SECOND oracle that
is only applicable on a WebGL-settled slide.** B stays implemented behind a flag, used by E0 and as the
documented escape hatch — a poke is a real DOM mutation on the deck under test and should not be the default.
F is inert on today's fixture and becomes load-bearing the day GL-replay arming ships; landing its contract
now means the arming PR adds no new instrument.

## 3. E0 — qualify the screenshot fix BEFORE touching the gate (research, scratch scripts, no product code)

Copy `output/live-visible-content/alt-perclear/{common,js,verdict}.py`; the stimulus is the qualified
per-`clear` upload + rVFC replay loop on settled slide 2 (known LIVE, with an independent in-page verdict).
Arms per viewport ∈ {1920×1080, 2560×1440, 1600×1000}: burst-12-rapid (the known-bad control) · A ·
A+C · B · C alone · D. Controls in every arm: **null** (loop off, poster only ⇒ must read DEAD),
**positive** (loop on ⇒ must read LIVE), **paused video** (loop on, `mv.pause()` ⇒ must read DEAD).
Second stimulus, the one that decides whether the gate is affected today: a **DOM-painted** live movie
(settled slide 3, no WebGL canvas) under the same arms — null control = the same slide with the video paused.
Record per arm: liveFrac per rect, unique screenshot shas, wall time, and the in-page verdict taken
concurrently. Then repeat the winning arm in **real OBS attach mode** (screenshots come from a different
path there; `run_attach_arm`) at 1920×1080 with the DOM stimulus — a fix that only works headless is not a fix.
**Gate on E0:** ship A only if (i) it reads the WebGL stimulus LIVE ≥ 3/3 sessions per viewport, (ii) all three
controls hold in every arm, (iii) the DOM stimulus is unchanged vs today, (iv) attach mode passes.

## 4. Scorer contract

### 4.1 Screenshot oracle (unchanged shape)
`liveness_mask` / `score_live_coverage` / `score_dead_rect` / `score_no_stray_movie` / `score_visible_slide`
keep their signatures, thresholds and semantics. Only `BURST_OFFSETS_MS` in `scripts/live_continuity_probe.py`
changes (to E0's winner, e.g. `(0, 360, 730, 1090, 1460, 1820, 2190, 2550)` — unequal by ±20 ms so the
anti-aliasing property of §1.3 survives), plus an optional `--burst-poke` flag and the recorded shot shas.
The artifact gains `burstProfile: {offsetsMs, poke, fromSurface, uniqueShas}` so any future flake is
attributable from the artifact alone.

### 4.2 In-page GL oracle (new, pure Python scorer + a JS read)
`score_inpage_liveness(samples, *, occluder_mask, min_samples=24) -> dict` in
`src/obed_edom/html_alpha_probe.py`, a port of `alt-perclear/verdict.py` with its thresholds frozen:
- **Inputs.** `samples`: list of `{t, ms, vt, mediaTime, bands: [cols*rows], control, green, greenRGB, glErr}`
  produced by one `readPixels` per rVFC tick over the movie rect (16×8 band means), a 40×40 static control
  patch, and the green-square patch — all in drawing-buffer px, taken in the SAME task as the draw.
  `occluder_mask`: per-band 0/1, **measured**, see §4.3.
- **Verdict.** `LIVE` iff every non-occluded band's max−min across the window exceeds
  `controlRange + BAND_MARGIN (1.0)`, AND `controlRange ≤ 1.0`, AND the green patch is static (`≤ 1.0`) and
  still green (G > R+30 and G > B+30), AND `len(samples) ≥ min_samples`, AND `glErr == 0`. Otherwise `DEAD`.
  Returns `INCONCLUSIVE` (verdict `None`) when there are no samples, no judged bands (fully occluded rect),
  or the control itself moved — never a pass, never the RED a control must earn.
- **Applicability.** The JS read returns `{applicable: false, reason}` unless a WebGL context exists whose
  canvas is a child of `#stage`, is connected, and covers the movie rect. A non-applicable slide records
  `status: "n/a"` and contributes NOTHING to the verdict. This is what keeps today's fixture bit-identical.

### 4.3 Occluded bands: measured, not plan-derived
Use the black/white marker swap (`R.occluderMask`): paint an 8×8 black then white marker into the movie
texture, replay, sample; a band whose mean does not move between the two markers (|Δ| ≤ 0.5) is fully covered
by later-authored artwork. Measured 20/128 on the fixture, identical at all three viewports.
Why not plan-derived rects: the export's draw-slot rect is ~2 % larger than what the player paints (`alt-perclear`;
Peer 2 path B over-cut 0.44 %), it is a bbox only for shapes/text/rotation, and the player's own opacity defect
means painted pixels and authored geometry disagree by design. The marker swap measures the actual renderer.
Two fail-closed rules: the swap must be taken in the same armed state as the samples and re-taken if the frame
is re-recorded; and a slide whose measured occlusion exceeds 50 % of bands is `INCONCLUSIVE`, not LIVE.

### 4.4 Two oracles, one verdict
Per rect: `screenshot` verdict and (where applicable) `inpage` verdict.
- both agree → that verdict.
- only screenshot applicable → screenshot verdict (today's behaviour, all four slides).
- **disagree → `verdict: None`, `status: "inconclusive"`, `reason: "oracle disagreement"`, evidence written
  (mask PNG, shot 0, sample JSON).** Never reconciled, never "the better oracle wins": a disagreement is the
  finding. `overall_status` already fails on anything that is not `verdict is True`, so this is fail-closed
  in the V pass and does NOT let the `Voff` control earn its RED by accident (`visible_control_reasons`
  requires an explicit RED, not a non-pass — verify that when wiring).

## 5. Controls inside the gate
Both passes already carry the live/dead expectation controls (`visible_expectation_reasons`: at least one
live-expected rect read live, at least one dead-expected rect read dead). Add, only where the in-page oracle
is applicable: a **paused-decoder control** — pause the bound `<video>`, take a short sample window, require
`DEAD`, resume — and a **null control** is already structurally present as the dead-expected rect. Each
control is recorded with its own numbers in the artifact; a control that does not hold makes the SLIDE
inconclusive, it does not silently vanish.

## 6. Runtime and existing verdicts
- A round is ≈13 min. Burst A is 2.45 s/slide vs 2.36 s today ⇒ **+0.4 s per pass, ~+1 s per round**. B, if
  enabled, adds ~8 evaluates/slide (< 0.5 s). The in-page oracle costs ~4 ms/sample × ~90 samples plus the
  marker swap ⇒ < 1 s per applicable slide, and today applies to **zero** slides.
- **Required invariance:** on today's fixture the V/Voff verdicts must be byte-equal in shape — slide 2 dead
  as the plan expects (refused 1→2), slides 1/3/4 live, `refused1to2/2to3/3to4` unchanged. Capture a
  before-artifact on the current `BURST_OFFSETS_MS` and diff against the after-artifact, field by field,
  at all three viewports plus attach. Any movement is a stop-the-line finding, not a threshold to adjust.

## 7. Work split (disjoint files)
| # | Files | Work |
|---|---|---|
| W0 | *none* (scratch under `output/live-visible-content/alt-oracle/`) | §3 E0 qualification, report only. Blocks W1/W2. |
| W1 | `src/obed_edom/html_alpha_probe.py` + `tests/test_html_alpha_probe.py` | `score_inpage_liveness`, `combine_oracle_verdicts`, occluder-mask helpers. Pure, no browser. Contract fixed up front so W2 runs in parallel. |
| W2 | `scripts/live_continuity_probe.py` + `tests/test_live_continuity_probe.py` | burst profile (A/C/poke flag), `INPAGE_LIVENESS_JS` + applicability probe, per-rect two-oracle record, artifact fields, `visible_reasons` wiring |
| W3 | `.agents/plans/keynote_live_alternatives_research.md` | fold E0's numbers into the results section |
| W4 | `scripts/p2_recovery_html_adversarial.py` | only if P2's `footprintFullyLive` shares the burst — align its offsets; otherwise no-op |

Order: W0 → (W1 ∥ W2) → invariance diff at 1920×1080 / 2560×1440 / 1600×1000 → attach arm → W3.

## 8. Tests
Unit, synthetic, no browser (`uv run pytest tests/test_html_alpha_probe.py tests/test_live_continuity_probe.py`):
all bands moving ⇒ LIVE · one non-occluded band static ⇒ DEAD · that same band marked occluded ⇒ LIVE ·
control patch moving ⇒ INCONCLUSIVE · green patch moving ⇒ DEAD · green not green ⇒ DEAD · 23 samples ⇒
INCONCLUSIVE · `glErr` non-zero ⇒ DEAD · >50 % bands occluded ⇒ INCONCLUSIVE · empty samples ⇒ INCONCLUSIVE.
Combiner: agree-live ⇒ live · agree-dead ⇒ dead · screenshot-only ⇒ passthrough · disagree either way ⇒
`verdict None`, `status inconclusive` · in-page inconclusive + screenshot live ⇒ inconclusive.
Burst: `burst_deadlines` with the new offsets is monotone, non-accumulating, gaps unequal; a slow capture does
not drift later offsets; `--burst-poke` off by default. Existing visible-slide tests must pass unmodified.
Full re-qualification as §6 of the gate plan (P2 ×3 profiles, host ×3 viewports with V/Voff, attach).

## 9. Codex review brief — outline
(1) Does any code path let the in-page oracle score a DOM-painted slide, or let `mediaTime`/`currentTime`
alone imply LIVE? (2) Can a disagreement ever resolve to a pass? (3) Can the `Voff` RED be earned by an
inconclusive? (4) Are the new offsets still anti-aliasing (unequal gaps, max−min over all shots)? (5) Is the
occluder mask always measured in the same armed state as the samples, and re-taken after a re-record?
(6) Does `--burst-poke` mutate the page in any pass where it is not explicitly requested? (7) Thresholds:
any number that is not traceable to a measurement in the research doc.

## 10. Risks
- E0 finds A insufficient in OBS attach mode ⇒ fall back to B or D; D means new transport plumbing (scope).
- The stale-surface mechanism may have other triggers (a second display, GPU vs SwiftShader) ⇒ the artifact's
  `uniqueShas` makes a recurrence diagnosable, but we cannot claim the class is closed.
- The in-page oracle measures the canvas, not the composited element; a canvas at opacity 0 (exactly slide 2's
  DOM layer today) would read LIVE while nothing is on screen. Mitigation: applicability requires the canvas
  itself to pass `checkVisibility({checkOpacity,checkVisibilityCSS})` + ancestor-opacity product == 1, and the
  screenshot oracle stays authoritative for element-level occlusion. Test this explicitly.
- The marker swap writes into the player's texture; it must run only in an armed state we own and restore the
  poster, or it corrupts the very frame being judged.
- Landing an oracle with zero applicable slides means it is unexercised in the product until arming ships —
  accepted deliberately (the alternative is shipping the instrument and the arming in one PR).

## 11. Owner decisions
- **D-a** Default burst fix: A (spacing, ~free) vs A+C vs B-by-default. Recommend A, C if E0 says it is clean,
  B behind a flag. *(A costs ~1 s/round; B mutates the deck under test.)*
- **D-b** Land the in-page oracle NOW as inert-but-contracted, vs defer it into the GL-replay arming PR.
  Recommend now: the arming PR then adds no instrument, and the contract gets reviewed on its own.
- **D-c** What a disagreement does to `overall_status`: inconclusive-and-fail (recommended) vs a distinct
  `RED-oracle-split` status that is visually separable in the dashboard.
- **D-d** Whether E0 must also cover the DOM stimulus in attach mode before ANY offset change lands
  (recommended yes — it is the only measurement that tells us whether today's greens were ever at risk).
- **D-e** Scope: fix the oracle only, or also re-run the full re-qualification suite in the same PR.

## 12. E0 outcome, headless part (2026-09-20) — amends §1–§3
Full numbers: "Paint-oracle E0" in [`keynote_live_alternatives_research.md`](keynote_live_alternatives_research.md).
- §1 is narrower than written: the misread needs UNSPACED captures over a WebGL-only repaint. The gate's actual
  `BURST_OFFSETS_MS` (12 shots over 2.36 s) read the WebGL stimulus live 9/9 and the DOM stimulus 9/9 with every control
  holding. Today's verdicts were never at risk; this work is margin + the future GL-replay oracle, not a repair.
- §2: option C (`fromSurface`) is REJECTED — alone it failed 4/9 WebGL sessions. A qualifies (9/9 + 9/9, controls 162/162);
  B qualifies but mutates the deck (flag only). D not run.
- §4.1: record `uniqueShas` for forensics only — it cannot detect a misread burst (12/12 unique while reading 0.004).
- E0 gate: (i)–(iii) satisfied; (iv) OBS attach mode NOT measured ⇒ A must not become the default yet (D-d stands).
- D-a is effectively answered by measurement: A, poke behind a flag, no `fromSurface`. D-b…D-e remain the owner's.

## 13. Owner decisions — ANSWERED 2026-09-20
- D-a: profile A (8 shots ≥360 ms) default; DOM poke behind an off-by-default flag; no `fromSurface` (settled by E0).
- D-b: land the in-page GL oracle NOW, inert-but-contracted.
- D-c: oracle disagreement ⇒ inconclusive-and-fail.
- D-d: the DOM stimulus in OBS attach mode must be measured before any offset change lands.
- D-e: FULL re-qualification suite in the same PR.

## 14. Owner decisions — ANSWERED 2026-09-21 (implementation brief questions)
- Burst = **12 shots at ≥360 ms**: the E0-qualified 8 offsets extended on the same alternating 360/370 cadence,
  `(0, 360, 730, 1090, 1460, 1820, 2190, 2550, 2920, 3280, 3650, 4010)`. Keeps the 12-shot aliasing bound (2·0.5¹² ≈ 0.05 %)
  AND the spacing fix; ≈+1.7 s/slide. The anti-aliasing tests restate the property as measured: min gap ≥ 350 ms and ≥ 2
  distinct gap values (gaps need not all be unique). The 12-shot spaced burst itself is NOT yet measured ⇒ a short
  headless + OBS-attach re-measurement is owed before merge (D-d), on the owner's go.
- In-page oracle applicability keys off a runtime-published handle `window.__OBED_GL_ORACLE__`
  (`{gl, canvas, sample(), markerBands()}`); never a speculative `getContext`. The GL-replay arming PR publishes it.
- Accepted documented residuals: attach mode measured at 1920×1080 only; a WebGL-only stimulus scored by screenshots in
  CEF is unmeasured (cannot be produced there at 166 ms/shot).
- W4 = no touch: P2 imports `BURST_OFFSETS_MS`; `FOOTPRINT_BURST_FRAMES` stays 12.
