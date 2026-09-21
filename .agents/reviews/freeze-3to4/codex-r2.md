# Verdict: FAIL

## BLOCKER

1. The production null control cannot arm.

   `arm()` calls `resolveOwnerEl()` before assigning `st.armedRect` ([script:643](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:643>), assignment only at [651](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:651>)). The resolver therefore passes the initial `null` rect ([438](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:438>)); the runtime rejects that as `unknown-key` ([live_continuity_js.py:244](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:244>)-[252](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:252>)). `armedElId` is also initially null, so fallback cannot recover.

   Fix: assign/validate `st.armedRect = rect` before resolution, or resolve directly with the supplied `rect`; require `armResult.ok` as an integrity key. Add an actual browser test asserting arm-at-`#7` succeeds.

2. The move-start trigger has neither advance causality nor a valid shared time origin.

   The poll accepts any >1 px owner-rect change after arming ([script:666](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:666>)-[675](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:675>)). Thus layout jitter, stage resize, an already-running footprint pin, or player pre-layout can fire it before the advance.

   `perfNowAtClick` and `holdStartedAt` are the same browser `performance.now()` clock, but the former is sampled before owner binding and before key dispatch ([2869](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2869>)-[2888](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2888>)). A pre-click trigger during that gap therefore has a positive offset and can pass. Worse, capture offsets use Python `time.monotonic()` while in-hold membership compares them with offsets based on browser `performance.now()` ([3101](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3101>)-[3117](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3117>)).

   The 0.375 s ceiling is not defensible. The runtime interpolation is linear ([live_continuity_js.py:687](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:687>)-[692](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:692>)); over the configured 952→1266 px width change ([script:143](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:143>)-[144](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:144>)), width departs by 1 px after about 4.8 ms and by >3 px on the first 60 Hz frame. At 0.375 s the move is already 25% complete.

   Fix: record a trusted ArrowRight `keydown` timestamp in the page, ignore/reject rect departures before it, record per-sample browser timestamps, and compare hold/release/capture using that one clock. Require the first departure within the first one or two delivered post-key rAFs, with stage geometry unchanged.

3. `flipWindowDecodable` weakens the existing gate and can permit a false PASS.

   `_moving_index_run_at_cut` calls a window “decodable” solely when `footprintSource=="measured"`; it never checks `index is not None` ([script:2599](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2599>)-[2603](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2603>)). The scorer blindly trusts that boolean ([3140](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3140>)). This replaces the prior decoded-value check with a weaker predicate.

   Release is also off by one: the flip sample increments `post_flip_measured`, and release occurs at count 6 ([2758](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2758>)-[2770](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2770>)), while the helper promises the flip plus six samples after it—seven samples ([2587](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2587>)-[2600](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2600>)). Post-release samples then contribute to `nAfterFlip` ([3141](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3141>)-[3178](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3178>)).

   A direct pure-function probe produced `freezeRunAtCut=6`, `reason="freeze run at cut"`, and `flipWindowDecodable=True` with the required flip+6 sample set to `index=None`.

   Fix: require both `footprintSource=="measured"` and `index is not None`; count six samples strictly after the flip before releasing; bound `enoughAfterFlip` to the covered at-cut segment. Prefer passing raw `indexSamples` to the scorer and recomputing instead of trusting a boolean.

## MAJOR

4. The split schedule is not identical across A1/B/A2.

   B receives a release callback, while positives receive `None` ([script:2895](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2895>)-[2899](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2899>)). Consequently positive `releaseOffsetS` is null and their settled filter admits every settled sample, whereas B admits only post-release samples ([2922](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2922>)-[2931](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2931>)). `movingContinuity3to4` is computed over the full pre/post-release sample set ([2941](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2941>)-[2947](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2947>)); not every isolation input is post-release.

   The release itself cannot race the screenshot—the screenshot and decode finish before the awaited release call—but the off-by-one means the required final covered sample is captured after removal.

   Fix: compute and record one split offset/index in every arm, execute a no-op callback on positives at the same point, and use that split for every contamination-sensitive isolation input.

5. M5 remains unresolved: `coverTracksFootprint` does not reliably detect the one-frame lag.

   Each loop logs the previous cover position before updating it ([script:563](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:563>)-[596](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:596>)). With the poll ahead of the runtime pin, this can compare old cover to old owner, then let the later runtime callback move the owner before paint—the rendered lag is never observed.

   Even when it compares old cover to new owner, a systematic 60 Hz one-frame lag passes the 2 px tolerance: per frame, x changes about 1.43 px, y 0.96 px, cover width 1.40 px, and height 0.98 px. At 30 Hz it would instead fail every frame and make the bracket permanently inconclusive.

   Fix without editing `src/`: schedule the control loop after the pin using a one-time timer/rAF ordering handoff; in each callback update the cover, then independently read both actual DOM rects and log those final pre-paint values.

