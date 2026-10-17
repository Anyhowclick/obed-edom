# Handover: Stage B instrument restructure (soft stop 2026-10-16 23:00 SGT)

**Coordinator (owner 2026-10-16):** session `local_4b825e27-26e0-4d7b-a4af-de1cc7d9d4c2`, worktree
`funny-pasteur-751a72`; merges happen in worktree `stage-b-coord` (on `claude/stage-b-arch`). The old "Stage B
Restructure" session is retired. This file supersedes the "Resume here" sections of `stage-b-implementation-2026-10-15.md`
and `alpha-b3to4-stall-2026-10-15.md`.

## Resume here

**Where things are** (`claude/stage-b-arch` @ `3cc337f5` + this handover, pushed)
- Merged 2026-10-16: C2 offline validity, gate 4 historical inventory, the Chrome rule (any 155.x, one build per round;
  plan §4 amended), the Chrome 155.0.8059.80 requal record, **C1** (`33cb7729`), the MM-FEED diagnosis (`ab2553ea`) and
  **C3** (`3cc337f5`; r1–r7, `c3-gate-record.md`; suites 3.13/3.10 11382 / 38 / 1 on the code-identical tree).
- A fresh worktree needs the main checkout's git-ignored fixtures symlinked (`output/{bank,evidence,fixtures}`,
  `Sermon Outlines/*.docx`) or tests skip (88 vs 38; one W1-bank test needs `output/bank`).

**FIRST on resume: the MM-FEED fix** (session "Diagnose Stage B MM-FEED baseline failures",
`local_6bc69277-054d-426a-b337-94574bac08fe`; its notes `mmfeed-fix-handover.md`; diagnosis
`.agents/reviews/stage-b/instrument-restructure/mmfeed-baseline-diagnosis.md`)
- Code: `claude/stage-b-mmfeed-fix` @ `a25a5db5` (Sol high; Opus 5.5 high r1/r2/r3 READY, lows folded). Owner decisions:
  Alpha gate staging restores the 5 movies from the complete q7 Alpha export and refuses a timed run on an unreadable
  movie; D7/D7s counter movies carry a second strip at source x=704 read through a per-deck `counterLayout`; the D7/D7s
  two-strip re-exports are in `~/Desktop/Convert wall to 16x9 CGs/Continuity/strip2/` (plan hashes equal the pins; posters
  decode both strips). r2/r3 folds are test-only on `claude/stage-b-mmfeed-fix-r23` @ `628b4973`: **rerun
  `tests/test_run_gates.py` and `tests/test_live_continuity_probe.py` on it**.
- Suites on `a25a5db5`: 3.13 11372 / 39 (extra skip = W1-bank link, fixed) / 1; 3.10 11373 / 38 / 1; UI 331/331.
- Gate round on `a25a5db5` (full tier, `QUAL_B_SOURCE=strip2`): **13 failed (was 25)**. Feed checks now MATCH for D7/D7s
  feed-on, no-linger, attach-once and Alpha feed-on. Still red:
  1. D7/D7s from-only: the crossfade blends the strip, so the GL counter decodes `ambiguous` (the D1 band edge from C1
     review r1). Needs a read rule: **owner decision** (do not loosen the band silently).
  2. 9 Alpha feed-off / control arms: holdFrame / posterHold / handbackContinuity. First real scoring of those arms
     (the movie-less fixture hid them); undiagnosed.
  3. HOST red D2 pin@6 mismatch: unrelated to the fix; check it on `3cc337f5` (C3 merged after the fix branch was cut).
- **Do not merge on that round.** Then: merge `claude/stage-b-arch` into the fix branch (probe/probe-test overlap with
  C3), rerun suites, diagnose 1–3, and re-run the round. That round closes C1's open item.

**OPEN, due before gate 5a (owner 2026-10-16):** C1's feed-control colours and holdMatch/poster positive/red separation,
and the D1 counter-policy obligations (D7 crossfade/from-only; a positive GL counter decode now exists on the strip2 D7
feed-on arms). C1 gate 2 timing passed (`c1-gate2-record.md`).

**Owner to confirm**
- Gate 4 decisions 2–5 (accept the inventory, cost `>` vs `>=` 8 ms, wrf-rule scope, Q2 cadence) at gate 5a.

**Next, in order (plan)**
MM-FEED fix merge + C1 separation re-proof → bounded C4 (stream F; also: refuse scoring a counter deck with Alpha
distances, the diagnosis side-finding) → C5 → C10 audit → **gate 5a (owner: Q1 host rows, Q2 cadence statistic, gate 4
list and decisions)** → 6a full suites → gates 7–15 → Q7 attempt 4 (the owner's live check).

**Open items carried**
- F4 (3): the Alpha b5to6 / b7to8:wa0121 flips. Re-check on the merged tree.
- `PRE_DRAW_GRACE_MS` = 320 ms: thin margin (D7 controls 306.5 ms); widening it is the owner's call.
- C2 integration items (`c2-offline-gate-record.md` §Open).
- Kernel measured only at the integer 10× downscale; non-integer ratios rely on the separation re-proof.

**Worktrees** (all clean of uncommitted work at 23:00 unless a session says otherwise; check `list_sessions` cwd before
trashing any): `stage-b-coord` (merges), `funny-pasteur-751a72` (coordinator, `claude/stage-b-c1`), `g2-old` / `g2-c1`
(gate 2 trees, detached; trash once the fix merges), `distracted-cartwright-b450e1` (C3, done), `inspiring-feynman-06914e`
(gate 4, done), the MM-FEED fix session's worktree(s), `stage-b-chrome`, `stage-b-q7` (kept until Q7).

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

## Owner decisions (2026-10-15/16/17)
- 2026-10-17: D7/D7s from-only read rule = **ambiguity in a crossfade read is red**. A crossfade counter read (`feed.to`
  non-null) whose markers pass but whose bits fall in the band (reason `ambiguous`, not `marker`) scores `ok: False`: with
  both units fed the inputs are the same frame, so a clean feed always decodes. `marker` stays None; single-texture reads and
  the band are unchanged. Re-register the D7/D7s per-progress expectations from a fresh round; null = 0 ambiguous crossfade
  reads on every feed-on arm.
- 2026-10-17: C3 carry-window deviation confirmed (union of the old legacy/paint starts minus the initial cold start).
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
