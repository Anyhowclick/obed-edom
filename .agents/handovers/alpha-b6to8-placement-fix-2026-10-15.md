# Handover: Alpha b6to7/b7to8 placement fix: folded solution (2026-10-15)

Owner go (2026-10-15): "handover the alpha placement solution to the diagnostic peer to orchestrate the fix once folded". Plan Q3 is answered as fix before Q7.

Method:
1. Blind Opus 5.5 and Fable peers investigated independently, without the earlier diagnosis (`e5f25d9f`, branch `claude/friendly-stonebraker-16d950`).
2. A neutral synthesizer combined the three.
3. Both peers critiqued the combination: Fable "no change", Opus removed one duplicated check.
4. A final fold produced the proposal below. Full JSON (blind reports, combination, critiques) is in the coordinator's session scratchpad and not kept.


## Convergence verdict

The two blind peers (Opus and Fable) and the earlier diagnosis (e5f25d9f) reached the same conclusions independently. They agree on the mechanism, the wrong canvases picked (CF6BC171, F86E3188, 45AAEB5D), the correct anchor (Z: C01CA56A or B75EFA5A), and why b5to6 and D7 escape (b5to6: 0.575 vs 1.0; D7: exact tie). They agree the bug predates the hand-back work (core 00b9a823 behaves the same). They differed only on how to pick the anchor. The own-layer rule was adopted, and both peers then approved it ("no change" from Fable; Opus only removed a duplicated check).

## Root cause

`findMovieCanvas` (live_continuity_js.py:1675-1712) ranks canvases by distance to the integer-rounded plan rect. The movie's own layer only breaks exact ties.

1. **At the carry.** The synchronous remount sees two canvases at distance 0: the old node `a` (`layerNNN-isPlaying`) and G's hidden leaf. Z is not in the DOM yet, so the result is ambiguous and the decoder goes to body#body. This happens on every under-artwork carry and is normally repaired in the same task.
2. **The repair fails on slides 8–9.** The stub observer asks for the stub's layer, but the integer-sized hidden leaf is uniquely nearest (0 vs about 1.08 for Z's fractional geometry). The stamp is refused and the observer disconnects.
   - The decoder stays on #body. That is the frame-2 #body read, and it is when the one-shot settledArtwork read gives artworkAbove False.
3. **Settled state.** The +50 ms retry and every later one pick the hidden leaf. The decoder lands inside a visibility:hidden leaf, under the opaque Z (alpha 255).
   - For a facade stub, Z is never removed (`hideMoviePoster` runs only on handleMovieDidStart), so the owner sees a still poster.

## Fix (src/obed_edom/live_continuity_js.py)

```diff
-   * authored parent, so we can't walk up from the video itself. Requires a
-   * UNIQUE best match: collect every canvas within tolerance, rank by
-   * geometric distance, and break ties by the video's own authored layer
-   * (outgoing vs incoming MM), then DOM order (incoming layer is later).
+   * authored parent, so we can't walk up from the video itself. Collects
+   * every canvas within tolerance: the only one inside the video's own
+   * authored layer wins; otherwise requires a UNIQUE best match by geometric
+   * distance, exact ties broken by that layer.
@@
     if (!candidates.length) return null;
+    const own = v && v.__obedLayer
+      ? candidates.filter((c) => nearestLayer(c.c.parentElement) === v.__obedLayer) : [];
+    if (own.length === 1) return own[0].c;
     const minDist = ...
     const tied = ...
     if (tied.length === 1) return tied[0].c;
     // Distance tie: try to resolve by the video's own authored layer.
-    const layerMatches = tied.filter(
-      (c) => v && v.__obedLayer && nearestLayer(c.c.parentElement) === v.__obedLayer
-    );
+    const layerMatches = tied.filter((c) => own.indexOf(c) >= 0);
```

The two versions behave identically, because `tied` and `own` are filtered from the same `candidates` objects.

**Test** (tests/test_live_continuity_js.py:4298):
- Add the row `("pin", "stub-layer-rounded")` with id `pin-rounded-canvases`.
- For that row only, the overlay rect is offset by `+0.41, +0.19, +0.25, -0.24`.
- `landed` and `stamped == "layer97"` are true for `stub-layer` and `stub-layer-rounded`.
- Add `assert result["ambiguous"] == 0` for this row. Here the poster is the unique nearest canvas at carry time, so the unit model does not reach the #body fallback.
- On HEAD the row is red (landed False, stamped None). With the fix it is green.

