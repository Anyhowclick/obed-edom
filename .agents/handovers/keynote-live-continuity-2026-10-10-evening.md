# Handover: main fix in its gate round; S2 merged (2026-10-10, ~17:00)

Read this first, then `keynote-live-continuity-2026-10-10-q7-findings.md` (same folder, commit `4a319b41`; its
findings/decisions still stand). A copy lives in the main checkout `output/evidence/s2-dev/merge-wip-2026-10-10/`.

## Where everything is
| Thing | State |
|---|---|
| `claude/main-bridge-easing` (pushed as backup at `87f8c450`, NO PR yet; worktree `main-bridge-easing`, from main `dd61e7c0`) | **Ready for its gate round.** Commits: `8204b87a` eased bridge overlay (core v5 → `06789fbd`; variant `linear-bridge`), `981d6df7` current-Keynote player `17c0c938` (byte-level proof; `SUPPORTED_PLAYERS` pins on/off/rendering), `98de4a80` hall entry, `41390ccd` carry-cover gate, `6ee91fc5` bridge-timing qualification (+ P2 fixture slide-3 transition slots restored), `5576f061` carry-cover sync bar + coverage bounds, `87f8c450` sync-bar-on-path ⇒ inconclusive. Full suites on `5576f061`: 9127 passed / 0 failed / 11 local skips; test:ui 316; maps 542+2 (re-run on `87f8c450`, tiny probe change). **Astra (gpt-6-astra, high) r1 REQUEST CHANGES (3 MAJOR) → folded; r2 APPROVE** (one MINOR edge case folded as `87f8c450`). Reviews: main checkout `output/evidence/main-bridge-easing/astra-r{1,2}.md`. |
| Gate worktree `gate-main-87f8c450` | Pinned at `87f8c450`, output links in place. Driver `output/evidence/s2-dev/tools-2026-10-10/main_gates3.sh`; evidence → `output/evidence/main-bridge-easing/r3/`. Gate round and host probe started 2026-10-10 evening; results pending. (`gate-main-5576f061` is superseded.) |
| `claude/s2-detach-fix` (origin now `fbba575e`, pushed as backup: `4ae33f99` merge of the main fix's first 4 commits, `fbba575e` PIN HOLD) | Worktree `obs-mac-camera-swap-fbc63b`, head `b5556a6f` (merge of `claude/main-bridge-easing`: `6ee91fc5`, `5576f061`, `87f8c450`); not pushed yet. See "S2 merge — DONE". |
| Other gate worktrees (`gate-s2-*`, `gate-main-{d45ae03a,dd61e7c0,41390ccd}`) | Throwaway; `gate-main-dd61e7c0/output/.html-preview/e17ff140…-p3-r1/html` = the owner's fresh `Minimal Alpha_DSK` export with the NEW player (needed for the main fix's deck round). Trash the rest after checking output. |
| `confident-elion-b41768` | Not ours. Leave it. |

## Main PR — remaining steps
1. DONE: gate worktree `gate-main-87f8c450` (pinned at `87f8c450`, links in place).
2. STARTED 2026-10-10 evening (driver `main_gates3.sh`, evidence `output/evidence/main-bridge-easing/r3/`; results pending). On a QUIET machine (load < 3; nothing else heavy): `GATE_JOBS=3 zsh scripts/run_gates.sh <wt> <out>` — full tier now includes carry-cover green (pass) / red `--core-variant linear-bridge` (fail) / null `--carry-cover-null` (fail). Must end `failed=0 pending=0`; check the restart-clock margins vs the 2026-10-09 baseline.
3. STARTED 2026-10-10 evening (results pending). Host probe on the fresh new-player export at 1920 (`--fixture <html> --original-index <html>/index.html`): confirms patching + presenter on player `17c0c938` (continuity may be declined there — record what it says).
4. Full suites once more on `87f8c450` (run in the worktree with `uv run`, `OBED_EDOM_CACHE_DIR=<main>/.cache`; the main checkout's `.venv` imports the MAIN checkout's code).
5. Gate record `.agents/reviews/main-bridge-easing/gate-record.md` (+ the two Astra rounds), push, open the PR (owner merges; never auto-merge).

## S2 merge — DONE
- Merge commit `b5556a6f`. R10 = narrow reader; the carried slot is the unique transition slot whose start rect matches
  the source instance's rect; checked last; bridges only.
- Corpus invariance: 856 plans / 34 roots, canonical byte-identical to `fbba575e`.
- Full suite 9636 passed / 0 failed / 11 local skips (3.12); continuity files 1770 passed on 3.10.
- `test_r2_the_repeated_instance_geometry_pairs_the_sibling_onto_the_far_destination` (older S2 pairing test) now
  expects R10, because its synthetic clone's slot only fades.

