Reviewed HEAD `1c5d3004`. Reran the Round 3 reproductions in memory; all 13 committed R3 regression cases returned their expected results. The full **275 passed, 1 skipped** count remains implementer-reported.

| R3 finding | Status | Verification |
|---|---|---|
| 1 — malformed video observations | **NOT CLOSED** | Missing `on`, `on=None`, and NaN rect now yield INCONCLUSIVE in DX-1 and CEF. Another malformed-value case still yields MATCH; see below. |
| 2 — animation state | **CLOSED** | Empty state plus NaN time yields INCONCLUSIVE both in `score_curve` and the CEF arm. |
| 3 — lifecycle coverage | **NOT CLOSED** | Original one-mid-frame and one-delay-shot reproductions now yield INCONCLUSIVE. Interrupted rows still accept insufficient coverage. |
| 4 — report-only shared integrity | **CLOSED** | Missing rVFC, tuple, or foreground inventory yields arm INCONCLUSIVE under both profiles. Inserting the missing-foreground result into the otherwise-perfect round also yields INCONCLUSIVE. |

**1. Major — CLASS: edge — finite but impossible video measurements produce a false MATCH.**  
Location: [scripts/dissolve_probe.py:1401](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1401).

Using `media_run("m-on", mutate="ov-intact")`, independently modify the added video at `dump.raf[20].videos[-1]`:

| Input | Overlay | Arm |
|---|---|---|
| Unmodified | FAIL | MISMATCH |
| `eff=-1.0` | PASS | MATCH |
| `rect[2]=-480.0` | PASS | MATCH |

Both mutations return `problems=[]` in **DX-1 and CEF**. Validation accepts finite values; subsequent opacity filtering or rectangle overlap hides these impossible hook measurements.

**Exact fix:** require `0 <= eff <= 1` and nonnegative rectangle width/height in `video_problem`, before filtering. Preserve valid zero values and propagate violations through shared integrity.

**2. Major — CLASS: edge — interrupted lifecycle rows falsely accept two mid frames.**  
Locations: [scripts/dissolve_probe.py:234](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:234), [scripts/dissolve_probe.py:1892](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1892).

Demonstrated for both `life-goto` and `life-back`:

- Build the run and its stock twin.
- Retain run screenshots `000,001,002,005,006,017,018,019`.
- Remove `eff` and `anims` from both captures’ rAF records at `t >= 608`, immediately after the action at `596`.

Result: **complement PASS, arm MATCH, problems=[]**. Ordinary fade scoring reports **`2 mid frames < 6`**; the two progress values are approximately `0.0549` and `0.1177`.

`minMid: 2` is explicit configuration, but **not a justified exception to [rev 9 §9.1](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:349)**: the specification provides neither that exception nor its rationale.

**Exact fix:** remove the four `minMid` overrides and enforce `COVERAGE["midFrames"]` for lifecycle fades.

The two “valid” sweep cells are defensible:

- **`geo=None`:** a documented hook sentinel. One early null observation can still MATCH when subsequent geometry exists; removing all usable outgoing geometry yields INCONCLUSIVE.
- **Free-form cast names:** image lookup keys, not an enum. An arbitrary name with its image yields cut PASS/MATCH; removing the image yields INCONCLUSIVE.

No independent standards findings.

**CHANGES REQUIRED**