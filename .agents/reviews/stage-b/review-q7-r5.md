## Standards

- **Major — edge case** — [live_continuity_js.py:1878](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_continuity_js.py:1878): The observer is neither scoped to its carry nor validates that the stub’s first layer is the movie’s authored layer. A delayed old stub—or one appended and removed before observer delivery—can arrive after a newer carry, overwrite `real.__obedLayer`, and remount into an obsolete/incorrect tied layer. `keepThroughPin`/`keepThroughBridge` only defer the remount; the stale stamp survives.

  **Exact fix:** Store a per-real facade token/observer, invalidate and disconnect it on each new `bindFacade`, and require the captured token or `real.__obedHold` to still match before stamping. Accept the layer only when it uniquely matches a same-rect canvas candidate for the current destination. Add delayed-old-stub and temporary-parent regression tests.

## Spec

- **Major — edge case** — Same lifecycle defect: the new stamp can select an old or temporary layer, reintroducing the labels-under-movie failure for chained carries.

No blocker findings. No other major findings. `findMovieCanvas`, G2 hand-back, and non-rehomed `bindFacade` remain unchanged.