# Looping movies (`loopMode`) gates r2 — rebased on main + managed OBS (2026-09-25)

Supersedes the verdict of `gates-r1.md` (kept for the r1 history and the harness defects it found). Branch
`claude/continuity-loopmode` rebased onto main `8fe3b551` (#229, OD-2 managed-OBS GL replay + binary counter).

**Verdict:** L0, L1, L2, L4 and L5 PASS. Residuals below.

## Provenance
- Gate worktrees `.claude/worktrees/loop-gate-pr` (`3ee7b345`, then `bda4a537` for the L5 soak re-run) and
  `.claude/worktrees/loop-gate-main` (`8fe3b551`), clean, fixture symlink to main-checkout `output/p2-recovery`.
  One headless Chrome or one managed OBS at a time; no Keynote. Core `e9338aff…` unchanged.
- Fixtures, both built by `scripts/loop_fixture.py` with the same splice (objectIDs `6BB39942`, `CBACAF27`, `F9AFED1B`,
  `98D59E27`, `E4728E7D`; plan shas off `3dc67558…`, on `2ba6fbed…`, sources proven unchanged):
  - `output/p2-loop` from `output/p2-binary` (binary counter `947f8944…`, 1381 frames; `fixture.json` + `loop`,
    `verify_fixture` passes) — L2, L5.
  - `output/p2-loop-grey` from `output/p2-recovery/html-adversarial` (grey counter) — L1. The binary movie's static
    grey regions fail Vgl's all-bands-move in-page oracle (125/128 bands); the non-looping `p2-binary` fails
    identically and the grey loop build passes 128/128, so the headless visible pass needs the grey movie.
- Evidence (git-ignored): main checkout `output/loop-gates/` — `l4-r2-{pr,main}.txt`, `l1r2/`, `l1r3-grey/`, `l2r3/`,
  `diag2/`, `l5/`; drivers `l1.sh`, `l1-grey.sh`, `l2.sh`.

## Results

| Gate | Verdict | Numbers |
|---|---|---|
| L0 unit | PASS | Full suite at `cfc61c13` (final): 7767 passed / 88 skipped / 1 xfailed; `test:ui` 305/305; `test:maps` 542 + 2 |
| L4 P2 regression | PASS | `run_gates.sh` at `3ee7b345` line-for-line identical to `8fe3b551` (host ×3, P2 fast/slow 14/14, `--disable-bridge34` red only on the 3→4 bridge) |
| L1 host on `p2-loop-grey` | PASS | 3 viewports + take 2 pass, V/Voff 4/4; `--gl-replay auto` Vgl 4/4. KB: `8fe3b551` exits 1 |
| L2 on `p2-loop` (`3ee7b345`) | PASS | 3→4 6/6 carried; 1→2 4/6 carried, 2 INVALID (wrap +115/+211 ms late); KBs FAIL ("no wrap was recorded"); rescore CvC vs `8fe3b551` host artifacts identical |
| L5 pre-check (managed OBS 32.2.2, rate 25) | PASS | (a) loop keys == splice, `video.loop` on both slide-1 instances and on the handed-back carried element; (b) qualified + injected on product code (no splice); (c) 2 wraps LIVE, no stand-down, uploads ≈ 30/s. 131 s |
| L5 re-run on the Codex r4 fold (`184cb3bd`) | PASS | pre-check incl. the hand-back read (G2 `RETIRED`, one `handoff` release of the element); re-scored offline with `cfc61c13`'s nested-release check: PASS (module and runtime release and element all `elId` 1). Soak 5 min: LIVE 29.98–30.0/s, windows 1 and 2 one wrap each, `maxWrapStep` 4, context loss retired, P3/P4 == off |
| L5 soak, 5 min (`bda4a537`) | PASS | LIVE 29.6–29.9 uploads/s each minute; windows at minutes 1 and 2 each 1 wrap, 0 backward, `maxWrapStep` 4; loseContext → contextLost stand-down, zone retired; P3/P4 == off twin. 345 s |

## Wrap rule (owner option 1, 2026-09-25)
The first soak (`3ee7b345`) failed window 1: 1380 → 3 across the loop point scored as a backward step under the
two-sided `WRAP_TOL = 2`. The element's own rVFC clock in 40 headless wraps shows Chrome's `video.loop` seek skipping
0/1/2 frames 16/20/4 times (50–133 ms presentation gap); the 30 → 25 capture step adds up to 2. `bda4a537`: a wrap
may advance at most `WRAP_TOL + LOOP_SEEK_SKIP` = 4 frames through the loop point; larger skips and mid-period jumps
stay backward; `maxWrapStep` is reported.

## Residuals
- All four OBS soak wraps (two runs) read `maxWrapStep` 4 — at the bound every time. A 3-frame browser loop-seek skip (not yet seen in 40 headless
  wraps) would fail the soak; that would be a finding, not a reason to widen further.
- 1→2 forced-wrap takes are INVALID in ≈ 1/3 of takes (≈ 200 ms decoder gap ~300 ms after the press when the loop
  point is within ≈ 2 s), below `MAX_STALL_S`; see `gates-r1.md`.

## Reviews
Codex (gpt-5.6-sol) r4 on `e57a6be9`: 1 high (negative `wrap_step` on an out-of-range binary read) + 5 medium/low folded
(`184cb3bd`); r5: every fold closed except the nested module-release identity, folded in `cfc61c13`.
