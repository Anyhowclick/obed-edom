**CHANGES REQUIRED**

Reviewed `cb646c07` against rev 12 and the earlier W2/W3 reviews. **190 callable scorer cases passed in memory**; the filesystem-dependent case was not run. No pytest or live captures were run. The reported **336 passed, 1 skipped** and mutation sweep remain implementer evidence.

**Standards:** no substantive findings. **Spec:** nine findings below. CLASS “closed” denotes recurrence of a previously hardened false-pass class.

1. **Blocker — CLASS: closed — new arms bypass shared media integrity.**  
   [dissolve_probe.py:2483](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2483), [score_engaged:1741](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1741).

   Concrete reproductions using the committed synthetic fixtures:
   - `m-snap`: set decoder `rv=[]`, `tuple=None` → **all four checks PASS, arm MATCH**.
   - `m-snap-frac` with `holder-shift` and its corresponding twin, same missing evidence → **holder_pixels FAIL, arm MATCH**.
   - `m-raw-caption` or `m-geo-scale`, no holders, empty decoder and per-rAF video inventories → **expected FAIL, arm MATCH**.
   - CEF `m-dsk78`, two holder records but no decoder observations → **geometry INCONCLUSIVE, cost PASS, arm MATCH**.

   The check-name dispatch omits reference/engagement integrity; CEF’s reporting exemption additionally suppresses binding failures.  
   **Exact fix:** validate shared media evidence independently of selected checks, including reference twins. Give engagement captures an appropriate completeness contract without fade-coverage requirements. Require two distinct bound outgoing decoders for DSK, and propagate binding failures to arm-level integrity even when geometry is reported.

2. **Blocker — CLASS: closed — incomplete hide controls qualify their gates.**  
   [dissolve_probe.py:1809](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1809), [score_hide_capture:2626](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2626).

   Delete every after-show screencast frame from `life-hide-nohide`: **hidden FAIL, arm MATCH, hidden gate PASS**. Delete every hidden-interval frame from `life-hide-noshow`: **shown FAIL, arm MATCH, shown gate PASS**.

   Coverage failures remain in unselected checks while `score_hide` returns no shared problems.  
   **Exact fix:** return missing-interval, insufficient-frame and duplicate-frame failures as shared capture integrity before selecting the control’s expected check. Both controls must establish the complete capture contract.

3. **Major — CLASS: new — tone scoring discards the verified production mask.**  
   [dissolve_probe.py:2348](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2348).

   `score_media` overwrites its `mask` argument with the counter-block foreground mask, then passes that replacement to `tone_coverage`.

   In `media_run("m-tone")`, use:
   ```python
   {
       "ramp": [[200, 40, 160, 40, 128]],
       "patches": [[200, 40, 160, 40, [128, 128, 128]]],
   }
   ```
   Both cells lie entirely beneath the verified foreground mask. Correct coverage is **0/1 ramp and 0/1 patch**, but scoring with `identity=False` returns **tone PASS, worst=0, arm MATCH**.

   **Exact fix:** keep the verified production mask unchanged; name the counter-block mask separately and use it only for foreground scoring.

4. **Major — CLASS: new — reference validation can qualify missing or different artifacts.**  
   [dissolve_probe.py:1682](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1682), [reference geometry:1709](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1709).

   Demonstrated:
   - Set F50’s names to `["ref-F50-0", "ref-F50-0"]`, delete `ref-F50-1` → **all checks PASS, MATCH**.
   - Set `perfect.shots=["live-0","live-1"]`, corrupt `ref-perfect-1` → **reference PASS, MATCH**. Validation reads the aliases while scoring reads hardcoded names.
   - Change `perfect-shift.reference.perfect.rect` to `[0,0,1,1]` → **reference FAIL, MATCH** despite an invalid crop declaration.

   **Exact fix:** require distinct, state-specific capture identifiers and score exactly the images that passed validation. Bind `perfect.rect` to the holder canvas’s device box, with ordered, in-bounds coordinates. Violations must invalidate the arm before either expected outcome counts.

5. **Major — CLASS: new — multi-frame timestamp shifts remain undetected.**  
   [dissolve_probe.py:1767](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1767), [after-show scoring:1804](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1804).

   Add **64 ms** to every cast timestamp after `show+17`, preserving order and pixels. Both the stock hide control and the complete `life-hide` row still return **MATCH**; `hidden`, `shown` and `after_show` remain PASS.

   Nearest-rAF proximity merely finds another frame, while the model independently fits progress. This exceeds the claimed sub-half-frame limitation.  
   **Exact fix:** preserve and validate capture-to-rAF correspondence, and compare image progress against the corresponding rAF progress within the permitted timing interval. Test an order-preserving shift.

