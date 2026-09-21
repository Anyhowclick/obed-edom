Verdict: `FAIL`

## BLOCKER

None.

## MAJOR

1. [p2_recovery_html_adversarial.py:4242](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4242), [p2_recovery_html_adversarial.py:4446](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4446), [p2_recovery_html_adversarial.py:4510](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4510) — **(b), semantic remainder of r9 MAJOR 1 and 3.** `_at_cut_boundary_valid` only verifies that cached `atCutBoundary.from` is in range; it does not prove it is the first sample at or after `advanceKeyPerfMs`. A stale later index can discard the first post-key reset/anomaly and green a positive. Release ordering likewise trusts `lastAtCutPerfMs`; a stale earlier value can claim release followed the final covered capture even when `indexSamples[releaseSplitIndex].perfNowMs` says otherwise.

   Smallest sound fix: rerun `_at_cut_boundary(indexSamples, advanceKeyPerfMs)` and require exact agreement with the cached boundary; derive `lastAtCutPerfMs` directly from the validated split sample. Top-level `atCutFrom` is otherwise genuinely redundant.

2. [p2_recovery_html_adversarial.py:4191](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4191), [p2_recovery_html_adversarial.py:4640](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4640), [p2_recovery_html_adversarial.py:4678](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4678), [tests/test_p2_adversarial.py:4403](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4403) — **(b), same cached-sub-verdict class as round-12 `collectorSeriesSound`.** The provenance allowlist excuses several gates that are re-derivable or insufficiently attested:

   - `advance.ok` is re-derivable from sent, landed, outstanding, unlanded, stopped, and final-hash fields. The allowlist’s claim that its inputs are absent is false.
   - Drain cleanliness is re-derivable from the recorded counts, unlanded list, and `hashAtArm`.
   - `settledIndexProgression.ok` is re-derivable from the post-split settled `indexSamples`.
   - `ownerSettle.settled` is not fully attested: the ordered rect readings were discarded, leaving only another derived count and Boolean.
   - `movingContinuity3to4.ok` cannot be fully re-derived because `mediaSamples` is discarded; stale green continuity fields can hide a handoff or rVFC rewind.
   - `bridgeEngaged` trusts a Boolean despite retaining `bridgeEvents`; the clean fixture itself combines `bridgeEngaged=True` with `bridgeEvents=[]`.

   Thus two presses, `hashAtArm="#8"`, zero stable readings, stalled settled indices, or absent bridge evidence can coexist with cached green values and PASS.

   Smallest sound fix: add pure advance/drain/settled-progression derivations and require cached agreement. Preserve ordered owner-settle readings and `mediaSamples`, then re-run the settle and continuity scorers. Derive bridge engagement from events validated for movie key, scene, old decoder identity, and generation.

3. [p2_recovery_html_adversarial.py:4315](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4315), [tests/test_p2_adversarial.py:4644](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4644) — **(b), same class as the round-12 collector fix.** The bracket re-runs `_collector_ok`, but MAIN still reads only `collector.ok`. A truncated, dropped, malformed, or unbracketed MAIN series with stale `ok=True` keeps `_advance_c_ok` green; the MAIN allowlist explicitly permits deletion of every primitive collector field.

   Smallest sound fix: invoke `_collector_ok(collector)` in `_advance_c_ok`, require its result to agree with cached `ok`, and remove those MAIN allowlist entries.

4. [p2_recovery_html_adversarial.py:4261](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4261), [p2_recovery_html_adversarial.py:4410](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4410), [tests/test_p2_adversarial.py:895](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:895) — **(b), same class as r7 MAJOR 1 and r8 MAJOR 1.** `_badge_samples_sound` trusts each sample’s derived `footprintSource=="measured"` and aggregate counters. It does not require or re-check that sample’s `badgeSeq`, `badgeRect`, `measuredRect`, or finite `perfNowMs`. The pass fixture omits the rect evidence entirely. A covered sample can therefore lose its clock and disappear from `covered_positions`, or retain a stale “measured” label after its coupling evidence disappears, while later frames still satisfy the freeze window.

   Smallest sound fix: for every non-exempt sample, require a finite clock, strictly increasing typed sequence, both rects, and `_couple_owner_rect(measuredRect, badgeRect) == measured`; recompute source instead of trusting it. Validate the re-handoff pair separately. The top-level `footprintSources` list remains a legitimate redundant view.

5. [tests/test_p2_adversarial.py:4771](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4771), [tests/test_p2_adversarial.py:4815](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4815) — **(c), test-harness correctness.** The “exhaustive” walk collapses list indices and ORs closure results. One deletion that fails closed marks the entire collapsed field gated even when deleting another occurrence still preserves PASS. This specifically conceals position-sensitive sample-clock and geometry holes.

   Smallest sound fix: retain concrete indexed paths, or aggregate with AND and explicitly classify diagnostic versus scored positions. The pass fixture must also mirror production fields such as owner samples and badge rect evidence.

## MINOR

1. [p2_recovery_html_adversarial.py:4581](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4581), [p2_alpha_spike.py:128](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_alpha_spike.py:128) — **(b), same class as the r4/r5/r8 minimal-comment findings.** New production comments and docstrings embed review history and long failure narratives, contrary to the repository’s minimal-comment rule.

   Smallest fix: keep concise behavioral contracts and move review history into the plan.

R9 MAJOR 2 and 4 are closed. `flipWindowDecodable` and gating uses of `movingIndexRunAtCut` are re-derived; `indexSequence` is redundant. The Chrome `_spawn`/`_attach` cleanup, terminate/kill reaping, `start()`-inside-`try`, separate profiles, and A1→B→A2 ordering exposed no additional defect.