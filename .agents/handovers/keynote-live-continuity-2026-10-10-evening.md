# Handover: main fix ready for its gate round; S2 mid-merge (2026-10-10, ~17:00)

Read this first, then `keynote-live-continuity-2026-10-10-q7-findings.md` (same folder, commit `4a319b41`; its
findings/decisions still stand). This file is UNTRACKED in the worktree because the S2 worktree is mid-merge — commit it
with the merge (step 2 below). A copy lives in the main checkout `output/evidence/s2-dev/merge-wip-2026-10-10/`.

## Where everything is
| Thing | State |
|---|---|
| `claude/main-bridge-easing` (pushed as backup at `87f8c450`, NO PR yet; worktree `main-bridge-easing`, from main `dd61e7c0`) | **Ready for its gate round.** Commits: `8204b87a` eased bridge overlay (core v5 → `06789fbd`; variant `linear-bridge`), `981d6df7` current-Keynote player `17c0c938` (byte-level proof; `SUPPORTED_PLAYERS` pins on/off/rendering), `98de4a80` hall entry, `41390ccd` carry-cover gate, `6ee91fc5` bridge-timing qualification (+ P2 fixture slide-3 transition slots restored), `5576f061` carry-cover sync bar + coverage bounds, `87f8c450` sync-bar-on-path ⇒ inconclusive. Full suites on `5576f061`: 9127 passed / 0 failed / 11 local skips; test:ui 316; maps 542+2 (re-run on `87f8c450`, tiny probe change). **Astra (gpt-6-astra, high) r1 REQUEST CHANGES (3 MAJOR) → folded; r2 APPROVE** (one MINOR edge case folded as `87f8c450`). Reviews: main checkout `output/evidence/main-bridge-easing/astra-r{1,2}.md`. |
| Gate worktree `gate-main-5576f061` | Pinned, output links in place. Gate round NOT run (owner: stop before it). Driver `output/evidence/s2-dev/tools-2026-10-10/main_gates2.sh` (re-pin to `87f8c450` first: P2's path is far from the sync bar, but pin the final head). |
| `claude/s2-detach-fix` (origin now `fbba575e`, pushed as backup: `4ae33f99` merge of the main fix's first 4 commits, `fbba575e` PIN HOLD) | **Worktree `obs-mac-camera-swap-fbc63b` is MID-MERGE** of `claude/main-bridge-easing` (bringing `6ee91fc5`, `5576f061`, `87f8c450`). See "S2 merge in progress". |
| Other gate worktrees (`gate-s2-*`, `gate-main-{d45ae03a,dd61e7c0,41390ccd}`) | Throwaway; `gate-main-dd61e7c0/output/.html-preview/e17ff140…-p3-r1/html` = the owner's fresh `Minimal Alpha_DSK` export with the NEW player (needed for the main fix's deck round). Trash the rest after checking output. |
| `confident-elion-b41768` | Not ours. Leave it. |

## Main PR — remaining steps
1. Pin a gate worktree at `87f8c450` (link `output/{fixtures,evidence,bank}` + compat links from the main checkout).
2. On a QUIET machine (load < 3; nothing else heavy): `GATE_JOBS=3 zsh scripts/run_gates.sh <wt> <out>` — full tier now includes carry-cover green (pass) / red `--core-variant linear-bridge` (fail) / null `--carry-cover-null` (fail). Must end `failed=0 pending=0`; check the restart-clock margins vs the 2026-10-09 baseline.
3. Host probe on the fresh new-player export at 1920 (`--fixture <html> --original-index <html>/index.html`): confirms patching + presenter on player `17c0c938` (continuity may be declined there — record what it says).
4. Full suites once more on `87f8c450` (run in the worktree with `uv run`, `OBED_EDOM_CACHE_DIR=<main>/.cache`; the main checkout's `.venv` imports the MAIN checkout's code).
5. Gate record `.agents/reviews/main-bridge-easing/gate-record.md` (+ the two Astra rounds), push, open the PR (owner merges; never auto-merge).

## S2 merge in progress (worktree `obs-mac-camera-swap-fbc63b`)
- Staged/resolved: `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py`, `tests/test_live_continuity_decks.py` (auto-merged; carry-cover fold verified intact), the P2 fixture JSON `D4D95253…json` (main's slide-3 slots + S2's two extra `objectID`s — verified both ways).
- `src/obed_edom/live_continuity.py`: conflict markers resolved (file still marked UU). Contains the **S2 port of the bridge-timing rule as code R10** (`_bridge_timing_refusal` ~:1571, wired in `_magic_move_movies` ~:1758, checked LAST; pins exempt — the pin hold is static). Coordinator decision (a): a NARROW reader (only the fields it uses; NOT the glReplay measured-keys allowlist, which rejects D-deck text slots' `textColor`) that finds the carried slot as the UNIQUE transition slot whose start rect matches the source instance's rect (none/several ⇒ R10). The implementer was stopped right after writing it, at "now re-dump" — **unverified**: re-dump and confirm, don't trust it blind.
- `tests/test_live_continuity.py`: STILL has conflict markers (2). Plan: keep S2's `_signed`; drop main's `test_to_runtime_refuses_actionable_boundaries_after_bridge` (S2 removed it from the base); port main's timing tests in S2 style (Linear / missing / begin 0.2 / duration 1.0 / no slot / ambiguous slot ⇒ R10 with the bridge retired; fixture + real P2 guard; D1–D6 bridges still qualify; a D-style case where an earlier build event draws fewer slots).
- README + SKILL: R10 lines added (unstaged) — commit with the rule.
- **Corpus invariance is the gate:** dump with `output/evidence/s2-dev/tools-2026-10-10/dump_corpus_s2.py` (takes the worktree path); before-dump = `output/evidence/s2-dev/dump_before.json` (S2 at `fbba575e`, 856 plans / 34 roots, glReplay on+off). The FIRST port (main's helper as-is) produced `dump_after.json` with 132 differing plans (every D-deck bridge refused); the narrow reader must make it byte-identical. If not, stop and report.
- Exact WIP snapshot: `output/evidence/s2-dev/merge-wip-2026-10-10/{staged,unstaged,working-tree-vs-fbba575e}.patch`.
- Then commit the merge ("Merge claude/main-bridge-easing into claude/s2-detach-fix (bridge timing ported to schema 2)"), plus this handover.

## S2 after the merge
1. **Instrument stream** (probe; not started): `painted` = ancestor opacity product + display/visibility + rect + readyState, sampled pre-paint (ResizeObserver per rAF); zero-tolerance in `score_continuity`; Pass G advance legs scored per frame with plan-derived "go-to source, advance across" cases; red controls: `--core-variant no-pin-hold` (D1 [1,3,4], D5 sequential ≈108 frames) and unmodified core; positive control = injected N hidden frames counts exactly N. Design: `output/evidence/s2-dev/pingap/SUMMARY.txt` + the pin-gap investigation report recorded in memory.
2. **Open:** D5 #5→#6 14-frame gap (pre-existing, not pins) — the new instrument will surface it; investigate. Red sets that might move with the pin hold: D4 `wrong-instance`/`fifo-reuse`, D5 `fifo-reuse` (re-register only with a measured reason). Carry-cover on S2 D1 with easing failed the 5 px strip rule at 7–8 px (poster corner marker) — check with the synced gate; GL-quad suppression via `patch_player` is the hardening if needed.
3. Full suites, Astra review, then the FULL RE-RUN on the final S2 head: Phases A (decks ×3 viewports), B/D1 (run_gates 3-wide incl. Pass G + carry-cover), D2, D3 (P2 main-vs-S2 interleaved), D4 (G2 seam), D5 (loop), Q6 (managed OBS 25/30, KBs, soak 4 min — owner pre-approved), then Q7 with the owner (Q7a external attach D1/D4; Q7b dashboard Keyer on D1–D5).

## Owner decisions added this session
- Main fix = (b) fix properly, incl. the new Keynote player on a byte-level argument; owner said "apply" to the blocked bridge-timing patch.
- Pin hold accepted. Owner napped with "trust ur decisions; try to do the full re-run" (Q6 managed OBS counts as approved; Q7 needs the owner).
- Coordinator calls made under that delegation: restore the P2 fixture's slide-3 transition slots; S2 bridge timing = narrow reader + R10 (not main's helper).

## Machine
- Nothing running at handover (gate driver and the S2 port agent were stopped; no Chrome left).
- One heavy job at a time machine-wide; run_gates refuses above load 4 (driver waits for < 3).
- Subagents may be blocked by a session-isolation hook from writing into a worktree other than the session's; spawn implementers for the target worktree from a session rooted there, or apply their patch with the owner's word.
