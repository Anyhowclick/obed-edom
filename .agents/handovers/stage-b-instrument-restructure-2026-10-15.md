# Handover: Stage B instrument restructure (updated 2026-10-16 evening)

**Coordinator (owner 2026-10-16):** session `local_4b825e27-26e0-4d7b-a4af-de1cc7d9d4c2`, worktree
`funny-pasteur-751a72`; merges happen in worktree `stage-b-coord` (on `claude/stage-b-arch`). The old "Stage B
Restructure" session is retired. This file supersedes the "Resume here" sections of `stage-b-implementation-2026-10-15.md`
and `alpha-b3to4-stall-2026-10-15.md`.

## Resume here

**Where things are** (`claude/stage-b-arch` @ `33cb7729`, pushed)
- Merged today: C2 offline validity (`61b8082d`), gate 4 historical inventory (`733cd70f`), the Chrome rule (any 155.x,
  one build per round, plan §4 amended; `749b63a0`), the Chrome 155.0.8059.80 requal record (`69c84865`), and **C1**
  (`33cb7729`: review r1/r2/r3 READY, records `c1-review-r1..r3.md`).
- Full suites on the C1 tree: 3.13 and 3.10 both 11366 passed / 38 skipped / 1 xfailed.
- A fresh worktree needs the main checkout's git-ignored fixtures symlinked (`output/{bank,evidence,fixtures}`,
  `Sermon Outlines/*.docx`) or ~50 extra tests skip (88 vs 38).

**C1 gate 2** (`.agents/reviews/stage-b/instrument-restructure/c1-gate2-record.md`)
- Timing PASS: `callbackCostP95Ms` 106–109 → 3.0–3.7 ms; scene 8/10/12 medians 100/100/200 → 33/17/33 ms.
- **OPEN, due before gate 5a (owner 2026-10-16):** the feed-control colours and the holdMatch/poster positive/red
  separation are not re-proved, and the D1 counter-policy obligations (D7 crossfade/from-only, at least one positive GL
  counter decode) are open. All 25 MM-FEED arms fail in a full run_gates round, identically on the pre-C1 tree:
  D7/D7s `feedLive` None (GL counter `coveredByLaterDraw`, flat 66.7 levels; F4 item 2, not a cost effect), and every
  Alpha_DSK carry INCONCLUSIVE on the gate's repaired fixture ("movie never decoded" / "core feed seam did not identify a
  feed or departure mode"; the q7 Alpha fixture scores normally). Diagnosis session: "Diagnose Stage B MM-FEED baseline
  failures" (`local_6bc69277-054d-426a-b337-94574bac08fe`), on the C1 tree; it hands back before fixing.
- Every host, P2, Pass G and carry-cover gate MATCHed in that round (wall 1251 s at GATE_JOBS=3).

**C3** (session `local_a393024c-7f20-4969-9cdf-f4fe6eec32ab`, branch `claude/stage-b-c3-adadcc`): fold rounds r4/r5 in
progress; it merges `claude/stage-b-arch` (now with C1: expect a small probe/probe-test merge), runs full suites in a
window, then hands back. The Alpha arm A b6to7/b7to8 `wa0125` carry=False (`missingSamples` inside the glInterval)
reproduces on both trees; C3's GL excuse fixes it.

