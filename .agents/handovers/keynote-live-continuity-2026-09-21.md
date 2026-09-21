# Handover — Alpha Keynote live continuity, state at 2026-09-21 (evening)

Supersedes `keynote-live-continuity-2026-09-20-night.md` (its paid-for facts and gotchas still hold). Owner rules unchanged:
accuracy and code quality over speed · plan first · never weaken a gate · minimal comments in src · no merge / auto-merge
without the owner · hands off Keynote · port 9222 / OBS only on the owner's word · full local suites for every code PR (no CI).
Worktree hygiene (owner, 2026-09-21): worktrees go once their work has landed unless something in them awaits review.

## Where things are (verified after PR #187 merged, `06014901`)
| Item | State |
|---|---|
| `main` | #184–#189 + **#187 (freeze control 3→4)** merged 2026-09-21. All Alpha Keynote work is on main. |
| Worktrees | `gate-runner` (detached; pinned gate checkout; own P2 fixture bank; **`output/run_gates.sh`** + `output/research-harnesses/` = the GL-replay / paint-oracle / go-to research drivers, sources only). `improve-codebase-architecture-55c211` = the architecture session's (`refactor/gate-verdict-seam-redo`). `friendly-sammet-32dab4` = this session's; removable once it closes. `freeze-3to4`, `pr158-handover-findings-4366b9`, `decklink-field-test-2ad808` REMOVED. |
| Gate script | now also committed as `scripts/run_gates.sh` (this PR). Usage: `git -C .claude/worktrees/gate-runner checkout --detach <sha>` then `zsh scripts/run_gates.sh .claude/worktrees/gate-runner <outdir>`; ≈15 min; host ×3 viewports then P2 fast / fast `--disable-bridge34` / slow. Expect host pass ×3, fast 14/14, bridge-off 13/14 (only `continueThroughMovingMagicMove3to4` red), slow 14/14. Preconditions: `pgrep -f "headless=new"` empty, gate-runner clean, record `uptime`. |
| Main checkout | on `main`, venv synced (`uv sync --frozen --all-extras --all-groups`). Durable fixture copy `output/p2-recovery/`. |

## 1. Freeze negative control — CLOSED (PR #187)
Re-bracketed at the moving 3→4 Magic Move. 17 rounds, 13 Codex reviews (`.agents/reviews/freeze-3to4/`), Opus MERGE
verdict, ten consecutive green gate rounds. Every measurement: `.agents/plans/p2_freeze_control_3to4.plan.md` §9–§10.19.
P2 `success: True` is reachable again (old main hard-coded the control's pass to False).
Residuals the owner accepted: ~1 bracket in 15 INCONCLUSIVE on `OWNER_NULL_MAX_RUN=5` at host load ≥ 9; suite ≈415 s
(exhaustive absence sweep over the real fixture `tests/fixtures/p2_freeze_3to4/clean_bracket.json`); `manifest=None`
default on `_score_freeze_control` is fail-closed but a footgun; the adversarial script's comments are heavily narrated
(cleanup pass owed); Codex's suite-time rec = derive continuity once per scorer call, never a cross-call cache.
The 2026-09-20 premise ("motion starts on arrival at #7") was an instrument artifact (queued key press) — plan §9.

## 2. In flight — architecture session
`refactor/gate-verdict-seam-redo`: moves the verdict layer into `src/obed_edom/p2_verdict.py` (309 tests import from src;
12 driver tests → `tests/test_p2_adversarial_driver.py`; async/driver code + injected-JS constants stay in the script).
Base is code-identical to what merged; it will merge `main` in. **The P2 gate must be re-run after the move** (driver bytes
change) — needs the owner's ok for a headless round; invocation above. `refactor/gate-verdict-seam` = parked reference only.

## 3. Owner decisions recorded 2026-09-21 (in the plans)
- Go-to autoplay (`keynote_live_goto_autoplay.plan.md`): player-faithful rule (play the leading run of `automaticPlay: true`
  events, never a click-driven one); +0.3–1 s latency accepted; `jumpToSlide(n,true)` deferred to v2. **Ready to implement.**
- Paint oracle (`keynote_live_paint_oracle.plan.md`): **GO**, full re-qualification in the same PR.
- GL-replay arming (`keynote_live_gl_replay_arming.plan.md`): D1 moot (feasible in OBS CEF); D2 opacity fix ships in v1
  WITHOUT editing `main.js` (inject `uniform1f(Opacity, export wrapper opacity)` in our replay; write 1.0 back on
  stand-down; first todo = prove the draw→export-object mapping; fallback = opaque look + presenter note); D3 the two-movie
  and equal-size-poster decks must be authored and measured refusing before v1; D4 accept; D5 arming stays `off` until a
  second deck is qualified. Still open before G3: the pool keep-warm variant inside OBS CEF (needs a fresh OBS go).

## 4. Open owner-raised defects (unchanged)
1. Go-to freezes movies on air (decided, see §3). 2. Carried movie invisible on a WebGL-settled slide (baseline refuses;
GL replay is the fix path, §3). 3. Player paints wrapper-opacity artwork opaque (folded into GL-replay v1 D2).
4. `scripts/p2_alpha_spike.py` still sends `nativeVirtualKeyCode`; owner HDMI eyeball at 2560×1440; native easing parity;
HEVC at the receiver; generalisation plan (retire `QUALIFIED_PLAN_SHA256`).

## 5. What the owner does next
Author the decks in the GL-replay plan §6 Q4 (no-build destination · two movies · equal-size posters · masked movie ·
no-overlap positive control), 1920×1080, grating-with-counter movie. Give the seam re-do its gate go. DeckLink venue test
2026-10-10 (`decklink-field-test-runbook.md`).

## Lessons this round (also in the Hall, "the press that was never sent")
Reproduce the gate's exact stimulus before blaming the runtime · interleave old/new when a loaded machine reds a run ·
a real captured fixture + exhaustive deletion sweep beats any hand-built fixture · peers cannot write into another
session's worktree (spawn them into the target, or fast-forward from a detached HEAD) · foreground bounded waits only.
