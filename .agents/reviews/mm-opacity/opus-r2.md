# MM opacity: Opus review r2

Scope: `git diff 102d4ca4..67c7d12e -- src scripts tests`. That covers `c9ff958b` (the MO-2 instrument rebuild and `--score`),
`0f6d0380` (R5, the synchronous swap hide) and `67c7d12e` (R4's known-bad enforced on the G2-less twin only). The review was
read-only. I ran no OBS, browser or Keynote.

**What I checked myself.**
- I read the real player (`output/p2-binary/.../main.js`, sha `e9b2fad4`). The parts I read were `animateEffects`,
  `animateEffect`, `animateEffectWillBegin`, `renderEffects`/`renderEffect`, `fB.draw`/`animate`, `R.createTexture` and
  `GB.drawFrame`.
- I read the continuity core's style observers and G2's context wrapper, observer and stand-down.
- I re-scored all 12 live MO-2 takes (`obs-mo2` ×2 and `obs-mo2-fix` ×10) with the branch code. I also decomposed the per-frame
  residual `R = P − α·S_off` by phase from the npz series.
- I ran `tests/test_live_runtime.py` and `tests/test_managed_obs_qualify.py`: 98 passed.

## Answers to the brief

**1. Is R5 correct, and what is its scope?** R5 is correct, and I found no new path to a blank frame.
- `draw(g)` pushes the program synchronously, before the hide. It uploads textures with `texImage2D` from the already-loaded
  `HTMLImageElement` in `slideCache`, so there is no async upload.
- If the loop is already running, as it is for every effect started by `animateEffects`, which calls `animate()` on every
  renderer before any `setTimeout(animateEffectWillBegin, e)` fires, the next rendering opportunity runs the renderer's pending
  rAF. That rAF draws the new program before paint, so the hide and the first GL frame land in the same frame.
- If `animationStarted` is false (a child effect's fresh `fB` from `handleEffectDidComplete`), `animate()` draws the first frame
  synchronously in the same task. That is better than stock.
- `beginTime > 0` / `e > 0` only moves the whole task later. The analysis is unchanged.
- There are only two blank paths:
  - `!A.baseLayer`, where no program is pushed;
  - a renderer whose loop has stopped (`elapsed > durationMax`), where the new program is never drawn.

  Both pre-exist and blank in stock too. Stock hides one 0-ms timer later, which normally lands before the next frame. R5 can
  move a blank earlier by at most one task; it cannot create one.
- Interaction with G2: while LIVE, the player's first GL call (`createTexture` inside `draw`) trips `UNFLAGGED_PLAYER_CALL` and
  the stand-down (a rest-frame replay, then RETIRED). This happens inside `draw()`, before the hide, in both stock and R5.
- G2's observer is childList-only.
- In the continuity core:
  - `forceTransparentChrome` now fires on the opacity mutation in the same task's microtask. It is idempotent.
  - `isCompositing` reads the video's own computed opacity, which does not inherit an ancestor's opacity.
  - The `dom-swap` observer is childList-only.

  No freeze or seam timing depends on the swapped layer's opacity.
- Evidence: before R5, 1 double in 6 gated patch-on sessions. After R5, 0 of 30 gated sessions and 0 of 10 CvC sessions go over
  τ, plus the Node task-order test.
- Scope: R5 changes every WebGL transition and build under the default-on flag. See F2.

**2. Is the instrument valid?**
- The neutral-background premise holds on this fixture for the whole window. The per-frame mean residual over ROI_top is in
  [−1.2, −0.4], which is black, on every `slide1-native`, `slide2-live`, `slide2-handback` and `slide2-after` frame of every fix
  take, including the handback DOM frames.
- The background is bright only on 0–4 `mm-move` frames per session, where the counter crosses (B̄ up to 178.6).
- Can R2 pass a wrong square? No, and lighting does not change that:
  - An opaque square hides B, so badness is (1−α)·spread(S_off) = 124.3 under any lighting.
  - An α² square scores 0.208·spread(S) ≈ 36 over any neutral B.
  - A double scores α(1−α)·spread(S) = 36.3.
  - A blank frame scores α·spread(S) = 51.5.

  Only a chromatic background of the opposite chroma could cancel an α error, and this fixture has none. That result depends
  on the fixture, though. See F4.
- The calibration (slide-1 max + 1) cannot mask a pop. τ is at most `MMO_CALIB_MAX` + 1 = 8, far below the smallest bad
  signature (36). It can, however, false-FAIL on bright-background frames. See F1.
- The τ_key fix is sound: the reference M patch alpha stands in for slide-1's covered patch, and τ_key moved from 114 to 1.15.
- The R4 known-bad on the G2-less twin is still a real known-bad. It shows that the key-alpha instrument separates opaque from
  translucent on the same pipeline, and if the reference M ever went translucent, τ_key would balloon and that KB would fail.
- `--score` is faithful for MO-2 itself, but it drops everything else the live verdict carries. See F3.

**3. Do the tests fail without the change?**
- Yes for R5. The stock run asserts `sync.opacity == ""` and the patched run asserts `0`.
- Yes for the R2 counter case (it asserts raw steps > 170, so the old E/R3 would have failed), the double, the premise
  INCONCLUSIVE path, the per-twin R4 KB, `--score`, and the τ_key-from-M case.
- Gaps are listed in F5 and F6.

## Findings (ranked)

### F1: gate-integrity, MEDIUM. R2's τ is calibrated on black backgrounds only; bright-background frames sit 0.26 below it
`scripts/managed_obs_qualify.py:1129` (`mmo_tau`) and `:1253` (`r_on["R2"] <= tau`).

**What τ measures.** τ = 4.57 comes entirely from slide-1 frames over black. The 3.57 is the DOM-versus-GL colour mismatch of
the square: S_off's red channel is 30 against the DOM's implied ~20, so R = (−2.84, 0.72, −0.59).

**What the bright frames read.** When the white counter crosses under the square, blend rounding adds chroma error. The badness
is quantised (2.09 / 3.57 / 4.31), and 4.31 appears in 4 of 36 patch-on sessions:
- `obs-mo2-fix/…143037` g2-on row 216 (gated), where P = (161, 207, 152) and R = (152.2, 155.7, 151.4);
- `…142421` g2-on-2;
- `obs-mo2/…132655` g2off-on;
- `obs-mo2/…133023` g2-on-2.

**Why it matters.** The next quantisation step is likely over τ. That gives a false FAIL, not a false PASS, but the margin is
luck: bright B is never calibrated.

**Fix:**
- Enforce `R2 <= max(tau, MMO_R2_FLOOR)`. Derive the floor from the known-bad signatures, for example 8.0. That is Δα ≈ 0.046,
  4.5× below the double-frame signature of 36.3, and it keeps the blank (51.5), α² (36) and opaque (124) signatures far above it.
- Keep crossings of τ visible as a non-enforced report.
- Add each frame's mean residual (B̄) to the `mmo_frame` output, so a bright-background instrument crossing is distinguishable
  from a pop at a glance.
- Enforce R2 on `g2-on-2` too. It is a free patch-on sample and is currently not gated.

**Test:** a synthetic counter frame with ~5 levels of chroma error at B ≥ 150 must PASS, and `double=11` must still FAIL.

### F2: gate-integrity, MEDIUM. R5 widens the blast radius, but part of the gate record predates it
R5 re-times every WebGL transition and build (`live_runtime.py:41-44`) whenever `mm_opacity` is on, which is the default.

What `gates-r1.md` shows:
- MO-6 (host probe ×3, P2 fast/slow, bridge-off) at `01a9ff55`;
- the full suites at `102d4ca4`.

Both predate R5. Headless MO-1/4/5 were re-run at `0f6d0380` (`output/mmo-gates/probe-0f6d0380/verdict.json`, overall PASS), but
that run is not in the record.

**Fix:**
- Re-run MO-6: the P2 GL arm exercises the non-MM GL transitions.
- Re-run the three full suites at the final code commit.
- Add a `0f6d0380` row for MO-1/4/5.
- State in the plan that R5 applies to every GL effect, not only Magic Move.

### F3: bug, LOW-MEDIUM. `--score` over-matches runs and drops validity, lifecycle and fixture identity
`scripts/managed_obs_qualify.py:1770`.

**The glob also matches MO-3 runs.** `glob("mmo-*.json")` also matches `mmo-cef-*.json`; `obs-mo3/runs/mmo-cef-20260925-132216.json`
is a real example. Scoring one with `mmo_gates` crashes or produces garbage.

**What `score_mmo` ignores.**
- `run["valid"]`/`run["invalid"]`: "Mac slept" and "not lossless".
- The failed enforced `run["checks"]`.
- `run["fixtureIdentity"]`: `:1773` re-derives the armed facts from whatever fixture is on disk now.

Concretely, take `…141513` failed `clean quit` and `ak-engine.json cleanExit` live, yet it re-scores PASS. "PASS ×10" in the
gate record is an MO-2-only verdict and should say so.

**Fix:**
- Skip runs whose `run.get("arm") != "mmo"`.
- Mark a run INVALID when `binary_counter_movie.verify_fixture(fixture) != run["fixtureIdentity"]`.
- Carry `valid`, `invalid` and the failed enforced lifecycle checks into each result and into the exit code.

**Test:** extend `test_score_rescores_saved_takes_without_obs` with an `mmo-cef-x.json` (skipped) and a run whose `valid` is
false (not PASS).

### F4: gate-integrity, LOW. R2's opacity sensitivity rests on S_off's chroma, and no premise check guards it
`scripts/managed_obs_qualify.py:1112`.

**The limit.** Badness sees an alpha error Δα only as Δα·spread(S). On a grey or white square, R2 is blind to α² and to any α
error. R1 would still catch a fully opaque square. Here min spread(S_off) = 172, so the floor is Δα ≈ 0.026. A future fixture
could quietly lose this.

**Fix:**
- Report `alphaFloor = tau / min_px(S_off.max(-1) - S_off.min(-1))`.
- Mark MO-2 INCONCLUSIVE when the floor is above, for example, 0.05.

**Test:** a grey S_off must give INCONCLUSIVE.

### F5: edge case, LOW. On most takes g2-on's R4 PASS measures G2, not the patch
`scripts/managed_obs_qualify.py:1257-1260`.

**Why g2-on's R4 is G2 evidence.** `shotM.g2Before` is `LIVE` for g2-on in 8 of the 10 fix takes, so M is G2's override. The
patch's settle key is evidenced by `g2off-on` alone. That is sufficient, but the record should say so.

**The shot state cannot condition the KB.** `g2Before`/`g2After` do not predict whether the g2-mmoff key is translucent:
- LIVE/LIVE gives 180 in `140655`, `142421`, `142737` and `143037`;
- LIVE gives 0 in `135354`, `135952`, `140339`, `141513` and `141934`.

This is presumably OBS screenshot latency. Leave g2-mmoff report-only, as `67c7d12e` does.

**Fix:** add one sentence to `mmo_key`'s doc and to the gate record: "g2-on R4 is G2 evidence when M lands after LIVE; patch
evidence is g2off-on."

### F6: test, LOW. The R5 Node test covers only the running-loop path, and it asserts task order, not the frame
`tests/test_live_runtime.py:253-283`.

The stub's `animate()` throws, so the `animationStarted: false` branch (synchronous `animate()`, then the hide) is untested.

**Fix:**
- Add a case with `animationStarted: false` whose `animate()` records an event.
- Assert the order `draw → animate → hide` within the task.
- Say in the docstring that frame alignment rests on "rAF callbacks run before paint". The test cannot prove that alignment.

### F7: style, LOW. `MMO_CALIB_MAX = 7.0` has no stated derivation
`scripts/managed_obs_qualify.py:157`.

**Fix:** tie it to the signatures in a short comment or in plan §10. For example: τ must stay at or below a quarter of the
smallest known-bad signature (the double, 36.3), which gives τ ≤ 9 and therefore calibration ≤ 7.

## Not findings (checked)

- `mmo_handovers`: `changed[0]` is False, so `rows[0] - 1 >= 0` and it never wraps.
- R5's anchor is unique on the stock player, and the off contract still round-trips. Both are tested.
- The R4 KB change does not weaken the known-bad. The G2-less twin's M is the τ_key reference, so a translucent reference would
  fail both τ_key and the KB.
- Folding R3 into R2 loses no opacity failure mode. Each handover frame is judged against the blend model on its own.