6. Capture helpers and production JS remain untested at their load-bearing seams.

   `_couple_owner_rect` and `_moving_index_run_at_cut` have no direct pure-function tests. Tests instead set `"unstable"` manually ([test_p2_adversarial.py:1256](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1256>)-[1266](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1266>)) and set `flipWindowDecodable=False` by hand ([1316](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1316>)-[1325](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1325>)). The fixture builder bypasses the helper and hardcodes the flag true ([900](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:900>)-[910](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:910>)). The only JS test is syntax parsing ([1351](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1351>)-[1359](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1359>)).

   Fix: directly table-test both helpers, including missing rects, exactly-at-tolerance, undecodable measured samples, flip off-by-one, and post-release contamination; add a browser test for arm/keydown/first-rAF/cover ordering.

7. The ordinary Transition-C caller no longer supplies a bound owner.

   `_advance_to_slide4_capture` is called without `bound_owner_id` in the main run ([script:4064](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4064>)-[4075](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4075>)). Therefore its samples become `modelled`, never `measured` ([2696](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2696>)-[2743](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2743>)), and the report-only at-cut result necessarily says no measured sample reached slide 4 ([4093](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4093>)-[4107](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4107>)).

   Fix: bind before Transition C and pass the ID, as the bracketed capture does.

## Round‑1 disposition

- B1: **PARTIALLY RESOLVED** — hash normalization is fixed ([script:625](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:625>)-[640](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:640>)); arm failure and false-early movement remain.
- B2a: **RESOLVED** — pre-move binding and direct ID reads exist ([2530](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2530>)-[2557](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2557>)).
- B2b: **PARTIALLY RESOLVED** — before/after coupling exists ([2560](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2560>)-[2579](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2579>)), but is untested and not atomic.
- B2c: **PARTIALLY RESOLVED** — flip position uses the full list, but decodability is wrong and trusted.
- B3: **PARTIALLY RESOLVED** — release is serial and mid-loop, but the boundary is off by one and positives lack the same split.
- M4 trigger timing: **NOT RESOLVED**.
- M4 stage origin: **RESOLVED** ([script:654](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:654>)-[656](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:656>)).
- M4 `noControlError`/readiness/stale-source/paint-once: **RESOLVED**.
- M4 cover stability/hit-test/tracking: **PARTIALLY RESOLVED**.
- M4 loop/gap: **PARTIALLY RESOLVED** — trigger→first-rAF is covered, move→trigger and last-rAF→release are not.
- M4 stale/flip/measured/release integrity: **PARTIALLY RESOLVED**.
- M4 bridge engagement: **RESOLVED**.
- M4 index verdict and decoder identity: **PARTIALLY RESOLVED** because capture timing remains unsound.
- M4 owner ambiguity: **PARTIALLY RESOLVED** — disconnect and per-rAF identity are now checked ([3190](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3190>)-[3198](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3198>)), but the production arm cannot establish the owner.
- M4 positive bracket/player errors: **RESOLVED**.
- M4 isolation greenness: **RESOLVED** ([3255](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3255>)-[3264](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3264>)).
- M5: **NOT RESOLVED**.
- M6a JS/stale-trigger coverage: **NOT RESOLVED**.
- M6b cover-tracking tautology: **PARTIALLY RESOLVED** — independent DOM reads exist, callback ordering is untested.
- M6c synthetic paint/decode tautology: **RESOLVED** by independent paint geometry ([test_html_alpha_probe.py:1682](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1682>)-[1721](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1721>)).
- M6d real-frame scale verification: **NOT RESOLVED**; the test remains ideal numeric geometry ([1621](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1621>)-[1635](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1635>)).
- Round‑1 fixture-coherence bullet: **PARTIALLY RESOLVED**; settled values are now clean, but the builder bypasses the new capture helper.

No existing numeric constant was changed; new tolerances/windows were added. The material gate weakening is `flipWindowDecodable`, not a threshold change. No swallowed exception found that independently yields PASS; resolver errors now populate `st.error`. Full pytest could not run because the read-only environment provides no writable temporary directory; JS syntax parsing succeeded.