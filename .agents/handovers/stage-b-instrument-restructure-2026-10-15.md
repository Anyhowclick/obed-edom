# Handover: Stage B instrument restructure (resume after 2026-10-16)

The coordinator session stopped on 2026-10-16 at the owner's request. This file supersedes the "Resume here" sections of
`stage-b-implementation-2026-10-15.md` and `alpha-b3to4-stall-2026-10-15.md`.

## Resume here

**FIRST THING ON RESUME (owner 2026-10-16): run the C1 tests.**
The coordinator stopped as soon as Sol finished C1's probe side, so the committed C1 WIP on `claude/stage-b-c1` has NOT been tested by the coordinator.
In the coordinator worktree, check out `claude/stage-b-c1`, then:
```
.venv/bin/python -m pytest tests/test_mm_feed_instrument.py tests/test_live_continuity_probe.py tests/test_managed_obs_qualify.py tests/test_detach_experiment.py tests/test_binary_counter_movie.py tests/test_live_evidence_contract.py tests/test_obs_cadence_decode.py -q -p no:cacheprovider -n 2
```
Before Sol's probe-side step, stream F alone gave 2455 passed and 1 failed (the old probe fake-GL test, which that step deletes). Investigate any failure at its root, then continue with the C1 next steps below.

**Where things are**
- Coordinator worktree: `.claude/worktrees/inspiring-feynman-06914e`.
- **`claude/stage-b-arch`** is pushed to origin and holds only reviewed work. It contains:
  - C6 and its r3 fold;
  - the Alpha placement fix and the noRider A/B;
  - the pre-draw rider exemption: the Python bounds (`5422f4ec`, `7746df27`) and the geometry check (merge `1a421de2`, cleanup `397a26c9`);
  - F4 movie warm-up (#295, #296);
  - main, including #294, and the suite speed-up port (#297; `6adaa752`, `fcd2b2ef`, merge `4e8444a6`);
  - the settle-wait test fix (`1a56be4c`);
  - the C1 timing record (`b9f2340a`).
- Full suites on `1a421de2`: 11311 passed / 38 skipped / 1 xfailed, on both 3.13 (157 s) and 3.10 (192 s).
- **C1 is UNREVIEWED and on its own local branch, `claude/stage-b-c1`** (not pushed). See C1 below.
- Env: the worktree `.venv` (3.13), and the 3.10 floor in the session scratchpad `venv310` (re-create it with `UV_PROJECT_ENVIRONMENT=<scratch>/venv310 uv sync --frozen --all-extras --all-groups --python 3.10`).

**Read first**
- Plan: `.agents/plans/keynote_live_continuity_stage_b_instrument_restructure.plan.md` (r3, owner-approved), §3 (C1), §5 (C3), §9 streams, §10 gates.
- C1 timing: `.agents/reviews/stage-b/instrument-restructure/c1-timing-split.md`.

**C1: bounded sampling (plan §3)**
- **Timing split: done.** `willReadFrequently:true` is the observer effect: a CPU-backed canvas makes about 115 ms drawImage stalls, and head runs show `callbackCostP95Ms` 113–116 ms with scene 8/10/12 medians of 100/100/200 ms.
- Only **one 192 px draw + one read with `willReadFrequently:false`** meets the targets: p95 2.5 ms and medians of 33/17/33 ms.
- The counter decodes identically (483/483). The patch vectors differ by up to 113.
- **Implementation (UNREVIEWED), on `claude/stage-b-c1`:** Codex GPT-5.6 Sol high implemented it.
  - Stream F: `sample()`/`decodeCounter()`, the layout from `binary_counter_movie.layout()`, the shared Python decoder in `obs_cadence_decode.py`, the 18-reference ring, `report()` shutdown, the contract patch, and a new `tests/test_mm_feed_instrument.py`.
  - The tiny P side: the probe passes `counterLayout`, and the old probe fake-GL test (`test_instrument_js_runs_realistic_fake_gl_end_to_end`) is deleted after its assertions moved to the new file.
  - Sol's reports: `c1-f-report.md` and `c1-p-report.md` in the coordinator scratchpad. The C1 commit message summarises them.
- **C1 next steps:**
  1. Opus 5.5 high review, in rounds 1–3, folding all severities.
  2. Fresh paired Alpha captures (gate 2). Measure `callbackCostP95Ms` ≤ ~4 ms and scene medians ≤ 33 ms.
  3. **Re-prove the holdMatch/poster positive/red separation.** The GL vector footprint now follows the 192 px source grid. Thresholds are unchanged; change them only on demonstrated separation.
  4. Full suites.
  5. Merge into `claude/stage-b-arch`. Expect a small probe/probe-test merge against C3.
- Then delete `claude/stage-b-c1-unbriefed` (`0abf8772`); its ideas are reused and justified by the timing split.
- Timing harness (scratch, reusable): `<coordinator scratchpad>/c1-timing/`. It contains `variant_builder.py`, `run.sh`, `summarize.py` and `matrix.txt`. `run_probe_c1.py` pins the worktree HEAD, so re-pin it before reuse. Results summary: `output/evidence/stage-b-2026-10-13/c1-timing/`.

**C3: phases and carry windows (plan §5), running in parallel**
- Session "Stage B C3: arm-wide phases, carry windows" (`local_a393024c-7f20-4969-9cdf-f4fe6eec32ab`), branch `claude/stage-b-c3-adadcc`, worktree `distracted-cartwright-b450e1`.
- r1 is in progress:
  - **Blocker:** registered no-pin-hold/strip reds turn None for carries with `transitionScene` None. The fix is in progress.
  - Fold: `score_continuity` excuses owner/rect rows inside the GL interval but not `missingSamples`. That is why Alpha arm A b6to7/b7to8 wa0125 read carry=False in all 10 C1 runs on `1a421de2`; the old instruments read None there. C3 is folding "a decoder absent inside a valid under-artwork glInterval is not a missing sample".
- C3 also closes F4's A3 item: the slide-entry poster exposure becomes visible as REPORT-only `entryColdStart`.
- It hands back to the coordinator, who merges; it never pushes `claude/stage-b-arch` itself.

**Next, in order (plan)**
C1 review/captures/merge and C3 merge → C2 → bounded C4 → C5 → C10 audit → **gate 5a (owner: Q1 host rows, Q2 cadence statistic, historical INVALID list)** → 6a full suites → gates 7–15 → Q7 attempt 4 (the owner's live check).
- C2: validity (`live_run_validity.py`, stream V; a new file).
  - The environment and host table can start any time.
  - The cost gate now has C1 measurements.
  - Gate 4's historical impact inventory is offline and pairs with it. It was proposed to the owner as a parallel session; no answer yet.
- C4 (stream F, the same file as C1) follows C1.

**Open items carried**
- F4 (2): D7/D7s feedLive None (`coveredByLaterDraw`; pre-move capture ~128 ms). Probably the same `willReadFrequently` cost; re-check after C1.
- F4 (3): the Alpha b5to6 / b7to8:wa0121 flips. In 12 C1 runs, b5to6 flipped once (single-96); b7to8:wa0121 was stable True. Re-check after C1 + C3.
- `PRE_DRAW_GRACE_MS` = 320 ms. The warm-up doesn't shorten the 2-frame MM prefix, and the D7 controls reached 306.5 ms: a thin margin, and widening it is the owner's call.

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
- Chrome 155.0.8059.79.
