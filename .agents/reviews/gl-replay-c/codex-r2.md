## Spec / correctness

1. **CLOSED** — `scripts/p2_recovery_html_adversarial.py:696–712`  
   Rejects boolean dimensions/pixels, validates byte ranges, catches conversion failures, recomputes alpha, and requires computed and reported minima to equal 255.

2. **CLOSED** — `src/obed_edom/p2_verdict.py:1060–1089`  
   Delta now requires clean metadata and non-boolean integer counters in `[0,255]`. Failed, missing, malformed metadata and invalid counters have known-bad coverage.

3. **CLOSED** — `scripts/p2_recovery_html_adversarial.py:455–463`  
   Oracle lookup and probe validation are inside `try`; both throwing oracle and probe getters return `reason: 'threw'`.

4. **CLOSED** — `tests/test_live_gl_replay_js.py:575–582,784–820,2719–2740`  
   The fake models `UNPACK_FLIP_Y_WEBGL` for TexImageSource uploads. The asymmetric test verifies the movie and poster have matching upright orientation.

## New correctness bugs

None found in `2af57a2d..bef57a23`.

## Standards

No findings. The changes are localized, match surrounding style, and `git diff --check` is clean.

Reported validation: 274 live-GL tests passed; 855 P2 tests passed.

**Summary:** 4/4 findings closed; 0 new correctness findings; 0 standards findings.