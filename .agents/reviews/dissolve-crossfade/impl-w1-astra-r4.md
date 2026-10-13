Reviewed `1091285c`; `src/` is unchanged since `debfc685`. **N1–N8 are CLOSED, but one demonstrated safety-test blocker remains.**

| Item | Status | File:line evidence |
|---|---|---|
| N1 | **CLOSED** | Eighteen additional near-misses; complete key-sorted input snapshots for rejection and construction failure. [tests:944][t944], [tests:993][t993], [tests:1570][t1570]. |
| N2 | **CLOSED** | Actual effect/event parameterization; rejected/missing effects, index-3 success and mismatched attachment. [tests:1116][t1116], [tests:1302][t1302]. |
| N3 | **CLOSED** | Above-stage controls; every bitmap border/radius/padding member; clipping-chain negatives. [tests:1167][t1167], [tests:1306][t1306], [tests:1372][t1372]. |
| N4 | **CLOSED** | Later video uses `readyState:1`; both-admitted positive and separate cover-gate rejection retained. [tests:1294][t1294]. |
| N5 | **CLOSED** | Complete readback/writeback coordinates, nonzero left/top clipping and independently calculated x/y scales. [tests:1110][t1110], [tests:1223][t1223], [tests:1311][t1311]. |
| N6 | **CLOSED** | Ordered per-canvas trace checked on every row, including two foreground canvases. [tests:1314][t1314], [tests:1612][t1612]. |
| N7 | **CLOSED** | All 256 inputs in every RGB channel compared with independent `_tone`. [tests:1200][t1200], [tests:1216][t1216], [tests:1328][t1328]. |
| N8 | **CLOSED** | Work advances the clock; external measurement brackets the take; both published durations must match. [tests:1104][t1104], [tests:1123][t1123], [tests:1610][t1610]. |

The two decoded-dimension survivors are **admission/safety-equivalent**, not strictly observationally equivalent. Removing either guard independently leaves the other to reject both-zero dimensions ([runtime:118][p118]). With one zero dimension, `contain` produces an empty content region; `fill` fails the aspect check ([runtime:125][p125]). Neither attaches a snapshot. Additional frame/style work and elapsed-time telemetry can differ.

**Blocker — indirect video detachment escapes the oracle.** At [runtime:143][p143], mutate:

```js
H.push(h),ad.push(v)
```

to:

```js
H.push(h),ad.push(v),v.parentElement.removeChild(v)
```

This survives construction, census, all **200 freeze rows**, and deck cases on **both players**, with identical observed results. The video proxy watches direct operations ([tests:1070][t1070]), but its parent stub lacks `removeChild` ([tests:1080][t1080]). The call throws after admission and the candidate catch swallows it. In a browser, it detaches the live video, violating [§3.2’s add-only/video-untouched requirement][spec187].

The oracle needs parent-removal observation and a negative control proving this indirect detach is caught.

Verification executed through in-memory Node input: all eight baseline behavioral cases passed; all 13 concrete Round 3 mutations were caught on both players. The reported full-suite **125/781** tallies were not independently rerun.

**CHANGES REQUIRED**

[t944]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:944
[t993]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:993
[t1570]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1570
[t1116]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1116
[t1302]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1302
[t1167]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1167
[t1306]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1306
[t1372]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1372
[t1294]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1294
[t1110]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1110
[t1223]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1223
[t1311]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1311
[t1314]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1314
[t1612]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1612
[t1200]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1200
[t1216]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1216
[t1328]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1328
[t1104]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1104
[t1123]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1123
[t1610]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1610
[t1070]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1070
[t1080]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1080
[p118]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:118
[p125]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:125
[p143]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:143
[spec187]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:187