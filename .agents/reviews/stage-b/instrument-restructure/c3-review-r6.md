# C3 review r6 (2026-10-16) — major/blocker only

Diff: `1a421de2..a1ab25e5` (r5 fold). Reviewer: one Opus 5.5 high lens, acceptance plus mutation (43 mutants, scenario
battery). All findings executed (`/private/tmp/claude-501/c3-review/r6/`). Suites (single process): paint 159, contract 133,
probe 1910, all passing.

Acceptance:
- All r4/r5 repros give their folded results.
- An independent rescore of the fresh captures (95 verdicts) shows 4 changes, all class (b) GL.
- The Alpha C1-matrix shows 2 changes, class (b): OLD's misses lie entirely inside `glInterval`, drop 0.
- Stored replay: 0 changed.
- Corpus scan: 29,912 visible-decoded and 127 visible-cold observations, zero hidden observations.

| # | Sev | Finding | Fold |
|---|---|---|---|
| F1 | major (r5 T-M2 class, theoretical) | A hidden decode on busy source-scene entry rows does not count in `carried_decoded`. OLD False → None | Drop `busy is False` from the hidden clause only; pin with one row |

Out of scope: a decoder decoded but disconnected on every pre-cut row goes False → None (class (c), predates r5,
theoretical).
