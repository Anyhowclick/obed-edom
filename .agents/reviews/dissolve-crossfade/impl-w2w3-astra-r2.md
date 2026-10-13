**CHANGES REQUIRED.** The fold fixes several original failures, but false-pass paths remain in both W2 and W3.

I inspected both commits and the requested files, and ran synthetic scorer calls in memory using the test helpers. I did **not** run pytest or live captures; the reported **242 passed, 1 skipped** remains implementer evidence.

**Round 1 closure**

Here, `dp` means `scripts/dissolve_probe.py`.

| R1 | Status | Evidence |
|---|---|---|
| 1. Shared media integrity | **NOT CLOSED** | Missing holder/rVFC evidence is rejected at `dp:1504–1556`, but malformed colour tuples and missing observation inventories still pass. Finding 1. |
| 2. Unclipped demixing | **CLOSED** | `dp:1140–1149` separates float demixing from decoding conversion; `dp:1185–1195` checks all RGBA channels. |
| 3. Complete rounds and controls | **NOT CLOSED** | Manifests exist at `dp:1323–1348`, but incomplete captures still qualify controls at `dp:1653` and `dp:1861–1865`. Finding 2. |
| 4. Curve evidence | **NOT CLOSED** | Finite-field and duplicate checks exist at `dp:1028–1032`, but filtering at `dp:1016–1027` discards malformed rows before validation. Finding 3. |
| 5. Every-pixel/every-frame bounds | **NOT CLOSED** | Pixel extrema are fixed; `dp:1009–1012` still checks only mid frames. Finding 4. |
| 6. Temporal coverage | **CLOSED for W2** | `dp:1082–1096` rejects missing pre-animation coverage; `dp:1125–1132` includes completion and rejects an after-cut-only cast. W3 introduces a separate timing loophole: finding 7. |
| 7. Lifecycle | **NOT CLOSED** | Twin capture validation exists at `dp:1738`; action timing, cleanup identity and automatic-delay verification remain incomplete. Finding 5. |
| 8. Hashes | **CLOSED** | Required hash syntax/equality at `dp:1380–1385`; terminal `#<scene count>` at `dp:639–654`. |
| 9. Current-take cost | **CLOSED** | Setter publications at `dp:315–317`; exactly one current-window measurement at `dp:1217–1229`. Negative-duration edge remains: finding 10. |
| 10. Fully containing foreground | **CLOSED** | `dp:1617` excludes every recorded later rectangle; `dp:1208–1214` makes an empty mask INCONCLUSIVE. Missing foreground inventory is a separate survivor below. |
| 11. LUT validation | **NOT CLOSED** | Empty/nonfinite samples and per-channel comparisons are fixed, but observed endpoints escape analytic qualification at `dp:847–854`. Finding 6. |
| 12. Eager movie metadata | **CLOSED** | Movies resolve before fields are copied at `dp:797–809`; headless capture also refreshes fields at `dp:2150`. |
| 13. DX-1/CEF profiles | **CLOSED** | Explicit profiles at `dp:1345–1348`, conditional headless checks at `dp:1399`, W3 reuse at `managed_obs_qualify.py:1520`. Report-only aggregation has a separate defect below. |

**Findings and concrete reproductions**

1. **Blocker — CLASS: edge — absent/malformed observation evidence still produces MATCH.**  
   [dp:1358](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1358), `:1252`, `:1535`, `:1607`; [managed_obs_qualify.py:674](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:674).

   Independently reproduced:
   - Delete `videos` from every transition rAF of a valid `m-on`: **overlay PASS, arm MATCH**.
   - Set its decoder tuple to `"malformed"`: **MATCH**.
   - Supply tone layout but omit `foreground` from `m-tone`: **tone PASS, MATCH**.
   - W3’s evidence validator accepts a record with no actual `g2` state and a decoder containing only `err="VideoFrame failed"` instead of a colour tuple: **no missing-evidence reasons**.

   **Exact fix:** require explicit observation inventories and validate their contents before scoring. Distinguish an observed empty list from an absent field; require the foreground inventory for the bound decoder; validate colour-tuple structure and required CEF state. A capture error is diagnostic evidence, not a substitute for the missing measurement.

2. **Blocker — CLASS: closed — incomplete captures still satisfy negative controls.**  
   [dp:1653](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1653), `:1855–1867`.

   Retaining only three suitably separated mid-frame screenshots makes both `m-off` and `m-hold` return **MATCH**, with their expected **FAIL**. The six-mid-frame integrity failure is discarded because only `class …` problems become shared failures.

   Separately, stock `off` screenshots with every post-transition screenshot removed produce:
   ```
   arm=INCONCLUSIVE, problems=[]
   model=FAIL, complement=FAIL, handoff=INCONCLUSIVE
   ```
   The round nevertheless reports **model gate PASS** and **complement gate PASS**. Overall remains INCONCLUSIVE, but the expected failures were counted from an inconclusive run.

   **Exact fix:** propagate all applicable capture-integrity failures to every check, including six-mid-frame coverage. Reject an INCONCLUSIVE control arm before reading any individual result; require its complete expected contract to match.

3. **Major — CLASS: edge — malformed animations disappear before validation.**  
   [dp:1016](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1016).

   In the valid curve helper, set both final-row animations to `ct=None, value=NaN`. The scorer returns **PASS**, counting ten remaining rows. `running_anims()` filters the malformed records away.

   **Exact fix:** validate every supplied transition-animation record before selecting running samples. Legitimate pre-animation absence may be represented explicitly; malformed populated records must yield INCONCLUSIVE.