**Re-pin the new `js_sha256()`** at tests/test_live_continuity_js.py:34, tests/test_live_host.py:1781 and scripts/detach_experiment.py:76. That file has another session's uncommitted edits, so coordinate with that session. test_detach_experiment.py:156 fails loudly if a pin is missed. The probe derives its value automatically. No variant or trace transform anchors in this function.

## Risks

1. **Callers whose `__obedLayer` is still connected now get their layer's single canvas, even when a nearer canvas exists elsewhere.** Affected paths: the dom-swap stamp (:2146), GL `releaseArmed` (:726) and the GL branch of bindFacade (:2111).
   - The stash path (:1105) is narrower than first stated. It records the layer only while `v.parentNode` is set. A detach-triggered stash records a detached layer, which never matches a candidate.
   - The remaining case: a decoder removed on its own keeps a stale but connected layer. On a near-stationary next carry it could anchor after the source Z until the observer re-stamps it. This has not been seen on any deck.
   - The rule never turns a pick into null, so it cannot add a #body painter.
2. **The carry-time #body fallback and the one-refusal observer disconnect remain.** Both predate this fix. They are harmless only while the player inserts the stub in the same task. Follow-up: hold in place for under-artwork holds.
3. **The fixed core has not run yet.** The settled position matches fix2's A/B, which used a different rule.
4. **The instrument cannot see Z.** A pass also needs the pixel check below.
5. **A sub-pixel poster edge is possible.** The decoder sits on the integer rect above Z's fractional rect, the same as slide 7 today.

## Proof route

Run heavy jobs one at a time, after the f4 measurement, on Chrome 155. Record `browserVersion` and `output.continuity.sha256` for every run.

1. **Unit.** The new row is red on 302c218d and green on the fix. The other five rows are unchanged. Run the full suites on 3.12 and the 3.10 floor, including test_live_gl_replay_js, test_detach_experiment and test_live_host.
2. **Headless A/B on Alpha/html-player, feed on AND feed off.** The owner's feed-off session showed the defect too.
   - Template: repro/run_dbg.py with the DOM recorder, stacks at +0.2/+1.2 s and a late read at about +2.5 s.
   - Arm A is 302c218d; arm B is the fixed core. Both use the same fixture, plan c9e54655…, feed SHA and instrument patch.
   - **Arm A (positive control), each b6to7 and b7to8 carry:** pin-rehome, then ambiguous (2 candidates), then remount-done, with no second pin-rehome. A wrong canvas is picked about 50 ms later, and body#body rows appear.
   - **Arm B:**
     - The same first three events. Ambiguous ×4 and remount-done ×4 are expected, so compare the event signature, not counts against fix2.
     - Then a second pin-rehome within 2 ms, and before the next row a `remount-into-authored-layer` on C01CA56A (elId 4) or B75EFA5A (elId 7).
     - Every later retry, including the hashchange +80/+400 ms retries at scenes 13 and 15, picks the same canvas with `v.previousSibling === Z`.
     - No body#body rows after any carry.
     - Hand-back frames read inStage, not onBody, and afterCanvas.
     - artworkAbove is True.
     - The hit stack shows the video above Z.
     - A pixel sample over 10 frames changes in arm B and is frozen in arm A.
   - **Scoring.** Score on `handbackContinuity`, `artworkAbove` and the raw events. Do not use the top-level carry verdicts: they are False in every arm because of atScene and noRider issues unrelated to this fix.
   - **Null controls, identical in both arms:**
     - the b3to4, b4to5 and b5to6 event trails;
     - `noRiderAboveCanvas` and `labelsOverFeed`;
     - the b8to9 retire verdicts (True);
     - onBody rows (9,4), (10,4) and (13,7).
3. **D7, D7 feed-off and D7s.**
   - The C700B07C sequence and the verdicts are unchanged.
   - The red controls are each still red for their own reason: departure-early-hide, interim-delay, no-linger, overlay-ride and d7-unrepaired.
   - Run the GL-replay gate once, and the D2/D5 slide-3 legacy pin probes. These cover the :2146 path.
4. **Served bytes.** Only the continuity SHA changes; the plan, mmFeed, glReplay and detach SERVED SHAs stay the same. `git diff` touches only the function, the test row and the three pins.
5. **Owner decision before Q7 attempt 4.** In every arm, decoders still ride on body#body during the scene-9 and scene-13 transitions, and noRider is False for b5to6 and b7to8-wa0121. This fix does not cover that. Either resolve it first with the open 03a35b28 vs HEAD A/B, or warn the owner. Then the owner checks by eye: labels stay on top and the video keeps moving on slides 8–9.