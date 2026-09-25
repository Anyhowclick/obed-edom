# MM opacity gates — r1

Plan `.agents/plans/keynote_live_mm_opacity.plan.md` rev 4 (§10). Fixture `output/p2-binary` (main checkout). Evidence under
main checkout `output/mmo-gates/`. Gate worktree `mmo-gate-p2`, detached at the commit named per row.

## Headless (blocking)

| Gate | Commit | GL replay | Verdict | Key numbers |
|---|---|---|---|---|
| MO-1 uniform + settle blend | `102d4ca4` | off, auto | PASS | 90 slot-4 draws α (+94 LIVE draws, auto); settle max\|P−E\| 0.50 / 0.48; KB patch-off 179.9, α² 53.1 FAIL |
| MO-4 G2 interplay | `102d4ca4` | auto | PASS | on: unproven `[{4, rest-opacity}]`, rest `[1,0,1,1,α]`, occludedBands 0; off: `[]`, `[1,0,1,1,1]`, 20; LIVE green (8.9, 51.6, 0) on = off; α² FAIL |
| MO-4 stand-down | `102d4ca4` | auto | PASS | forced `frameLengthChanged` stand-down replays slot 4 at α; KB `fsdoff` reads 1 |
| MO-5 blast radius | `102d4ca4` | off, auto | PASS | 3→4 settle hash on = off = off2; 1→2 (movie masked) differs on vs off |
| MO-6 host probe ×3 viewports | `01a9ff55` | default | PASS | A/B/C/attach as baseline; V and Voff all slides True |
| MO-6 P2 fast / slow | `01a9ff55` | default | PASS 14/14 | patch exercised in the GL arm only (non-GL arms run `--disable-gpu`: no WebGL; Opus r1 F3) |
| MO-6 P2 bridge-off | `01a9ff55` | default | expected red | only `continueThroughMovingMagicMove3to4` False (the negative arm) |
| MO-6 suites | `102d4ca4` | | PASS | pytest 7744 passed / 88 skipped / 1 xfailed; test:ui 305/305; test:maps 542 + 2 |

Q0b (scratch, `f6a87ee8`-era bytes) is recorded in the plan §9.

## Managed OBS (pending owner go)

- MO-2 `--arm mmo` (rates 25, 30; per-rate CvC), MO-3 `--arm mmo-cef`, `g2` arm re-run (M1 stats incl. CEF occludedBands, M3 via
  `mm-off` twin, enforced g2-off T alpha).
- MO-7 owner eyeball.

## Review

Opus r1 `opus-r1.md`: F1–F11 folded (`60009ce3`, `5178be70`, `102d4ca4`); F5/F11 plan corrections; F8 min/max refuted (rAF
timing), time-interpolated match instead.
