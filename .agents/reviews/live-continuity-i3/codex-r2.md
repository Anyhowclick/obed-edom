## Findings

- **BLOCKER:** None.
- **MAJOR:** None.
- **MINOR:** None.

## Verified sound

- Non-ready partial installs are disabled and confirmed; failure to confirm raises `LiveHostError` ([live_host.py:797](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_host.py:797)).
- The startup-only `disable()` contract is coherent. `everPreserved` flips immediately after pooling and before further preservation side effects; pre-stash disable is pass-through, while post-stash disable is refused ([live_continuity_js.py:68](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:68), [live_continuity_js.py:384](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:384)).
- A stash during startup polling is reachable for an auto-advancing first slide. Turning a subsequent gate failure into `LiveHostError` is correct: preservation has already affected teardown, so raw fallback cannot be proven safe.
- The remount invalid-origin heuristic now uses the live stage origin. Authored-footprint fallback refuses a missing map, and in-stage authored writes also refuse it ([live_continuity_js.py:872](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py:872)).
- `stageFit` now requires at least one valid sample, zero mismatches, and zero invalid samples across the entire arm ([live_continuity_probe.py:460](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/live_continuity_probe.py:460)).
- Tests meaningfully cover partial-install disabling, pre/post-stash behavior, live-origin fallback, null-map refusal, scaled/letterboxed mapping, and an invalid stage-map sample outside all boundary windows.
- The probe converts its measured screen rect to authored coordinates before calling the authored-input ownership API.
- No gate or existing threshold was weakened.

I did not re-run pytest because this read-only environment has no writable temporary directory; no browser was launched and no files were changed.

**Overall verdict: PASS**