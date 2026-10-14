## Standards

No blocker/major findings.

## Spec

1. **Major — edge case** — [live_continuity_js.py:1479](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_continuity_js.py:1479)

   The `-contents` suffix does not guarantee object identity. Keynote gives an animation-free child of an opacity action-build the full wrapper chain, including `contents`, even when that child is a group containing multiple authored objects. A grouped movie and coincident sibling can therefore export as:

   `canvas(movie) > layerA > layerGroup-contents`  
   `canvas(sibling) > layerB > layerGroup-contents`

   `objectOf()` treats them as one object and selects the later sibling. G2 hand-back at line 725 can then report a successful remount into the wrong object; `bindFacade()` at line 1901 can remove a valid stub and hold at the root. `shared-plain-wrapper-refuses` misses this because the defeating group wrapper genuinely ends in `-contents`.

   **Exact fix:** “Capture the destination video’s authored layer when Keynote actually appends it: in `bindFacade`’s rehomed MutationObserver, stamp `real.__obedLayer = nearestLayer(stub.parentElement)` before removing the stub and reschedule remount; likewise record added G2 destination stubs keyed by `GL.dst.objectId`. Remove suffix-only tie acceptance and accept only a unique stamped-layer match; without one, retain ambiguity and retire/hold. Add nested action-build-group tests for ordinary remount, G2 hand-back, and `bindFacade`.”

No blocker findings. No other major findings.