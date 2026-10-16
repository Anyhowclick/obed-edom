# Critique r1: predraw-geometry.plan.md

**Verdict: NOT READY.** 1 blocker, 3 major, 4 medium, 6 low.

I checked the plan's code citations against 7746df27, and they hold. Specifically:
- `collectRiders` keeps the first row (`mm_feed_instrument.py:397-399`), and `finalizePixels` resets and recollects (`:329`).
- `gl.clear` collects the previous frame and then the new frame (`:256,260`).
- The `!G.frame` draw path is at `:263`, and `contextRecord` is at `:226`.
- The `stageMap` gap matches the plan: the instrument checks offset width only (`:122`), while the core checks both dimensions and a uniform scale (`live_continuity_js.py:369-380`).
- The pin `srcRect=dst_rect` shortcut is at `live_continuity_probe.py:1566-1567`. `feed_specs_for` passes only `dstRect` (`:1930-1940`).
- The contract sites are `live_evidence_contract.py:628-633,786-795`. The variant machinery is `continuity_core_variants.py:140-197`, and `run_gates.sh` is at `:100-128,725-791`.
- The red-control anchor `if (waitForGl && (document.contains(v) || departureInterimPlace(v, boundary))) {` occurs exactly once (`:1406`).
- F4 `41800609` is not an ancestor of HEAD.

The findings below are about design, not citations.

## Blocker

**B1. "Opacity does not waive geometry" makes the positive Alpha bridges fail.** Plan refs: Contract section ("A hidden decoder with a valid rect can still produce a finite error"), and Design 3 (fold every sample).
- How it happens:
  - `finishDepartureHides` hides the decoder after the GL callback that advanced `framesFed`. It then calls `rideFrame`, which moves the decoder to `rectAt()` (`live_continuity_js.py:868-875,1325-1332`).
  - For a bridge, `rectAt()` is the eased interpolation on the GL clock (`:1436-1443,1271-1279`). By the time of the hide, the clock has been running for up to about 300 ms (the cold start), so the decoder is already many px from `src.rect`.
  - The last prefix frame is still open at that point. `riderTick` (`mm_feed_instrument.py:402`) and the next `gl.clear` (`:256`) both sample it after the hide.
  - Stored evidence fixes this ordering: the offenders sit at (0,0) and (1,0), and frame 2's final-draw row is already hidden (`norider-ab/riders-summary.txt`). So the hide falls between frame 1's callback and frame 2's final draw.
- Result: the folded maximum goes above 1 px, the exemption is denied, and the visible frame-0/1 rows are scored. Alpha `b5to6` and `b7to8`-wa0121 (bridges) then read False on the current core.
- **Fix:**
  - In `collectRiders`, fold a geometry sample only when `d.visible === true`. `visible()` already treats opacity 0 as hidden, via `checkVisibility({opacityProperty:true})` (`:117-121`).
  - Define `sourceRectError` as the maximum over the frame's visible samples, and `0` when no sample was visible (there is no rider to place).
  - Set it to `null` when a visible sample's geometry is unreadable. Keep `null` sticky.
  - Per sample, read only `decoderForEntry` + `visible` + `getBoundingClientRect`, not the full `decoderRead`.
  - Update the Contract text and the coverage/score table to match.
  - Departure-early-hide then becomes deterministic: exempt True, 0 exempted visible samples.

## Major

**M1. The 1 px feasibility check comes last; it should come first.**
- Stored Alpha `closedDom.rectError` (the same DOM-vs-authored comparison, at the destination) is 0.337–0.484 px at 1920 (`MAIN:output/evidence/stage-b-2026-10-13/alpha-placement/alpha-fix.verdicts.json`, 50 rows). D7 reads 0.0.
- That metric is max(|dx|,|dy|,|dw|,|dh|). The owner's edge metric can be nearly twice that, because the right edge carries dx+dw. At 2560 the scale is about 1.33.
- So the current core can plausibly exceed 1 px on Alpha positives. If it does, the tests, contract, control and gate wiring are all wasted.
- **Fix:** add a Step 0 before any Python, contract, control or test work.
  - Land only the JS accumulator.
  - Run Alpha and D7 positives at 1920x1080 and 2560x1440 (4 captures, about 15 min, heavy).
  - Report the maximum visible-prefix `sourceRectError` per carry.
  - If any value is above 1.0, stop and take the numbers to the owner. The threshold is the owner's call. Do not relax it or reinterpret it in the plan.

