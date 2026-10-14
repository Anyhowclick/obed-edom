# MM fade gates — r1

Plan `.agents/plans/keynote_live_mm_opacity_fade.plan.md` rev 5 (§3). Fixture: a scratch copy of the G4 Alpha_DSK export
(identical to `output/fixtures/alpha-dsk-textures`), plus a scratch copy whose 7→8 slot-4 leaf carries slide 6's real short
fade-out encoding (the only edit). KB arm: a detached checkout of `main` at `ad6dac98`. Evidence, with the scratch drivers
under `probes/`: main checkout `output/evidence/mm-fade-gates/`.

Implementer: Codex GPT-5.6 Sol high. Reviewer: Opus 5.5 high. r1: changes requested, folded in `c0628297`. r2: approve, four lows; three folded, the optional probe-signature test skipped (minimal-tests rule).

## Results

| Gate | Commit | Verdict | Key numbers |
|---|---|---|---|
| PF-0 Node behavioural | `c0628297` | PASS | extracted `setupTexture` path; fade-in, short fade-out and partial at explicit samples; four refusals stay at today's value; mirror agrees |
| PF-1 headless Opacity, 7→8 fade-in | `c0628297` | PASS | max \|fix − 0.6118 × today\| 0.0006 over 88 frames (limit 0.002); settle pixel α_eff 0.6112 (0.612 ± 0.003); slot 6 constant 0.6118; KB today 0.388 off; fixed vs fixed 0.0005 |
| PF-1, derived fade-out | `c0628297` | PASS | onset 0.609 (today 0.998); ramp max error 0.0007; both settle 0 |
| PF-1, 6→7 fade-in | `c0628297` | PASS | max error 0.0004; today ramps to 0.9985 |
| PF-2(a) incremental census | `c0628297` | PASS | changed set exactly {6→7/3, 7→8/4, 7→8/8}; stock-vs-today expectations unchanged; 0 shimmer/sparkle. Opus r1's independent JS census agrees (every differing sample ×0.61177), re-confirmed by r2 on `c0628297` |
| PF-2(b) `mm_opacity_probe` | `c0628297` + probe fix | PASS | MO-1, MO-4, MO-4 stand-down, MO-5 (GL off and auto) |
| PF-2(b) `mm_handback_probe` | `c0628297` + probe fix | PASS | HB-1 at 1920 / 2560 / 1600: on 0.0 / 0.018 / 0.005 px (KB off 2.78 / 3.74 / 2.42), CvC 0; HB-2 PASS |
| PF-2(c) continuity on | `c0628297` | PASS | continuity `qualified`; slot 4 ramps to 0.611; hand-back frames keep the box translucent (`pf2c-handback.png`) |
| PF-3 suites | `c0628297` | PASS | 3.10 floor is the fixture-linked full run: 10819 passed / 36 skipped / 1 xfailed; 3.12 ran before the fixtures were linked: 10770 / 85 / 1; test:ui 321/321; test:maps 542 + 2. The touched files re-ran green on `a9a02773` (973) and after the r2 fold |
| PF-4 owner eyeball | `05476093` | PASS (owner, 2026-10-13) | Chrome screen output, 6→7 and 7→8: "opacity's fixed" |
| PF-4b owner eyeball, fade-out | | deferred | after the owner authors the Q-deck (non-blocking) |

## Notes

- `mm_opacity_probe.py` and `mm_handback_probe.py` still called `prepare_export` with the pre-isolation 3-argument
  signature (`8176e06a`). Both were broken on `main`. Fixed in this branch (owner go): each passes its own `run_root`.
