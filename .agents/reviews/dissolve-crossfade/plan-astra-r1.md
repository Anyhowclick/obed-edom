# Plan critique r1 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 1 \`8e572864\`. Prompt: `plan-astra-r1.prompt.md`.

1. **Major · New class — §§3.1–3.2, 7: fade and blend do not fail together.**  
   **Claim:** exceptions leave stock behavior, and blending is “all-or-nothing.”  
   **Evidence:** D2 commits the mirrored animation before D3 installs styles. D3 silently ignores missing nodes and exceptions; unsupported CSS values also need not throw. Running the proposed methods with missing DOM nodes left `obedDissolve=true`, incoming opacity `0`, and the mirror animation installed. That produces the rejected double-fade if blending fails.  
   **Recommended wording:** “Preflight required CSS support before copying the tree. If blend installation fails, restore the stock transition before removing the outgoing DOM, or refuse explicitly. Never continue with mirrored opacity alone. Add unsupported-style and missing-node cases to the parametrized behavioral test.”

2. **Major · New class — §§3.1, 6.1, 10: D1 necessarily fails existing tests.**  
   **Claim:** no replacement contains an anchor; existing generic tests need no changes.  
   **Evidence:** D1’s replacement explicitly retains its entire 75-byte original anchor. Existing assertions require that anchor to disappear: [test_live_runtime.py:205](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:205), lines 265 and 367. The scratch `overlap.py` excludes self-pairs with `n1 != n2`, explaining the missed conflict.  
   **Recommended wording:** “Choose a D1 replacement head that consumes its original anchor instead of reproducing it verbatim. Preserve the existing zero-original-anchor assertions. Check replacement containment against every anchor, including its own.”

3. **Major · New class — §§2, 6.2, 9.1, 13: S2 masking excludes part of the owner’s requested result.**  
   **Claim:** placing held video outside the isolated group preserves the required cross-fade; its appearance can be assigned to S2.  
   **Evidence:** at `origin/claude/s2-detach-fix` (`d88584eb`), `live_continuity_js.py:758–763` deliberately preserves a held decoder through Dissolve; lines 1759–1777 remount it visibly at opacity `1`; lines 2158–2169 defer retirement until the fresh movie starts. Isolation prevents additive contamination, but does not make that independently painted video participate in `(1−e)·P_out + e·P_in`. Masking its rectangle removes precisely that failure from scoring.  
   **Recommended wording:** “DX-1’s masked model proves texture-group correctness only. Add an unmasked media-overlap and hand-off check for S2. Resolve whether held movies must participate in the normal cross-fade; recommended: they must. Whole-slide equivalence remains unproven until that integration passes.”

4. **Major · New class — §9.1: the control-arm integrity rules contradict their expected outcomes.**  
   **Claim:** opaque controls PASS; `noblend` produces a scored FAIL; integrity failures are INCONCLUSIVE.  
   **Evidence:** lines 358–361 require every class to contain 2,000 pixels and the served SHA to equal the pinned output for its mode. Fully opaque controls necessarily have empty incoming-only, outgoing-only, and empty classes. `noblend` necessarily differs from the production “on” SHA. The explicit class exemption names D2 only.  
   **Recommended wording:** “Define required pixel classes, applicable checks, expected styles, and expected digest per arm. Opaque controls require overlap and report complement N/A. The `noblend` arm verifies the production base digest, exactly one counted splice, and its derived variant digest. INCONCLUSIVE must never satisfy an expected FAIL.”

5. **Major · New class — §9.2: CEF qualification lacks independent controls and bounded calibration.**  
   **Claim:** `on`, `on2`, and stock `off` sufficiently qualify the previously untested OBS compositor.  
   **Evidence:** stock `off` demonstrates pop-in but normally passes no-dip; it cannot validate that check. There is no CEF `noblend` negative control or opaque positive control. The proposed take-derived thresholds have no exact calculation or maximum admissible value. Chrome support does not establish correctness of OBS’s off-screen compositor.  
   **Recommended wording:** “Run opaque positive and `noblend` negative controls inside CEF as well as `off`. Specify the calibration formula and hard upper bounds before capture; excessive calibration noise is INCONCLUSIVE. Require each blocking check’s designated negative control to FAIL and positive control to PASS.”

6. **Major · Edge case — §§3.3, 9.1, 10: acceptance can miss the pre-animation flash and does not exercise lifecycle claims.**  
   **Claim:** the timing-free complement check cannot miss pop-in, and all creation/cleanup paths have been rechecked.  
   **Evidence:** six screenshots across a 1.5-second fade cannot exclude a one-frame flash. The planned rAF log records animations, but before attachment there is no incoming opacity animation to inspect. The proposed Node test exercises only the tree-copy helper. The player has distinct queue/skip/back paths around `17c0c938` byte 2349242, plus delayed rendering/animation at 2356319; these are not exercised by the acceptance matrix.  
   **Recommended wording:** “Record effective leaf opacity from DOM insertion, including frames with no attached animation. Add a controlled render-to-animate delay and require incoming opacity zero throughout it. Reuse one parametrized browser scenario for replay, queued advance/skip, interruption/back or jump, automatic delay, loop, and end-of-show; verify final pixels and removal of old DOM/keyframes. Add wrong-curve and non-monotone scorer negatives.”

