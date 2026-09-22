# Handover — Alpha Keynote live continuity, state at 2026-09-22

Supersedes `keynote-live-continuity-2026-09-21.md` (its facts hold; worktree table below replaces its). Owner rules unchanged.

## Where things are (verified after #196 merged, `c2089691`)
| Item | State |
|---|---|
| `main` | #191 (seam re-do), #192, **#194 (test suite ≈90 s)**, **#196 (paint oracle)** merged 2026-09-22. |
| Full suites | `uv run pytest tests/ -n auto --dist loadfile` (≈90 s; 5336 passed) · `npm run test:ui` · `npm run test:maps`. Serial escape hatch: `OBED_TEST_SWEEP_WORKERS=1`. |
| Worktrees | `gate-runner` REMOVED 2026-09-22 (owner). `run_gates.sh <any pinned checkout> <outdir>` still works from `scripts/`; make a fresh detached worktree per gate round. `test-speed`, `paint-oracle` removed after merge. |
| Fixture | Durable P2 fixture = MAIN checkout `output/p2-recovery/html-adversarial` (git-ignored). |
| Research evidence | `output/gate-runner-archive/{research-harnesses,requal-paint-oracle,run_gates.sh}` (git-ignored, 2.0 GB). Harness sources only there — do not lose. |

## Paint oracle — SHIPPED (#196)
12-shot spaced burst as the single `BURST_OFFSETS_MS` in `p2_verdict.py`; `--burst-poke` off by default; `burstProfile`
artifact; inert in-page GL oracle. Five Codex rounds (`.agents/reviews/paint-oracle/r1–r5.md`) + a Fable peer opinion
on the cadence bind (decision recorded in the plan §14). Re-measured (A12 headless 18/18 + OBS attach 4/4, controls all
DEAD) and re-qualified (host ×3, P2 fast 14/14 / bridge-off 13/14 / slow 14/14, invariance identical at 3 viewports).
**Contract the GL-replay arming PR must publish:** `window.__OBED_GL_ORACLE__ = {gl, canvas, video, epoch, sceneId,
instanceId, rect, canvasId, sample(n)→Promise, markerBands()→Promise, pause()→Promise, resume()→Promise}` — `sample(n)`
across distinct rVFC callbacks in the draw's task; only an ABSENT handle is n/a.

## Open
- **GL-replay v1** (`keynote_live_gl_replay_arming.plan.md`): first todo = prove the draw→export-object mapping for the
  D2 opacity fix; needs the owner's five decks (§6 Q4) and a fresh OBS go for the pool keep-warm measurement.
- Go-to autoplay (decided, ready to implement) · `instanceCheck.painting` on slide 3 varies 1↔2 run-to-run on main
  (verdict unaffected; pin the inventory read) · a freeze-control fixture refresh under the new cadence is an owner-gated
  decision (tripwire test names it) · DeckLink venue test 2026-10-10.

## Lessons this round
A reviewer's counterexample beats a peer's clean argument — the max-delta re-score has no time axis, yet a different
cadence is still a different instrument · one pre-existing race (`test_codecs_recorded_in_session_log`) only surfaced
under xdist load · Codex sometimes stalls on "approve this plan": say NON-INTERACTIVE up front · implementers will
background a >10 min run whatever the brief says; budget for interim notifications.
