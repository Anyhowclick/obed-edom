# MM opacity gates — r1

Plan `.agents/plans/keynote_live_mm_opacity.plan.md` rev 4 (§10). Fixture `output/p2-binary` (main checkout). Evidence under
main checkout `output/evidence/mmo-gates/`. Gate worktree `mmo-gate-p2`, detached at the commit named per row.

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
| MO-6 suites | `f7ecda5d` | | PASS | pytest 7761 passed / 88 skipped / 1 xfailed; test:ui 305/305; test:maps 542 + 2 |
| MO-6 host probe ×3 + P2 ×3, after R5 | `7c20dde4` | default | PASS / as baseline | host V/Voff all True at 3 viewports; P2 fast/slow 14/14; bridge-off red only on its negative check |
| MO-1/4/5 + stand-down, after R5 | `0f6d0380` | off, auto | PASS | output `output/evidence/mmo-gates/probe-0f6d0380/` |

Q0b (scratch, `f6a87ee8`-era bytes) is recorded in the plan §9.

## Managed OBS (owner go 2026-09-25; lossless utvideo; binary fixture)

| Gate | Commit | Verdict | Key numbers |
|---|---|---|---|
| MO-3 MO-1..MO-5 inside CEF (`--arm mmo-cef`) | `66567617` | PASS | every sub-gate PASS in OBS CEF, incl. MO-4 (occludedBands 0 / 20) and the stand-down |
| G2 arm re-run (`--arm g2`, 2 takes @25) | `66567617` | PASS | M0–M4 PASS ×2; M1 mode-keyed stats; M3 via the `mm-off` twin |
| MO-2 before R5 (`--arm mmo`, 25 + 30) | `66567617`, rescored at `67c7d12e` | 25 PASS, 30 FAIL | one frame: first GL frame of the move (30 fps, `g2off-on`) reads (12,87,0), α_eff 0.498 = DOM + GL squares overlapping |
| MO-2 after R5, 5 runs × 25 + 30 | `0f6d0380`, rescored at `67c7d12e` | PASS ×10 | 0 of 30 patch-on sessions over τ (4.57); CvC 0; τ_key 1.15; twins fail R1/R2 and the G2-less R4 KB (180) |

Instrument amendments found live: R2 = neutral-background blend consistency (the white counter crosses under the square; the
empty patch is not empty during the move); τ_key read slide 1's covered patch (113 → 1.15); R4's KB is enforced on the G2-less
twin only (G2's LIVE override makes the g2 patch-off settle key translucent — timing luck, 5/10 takes). Headless overlap probe
for R5 was INCONCLUSIVE (its positive control read 0) and is not evidence; R5 rests on the Node task-order test + MO-2 ×10.
MO-7: final-commit take (`67c7d12e`) 25 + 30 PASS; recordings kept at `qualify-home/recordings/mmo-20260925-143530/` (25) and `mmo-20260925-144012/` (30) — `g2off-on` (fix, no G2) vs `g2off-mmoff` (stock) side by side; owner eyeball done (found the pre-existing build-1 geometry jump below).

## Findings outside this PR

- Managed OBS lifecycle: 1 of 13 launches today ended `stateAfterQuit: stuck` (take `141513`, rate 30); MO-2 content PASS, take FAIL
  on lifecycle. Page content is the only thing this PR changes; not root-caused here.
- Build-1 GL→DOM geometry jump (owner eyeball MO-7): the settled GL frame is ~1.7 % smaller than the DOM layout (square bbox
  (793,677)–(1137,982) → (790,675)–(1140,985)); identical patch on/off × GL replay on/off ⇒ pre-existing. Follow-up session spawned.

## Review

Opus r2 `opus-r2.md`: R5 sound (no blank-frame path); F1 R2 floor 8.0, F3 `--score` keeps validity/lifecycle, F4 colour
premise, F6 test, F7 natspec folded (`f7ecda5d`); F2 re-runs recorded above.
Opus r1 `opus-r1.md`: F1–F11 folded (`60009ce3`, `5178be70`, `102d4ca4`); F5/F11 plan corrections; F8 min/max refuted (rAF
timing), time-interpolated match instead.