**M2. The `run_gates.sh` per-target scoping is over-built.** Plan refs: probe §4, `run_gates.sh` section, Test 7.
- The repo already has the right pattern for a control that reds only some rows.
  - interim-delay registers `{}` (`live_continuity_probe.py:377`).
  - Its red is asserted in `mm_feed_control_aggregate_problems` (`:1182-1203`): every row is readable, and at least one row shows the specific red.
- **Fix:**
  - Register `"startup-moved-decoder": {"labelsOverFeed": True}`.
  - Add one branch to `mm_feed_control_aggregate_problems`. It reports a problem unless no row's `noRiderAboveCanvas` verdict is None and at least one row is False with an entry in `offenders` whose `sourceRectError` is finite and > 1.0. Offenders carry raw rider rows (`mm_feed_instrument.py:929-931`).
  - Add only the two `MM_FEED_ARMS` lines: `Alpha_DSK startup-moved-decoder --core-variant startup-moved-decoder` and `D7 startup-moved-decoder --core-variant startup-moved-decoder`. Make no other edits to the heredoc.
  - Extend the existing aggregate test (`tests/test_live_continuity_probe.py:~12060-12080`) with one red case and one case without geometry.
  - Delete probe §4 (fact-ID target resolution), the raw-prefix and suffix checks in the shell, and Test 7.
  - Pinning exact targets is a theoretical false-pass guard. If wanted, take it to the owner with its gate cost.
  - Why the strict version is also risky: if the control makes later chain carries visible, the plan's "other carries have no post-draw offenders" rule can fail spuriously.

**M3. The validation matrix is out of proportion to what it can decide.**
- F4 has not landed (verified), so the plan's own grace rule already says "keep 320". The 3 viewports × 3 repeats × 2 decks matrix, the 6 grace-confirmation runs, the pinned-old-module replay of stored D7, and the synthetic counterfactual decide nothing new.
- **Fix:** replace "Grace re-look gate" steps 2–6 and "Stored replay" with:
  - **Positives:** Alpha and D7 at 1920x1080 ×2, plus 2560x1440 ×1 (one non-unit scale for geometry). That is 6 captures.
  - **Controls, once each:** overlay-ride (Alpha), departure-early-hide (D7), startup-moved-decoder (Alpha, D7). That is 4 captures; about 35–50 min in total.
  - **Null control:** re-score every fresh producer with the 7746df27 scorer (`git show 7746df27:scripts/mm_feed_instrument.py`, calling `verdict_records` directly, no contract), and diff the rider verdicts.
    - Expected: positives and overlay-ride identical; startup-moved-decoder True→False on its red rows.
    - This replaces both the stored replay and the synthetic counterfactual.
  - **Grace:** record `firstDrawAt − move_frames[0].t` and `firstDrawAt − first_draw.t` from these captures and keep 320. Tightening becomes a follow-up when F4 lands.
- Unit tests already cover "old keys absent → refused" (Test 5).

## Medium

**D1. Normalized-record contract additions are out of scope.** Plan ref: Contract table rows 3–4.
- Scope item 4 is the producer fields only.
- `score_verdicts` validates the record it rebuilds from the producer (`live_continuity_probe.py:4361-4368`), so these checks guard nothing new.
- They would force fixture churn: rider records at `tests/test_live_continuity_probe.py:12242-12250` lack the new keys.
- **Fix:** delete both rows and File-by-file §`live_evidence_contract.py`'s normalized-rider work. Keep only `sourceRectError` on producer rider rows and `firstDrawAt` on producer contexts.

