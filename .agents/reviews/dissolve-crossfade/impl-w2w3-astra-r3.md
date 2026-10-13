Reviewed HEAD `243de015`. All 20 committed R2/sweep case builders returned their expected results when called directly. The additional sweep covered **960 mutations** across the six requested arms, with no escaped exceptions. Four demonstrated gaps remain.

No pytest or live captures were run; **262 passed, 1 skipped** remains implementer-reported. No substantive standards findings.

Below, `dp` = `scripts/dissolve_probe.py`; `q` = `scripts/managed_obs_qualify.py`.

| R2 finding | Status | Evidence |
|---|---|---|
| B1 — observation inventories | **NOT CLOSED** | Original missing-inventory/tuple/G2 reproductions are rejected at `dp:1369`, `dp:1547`, `q:679`. Malformed video entries still produce MATCH: finding 1. |
| B2 — incomplete controls | **CLOSED** | `dp:1670` propagates fade-integrity failures; `dp:1918` requires a problem-free MATCH before reading controls. Three-mid-frame `m-off`/`m-hold` are INCONCLUSIVE. Removing post-transition `off` screenshots now makes both model and complement gates INCONCLUSIVE. |
| M3 — animation validation | **NOT CLOSED** | `dp:1028–1033` rejects the original malformed-running records, but validation still depends on an insufficiently validated state: finding 2. |
| M4 — endpoint alpha bounds | **CLOSED** | `dp:1010–1015` checks all admitted frames. The endpoint-alpha reproduction returns complement FAIL and no-dip FAIL. |
| M5 — lifecycle evidence | **NOT CLOSED** | Actions are checked on run and twin at `dp:1757–1759`; cleanup inventory at `dp:1772–1776`; collector fallback removed at `dp:2107`. Automatic frame 99 now fails. Coverage remains insufficient: finding 3. |
| M6 — LUT endpoints | **CLOSED** | `dp:847–855` retains endpoints and includes them in analytic qualification. The contradictory endpoint reproduction returns `table`. |
| M7 — CEF cut timing | **CLOSED** | `q:708` preserves raw intervals; `dp:1132–1140` requires containment. `[-20,36]` across cut `[0,16]` is INCONCLUSIVE. |
| M8 — report-only aggregation | **NOT CLOSED** | `dp:1713–1716` fixes the original report-only no-flash blocker, but shared media-integrity failures can now escape aggregation: finding 4. |
| m9 — cached calibration | **CLOSED** | `q:1518–1520` re-derives thresholds and compares the cache. The original contradictory calibration is rejected. |
| m10 — negative duration | **CLOSED** | `dp:1238` rejects negative duration. `-42` produces INCONCLUSIVE. |

Reproductions below use the committed synthetic helpers with `VIEWPORT=(640,360)`.

1. **Blocker — CLASS: edge — malformed video observations become “no overlay.”**  
   Evidence: [dp:1263](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1263), [dp:1369](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1369).

   Start with `media_run("m-on")`. Add a tagged decoder and, at transition rAF index 20, a video record with:
   ```
   id=1, on=True, rect=CONTENT, eff=1.0, inT=False, inStage=False
   ```
   The intact observation produces **overlay FAIL, arm MISMATCH**.

   Independently deleting `on`, setting `on=None`, or setting `rect[0]=NaN` produces **overlay PASS, arm MATCH, problems=[]**. Missing `on` is filtered away; NaN coordinates make overlap comparisons false.

   **Exact fix:** validate every video record before filtering. Require valid unique IDs and boolean `on`; connected records must have finite rectangle coordinates, finite effective opacity and boolean membership fields. Propagate malformed observations as shared integrity failures.

2. **Major — CLASS: edge — invalid animation state still hides malformed records.**  
   Evidence: [dp:1029](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1029).

   In `raf_curve("ease")`, change both final-row animations to:
   ```
   state="", ct=NaN
   ```
   Result: **curve PASS**, ten remaining rows counted.

   The corresponding full-arm reproduction—`media_run("on")`, modify both animations in `dump.raf[-20]`, score with CEF—returns **curve PASS, arm MATCH, problems=[]**.

   Any string satisfies state validation, while only `"running"`/`"finished"` trigger timestamp validation. The malformed records then disappear during filtering.

   **Exact fix:** validate the animation-state enum and every supplied numeric field before sample selection. Permit null timing fields only for explicitly supported states; reject nonfinite populated fields regardless of state.

3. **Major — CLASS: edge — lifecycle coverage remains below the required minimums.**  
   Evidence: [dp:1797](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1797), [dp:1844](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1844). Requirements: plan §9.1, lines 349–352.

   Two independent reproductions:

   - Build `life-advance` and an untouched stock twin. Retain screenshots `000,001,002,010,017,018,019`. Only `[890,900]` remains inside the transition. Ordinary fade scoring reports **`1 mid frames < 6`**; lifecycle scoring returns **complement PASS, MATCH, problems=[]**.
   - Build automatic run and twin with `mutate="delay-42"`. Remove run screenshots satisfying `120 < t0 and t1 < 596`. Only one delay screenshot remains. Result: **frozen_delay PASS**, `delay=[42]`, **MATCH**.

   **Exact fix:** enforce six mid frames for uninterrupted lifecycle fades and at least two screenshots inside the automatic delay. Insufficient coverage must make the row INCONCLUSIVE. Any interrupted-row coverage exception needs an explicit contract.

4. **Major — CLASS: edge — report-only exemption suppresses shared media-integrity failures.**  
   Evidence: [dp:1584](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1584), [dp:1699](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1699), [dp:1713](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1713).

   Build `media_run("m-tone")`, supply `tone_layout()`, and score with `profile.arm("m-tone", True), identity=True`.

   Independently delete the decoder’s `rv`, its `tuple`, or the `foreground` inventory. Under **both DX-1 and CEF**, each produces:
   ```
   tone=INCONCLUSIVE
   arm=MATCH
   arm.problems=[]
   ```
   Inserting the missing-reference result into the existing otherwise-perfect scored-round fixture produces **overall PASS**.

   Shared media problems live only inside individual check results; report-only aggregation ignores them.

   **Exact fix:** return shared media-integrity problems separately and append them to arm-level `problems` before aggregation. Keep diagnostic-only report gaps non-blocking.

**CHANGES REQUIRED**