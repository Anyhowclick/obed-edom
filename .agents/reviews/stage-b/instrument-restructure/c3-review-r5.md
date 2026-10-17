# C3 review r5 (2026-10-16) — major/blocker only

Diff: `1a421de2..c5a9354c` (r4 fold). Reviewers: two Opus 5.5 high lenses, acceptance and tests/mutation (46 mutants). All
findings were executed (`/private/tmp/claude-501/c3-review/r5a/`, `r5t/`). Suites (single process): paint 159, contract 133,
probe 1907, OBS 208 + 1 skipped, detach 118, all passing. The r4 repros all give their folded results; no test was weakened.

| # | Sev | Finding | Fold |
|---|---|---|---|
| A-F1 | major | The r4 settled-row check is too strict: real cold starts mostly end on busy entry rows (71/75 in stored and fresh captures). A clean cut carry goes True → None | Require some settled source row in [start, lastBeforeT] on which the decoder is decoded |
| T-M2 | major | The never-decoded guard's rect requirement contradicts F2. Decoded-hidden on the settled source, then blank-visible to the cut: OLD False → None | A hidden decode on a settled source row counts |
| T-M1 | major | The F4 removal is unpinned: restoring the fallback passes every test (r4 a3 M0 None → True) | Fixture row |

Out of scope (medium, theoretical; no hidden video observation exists in the real corpus):
- F2 over-corrects a hidden-preload-then-visible-cold-entry (OLD True → False, stricter);
- a decoder decoded but zero-rect on every pre-cut row goes False → None;
- `decodeloss_verdict_off` survives (paint-off captures only).