**D2. Changing the pin `srcRect` in `verdict_specs` changes continuity scoring.**
- `spec["srcRect"]` feeds `score_continuity` (`live_continuity_probe.py:3752`), `at_source` (`:3900-3901`) and the paint-gap source lookup (`:3988`) for every pin. That is outside the instrument-only scope.
- **Fix:** leave `srcRect` unchanged. Add `authoredSrcRect=movie.src_rect.as_dict()` to the carry `add(...)` (`:1571-1575`). Have `feed_specs_for` emit it as the instrument entry's `srcRect`. Test 4 then asserts `feed_specs_for` output only.

**D3. The full-suite commands contradict the repo's documented ones.**
- The plan uses `uv sync --extra test` (missing extras), runs serially without xdist, and estimates 30–90 min.
- Documented (`.agents/skills/obed-edom/SKILL.md:50`):
  - `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (about 60 s warm).
  - 3.10 floor: `UV_PROJECT_ENVIRONMENT=<scratch>/venv310 uv sync --frozen --all-extras --all-groups --python 3.10`, then `env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT=<scratch>/venv310 uv run --frozen --python 3.10 pytest tests/ -n auto --dist worksteal`.
  - Dashboard: `npm run test:ui` and `npm run test:maps`, with the bundled Node first on `PATH`.
- **Fix:** use those commands verbatim. Send a separate "need window" before each interpreter run.

**D4. The `stageMap` alignment also changes existing leaves.**
- `expectedBox` feeds `domRead` and the hand-back `closedDom` (`mm_feed_instrument.py:122-137,342`).
- **Fix:** leave `stageMap` unchanged. In the new source-error helper, add the core's checks locally: `offsetHeight > 1`, bounding height > 1, and `|sx−sy|/avg ≤ 0.001`. Alternatively, keep the shared change and add a hand-back null-control line to validation. Pick one and say so.

## Low

- **L1. Simplify the accumulator.** Frames reach `S.frames` only through `finishFrame` (`:334`; report, lost-context and tick all call it). So keep `F.srcErr = {}` on the frame and write it into the rows only in `finishFrame`. Delete "synchronize `row.sourceRectError` on every collection".
- **L2. Red control: use a fixed +8 CSS px on x, with no sign rule.** Source slots are much wider than 8 px, and overlap is confirmed from rider rows anyway. Keep the plan's other choices: one-shot reparent to `stage`, no transform, `rideFrame` restoring placement.
- **L3. Trim the tests.**
  - `firstDrawAt` is stamped in the shared `draw()`. Test the frame path, the `!G.frame` path and a thrown draw. Drop the `drawArrays`/`drawElements` duplication and the fake-GL rework (`tests/...:12604`).
  - Test 2: one offset with a non-unit scale, one non-uniform map, one sticky-null case, and one right-edge (dx+dw) case. Drop scales 0.5 and 1, and the duplicate null orderings.
  - Drop Test 8; Test 5's deletion cases cover it.
  - Test 1: drop "malformed geometry" (that is contract territory).
- **L4. Contract strictness.** State the precedent:
  - Required fields were added with no version bump, refusing old files, in `9bf912b6` and `51ee3be2`. `1df31c33` instead bumped to v2 and gated the new fields.
  - Say plainly that v1 reports are now always refused.
  - Say that refusal makes the whole carry verdict inconclusive (None) for under-artwork carries in old artifacts (`live_continuity_probe.py:4355-4373`), not just the rider leaf.
- **L5. Drop the extra `exempt` conditions** ("usable, non-lost context and complete attribution", Design 5). They are not in the brief and do not change any verdict.
- **L6. Evidence location.** `/private/tmp` is cleared on reboot. Use the evidence location the coordinator names, next to the prior gate's evidence.
