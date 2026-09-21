# Verdict: FAIL

## BLOCKER

1. The null control fires immediately, before the 3→4 advance.

   `_capture_3to4_snapshot` passes `"7"` to `arm()` ([p2_recovery_html_adversarial.py:2656](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2656>)), but the poll compares it directly with `location.hash`, which is `"#7"` ([p2_recovery_html_adversarial.py:590](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:590>), [p2_recovery_html_adversarial.py:613](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:613>)). Therefore it immediately calls `trigger("hash")`, before the keypress at line 2664. The real bracket can only become inconclusive; the clean unit fixture bypasses this wiring.

   Fix: require `hash3 == "#7"` and pass `hash3`, or normalize both values identically before comparison. Add a browser/JS test covering arm-at-`#7`.

2. `_measured_footprint` does not measure the moving footprint reliably, and its rect is from the wrong frame.

   During the actual move the hash remains `#7`, so capture progress stays `0` ([p2_recovery_html_adversarial.py:2528](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2528>)). `_measured_footprint` nevertheless resolves the owner by IoU against that modelled, slide-3 hint ([p2_recovery_html_adversarial.py:2465](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2465>), [p2_recovery_html_adversarial.py:2473](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2473>)). The runtime’s video has already moved, so the ≥0.75 IoU gate rejects it ([live_continuity_js.py:278](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:278>), [live_continuity_js.py:287](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:287>)). After `#8`, the probe restarts its own interpolation from zero, so the first “measured” `#8` sample can be well after the real cut.

   Additionally, the screenshot is taken at line 2541, while the rect used to decode it is measured later at line 2566. The moving element can change between those operations ([p2_recovery_html_adversarial.py:2540](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2540>), [p2_recovery_html_adversarial.py:2566](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2566>)).

   Consequently, `footprintSource=="measured"` does not prove that the screenshot was decoded at its painted rect, and `flipIndex` identifies the first late resolvable sample rather than the cut.

   Fix: bind the keyed decoder ID before movement, then read that element directly without a modelled IoU hint. Capture the rect and screenshot atomically in the same post-layout frame, with the rect read immediately before capture.

3. A genuine captured B arm cannot satisfy `isolationEqual`.

   The cover remains installed through the entire dense capture and is released only afterward ([p2_recovery_html_adversarial.py:2670](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2670>), [p2_recovery_html_adversarial.py:2673](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2673>)). `settledIndexProgression` is then calculated from those covered samples ([p2_recovery_html_adversarial.py:2691](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2691>)). A working freeze necessarily makes B’s settled progression red, while A1/A2 remain green. Yet that field is required equal across all arms ([p2_recovery_html_adversarial.py:2786](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2786>), [p2_recovery_html_adversarial.py:3001](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3001>)).

   The passing fixture conceals this contradiction by inheriting `settledIndexProgression={"ok": True}` despite supplying a frozen sequence ([test_p2_adversarial.py:864](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:864>), [test_p2_adversarial.py:905](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:905>)).

   Fix: split the capture. Hold only through a bounded at-cut window with enough post-flip samples, release, then collect settled progression and the visible-content burst uncovered.

## MAJOR

4. `_score_freeze_control` can accept a wrong-time/wrong-surface freeze; several integrity keys are vacuous or use the wrong snapshot field.

   Integrity-key audit:

   - `firedAtMoveStart`: only checks the string `"motion"`; it does not compare the marker’s `started` value with the click or hold ([p2_recovery_html_adversarial.py:2966](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2966>)).
   - `firedAfterAdvance`: allows 50 ms before the click and has no upper bound, so a delayed poll after the move passes ([p2_recovery_html_adversarial.py:2967](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2967>)).
   - `stageOriginZero`: reads `body#body`, not `#stage`; it does not test the stage-map origin used by the runtime ([p2_recovery_html_adversarial.py:594](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:594>), [live_continuity_js.py:323](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:323>)).
   - `noControlError`, `ownerReadyAtTrigger`, `staleFrameFromPlayback`, and `paintedOnce` are meaningful.
   - `coverPatchStable` proves only that the canvas backing store was not repainted, not that it covered the movie.
   - `coverHitTest100` tests the cover at a point derived from the same pre-pin rect, before later rAF callbacks can move the video ([p2_recovery_html_adversarial.py:555](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:555>)).
   - `coverTracksFootprint` is tautological: `coverRect` and `measuredRect` are both derived from the same local `fp`; it never reads `cover.getBoundingClientRect()` ([p2_recovery_html_adversarial.py:546](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:546>), [p2_recovery_html_adversarial.py:557](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:557>)).
   - `loopLive` and `maxRafGapOk` cover only the post-trigger log; they cannot detect a long delay from movement start to trigger.
   - `everyInHoldStale` is the strongest composite check, but it decodes a screenshot using a later rect, so a flat wrong ROI matching the cover mean can satisfy it.
   - `flipIndexPresent`, `flipWindowDecodable`, and `enoughAfterFlip` operate on the measured-only subsequence, but its “flip” is the late artificial one described above.
   - `allInHoldMeasured` trusts the post-screenshot source tag.
   - `releaseBetweenLastCaptureAndBurst` is backed by real sequential capture ordering, although its predicate uses `<=`, not the promised strict inequality ([p2_recovery_html_adversarial.py:2935](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2935>)).
   - `bridgeEngaged` is meaningful but only proves that some bridge event occurred.

   Verdict-key audit:

   - `indexRunRed`, reason, margin, and negative-anomaly are meaningful only if the cut and ROI are genuine; currently neither is.
   - `movingContinuityOk`, bound-decoder identity, and rVFC advancement establish decoder liveness, mostly after `#8`; they do not establish correct cover timing.
   - `noOwnerAmbiguousInWindow` is effectively vacuous after binding. The poll binds before trigger ([p2_recovery_html_adversarial.py:610](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:610>)); subsequent calls return the bound element without re-running ambiguity resolution ([p2_recovery_html_adversarial.py:413](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:413>)). Resolver exceptions are also swallowed and the fallback is not gated ([p2_recovery_html_adversarial.py:419](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:419>)).
   - `playerBuildErrorsEmpty` and `positivesGreen` are meaningful, subject to the same bad measurement path.
   - `isolationEqual` checks equality, not greenness; `settledIndexProgressionOk=False` in all three arms would pass equality.

   Fix: log independently measured, post-pin video and cover DOM rects; gate `ownerResolved`; validate the marker timestamp/boundary; make every isolation value both green and equal; couple screenshot pixels and measured rect to one frame.