4. **Major — CLASS: closed — endpoint alpha violations still pass.**  
   [dp:1009](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1009).

   I added valid frames near `e=.01` and `.99`, changed one overlap pixel’s alpha to **100** in the first and one incoming-only pixel’s alpha to **100** in the last. Result:
   ```
   model=True, complement=True, no_dip=True, problems=[]
   ```

   **Exact fix:** evaluate complement and no-dip over every admitted transition frame. Keep the mid-frame restriction for the model check only.

5. **Major — CLASS: edge — lifecycle success does not establish the required scenario.**  
   [dp:1739](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1739), `:1758`, `:1785`; collector `:2050`.

   Three independent survivors:
   - Move a queued/goto action timestamp to `-1_000_000`: lifecycle **MATCH**.
   - Delete `dump.first.layerIds`: cleanup **PASS**, lifecycle **MATCH**. The collector’s empty-ID fallback also cannot identify leaked layers/rules.
   - Extend the pre-animation interval by 500 ms and insert a screenshot containing movie frame **99**, while the frozen reference is **42**: automatic lifecycle **MATCH**, frozen-frame **PASS**. Demixing excludes the delay’s `e=0` samples.

   **Exact fix:** validate action order and placement within the prescribed intervals in both captures; require and bind cleanup to a valid transition-ID inventory; require delay coverage and compare the frozen movie against its reference throughout that interval.

6. **Major — CLASS: edge — LUT qualification ignores observed endpoints.**  
   [dp:847](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:847).

   Paired RGB samples `snapshot=[0,128,255]`, `live=[30,139,220]` return **`kind="analytic"`**, with `observed=[128]`. The endpoint discrepancies of 30 and 35 are ignored.

   **Exact fix:** retain every observed value in provenance and analytic qualification, including 0 and 255. Keep endpoint pinning separate from validating observations; incompatible endpoint measurements must not qualify the analytic curve.

7. **Major — CLASS: new — CEF midpoint timing invents an inside-cut observation.**  
   [managed_obs_qualify.py:705](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:705), `dp:1125`.

   With insertion at `t=0`, completed cut at `t=16`, and three following rAFs, a screenshot request spanning `[-20,36]` becomes `t=8`. Supplying the completed incoming image yields **cut PASS, inside=1**, although it could have been rendered at `t=30`, after completion.

   **Exact fix:** preserve `[t0,t1]` and require the entire capture interval inside the observed cut window, or use an authoritative compositor timestamp. A straddling request alone is INCONCLUSIVE.

8. **Major — CLASS: new — report-only checks still invalidate CEF.**  
   [dp:1691](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1691).

   A synthetic CEF `on` baseline returns MATCH. Removing only its pre-animation rAF leaves **every blocking check PASS**, but `no_flash=INCONCLUSIVE` makes the arm INCONCLUSIVE. Empty tone masks similarly block identity-L arms despite tone being non-blocking there.

   **Exact fix:** retain the diagnostic verdict of report-only checks but exclude it from blocking mismatch/inconclusive aggregation. Shared capture-integrity failures must remain blocking.

9. **Minor — CLASS: edge — W3 trusts contradictory cached calibration.**  
   [managed_obs_qualify.py:1514](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:1514).

   A calibration record containing `n=None`, `model="INCONCLUSIVE"` and thresholds `{tau:4, complement:2, no_dip:252}` receives **calibration check `ok=True`**. This demonstrates a subcheck false-pass, not a complete-round PASS.

   **Exact fix:** rederive thresholds through `dissolve_calibration(n)`, validate the source result and compare stored thresholds with the derived values. Contradictory or malformed calibration must invalidate the gate.

10. **Minor — CLASS: edge — negative take duration passes.**  
    [dp:1227](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1227).

    Changing a valid `m-on` take duration to `-42` still returns **MATCH**.

    **Exact fix:** require a nonnegative finite duration before applying the 50 ms bound; negative durations are malformed evidence.

**W3 against §9.2**

The session manifest, controls-first ordering, opaque-off-first calibration, one-launch integration, shared resolver/driver/scorer, G2-off configuration and environment refusal are present. The calibration formula and caps are correct at `managed_obs_qualify.py:656–663`; the required calibration and environment tests are present at `tests/test_managed_obs_qualify.py:71–94`.

Acceptance remains incomplete because of findings 1, 2 and 7–9. The committed tests cover the formula and refusal, but do not establish these integrated evidence-handling properties.

**The two flagged risks**

- **Pre-animation rAF:** the stricter W2 result is correctly fail-closed. The hook at `dp:358–377` does not establish that a real capture will contain such a sample; live qualification must demonstrate it. Do not restore a vacuous PASS. Finding 8 additionally makes this risk block CEF despite its reporting exemption.
- **Tone mask and `3231B69B`:** credible qualification blocker. The fixture describes that build-frame layer as **960×276**, larger than the colocated **951.54×267.62** movie texture. If the observed DOM rectangles contain the movie, rectangle exclusion removes its tone samples even where the canvas pixels are transparent. Empty → INCONCLUSIVE is correct for blocking tone qualification. Use a tone fixture with verified exposed ramp/patch interiors, or a verified painted-pixel foreground mask; do not count covered pixels to obtain PASS.

The independent standards review found no substantive standards violations. The remaining issues are acceptance and evidence-integrity failures.

**CHANGES REQUIRED.**