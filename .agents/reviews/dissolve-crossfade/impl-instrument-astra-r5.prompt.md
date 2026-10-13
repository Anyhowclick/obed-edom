NON-INTERACTIVE. Do not propose a plan or ask for approval; produce the review directly.

Round 5 (major/blocker only) of the dissolve qualification-instrument review. Round 4 (`.agents/reviews/dissolve-crossfade/impl-instrument-astra-r4.md`) APPROVED f8058937. Live DX-2 then showed the r3 fold was too strict: the mode-off (STOCK player) controls opaque-off, off and cut-off animate only the outgoing leaf with the incoming leaf at 1, so their legitimate pre-start rAF gap starts at leaf_effs [1, 1] and `leaf_effs(a) == [0.0, 1.0]` rejected it (false INCONCLUSIVE; calibration invalid). Commit under review: `git show 9c00e529` (scripts/dissolve_probe.py `raf_gaps` + tests/test_dissolve_probe.py): the exemption is now `not started and pending(b) and leaf_effs(a) is not None and leaf_effs(a) == leaf_effs(b)` — nothing changed during the gap. Offline re-score of the saved live DX-2 run with 9c00e529: calibration n 0.66 PASS; opaque-off/off/cut-off/noblend/on2/cut-on/opaque-on/cef-skip/cef-skip-dsk MATCH; `on` INCONCLUSIVE only for capture coverage (4 mid frames < 5).

Question: does 9c00e529 reopen Astra r3's class (a pre-start gap hiding an outgoing or incoming dip) or create any other false pass / weakened control in DX-1 or DX-2? Consider what `pending(b)` does and does not check for an unanimated leaf.

Owner rules: report ONLY blocker and major findings with a concrete scenario (inputs -> wrong verdict) and the exact smallest fix; ignore medium and below; no scope creep. If none, say so; that ends the loop. Do NOT run pytest or start browsers; small python checks are fine.

Output: findings (severity, file:line, scenario, exact fix), classify each (new class / closed class / edge case); one-line verdict: APPROVE or CHANGES REQUIRED.