5. The stale-motion guard and rAF ordering are not sound.

   `keepThroughBridge` reuses an existing marker when generation and boundary-object identity match ([live_continuity_js.py:661](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:661>)). Therefore:

   - An exact stale marker can cause the hold never to fire on motion; it falls through to the late hash trigger.
   - If the owner was unresolved at arm, `armedMotionMarker` is null and any later stale marker is accepted as new ([p2_recovery_html_adversarial.py:583](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:583>)).
   - A stale marker from another boundary causes the fresh correct marker to be rejected because differing `atScene` returns false ([p2_recovery_html_adversarial.py:585](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:585>)).
   - A delayed rAF can observe a genuine marker after the move and still report `firedVia="motion"`; the scorer has no lateness bound.

   The poll rAF is queued before the keypress. `keepThroughBridge` then schedules its footprint-pin rAF ([live_continuity_js.py:703](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:703>)). The poll runs first, creates/schedules the cover loop, and the runtime pin runs afterward. This ordering can leave the cover one rendered frame behind, while the pre-pin self-comparison still reports perfect tracking.

   Fix: use an explicit runtime event containing generation, boundary identity, and start timestamp; require `atScene==8` and a bounded delta from the click. Update or attest the cover after the runtime pin, ideally from the same rAF owner.

6. Tests validate hand-built fixtures rather than the production capture.

   - The stale-marker test explicitly does not exercise the JS guard ([test_p2_adversarial.py:1108](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1108>)).
   - The cover-tracking test mutates one of two values that production always derives from the same `fp`, so it cannot expose the tautology ([test_p2_adversarial.py:1130](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1130>)).
   - The “measured footprint” null control actually uses `footprint_at`, paints the patch at that exact modelled ROI, then decodes through the same ROI ([test_html_alpha_probe.py:1682](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1682>), [test_html_alpha_probe.py:1730](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1730>)).
   - The scale-guard test derives the asserted patch bounds from the same ideal rectangle; it does not verify real frames as the plan requires ([test_html_alpha_probe.py:1621](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_html_alpha_probe.py:1621>)).
   - The clean scorer fixture cannot be produced by `_capture_3to4_snapshot` because its frozen B sequence is paired with a green settled progression.

   All original freeze tests were ported; the changed rAF-gap intent matches the new moving-target plan. The missing coverage is integration/coherence coverage.

   Fix: test the real JS in a browser, derive scorer fixtures through a capture-builder matching `_capture_3to4_snapshot`, and add assertions for `"#7"` arming, actual cover/video DOM rects, and capture-time rect alignment.

## Verified points

- The 3→4 premise is real: `keepThroughBridge` moves the live `<video>` itself, forces it visible/opaque, and writes its moving CSS box ([live_continuity_js.py:667](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:667>), [live_continuity_js.py:674](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:674>), [live_continuity_js.py:687](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:687>)). The fresh slide-4 decoder is hidden and the carried video remains authoritative ([live_continuity_js.py:1480](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:1480>)). Its `getBoundingClientRect()` is therefore the element’s painted viewport rect in this fixture.
- `movingIndexRunAtCut` is report-only for the main `continueThroughMovingMagicMove3to4` finding: it appears only in detail; the finding pass uses continuity, settled progression, visible liveness, and build errors ([p2_recovery_html_adversarial.py:4180](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4180>), [p2_recovery_html_adversarial.py:4190](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4190>)). It does gate the separate freeze bracket’s positive arms ([p2_recovery_html_adversarial.py:2994](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2994>)).
- Success wiring is fail-closed for every verdict except `pass`, and accepts `skipped` only with bridge disabled ([p2_recovery_html_adversarial.py:3078](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3078>), [p2_recovery_html_adversarial.py:4242](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4242>)). Bridge-off cannot green the current fixture because the independent 3→4 continuity finding remains in `all(f["pass"])` ([p2_recovery_html_adversarial.py:4283](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4283>)). No non-bridge-off production path returns `skipped`.
- Exact `"modelled"`/`"none"` samples do not enter `movingIndexRunAtCut`; it filters to `"measured"` ([p2_recovery_html_adversarial.py:2698](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2698>)). The defect is that the `"measured"` label is temporally and geometrically untrustworthy.
- Release is genuinely sequenced after dense capture and before the burst ([p2_recovery_html_adversarial.py:2670](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2670>), [p2_recovery_html_adversarial.py:2680](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2680>)); `footprintFullyLive` is not covered. The problem is the covered settled-index invariant collected before release.
- Viewport/screenshot units are otherwise consistent because Chrome is forced to device scale factor 1 ([p2_alpha_spike.py:140](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_alpha_spike.py:140>), [p2_alpha_spike.py:185](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_alpha_spike.py:185>)).

Tests could not be executed in the read-only environment because pytest could not create a temporary directory.