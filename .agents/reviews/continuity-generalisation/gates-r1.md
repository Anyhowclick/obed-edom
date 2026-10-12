# S2 (continuity generalisation): gate record

Plan: `.agents/plans/keynote_live_continuity_generalisation.plan.md` §3.4 (the ONE re-qualification). Branch
`claude/s2-detach-fix`. Every final gate ran at code **`ecf1b553`** from the detached gate worktree `gate-v-ecf1b553`
(fixtures resolve via `fixture()` to the main checkout). Core: `CONTINUITY_VERSION` 6, sha `a9e1e66a…48be0`; GL replay
v1 `10a5b36a…5288`. `main` comparison worktree at `1589d096`. Reviews: GPT-6 Astra (high). Evidence (git-ignored, main
checkout): `output/evidence/s2-dev/instr-v-ecf1b553/final/` (C1, retakes, phaseD, Q6) and
`output/evidence/s2-dev/instr-v-8bdaf582/final/` (V2b, serial, V5; scorer-only difference to `ecf1b553`, re-scored
offline with the `ecf1b553` scorer).

## Result: PASS (owner Q7 on D1–D6; `run_gates.sh` → `DONE tier=full failed=0 pending=0`)

| Q | Gate | Result |
|---|---|---|
| Q1 | Full suites at `ecf1b553` | 3.12: 10498 passed / 11 skipped / 2 xfailed / 0 failed; 3.10 floor (probe, paint, run_gates files): 2080 passed |
| Q2 | P2 oracle in `run_gates` (fast, slow, `--gl-replay auto`) + reds | 15/15 each; reds exact |
| Q2 | Phase D3: P2 `main` vs S2 interleaved (fast, slow, auto) | 15/15 on all six runs; identical tables |
| Q3 | Host probe A/B/C + attach + V/Voff/Vgl at 2560×1440, 1600×1000, 1920×1080 | pass ×3 (`run_gates`) |
| Q3 | Registered reds (strip per action type, `wrong-instance`, `fifo-reuse`, `stash-any`, `no-pin-hold` D2/D3/D5, V4 moved sets) | every arm exact (`run_gates`) |
| Q3 | Pass G on P2 + D1–D6 | pass ×7 in `run_gates`; serial re-run pass ×7 |
| Q3 | Deck sweep D1–D6 × 3 viewports + P2 full (V5) | 19/19 pass |
| Q3 | Paint controls, carry-cover green/red/null (P2, D1) | as registered |
| Q4 | G2 seam: Vgl host (auto) + `--gl-force-fail` ×4 | pass; `forced-ok` ×4 |
| Q5 | Loop L1 host on `p2-loop` ×3 viewports + auto | pass ×4 |
| Q5 | Loop L2 force-wrap (`p2-loop`, 1to2 / 3to4 × 6 offsets) + KB | 3to4 6/6 pass; 1to2 −200/0/750/1125/1700 pass; 1to2 @375 INVALID ×4 ¹; `kb-1to2`, `kb-3to4` FAIL as required |
| Q6 | Managed OBS `both`, `g2`, `failsafe`, `soak` (4 min, looping) at 25 and 30 | 8/8 PASS; lifecycle clean every launch |
| Q6 | KB `frozen`, `oldbytes`, `latelost` (g2, 25) | frozen caught ×2; oldbytes caught ×2; latelost caught ×2 but take INVALID ² |
| Q7 | Owner, real OBS 32.2.2: Q7a external attach D1 + D4; Q7b dashboard Keyer D1–D6 | PASS (no stray, no visible restart where carried) ³ |

¹ The take lands its wrap ~535–586 ms after the press, outside 375 ± 100 (same at Stage 3 and in the original
`loop-gates/l2`). Invalid = retake, never a pass or a fail; every neighbouring offset passes. Harness scheduling limit.
² Once `latelost` kills the movie, the take-validity read (media time at slide2-after) has nothing to read. Identical on
`main` (`Q6/main-kb-latelost/`); the targeted M4 check fails as required.
³ Seen and accepted by the owner: D4 S1→S2 the non-carried movie fades out on frame 0 (the export bakes the clip's
opening frame into the transition texture — dissolve patch F3); D6 S4→S5 is the designed `retire` (refused mismatch):
the export player starts the movie fresh after its 1.5 s transition.

## Allowlist
`QUALIFIED_PLAN_SHA256` keeps P2 off/on, p2-loop off/on and D1–D6 (D2 and D2-across share a plan): every deck passed
Q3 and Q7.

## Instrument (S2 live-validation round, 2026-10-12)
V0–V6 and the red registrations (Astra r19 APPROVE) → three root-caused fixes (force-wrap `show()`, the 1→2 press
scene, local cadence for Chrome's 30 Hz throttle with ≥ 2 playing videos) → Astra r20–r24 folds → **r25 APPROVE at
`8bdaf582`** (carry-cover gaps count elapsed rAF intervals from raw tick times; sampler ticks must span the mid-move
window; decision 14: on a classified looping wrap sample, the carried decoder's `seeking` read waives only decode
readiness — pixel-checked twice, the last frame stays painted). Then the owner reverted the paint coverage tightening
(r21–r23: "fastest nearby delta") to the slower side's median (`ecf1b553`, owner: "fix what my eyes can catch"): the
tightened rule read every throttle-onset gap as inconclusive and failed 5 registered reds whose red evidence was
present (final-round C1 at `8bdaf582`: `failed=5`). Regression oracle vs `9d4fbef5`: the intended changes only
(force-wrap 1→2 red; decision-14 takes pass).

## Follow-ups (not blocking)
- Show OBS cannot surface the tray-minimised managed OBS ("no available windows"); previews used `chrome://inspect`.
- Owner: start the output session visible; Show/Hide output coloured like Take/Release.
- `live_fixture_session.py`: CDP keepalive timed out on a hidden HDMI window before the first `s`.
- `managed_obs_qualify` latelost validity read (²); force-wrap 1to2 @375 scheduling (¹).
- Astra r21 P3 (exact legacy rescore vs a renamed diagnostic), r23 P3 (window-edge interval), r24/r25 contract slack
  (wrap excuse trusts `unwrap_clock`), D-deck pin-window margin (84–100 ms before the press).
