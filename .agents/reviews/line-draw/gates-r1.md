# Line Draw: gate record r1 (2026-10-13)

Plan `.agents/plans/keynote_live_line_draw.plan.md` rev 6, with owner decisions in §4.

**Roster:**
- Plan: written by the coordinator (Opus 5.5) and critiqued by Codex GPT-6 Astra high (r1–r3).
- Implementation: Codex GPT-5.6 Sol high.
- Code review: Opus 5.5 high (r1, r2).

Deck: owner's `Alpha_DSK.key`, slide 2. The export is a read-only copy of
`s2-followups-dsk-deck-902af1/output/.html-preview/7e3c9301…-p3-r1`.

| Gate | Result |
|---|---|
| Origin | Slide 2's chain: `LineDraw` (Rounded Rectangle, Clockwise, Ease In & Out, 0.8 s), then `LineDrawForLine` (Connection Line, Start to End, Include endpoints, 0.7 s), then the label Dissolve (1.0 s). The export bakes both Line Draws as `opacity 0→1`. The stock and patched-off players fade them identically on every output. |
| Calibration | Head symmetric difference: Chrome 155 = 31, CEF 127 = 39. `X` = 48. |
| Headless gate (Chrome 155) | Probe runs `g4` (full) and `g5` (destroy). PASS: `on`, `hold-p1`, `hide-show`, `destroy`, `busy`. Controls hold: `off` fails reveal, head-static fails hand-back, and the diamond tail (diff 124) and paired protrusions (127) are refused. `neighbour` is INCONCLUSIVE, because Chrome 155 gets no snap grant (`unqualified-version`). |
| Keyer (managed OBS 32.2.2, CEF 127) | GetSourceScreenshot sheets. At `X` = 38 the arrow faded (diff 39 refused); at `X` = 48 the box and arrow both draw. The probe's own `keyer` arm was not run, so this gate rests on the screenshot sheets and the owner's eye. |
| Owner's eye | Chrome frames: "looks correct". Keyer frames: "looks good". The arrowhead pose is an eye gate (owner decision §4). |
| Suites | 10807 passed, 0 failed (3.12 and the 3.10 floor) on the pre-rebase head `4b5d16d7`. **Pending (owner: 2026-10-14):** both suites and the full headless gate on the rebased head over #269 (mm-fade). `test_live_runtime.py` is 176/176 there. |

**Known limits and deviations:**
- The body reveal allowance is 2 frames + 4 %. On the box it measured 0.045, against the plan's one-frame bar of 0.021.
- Held `p = 1` is within 1 LSB: 8 anti-aliased arrow pixels are off by 1.
- The automated arrowhead pose check was removed, because it cannot separate a 2 px / 3° offset at the headless capture
  size.
