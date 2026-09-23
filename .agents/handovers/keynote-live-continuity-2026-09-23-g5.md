# Handover — Alpha Keynote live continuity, state at 2026-09-23 (G3+G4 PR open)

Supersedes `keynote-live-continuity-2026-09-22-g3.md` (kept: the G3+G4 plan cites it as its spec). Owner rules unchanged: no merge
without an explicit request; hands off Keynote unless told it is free; run the full local suites for every code PR (no CI).

## Where things are
| Item | State |
|---|---|
| Branch | `feat/gl-replay-g3g4`: G3 core seam + zone (`live_continuity_js.py`, `CONTINUITY_VERSION` 5, `PINNED_CORE_SHA256 e9338aff…`), P2 injected plan = glReplay shape with retire fallback (`p2_verdict.py`, P2 script kept kinds from `PRESERVE_EVENT_KEEP_KINDS`), G4 host flag (`OBED_LIVE_GL_REPLAY` / `gl_replay="off"\|"auto"`, default off, off byte-identical), G2 fix (poster snapshot before the first upload; G2 sha `4f8850e0…`). PR open, not merged. |
| Plan | `.agents/plans/keynote_live_gl_replay_g3g4.plan.md` rev 3 — read §8 first (round-1 and Codex amendments). |
| Evidence | `.agents/reviews/gl-replay-g3/`: `gates-r3.md` (PR-citable, all PASS on `a9637d62`), `gates-r1/r2.md`; raw review rounds pruned after merge (git history). Harness (git-ignored): coordinator worktree `output/live-visible-content/g3/` (`g3_flow.py`, `run_arms.sh`, `analyse_g3.py`, `validate_r2_instruments.py`) and `output/gates-g3/` (`run_gates_g3.sh`, `summarise_gates.py`, `g0/`, `gp2-*`). |
| Gate worktrees | `gates-g0-9ad4fc69` (G-0 baseline) and `gates-g3-a9637d62` (r3), detached. Remove once the PR lands unless a re-gate is pending. |
| Suites at the PR tip | pytest 6169 passed / 88 skipped / 1 xfailed; `test:ui` 238; `test:maps` 542 + perf 2. |
| Owner decisions closed 2026-09-23 | OD-1 LIVE-phase failures retire; OD-2 auto + OBS attach ⇒ not injected; OD-3 no README/presenter change; A2 hand off at `toScreen(instanceRect)` + guard G + stash rule; gate-6 frozen frame fixed in G2 in this PR; no second Opus review round (straight to Codex). |

## Next
1. Owner review/merge of the G3+G4 PR.
2. **G5** (probe `armed1to2` flip) and **G6** (P2 `glReplayCarry1to2`) per the arming plan, then full re-qualification; only then consider an
   `auto` default.
3. OD-2 follow-up: measure pool keep-warm and stash order inside OBS CEF before allowing `auto` in attach mode.
4. Option (c) (G2 draws the movie into the texture's inner instance sub-rect): removes the LIVE-phase 2 % stretch and the build-1
   inward move (≈1 px edge, 3–4 px of white frame reappearing). Moves G2's sha; full re-gate.

## Known limits (accepted, measured in gates-r3)
- Build 1 moves the movie edge inward (105/791 → 106/792) as the GL-drawn stretched movie becomes the DOM video; the ring matches the
  control from P3 on.
- `posterRestored` is null on a context loss (no live context to restore into); the forced arm still equals the control at P2c.
- Late real `contextLost` blanks the context at P2d (report-only by ruling), equal to the control at P3/P4.

## Workflow notes from this round
- Opus MAX planner + Opus EXTRA HIGH critic (owner trial replacing Fable): the critic found 2 blockers the planner missed (go-to ⇒
  3→4 bridge kill; hand-off without LIVE). One Opus EXTRA HIGH advisor settled A2 and root-caused gate 6 (10 arms, not 2).
- Gates still found what reviews did not: r1 gate-6's "parity" had compared one ROI; the poster crop was invisible to the counter
  decoder. Every new gate check was validated to FAIL on the known-bad round and read 0 control-vs-control before it counted.
- Plan facts can be wrong even when cited (F10: the P2 script needed a change) — implementers found it by testing the real consumer.

## Still open elsewhere (carried from the 09-22 handover)
go-to autoplay (other worktree) · `instanceCheck.painting` 1↔2 on slide 3 · freeze-control fixture refresh (owner-gated) · DeckLink venue
test 2026-10-10 · D3 `writebackFailed` secondary by design · owner to confirm the candidate-closed plans listed in the 09-22-g3 handover.
