Verdict: `FAIL`

r10 closure: MAJOR 1, 3, and 4 are closed. MAJOR 2 remains partial. MAJOR 5 fixed the indexed-path/AND mechanics, but the allowlist still misclassifies scored evidence.

## BLOCKER

None.

## MAJOR

1. [tests/test_p2_adversarial.py:4525](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4525), [tests/test_p2_adversarial.py:4713](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4713), [scripts/p2_recovery_html_adversarial.py:3549](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3549) — **(b), same positional-absence class as r10 MAJOR 5 and r7/r8 raw-sample findings.** The sweep calls positive `indexSamples[*].index` outside the flip window “diagnostic,” but `score_composited_index_run` consumes the entire at-cut segment. A pre-flip reset at position 5 makes the positive red; deleting only that `index` makes it green again. MAIN similarly allowlists every `index`/`sceneHash`/`progress`: a bad settled index makes progression red, but deleting that sample’s `sceneHash` removes it from the settled window and restores green.

   Entries that should fail closed: positive `indexSamples[*].index` throughout `atCutBoundary.from..releaseSplitIndex`; MAIN post-split candidate `indexSamples[*].index`, `sceneHash`, and `progress`.

   Smallest sound fix: schema-gate key presence separately from value validity before selecting/scoring windows. Explicit `index=None` may remain admissible where intended; an absent key may not. Remove these entries from the blanket allowlist and classify only genuinely out-of-window positions as partial.

2. [scripts/p2_recovery_html_adversarial.py:1810](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1810), [scripts/p2_recovery_html_adversarial.py:2057](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2057), [tests/test_p2_adversarial.py:4356](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4356), [tests/test_p2_adversarial.py:4430](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4430) — **(b), same incomplete-evidence class as r10 MAJOR 2.** The prefix reasons say these fields are “not read,” but continuity directly reads them. Missing fields can erase the only ambiguous owner, transient handoff, or rVFC rewind while redundant healthy samples keep PASS.

   Entries that should fail closed in their scored positions:

   - `ownerSamples[*].sceneHash`, `decoderId`, `ownerAmbiguous`
   - `mediaSamples[*].sceneHash`, `videos`
   - the bound video’s `videos[*].decoderId` and `presentedMediaTime`

   Smallest sound fix: validate per-sample schemas before continuity scoring, allowing explicit null only where the model permits it; require a finite bound-decoder observation for each after-window media sample and reject conflicting duplicates. Individually classify only unrelated video/pool fields as diagnostic.

3. [scripts/p2_recovery_html_adversarial.py:4394](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4394), [tests/test_p2_adversarial.py:4297](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4297) — **(b), same r10 MAJOR 2 bridge-evidence class.** `_bridge_engaged` validates the detail but never requires `kind == "bridge-3to4"`. Replacing the fixture event’s kind with `"reuse-decoder"` still yields bracket PASS. Thus deletion of `bridgeEvents[*].kind` should fail closed.

   Smallest sound fix: require the exact event kind before examining its detail and remove the `kind` allowlist entries.

4. [scripts/p2_recovery_html_adversarial.py:4497](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4497), [tests/test_p2_adversarial.py:4981](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4981) — **(b), same cached-sub-verdict class as r10 MAJOR 2.** MAIN still accepts `owner_settle={"settled": True, "readings":[]}`. It likewise accepts `settle={"exact": True, "hashAtAdvance":"#6","expected":"#7"}`. The MAIN sweep passes synthetic one-Boolean dictionaries rather than walking these actual arguments.

   Concrete failure: binding during residual/pre-`#7` motion can retain stale `settled=True`/`exact=True`; `_advance_c_ok` stays green despite absent or moving readings.

   Smallest sound fix: call `_owner_settle_ok(owner_settle)` and derive the advance settle from `hashAtAdvance`/`expected`; include both real argument dictionaries in the MAIN sweep.

5. [scripts/p2_recovery_html_adversarial.py:4211](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4211), [tests/test_p2_adversarial.py:4308](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4308) — **(b), same cached-sub-verdict class as r10 MAJOR 2.** `footprintFullyLive.ok` remains a material fail-open. Setting `verdict=False`, `status="fail"`, and `perRect[0].verdict=False` while leaving `ok=True` still produces bracket PASS.

   Under the current summary-only design, deletion of at least `n`, top-level `verdict`, `noiseFloor.verdict`, every `perRect[*].verdict`, and `stray.verdict` should fail closed through agreement checks. That only provides internal consistency, not pixel re-derivation.

   A digest alone is insufficient: it authenticates unavailable bytes but cannot reproduce the verdict. The burst PNGs are not strictly required. The smallest sound capture-side evidence is the lossless uint8 maximum-delta raster used by `score_visible_slide`, stored as one grayscale PNG or compressed byte array, together with frame count, dimensions, rectangles, and scoring parameters. Recompute coverage, bands, noise, and strays from that raster and require agreement with the cached result. Retaining and hash-verifying all burst PNGs is also sound but larger.

## MINOR

1. [tests/test_p2_adversarial.py:4903](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4903) — **(c), test-harness hygiene.** Both positive arguments are copied from fixture `a1`; committed `a2` is never scored or walked. Value-dependent load-bearing positions in the real A2 snapshot can therefore be missed.

   Smallest fix: load and walk the actual `a1` and `a2` snapshots independently.

2. [scripts/p2_recovery_html_adversarial.py:4707](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4707), [scripts/p2_recovery_html_adversarial.py:4832](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4832) — **(b), same class as r10 MINOR 1.** New production comments continue embedding review history and failure narratives despite the minimal-comment rule.

   Smallest fix: retain concise invariants and leave the review rationale in plan §10.15.

The runtime edit at [live_continuity_js.py:1478](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/src/obed_edom/live_continuity_js.py:1478) is additive only: it reads two existing generation values into the diagnostic note payload. It changes the runtime hash and event shape, but no presenter branch, decoder choice, bridge behavior, DOM mutation, or timing control flow.