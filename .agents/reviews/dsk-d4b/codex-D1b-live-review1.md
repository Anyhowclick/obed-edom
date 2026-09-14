REVISE

1. **Critical — the alignment transform confuses raw IWA coordinates with Keynote’s live `position`.**  
   `src/obed_edom/dsk_assemble.py:2152`  
   `_autosize_rect` converts the archive’s stored anchor coordinate into a visual-top rect: top → `y`, bottom → `y-h`, middle/default → `y-h/2` (`src/obed_edom/iwa_geometry.py:204`). That does **not** imply the inverse is required when writing through AppleScript. Keynote’s live `position` getter/setter is already the visual top-left for autosize boxes. Therefore adding `h` or `h/2` moves GW44/46/50 downward—the exact class of write-side compensation previously live-probed and reverted.

   The numeral makes the calculation additionally unsound: its `rect.h == 46` is the badge layout cell (`src/obed_edom/dsk_assemble.py:748`), not a measured post-size natural height. The 28.4pt size is written only afterward (`src/obed_edom/dsk_assemble.py:2165`), so `rect.h/2` is neither the source-height nor a guaranteed rendered-height correction.

   **Fix:** retain raw-height-zero detection and the `plan.autosize` height skip, but remove `cluster_align` and always write `{rect.x, rect.y}`. Prefer applying width/text size before the final position write so the final operation explicitly restores the planned visual top.

2. **Major — the refit writer does not apply the claimed transform.**  
   `src/obed_edom/dsk_assemble.py:2411`  
   `_build_refit_round` rewrites cluster members using visual-top rects (`src/obed_edom/dsk_assemble.py:3397`), but `build_refit_script` writes `rect.y` directly and never consults `plan.cluster_align`. Thus the initial assembly applies the compensation once, while a later cluster refit overwrites it with an uncompensated position. The plan’s claim that emission transforms the refitted rect afterward is false because refits use this separate emitter.

   **Fix:** removing the incorrect transform per finding 1 makes both paths consistently use visual-top coordinates. If compensation were retained, it would need one shared positioning helper used by both emitters.

3. **Major — none of the three tests exercises the position behavior being introduced.**  
   `tests/test_dsk_assemble.py:8280`  
   The autosize test only checks that a position line exists; it never checks its value. The fixed-frame test checks only height emission, and the real-deck test checks only autosize classification. Consequently all three pass whether middle alignment writes `rect.y`, `rect.y+h/2`, or an arbitrary coordinate, and none covers top/bottom/default alignment or refit consistency.

   **Fix:** assert exact emitted y values, with the expected invariant that every alignment writes the planned visual-top `rect.y`. Add a regression that builds a cluster refit and verifies `build_refit_script` preserves that same y. The existing tests are useful and non-tautological for raw-autosize detection and height suppression, but they do not validate the risky part of this patch.