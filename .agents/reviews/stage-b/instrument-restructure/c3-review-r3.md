# C3 review r3 (2026-10-16)

Diff: `1a421de2..fab64229` (r2 fold). Reviewers: two Opus 5.5 high lenses (acceptance/semantics; tests/mutation/plan
conformance). Executed repros: `/private/tmp/claude-501/c3-review/r3a/`, `r3t/` (fixtures `fx/`, `fx2/`, 26 mutants).
Suites (single process): paint 159, contract 133, probe 1906, OBS 208 + 1 skipped, detach 118, all passing; 3.10 compile OK.

## Class verdict
Rounds 1–3 kept finding the same class: the r1/r2 start, source-range, visibility and replacement heuristics exclude rows that
the old code scored, beyond the carried decoder's initial cold start. The r3 findings in this class:
- A1: the predecessor is visible later in the arm (False → True);
- A2/T2: a hidden pre-mounted successor (False → True);
- A3: a visible overlap hides the replacement (False → True);
- A4/T5: decoded but unpainted at entry is excluded (False → True; owner-call shaped);
- A5: unreadable visibility (None → True);
- A6: element reuse with a new src (True → False);
- T1: decode loss across the whole source (False → None), masked by a weakened r2 test;
- T4: decoded, then absent at entry (False → True).

The r2 fold also weakened three tests: the prior-decode-loss fixture and threshold, TestFold5 entry absence, and
TestCarryPaintWiring offscreen.

Per the review stop rule (fix by class), the coordinator replaces the heuristics with one conservative rule (r3 fold):
**the window start is the pre-C3 (1a421de2) start; for the chosen carried decoder it advances only past an unambiguous
initial cold-start prefix**: the consecutive rows from that start on which the decoder is present, connected, has a
readable non-zero rect and a finite readyState < 2, and has never been decoded before (naming the spec asset). Any doubt
ends the prefix, so the old scoring applies. Acceptance: NEW == OLD on every repro and fixture except
(a) the initial cold-start prefix,
(b) GL-excused absence inside an evidenced interval,
(c) never-decoded → None, and
(d) the planned decode-loss red after the start.

Other r3 items folded with it:
- A7/T3: the visible-undecoded report is always 0 on schema 2;
- A8: misleading "never decoded" reason;
- T6: surviving mutants (reach fixture length, GL count, predecessor rules — deleted with the heuristics);
- T7: false docstrings and names;
- T8: re-derived source scene, dead branches.

A9 (a lingering previous decoder on a restart at entry) matches the old behaviour: not a regression, recorded only.

## r3 fold (closing rule), as implemented
- Base window = the exact pre-C3 legacy window (crossing, grounding, forced floor, chain clip; force-wrap without clip).
  Candidate selection is unchanged on it.
- Shared start for legacy checks AND paint = min(legacy start, old `paint_start`). That is the UNION of what the two old
  checks scored. Only the chosen decoder's initial cold-start prefix is then skipped: present, connected, readable non-zero
  rect, readyState < 2, never decoded while visible before.
- Integrity reach extends back to the shared start. Never decoded → None.
- The heuristics are deleted: source range, decodedStarts, visibility, replacement. Net −194 lines.
- Acceptance on every reviewer repro and fixture: NEW == OLD except
  (a) cold-start prefix, (b) GL-excused absence, (d) decode loss after the start, and
  (e) union start (stricter: rows newly scored, e.g. hidden-premount True → False).
- Real captures: 95 fresh verdicts with 4 changes, all (b); Alpha C1-matrix artifact 2 changes, both (b); stored attempt-3
  replay 0 changed.
- The three weakened r2 tests are reverted.