## S2 after the merge
1. **Instrument stream** (probe; not started): `painted` = ancestor opacity product + display/visibility + rect + readyState, sampled pre-paint (ResizeObserver per rAF); zero-tolerance in `score_continuity`; Pass G advance legs scored per frame with plan-derived "go-to source, advance across" cases; red controls: `--core-variant no-pin-hold` (D1 [1,3,4], D5 sequential ≈108 frames) and unmodified core; positive control = injected N hidden frames counts exactly N. Design: `output/evidence/s2-dev/pingap/SUMMARY.txt` + the pin-gap investigation report recorded in memory.
2. **Open** (evidence-only triage 2026-10-10 evening, reports in main checkout `output/evidence/s2-dev/triage-2026-10-10/`):
   - **D5 #5→#6 gap = end of show, plus a stale-timer bug.** Advancing past D5's last slide tears down the slide layer holding the re-homed pin decoder; the core declines it (no next entry); a leftover `scheduleRemount` 2000 ms retry (no still-wanted check in `tryRemount`) re-adds it on `body` ~250–280 ms later (r9 17 frames, f5 14 frames; same counter). D1–D3 keep the decoder on `body` through end of show. Owner: hold the last movie through end of show (low priority — last slide usually a still); close the stale-timer revival regardless. Confirm first with single-Chrome experiments E1–E3 (`d5-end-of-show.md` §4). The instrument's advance legs must treat end of show (hash ≥ numScenes) as an exit.
   - **Carry-cover on S2 D1 = real ~7 ms GL-poster lag, not the corner marker.** Strip grows with speed (5–8 px vs 5). Never mask/exempt; recommended fix = align the core's clock with Keynote's, after the 5-run D1 experiment decides constant per-frame offset vs press-phase start offset (`carry-cover-D1-lag.md`; runs in `output/evidence/s2-dev/cc-D1-63606556/`). Separate instrument fix: the strip rule rounds left/top up but right/bottom down (1 px inconsistency).
   - Red sets that might move with the pin hold: D4 `wrong-instance`/`fifo-reuse`, D5 `fifo-reuse` (re-register only with a measured reason).
3. Full suites, Astra review, then the FULL RE-RUN on the final S2 head: Phases A (decks ×3 viewports), B/D1 (run_gates 3-wide incl. Pass G + carry-cover), D2, D3 (P2 main-vs-S2 interleaved), D4 (G2 seam), D5 (loop), Q6 (managed OBS 25/30, KBs, soak 4 min — owner pre-approved), then Q7 with the owner (Q7a external attach D1/D4; Q7b dashboard Keyer on D1–D5). GATE_JOBS=3 was qualified (#247, `.agents/reviews/gates-speedup-2026-10-09/gate-record.md`) on the 16-run P2/host mix only; the 22 deck red arms and Pass G were added later and have run 3-wide (Phase D, failed=0) but never against a serial baseline. Before the S2 gate record relies on 3-wide, compare one GATE_JOBS=1 round with the 3-wide round: identical verdicts, restart-clock margins within the 2026-10-09 baseline.

## Owner decisions added this session
- Main fix r3 (2026-10-10 evening): freeze-bracket integrity checks were calibrated on linear motion; under the ease a 1 px departure takes ~61 ms (4 frames). Owner: fix = option A (derive the expected departure latency from the bridge's curve + geometry; never relax `firedVia=='moved'`, marker identity, the 1 px detector). Triage: main checkout `output/evidence/main-bridge-easing/triage-r3/`.
- Dashboard (2026-10-10 evening): keep refusing continuity-refused decks even with continuity off — option (i) — until the allowlist widens and is eventually removed. The owner's fresh `Minimal Alpha_DSK` (player `17c0c938`, ambiguous ownership 7→8) stays dashboard-blocked on main meanwhile.
- End of show (2026-10-10 evening): (a) hold the last carried movie through end of show (D1–D3 already do; fix D5). Low priority.
- Main fix = (b) fix properly, incl. the new Keynote player on a byte-level argument; owner said "apply" to the blocked bridge-timing patch.
- Pin hold accepted. Owner napped with "trust ur decisions; try to do the full re-run" (Q6 managed OBS counts as approved; Q7 needs the owner).
- Coordinator calls made under that delegation: restore the P2 fixture's slide-3 transition slots; S2 bridge timing = narrow reader + R10 (not main's helper).

## Machine
- Nothing running at handover (gate driver and the S2 port agent were stopped; no Chrome left).
- One heavy job at a time machine-wide; run_gates refuses above load 4 (driver waits for < 3).
- Subagents may be blocked by a session-isolation hook from writing into a worktree other than the session's; spawn implementers for the target worktree from a session rooted there, or apply their patch with the owner's word.
