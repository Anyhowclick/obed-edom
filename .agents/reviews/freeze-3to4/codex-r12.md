Verdict: `FAIL`

## BLOCKER

None.

## MAJOR

1. [scripts/p2_recovery_html_adversarial.py:4323](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4323), [scripts/p2_recovery_html_adversarial.py:4362](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4362) — **(b), r11 MAJOR 5’s retained-evidence class.** The raster is re-scored but not bound to its arm or the fixed capture contract. Pure scorer probes showed PASS after:

   - replacing B’s evidence with A1’s raster;
   - changing both cached/evidence frame counts from 12 to 2;
   - padding and re-encoding the raster as 1921×1081;
   - replacing it with an all-zero raster while weakening its self-described parameters.

   Only Boolean verdicts and labels are compared, so the committed A1/B numeric differences such as `liveFrac` and `maxDelta` are ignored. A stale green raster can therefore hide a dead B burst.

   Smallest sound fix: require canonical dimensions, frame count, rectangles, control rectangle, and parameters; compare the complete re-derived result with the cached result; bind evidence to an independently retained arm/capture ID. If deliberate forgery is in scope, retain the burst frames and recompute the delta—self-described metadata cannot authenticate its provenance.

2. [scripts/p2_recovery_html_adversarial.py:4444](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4444), [src/obed_edom/html_alpha_probe.py:1334](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/html_alpha_probe.py:1334), [src/obed_edom/html_alpha_probe.py:1520](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/html_alpha_probe.py:1520) — **(b), r11 MAJOR 1’s positional-sample-evidence class.** A positive arm still reaches bracket PASS with `index=None` at positions 1–13 of its 24-sample at-cut segment. Null-adjacent deltas become `None` and are omitted from progress/anomaly totals, so that interval can conceal a reset or freeze.

   Smallest sound fix: permit only a narrowly identified acquisition miss, then fail closed on a consecutive null run or any unexplained null inside the positive at-cut and MAIN settled windows.

3. [scripts/p2_recovery_html_adversarial.py:4451](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4451), [scripts/p2_recovery_html_adversarial.py:1920](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1920) — **(b), r11 MAJOR 2’s incomplete-owner-evidence class.** B still reaches PASS with the first 24 of 80 after-window `decoderId` readings set consecutively to `None`; `nonNullFrac == 0.700` satisfies the majority gate. A replacement decoder can own the footprint during that blind interval while the bound decoder’s offscreen rVFC clock continues.

   Smallest sound fix: bound consecutive null-owner runs independently of the aggregate 70% threshold, require matching owner identities immediately around each admitted gap, and attest that no competing decoder owns/overlaps the footprint during it.

## MINOR

1. [scripts/p2_recovery_html_adversarial.py:1640](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1640) — **(c), edge-case robustness.** Ordinary malformed/truncated PNGs and declared-shape mismatches return `None`, but decoding is not fully fail-closed: a decompression-bomb header raises uncaught `Image.DecompressionBombError`. `"png-gray"` also accepts any Pillow-readable L-mode format.

   Smallest fix: require `img.format == "PNG"`, enforce the expected dimensions/pixel limit before loading, use a context manager, and catch Pillow decompression/decode exceptions.

2. [scripts/p2_recovery_html_adversarial.py:4486](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4486) — **(b), r11 MAJOR 2’s schema class.** “Exactly one” bound-decoder clock is implemented as a set. Two duplicate entries with the same `presentedMediaTime` collapse to one and bracket PASS.

   Smallest fix: collect matching finite observations in a list and require `len(matches) == 1`.

3. [tests/test_p2_adversarial.py:3902](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:3902) — **(c), harness provenance.** Yes, the capture artifact should emit and persist `advanceSettle`. Production passes the real `_settle_at_advance_hash` result and includes it in report detail, but the harness reconstructs it from bracket-only `drain.hashAtArm`; its “real arguments” sweep therefore does not exercise a captured MAIN block.

   Smallest fix: persist the actual `settle_c` object in the MAIN fixture/artifact and load it directly.

4. [scripts/p2_recovery_html_adversarial.py:4969](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4969), [scripts/p2_recovery_html_adversarial.py:5100](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:5100) — **(b), r11 MINOR 2 / r10 MINOR 1.** Review-history narratives remain in production comments. The minor is still open.

   Smallest fix: retain concise behavioral contracts and move review history to the plan.

5. [tests/test_p2_adversarial.py:4613](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4613), [tests/test_p2_adversarial.py:4760](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4760) — **(c), duplicated-code hygiene.** The positive allowlist is copied for A2. Future drift can classify identical evidence differently despite independent walks.

   Smallest fix: define the positive path-to-reason map once and generate the A1/A2 class-keyed entries.

## r11 disposition

- MAJOR 1–2: missing-key deletion is closed; the explicit-null paths leave both findings partial.
- MAJOR 3: closed.
- MAJOR 4: production derivation closed; capture-fixture provenance remains partial.
- MAJOR 5: not closed.
- MINOR 1: closed.
- MINOR 2: open.

The remaining risk is **not edge-case-only**.