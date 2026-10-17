# C3 review r2 (2026-10-16)

Diff: `1a421de2..307f7068` (r1 fold). Reviewers: two Opus 5.5 high lenses (acceptance/window semantics;
tests/quality/performance). Every finding comes with an executed old-vs-new repro (`/private/tmp/claude-501/c3-review/r2a/`,
`r2t/`). Suites (single-process): paint 159, contract 133, probe 1901, OBS 208 + 1 skipped, detach 118, all passing.

| # | Sev | Class | Finding | Fold |
|---|---|---|---|---|
| A1/T1 | blocker | new (from the r1 fold) | Predecessor/start rules use any decoded observation. A deliberate restart at slide entry, or a second same-asset decoder on the source, becomes `replacedFrom` and turns the carried decoder's initial cold start red (True → False) | Mount rules use VISIBLE presence on the source |
| A2 | major | new | A hidden pre-mounted/preloaded decode counts as "first decode" (True → False); `entryColdStart` misreports it | First decode = decoded AND visible |
| A3 | medium | edge | A predecessor that is hidden but still listed escapes the replacement rule (False → True) | Survival judged on visible observations |
| A4/T2 | medium | closed class, incomplete | Integrity reach still uses `(transition or at) - 1`, so multi-scene source rows skip the duplicate/unnamed/unidentified/phase checks | Reach covers the whole window |
| A5 | low | — | IdleAtInitialState reason fires on transition-less carries | Guard |
| A6/T4 | low | — | Force-wrap still reports `chainClip`; three `untilScene` pops | One rule in `carry_window` |
| T3 | medium | gap | Mutants survive: predecessor survival, force-wrap no-clip, GL decode-loss exemption, the exact `glExcusedMissing` count | Test rows |
| T4 | low | closed | Dead clauses and fields; a docstring that no longer holds; inconsistent "decoded" (videoWidth) | Clean up |

Checked clean: the GL excuse cannot hide a destroyed or restarted decoder (a new element gets a new probe id); real
replacement, later decode loss and never-decoded behave as intended; `entryColdStart` is report-only; performance
(20k rows: `read_phases` 0.06 s, `carry_window` 0.03 s, `score_continuity` 0.6 s).
