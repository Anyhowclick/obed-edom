# C3 review r4 (2026-10-16) — major/blocker only

Diff: `1a421de2..aef4d4ae` (the r3 closing rule). Reviewers: two Opus 5.5 high lenses, acceptance and tests/mutation (32
mutants). All findings were executed (`/private/tmp/claude-501/c3-review/r4a/`, `r4t/`). Suites (single process): paint 159,
contract 133, probe 1900, OBS 208 + 1 skipped, detach 118, all passing.

| # | Sev | Finding | Fold |
|---|---|---|---|
| F1/M1 | major | A cold prefix ending on the first after-cut row or on a busy source row gives True on pins (OLD False). The never-decoded guard is bounded by `firstAfterT` | Bound by `lastBeforeT`; a non-empty prefix must end on a settled pre-crossing source row, else None |
| F2 | major | Decoded while hidden on the previous slide, then visible and undecoded at entry, is excused as a cold start (OLD False → True) | Any earlier decode ends prefix eligibility |
| F3 | major | GL interval with no decoder in the window: paint "no pre/post GL segment" turns OLD False into None | Base-window GL segments when no decoder is chosen |
| F4 | major | `sourceSceneFallback` exceeds the stated union (multi-scene build rows scored; None → True/False) | Delete it |
| M2/M3 | major | The never-decoded guard's conditions and the prefix visibility condition are unpinned (mutants → False → True) | Fixture rows |
| M4 | major | Deleted dark-source paint test was the only pin on paint over the union rows | Restore it |

Clean: candidate selection; forced seek/force-wrap; loop wraps; poster hold; restart at entry; GL replacement; `entryColdStart`
report-only; `nextSceneId` captured and contract-checked; the three r2 weakenings are reverted.
