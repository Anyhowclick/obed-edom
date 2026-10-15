# Handover: Stage B instrument restructure (resume 2026-10-16)

The owner paused the round on 2026-10-15 after the C6 r3 review. This file supersedes the "Resume here" sections of
`stage-b-implementation-2026-10-15.md` and `alpha-b3to4-stall-2026-10-15.md` for this branch.

## Resume here

**Where things are**
- Worktree: `.claude/worktrees/inspiring-feynman-06914e`, branch **`claude/stage-b-arch`**. Local only, not pushed.
- `claude/stage-b-arch` = Stage B (`origin/claude/stage-b-implementation` @ `16f6c9fa`) + main #288–#293 (merge `fc0a0726`, Astra merge review READY).
- Main has since gained **#294** (`163ec812`: pre-load qualification truth, `web/live.py`). Merge it before the PR.
- Env synced (`uv sync`, `npm ci`, output symlinks). Run tests with this worktree's `.venv`.

**Read first**
- Plan: `.agents/plans/keynote_live_continuity_stage_b_instrument_restructure.plan.md` (r3, owner-approved), especially §9 streams and §10 gates.
- Review: `.agents/reviews/stage-b/architecture-review-2026-10-15.md`.

**Done**
- **C6** = `ad2bd89f`. Gate record: `.agents/reviews/stage-b/instrument-restructure/c6-gate-record.md`.

**Next, in order**
1. **Fold C6 r3** (`c6-review-r3.md`): 1 medium (malformed/missing stored sample rows coerced to `[]` → contract bypass on replay) and 1 low (owned-descendant and missing-pid test coverage). Round 3 folds mediums and lows. Then one closing r4 for majors/blockers only; stop when none.
2. **C1** (plan §3). The FIRST step is the scratch timing split (drawImage vs getImageData vs DOM; `willReadFrequently` on/off; source size).
   - It is a heavy job, so ask the linked sessions for the window.
   - Then stream F implements, with Opus review.
   - Raw material: branch **`claude/stage-b-c1-unbriefed`** (`0abf8772`). It is an UNREVIEWED attempt produced from an empty brief: 192 px single downscaled draw/read, `willReadFrequently:false`, shared counter layout/decoder, `report()` shutdown. **Do not merge it.** Reuse it only after the timing split justifies its choices.
3. Then follow the plan: C2 (cost/environment validity + cadence *measurement*) → C3 + bounded C4 → C5 → C10 audit → **gate 5a (owner: Q1 host rows, Q2 cadence statistic, historical INVALID list)** → 6a full suites → gates 7–15.

**Roster** (until 2026-10-27; see memory `feedback-delegate-implementation`)
- Codex GPT-5.6 Sol high implements: `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write -c 'sandbox_workspace_write.writable_roots=["<scratch>"]' -C <worktree> -o <report> "<brief>" < /dev/null`.
- Opus 5.5 high reviews, as a Workflow: lenses, then each finding adversarially verified.
- Planner: Astra. Critic: Opus.
- Sol's sandbox cannot read the uv cache; it falls back to `.venv/bin/python`. Re-run its tests outside the sandbox.
- **Write briefs with a QUOTED heredoc and check `wc -c` before launching.** 2026-10-15: an unquoted heredoc sent an empty brief, and Sol implemented C1 unbriefed.

## Side work (linked sessions)

| Item | Where | State | Next |
|---|---|---|---|
| Alpha b6to7/b7to8 hand-back placement fix (plan Q3: fix before Q7) | Session "Diagnose Alpha b6to7/b7to8 decoder placement", branch `claude/friendly-stonebraker-16d950` @ `3a9a85b4`; fix `48d8182e`, core **`838eeedf`**; its gate record + resume-here on that branch | Headless A/B green: old core reproduces (frozen pixels slides 8–9, `#body`, hand-back/artwork False); fixed core all green with moving pixels. D7/D7s signatures identical. Red controls red. P2 GL-replay and D2/D5 pass. Opus r1 READY (3 lows folded). | Full suites (3.12 + 3.10). Then merge into `claude/stage-b-arch`; it re-pins `detach_experiment.py:76`, a different hunk from C6. |
| `noRiderAboveCanvas` A/B (plan gate 10b, owner go) | Same session, queued (paused for the night) | Not started (queued after its suites, in its resume doc) | Cores 03a35b28 / 302c218d / 838eeedf × pre-move capture on/off, D7 + Alpha. Diagnosis only. **Lead:** the `departure-early-hide` control read `noRiderAboveCanvas` True on D7 b0to1 while the departure-fixed cores read False, which points at the departure fix's interim/ride path (`af3edf73`: `deferDepartureHide` / `departureInterimPlace`), not the placement fix. |
| F4 cold start | Session "Measure F4: faststart remux vs Alpha cold start", branch `claude/trusting-aryabhata-f69fdc` (`c9367666`, `dc63372c`, `7a49aa25`) | Faststart remux: **no** (no effect; plain `ffmpeg +faststart` is not lossless here). Deck-load warm-up of any one movie: **yes** (~200 → 20–30 ms; managed OBS 280 → 56 ms; holds across a 3-min idle). **Owner go on the warm-up** (`7a49aa25`). | That session runs an Astra plan + Opus critique, then the plan goes to the owner before code. It is a product change; sequence it against Stage B with the owner. |
| Pre-load qualification truth | PR #294 | **Merged** | Merge main into `claude/stage-b-arch`. |

## Owner decisions this round (2026-10-15)
- Scope C6, C1, C2, C3, C4-slice, C5, C10-audit approved; plan r3 approved.
- C4 keeps the report-wide producer-error rule.
- `entryColdStart` is report-only.
- "1 video to 3" = slides 7→8→9 (the F1 observer effect).
- Q3: fix the Alpha placement before Q7.
- Run the `noRiderAboveCanvas` A/B before Q7 attempt 4.
- F4: warm-up yes, faststart no.

## Machine
- One heavy job machine-wide. Send "need window" / "done" to the linked sessions.
- At most 3 headless Chromes. Record uptime.
- Chrome 155.0.8059.79.