**Next, in order (plan)**
C3 merge → MM-FEED baseline fix + C1 separation re-proof → bounded C4 (stream F, same file as C1) → C5 → C10 audit →
**gate 5a (owner: Q1 host rows, Q2 cadence statistic, gate 4's historical list and its decisions 2–5)** → 6a full
suites → gates 7–15 → Q7 attempt 4 (the owner's live check).

**Open items carried**
- F4 (2): D7/D7s feedLive None: coverage, not cost (see C1 gate 2). In the diagnosis session.
- F4 (3): the Alpha b5to6 / b7to8:wa0121 flips. Re-check after C3.
- `PRE_DRAW_GRACE_MS` = 320 ms: thin margin (D7 controls 306.5 ms); widening it is the owner's call.
- C2 integration items (`c2-offline-gate-record.md` §Open): hook names, `gl_intervals`, attach profile field, probe
  imports host kinds from `live_run_validity`.
- Kernel measured only at the integer 10× downscale; non-integer ratios rely on the separation re-proof.

**Roster** (until 2026-10-27; memory `feedback-delegate-implementation`)
- Codex GPT-5.6 Sol high implements: `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write -c 'sandbox_workspace_write.writable_roots=["<scratch>"]' -C <worktree> -o <report> "<brief>" < /dev/null`.
- Opus 5.5 high reviews. The Workflow tool needs the owner's explicit opt-in; otherwise use an Agent with `model: opus`, `effort: high`, and lenses with self-refutation.
- Planner: Astra. Critic: Opus.
- Sol's sandbox can't use the uv cache; it uses `.venv/bin/python`. Re-run its tests outside the sandbox.
- **Write briefs with a QUOTED heredoc and check `wc -c`.** zsh: `status` is read-only, so don't use it as a variable name.

## After Stage B merges (owner 2026-10-16)
- **Suite speed-up:** #297 is on main (`76452a91`) and already ported. When Stage B merges main, `run_gates.sh`, `test_run_gates.py` and `conftest.py` should already match. Notes: `.agents/handovers/suite-speedup-stage-b-rebase.md`.
- **Pass G option A** (`.agents/plans/suite_speedup.plan.md`) lands only after Stage B merges.
- **Feed-dwell shortening is a Stage B item, low priority, after the merge.**
  - Apply `FEED_DWELL_S` only before the presses out of the scored carries.
  - Then either limit the dwell arms' gate expectations to those carries (run_gates' `check_mm_feed` applies the feed-off expectations to EVERY under-artwork record), or prove headless that the non-scored carries pass at `CLICK_DELAY_S`.
  - D7 attach-once gets the same treatment.
  - Add an arm-level check that the dwell was applied.
  - Saves about 35 s of wall time per round.

## Owner decisions (2026-10-15/16)
- 2026-10-16: requalify Chrome 155.0.8059.80; minor/patch builds auto-qualify (any build in a qualified major, one
  build per round, recorded per run).
- 2026-10-16: the coordinator role moves to this session; the old coordinator is retired.
- 2026-10-16: MM-FEED arms need to pass on the post-C1 tree only; merge C1 after full suites, with the feed-colour and
  holdMatch/poster separation proof open before gate 5a.
- Scope C6, C1, C2, C3, C4-slice, C5, C10-audit approved; plan r3 approved.
- C3 runs in parallel with C1, in its own session.
- C4 keeps the report-wide producer-error rule.
- `entryColdStart` is report-only. "1 video to 3" = slides 7→8→9.
- Q3: fix the Alpha placement before Q7 (done). The noRider A/B ran before Q7 attempt 4 (done).
- The rider census skips the zero-draw prefix, with these bounds:
  - `PRE_DRAW_GRACE_MS` = 320 ms (provisional);
  - an accepted stand-down ends the exemption;
  - a 1 authored px source-rect tolerance;
  - JS `firstDrawAt`.
  Records: `.agents/reviews/stage-b/alpha-placement/gate-record-2026-10-16-predraw.md` and `.agents/reviews/stage-b/predraw-geometry/gate-record-2026-10-16.md`.
- F4: warm-up yes, faststart no.
- The suite speed-up merged into Stage B optimistically.

## Housekeeping (owner 2026-10-16: done)
- Finished sessions are archived: the geometry check, F4, the Alpha placement diagnosis and the suite speed-up.
- The `stage-b-impl` worktree went to the Trash, and its merged branch `claude/stage-b-implementation` was deleted locally (the remote copy remains).
- `stage-b-q7` (detached `03a35b28`, the pre-departure-fix core) is **kept until Q7** as an A/B reference.
- Deleted local branches:
  - `claude/cool-shannon-0179e4`: its handover lines are already in `alpha-b3to4-stall-2026-10-15.md`;
  - `claude/f4-warmup-cleanup`, `claude/friendly-stonebraker-16d950`, `claude/funny-pasteur-751a72`, `claude/gallant-matsumoto-1444a2` and `claude/predraw-cleanup` (all fully merged).

## Machine
- One heavy job machine-wide (full suites, gate rounds, captures). Send "need window" / "done" to the linked sessions.
- At most 3 headless Chromes. Record uptime.
- Chrome 155.0.8059.80 (auto-updated 2026-10-16 08:53; requalified).
