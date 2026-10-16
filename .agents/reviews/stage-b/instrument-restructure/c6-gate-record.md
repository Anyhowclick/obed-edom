# C6 gate record: one arm-scoring interface (2026-10-15)

Commit `ad2bd89f` on `claude/stage-b-arch`. Plan r3 §2.
Implementers: Codex GPT-5.6 Sol high (stream P = probe + detach; stream O = managed OBS). Stream F found no contract change was needed.
Reviewer: Opus 5.5 high (workflow lenses, each finding adversarially verified by Opus 5.5 high).

| Round | Confirmed | Refuted | Status |
|---|---|---|---|
| r1 | 25 (several duplicated across lenses; 12 distinct items) | 0 | folded |
| r2 | 6 | 0 | folded |
| r3 | 2 (1 medium, 1 low) | 0 | folded 2026-10-16 |
| r4 | 0 major/blocker | — | closing round; loop stopped |

Review records: `c6-review-r1.md` through `c6-review-r4.md`.

**r3 fold (2026-10-16).** `score_arm` no longer coerces missing or malformed sample rows to `[]`. A non-list value, or a list with a non-dict row, now returns `_contract_inconclusive` for every spec id. It carries the contract's own `rows:list`/`row:object` errors, skips the summaries and `score_verdicts`, and adds no `sampleRows` key. The capture's own copy of the raw value is kept. The coordinator dropped Sol's `result["samples"] = samples` line so the uncopied capture list never aliases into the result. Tests: the rescore known-bad test is parametrized with a non-dict row, and groundTruth is kept. The environment test gains an owned "for Testing" descendant and an absent-getpid case. Sol's mutation checks: reverting the fix fails the new case; `owned = 0` fails the environment test.

## Tests
Coordinator rerun on the committed tree, `test_live_continuity_probe.py` + `test_detach_experiment.py` + `test_managed_obs_qualify.py`:
**2203 passed, 1 skipped** (the optional real-recording fixture). After the r3 fold (`-n 2`): **2204 passed, 1 skipped**. The full suites (3.12, 3.10 floor) are not yet run; plan gate 6a.

## Offline replay (plan gate 1)
This replays the 10 stored attempt-3 sessions through `score_arm`: Alpha ×2, D7 ×6, D7s ×2 (`q7-attempt3/*/runs/feed-*.json`).

- **Comparable outcomes:** 60. 48 reproduced, 12 became unknown, 0 contrary, 0 fabricated successes.
- **The 12 unknowns** all fail with `evidence contract: rows:schema at samples (sampler schema None)`. The stored OBS sessions have no `sampler` key because the pre-C6 writer hard-coded schema 2, so this is genuinely missing evidence.
  - The 12: Alpha feed and feed-off b3to4/b4to5, D7 feed-off b2to3 a/b in each of three runs, and D7s feed-off b1to2 a/b.
- **Null control:** supplying sampler schema 2 to `score_arm` gives exactly the same 12 differences from the stored verdicts as `score_verdicts` at `d898f445`.
- "0 contrary / 0 fabricated" does not cover those 12.
- **For C3's "no later failure disappears" review:** pre-C6 drift since capture head 03a35b28 is:
  - Alpha feed b3to4 False → True;
  - three Alpha feed verdicts None → False;
  - eight D7/D7s feed-off carries False → None ("handbackContinuity unreadable").
- **Closed (r3 medium, folded 2026-10-16):** malformed stored sample rows are now contract-rejected on replay. r4 checked 16 replay variants; every one gives `ok=False`, `contractRejected=4`.

Still unproven, and needs fresh capture: complete OBS parity, and both Alpha `b8to9 …->end:retire` verdicts readable in each session (plan gate 11).
