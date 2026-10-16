# Handover: F4 deck-load movie warm-up, planning stopped for the night (2026-10-16)

The owner stopped the work at planning (~23:00, 2026-10-15). Nothing is implemented.
Branch `claude/trusting-aryabhata-f69fdc` = `claude/stage-b-arch` (`ed8e24e2`) + docs only.

## State
- **Evidence and owner decision:** `.agents/handovers/f4-faststart-measure-2026-10-15.md`. The owner agreed to
  take the deck-load warm-up forward and to drop faststart.
- **Plan:** `.agents/plans/keynote_live_movie_warmup.plan.md` is **r2**, awaiting owner approval.
  - r1: GPT-6 Astra high planner (raw copy and brief in `.agents/reviews/movie-warmup-2026-10-16/`).
  - Critique: one Opus 5.5 high round, NOT READY with 1 blocker and 3 mediums
    (`.agents/reviews/movie-warmup-2026-10-16/critique-r1-opus.md`).
  - All findings are folded into plan §0, which overrides §2–§6 where they conflict.
  - Not re-critiqued. Under the review stop rule a second critique round is allowed (≤ 3) if the owner wants it
    before approving.

## Design in one paragraph (plan r2 §0)
- `_program_html` serves one inline IIFE, injected after the overlay and **before** the continuity script.
- The IIFE captures `removeAttribute`/`load`, then creates a detached, muted, `preload=auto` video on the first H.264
  movie the deck references (slide order, each copy's own bytes).
- It releases once on `loadeddata`, `error` or a 5 s timeout, and exposes `window.__obedMovieWarmup={state,readyMs}`.
- Selection is `live_continuity.first_h264_movie`. The env switch `OBED_LIVE_MOVIE_WARMUP=off|auto` defaults to auto
  and raises on invalid values, like its neighbours. One `movieWarmup` log line is written at start.
- It applies whenever the deck has an H.264 movie, independent of continuity, in every output mode. Decks with no
  H.264 movie skip it.
- No export bytes, plan pins or `main.js` change. No refactor-owned file is touched.

## Owner calls open
1. Approve plan r2, or ask for a second critique round.
2. Invalid env value: raise (plan r2) or silently disable (plan r1).
3. A4 needs a managed-OBS go at implementation time; the earlier go covered only the measurement runs.

## Next (after approval), per the roster until 2026-10-27
1. **Implement.** Sol high implements (Codex `gpt-5.6-sol`, `-s workspace-write -C <impl worktree>`), one stream:
   `live_continuity.py`, `live_host.py`, tests and README.
2. **Review.** Opus 5.5 high reviews. Rounds 1–3 fold all severities.
3. **Acceptance.** A1–A5 per plan r2:
   - A2 headless ≤ ~50 ms (5 + 5 runs);
   - A3 feed-on b3to4 not-decoded ≤ 3;
   - A4 OBS ≤ ~80 ms (4 + 4 runs);
   - A5: one gate round at `GATE_JOBS=3` from a pinned worktree, then both suites.
   - Wrappers live outside the repo: `output/evidence/stage-b-2026-10-13/f4-faststart/tools/`.
4. **Ship.** One PR, no merge without the owner.
- Before implementing, rebase on `claude/stage-b-arch`. The instrument restructure may have moved the
  `mm_feed_instrument` pre-move-capture seam that the A2/A3 wrapper patches; if so, adapt only the outside-repo wrapper.

## Follow-ups (not in this increment)
- WebM/VP9-only decks: does a WebM warm-up warm the pipeline? Use the gap harness in `f4-faststart/gap/`. Default
  stays skip.
- Idle longer than 3 min (e.g. a 20-min pre-service hold): unmeasured.