6. **Major — CLASS: new — engagement accepts the incoming wrapper.**  
   [dissolve_probe.py:1744](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1744).

   In valid `m-raw-svgclip`, change the holder parent from outgoing `layer4-opacity` to incoming `layer3-opacity` → **exterior PASS, arm MATCH**.

   Membership in any transition wrapper does not satisfy §9.1’s outgoing-wrapper requirement.  
   **Exact fix:** derive the outgoing wrapper from the captured outgoing texture’s ancestry and require every admitted holder to belong to that wrapper.

7. **Major — CLASS: edge — failed raw injections can satisfy negative controls.**  
   [dissolve_probe.py:2158](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2158).

   Set a no-holder `m-raw-modal` record’s injection result to `[False]` → **exterior FAIL, arm MATCH**. The validator accepts any nonempty list of numbers or booleans, including explicit failure.

   **Exact fix:** validate each injection’s semantic result: confirmed open modal/shadow dialog, visible navigator placement, or the required painted geometry. Failed or malformed injection evidence must be shared INCONCLUSIVE.

8. **Major — CLASS: closed — insufficient tone coverage escapes through report-only aggregation.**  
   [dissolve_probe.py:2365](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2365).

   `m-tone`, identity mode, `mutate="tone-small-cells"` → **tone INCONCLUSIVE** (`1/4` ramp cells exposed), **mask PASS, arm MATCH, problems=[]**.

   Rev 12 explicitly places the ≥50% rule under capture integrity. Ordinary tone error may be reported; missing measurement coverage may not.  
   **Exact fix:** propagate coverage failures through the shared problems returned by `score_media`, while keeping valid tone measurements report-only under identity.

9. **Major — CLASS: new — W3 does not require the OBS launch’s measured map.**  
   [managed_obs_qualify.py:1526](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:1526), [dissolve_probe.py:3299](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:3299).

   W3 never supplies `lut`; scoring falls back to generic `lPath.gpu`, without launch or CEF-path binding. On the synthetic tone-step `m-snap`, `lPath.gpu="analytic"` gives **holder_pixels PASS, MATCH**, whereas `"identity"` gives **FAIL, residual 11**. Neither requires OBS calibration evidence.

   **Exact fix:** obtain and validate the map associated with that OBS launch, acceleration state and compositing path, then pass it explicitly. Missing or mismatched provenance must make holder-pixel qualification INCONCLUSIVE.

The ambiguity resolutions assess as follows:

| # | Judgment |
|---|---|
| 1 | **Accept the profile split**, but mandatory holder binding remains shared integrity. Current DSK behavior fails that requirement; see 1. |
| 2 | **Reject.** Tone coverage is explicitly capture integrity; see 8. |
| 3 | **Accept.** `(1, τ]` qualifies neither the ≤1 positive nor the >τ negative. |
| 4 | **Accept the conceptual split**, provided capture integrity reaches both controls and the model check remains qualified. Current implementation fails this; see 2 and 5. |
| 5 | **Reject.** A 64 ms order-preserving shift passes, not merely a sub-half-frame shift; see 5. |
| 6 | **Accept.** Separate `m-raw` and `m-raw-end` arms make both transitions independently required. |
| 7 | **Accept for transparent capture**, with the modification and digest recorded. It is not literally an unmodified-page capture. |
| 8 | **Accept.** Engagement-only geometry controls need not pause or satisfy timed fade coverage. They still need complete scenario evidence. |
| 9 | **Accept.** These mutations exercise the intended base-size and nested-scale rejection conditions. |
| 10 | **Accept.** Sequential counted `a+b` splices preserve refusal on anchor mismatch. |
| 11 | **Accept.** W3 specifically requires DSK 7→8; Q0b-bis separately owns broader cost measurements. |
| 12 | **Accept only as dormant under explicit identity.** The stale anchor is fail-closed, but the nonidentity path is not implemented successfully; its reference/mask contract also needs updating before activation. |
| 13 | **Accept missing-map → INCONCLUSIVE.** The generic `lPath` schema is insufficient for W3’s launch-specific requirement; see 9. |

**CHANGES REQUIRED**