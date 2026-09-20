## BLOCKER

None.

## MAJOR

- **Movie identity and pool ownership become stale when an element is assigned another asset.** [live_continuity_js.py:1343](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:1343) and [live_continuity_js.py:1399](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:1399) update `__obedMovieKey` only when the new source matches a planned movie; they never clear it for an unplanned source, nor remove the element from its old pool queue. A movie1 decoder pooled under `untitled.mov` can be reassigned to WA0125—which is now deliberately absent from the plan—yet remain stamped and queued as movie1. The retire sweep then selects it by the old pool key at [live_continuity_js.py:994](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:994) and pauses/removes the now-WA0125 element. Even assignment to another planned asset remains vulnerable because the pool branch ignores the updated stamp. Every non-empty assignment must retire/update stale pool membership and clear the stamp when no plan key resolves.

- **The frozen-composite clause can accept a dead or transiently blank post-flip instrument.** [p2_recovery_html_adversarial.py:1039](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/p2_recovery_html_adversarial.py:1039) requires only four low-MAE after-pairs and earlier motion. If the movie is visibly live before the flip but the dense post-flip captures become an all-black or otherwise dead static ROI, `beforeOk=True` plus four zero MAEs passes. The settled slide-2 screenshot can recover afterward, so the other settled-image findings need not expose the transient blank. This proves stillness, not that the still surface is the expected poster. It needs post-flip content validity or comparison with the settled/raw poster. Additionally, “forward” is not strictly enforced at [p2_recovery_html_adversarial.py:1141](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/p2_recovery_html_adversarial.py:1141): `#5 -> #2` satisfies the current expression.

- **The pool census loses exactly the stamped identity needed after a real source clear.** `snapshot()` records DOM-preserved entries using only the live source at [live_continuity_js.py:152](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:152), while [p2_recovery_html_adversarial.py:998](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/p2_recovery_html_adversarial.py:998) silently ignores entries whose key cannot be mapped. A target decoder consumed from the pool before the retire zone, then genuinely cleared inside it, can remain as `data-obed-preserved` with snapshot key `""`. If hidden, it also escapes the painting check; the census reports zero target entries and `neverPooledEvidence` can pass. Snapshot should expose `movieKeyFor(v, src)`/`__obedMovieKey`, and an unattributable preserved entry should invalidate the census rather than be ignored.

## MINOR

- **Malformed-shape conversion to `Unsupported` remains incomplete.** [live_continuity.py:325](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity.py:325) calls `list()` on an unchecked `affineTransform`, and [live_continuity.py:330](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity.py:330) assumes `anchorPoint` is a dictionary. `affineTransform=None` or `anchorPoint=[]` therefore raises `TypeError`/`AttributeError`; `derive_plan()` catches only `_Refuse`. Also, `contentsRect.width = NaN` passes [live_continuity.py:384](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity.py:384), because comparison with NaN is false and Python’s JSON decoder accepts `NaN` by default. These should fail closed.

## Verified sound

- The subtree walk now reaches every dictionary, classifies it by its holding key, refuses objects under unmeasured containers, rejects unknown and mask-like keys, and validates ordinary finite `contentsRect` shapes and `masksToBounds`.
- The measured-vocabulary tests pin both the fixture and available real export, preventing accidental refusal from an incomplete table.
- For an element whose asset has not changed, stamped identity correctly survives `src=""`; remount guards use it, the pool sweep uses its own key, and DOM victims use `movieKeyFor`.
- The carry census counts the full in-page event log before slicing and fails closed when its top-level result is absent.
- A genuine no-flip scorer result lacks the required after-pair data and fails; the after-pair slice excludes the crossing pair and enforces the four-pair minimum.
- The injected P2 plan now matches the derived runtime plan in full and names only movie1.
- Ordinary numeric slot geometry failures are converted to `Unsupported`.

Static review only; no tests, browsers, edits, or scripts were run.

**VERDICT: FAIL**