7. **Major · New class — §§2, 9.0–9.1: the ‘opaque/HDMI’ controls do not test HDMI or the advertised one-LSB bound.**  
   **Claim:** `opaque-on/off` validate screen output and equivalence within one LSB.  
   **Evidence:** §9.1 keeps the alpha attach driver and changes only the PDF overlay. The real screen path uses different page/hide behavior in [live_host.py:418](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_host.py:418). Separately allowing each arm four LSB model error does not establish one-LSB on/off equivalence. Q0 explicitly did not run opaque controls.  
   **Recommended wording:** “Rename these arms ‘opaque-texture controls.’ Add a black-page/screen-path check with fill-less textures, comparing RGB against the cross-fade composited over black. Compare opaque-texture on/off results at matched eased progress. Treat the one-LSB browser bound as unproven until measured; retain the exact algebraic equivalence separately.”

8. **Major · Closed class — §§6.2, 9.4: an existing OBS regression arm is omitted.**  
   **Claim:** no existing managed-OBS session crosses 2→3.  
   **Evidence:** [managed_obs_qualify.py:611](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:611) delegates `mmo-cef` to `mm_opacity_probe.drive`; [mm_opacity_probe.py:100](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/mm_opacity_probe.py:100) explicitly includes `d23` before `mm34`. The regression list names `mmo` and `g2`, but omits `mmo-cef`.  
   **Recommended wording:** “Existing `mmo-cef` traverses the changed dissolve and must be rerun, including its existing control matrix and downstream 3→4 checks. Keep `EXPECTED_STATS` unchanged unless an independently diagnosed change warrants otherwise.”

9. **Minor · New class — §§9.1–9.2, 11: fixture resolution needs an explicit shared contract.**  
   **Claim:** promoting the evidence driver and overlaying stripped PDFs is sufficient.  
   **Evidence:** the evidence’s `dissolve_ab.py:14` explicitly substitutes H.264 movies because the original HEVC movies do not decode headless. Its resolver uses `html-player` media. Meanwhile [managed_obs_qualify.py:299](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/managed_obs_qualify.py:299) copies existing `html-player` PDFs, so cherry-picking the strip function alone does not correct those already-generated assets.  
   **Recommended wording:** “W2 defines one read-only resolver: stock index/player/JSON, fresh scratch PDFs derived from unmodified PDFs using the corrected stripper, and explicitly mapped decode-compatible movies. W3 uses the same scratch PDF overlay rather than existing stripped PDFs. Record asset provenance and verify required movies decode.”

10. **Minor · Edge case — §§2, 3.2, 10: the predicate does not enforce the proof’s geometry and media assumptions.**  
    **Claim:** matched trees contain only texture canvases with identity transforms, so flattening cannot move pixels.  
    **Evidence:** the predicate checks topology and opacity, but not video flags or the relevant geometry. Executing it against a valid export modified with `isVideoLayer=true`, nonidentity 3D transform, or nonzero rotation accepted all three. CSS grouping properties do force flattening, making those assumptions material. [CSS Transforms §7.1](https://drafts.csswg.org/css-transforms-2/#grouping-property-values)  
    **Recommended wording:** “Enumerate and enforce the media/geometry conditions needed by the compositing proof, or supply evidence for the broader accepted shapes. Add those near-misses to the existing parametrized helper test; unsupported shapes retain stock behavior.”

11. **Minor · Edge case — §§1.3, 9.3, 12: the real-deck null requirement may be impossible.**  
    **Claim:** the selected production DSK deck must visibly pop in with the patch off.  
    **Evidence:** §1.3 explicitly says production export transparency is unverified. A forced Dissolve does not establish fill-less outgoing pixels or incoming-only coverage. A black-filled production export should correctly show no stock pop-in.  
    **Recommended wording:** “Before the owner session, verify the selected transition’s outgoing transparency and incoming-only coverage. Use an affected production transition for the required null reproduction. A non-reproducing opaque production deck is a regression control, not a failed or successful pop-in demonstration. Report separate candidate/null results and the served mode/SHA.”

12. **Nit · Closed class — §5: the build census total is wrong.**  
    **Claim:** the listed per-object CSS builds total 263.  
    **Evidence:** rerunning the read-only census reproduced 48 `apple:dissolve character`, 167 `apple:movie-start`, and 167 `renderMovie`: **382** total.  
    **Recommended wording:** “Replace 263 with 382; retain the explicit distinction between surveyed fixtures and unmeasured transition families.”

Verified claims to preserve:

- Both stock SHA identities and the cited patch offsets match. D1–D3 occur exactly once, their byte intervals are disjoint from R1–R8 and the hook, all six group orders produce identical bytes, and both patched players pass `node --check`.
- Dissolve uses the CSS base-layer route; the outgoing-only fade, separate render/animate tasks, and `EaseInEaseOut` mapping are correctly identified.
- The isolated additive arithmetic is correct under its stated preconditions. The specification explicitly describes this cross-fade use. [Compositing §9.1.15](https://drafts.csswg.org/compositing-2/#porterduffcompositingoperators_plus_lighter)
- Full-resolution rescoring reproduced approximately **1.34 LSB** GPU residual, **2.71 LSB** software residual, **206.56 LSB** stock error, and **64.03 LSB** double-fade error. The software take remains exploratory: four mid frames and starting load 4.98 violate DX-1 integrity.
- Chrome 100 support is documented; the installed OBS framework plist reports CEF 127. These establish feature availability, not completed CEF qualification. [Chrome release summary](https://web.dev/blog/web-platform-03-2022)
- Existing switch precedence, three-output pin shape, unchanged off bytes, `output.mmOpacity`, runtime version 2, preview patching, and stock paint-oracle separation are consistent.
- W1–W4 file ownership is disjoint. W0 changes the stripper and its test; no proposed product patch requires modifying `main.js` or writing fixtures.

**Verdict: needs another planning pass.**