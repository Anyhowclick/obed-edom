# CEF/OBS placement calibration — handover (2026-10-14, evening)

Branch `claude/cef-obs-placement` (local, **not pushed**, no PR), worktree `.claude/worktrees/angry-mestorf-abe88f`, merged with
`origin/main` at `dd8c8753`. Plan: `.agents/plans/keynote_live_cef_placement.plan.md` rev 3.3 (§11.5 amended 2026-10-14, §12 status).
Reviews, briefs and implementer reports: `.agents/reviews/cef-placement-2026-10-13/` (keep until merge; then gate records + review log).
Evidence `E=output/evidence/s2-dev/dissolve-alpha-2026-10-11` (main checkout): `cef-placement-live-2026-10-13/` (live1–3, 2A raw)
and `cef-placement-live-2026-10-14/` (live4–6 results; `live6/raw-out` is the qualifying run's raw output, keep until review closes).

## State

- Live-qualified on the final code: live6 on `f8059380` (25 fps ×2) and `398ddd1d` (30 fps ×2), all valid, no sleep. 30 fps PASS live;
  25 fps PASS on offline rescore once the Chrome-row scorer fix landed (29/29 arms MATCH per take; `live6/offline-score.log`: 188
  sessions PASS, W5 INCONCLUSIVE "rows incomplete" — known, reported). One-rate runs used `live6/qualify_rates.py` (sets `MMO_RATES`).
- Owner decisions today: inherited INCONCLUSIVEs are not REPORTED for this PR (the instrument was fixed instead); geometry-aware near
  strip; `cut` and `tone` REPORTED (identity take); edge-band and DSK cells fixed in this PR; DSK decoders aliased to the pinned
  counter; frac edge residual → product fix (no relaxation); no committed fast tier; review stop rule extended (mediums folded r4–r5
  in the live3 series).
- Fixes found by today's live runs: paused-animation validator; near-clip geometry; edge-band foreground; fractional displaced
  attribution; nooffset x/y at -80; frac boundary redraw + exterior-centre refusal (product); DSK VideoFrame identity and session-level
  recapture; m-fg-cef frozen_region control; ownership "unknown" retry (product) and labelling; Chrome classifier rows.

## Open items (resume in this order)

1. Full suites on `398ddd1d`: 3.12 and 3.10 floor 10986 passed, 38 skipped (all environmental), 1 xfailed; dashboard tsc + maps clean,
   test:ui 329/330 — the 1 red (`resize-offline-hides` "fresh Propose carries offline hides off") passes 6/6 ×3 alone and the branch
   does not touch Resize (load flake).
2. **Owner check** with a real DeckLink: Keyer output → Recalibrate, then freeze on a movie slide (the configured-device
   `decklink_preview_output` response is untested; the precheck only knows the no-device 600 response).
3. PR (one integration PR; never merge without the owner).
4. Follow-ups (not this PR): restructure the full qualification run (speed investigation
   `.agents/reviews/cef-placement-2026-10-13/speed-investigation.md`: ~22 min target needs a §5/§11.6 evidence-model change —
   owner sign-off); W5 tone map / non-identity application; DX-1 `cut` capture-timing fix (dissolve follow-ups); frac letterbox offset
   rounding (`Math.round(cy-r.top)`, no arm checks fractional letterbox pixels — edgefix r2 low 3); unfolded lows recorded in
   `review-live5-r4.md`, `review-edgefix-r2.md`, `review-live3-r4.md`/`-r5.md`; r13 #3 Chrome stale grant with the O4 CEF residual;
   scaled stages; Q6 bridge.

## Gotchas

- `managed_obs_qualify.py --arm placement` always runs both rates; to split, SIGINT the **python** pid after the 25 fps take line
  (its finally quits OBS cleanly) and move the aborted stub run JSON aside — it reads `valid: true` with no sessions.
- Write Codex briefs with the Write tool or a quoted heredoc: an unquoted heredoc runs backticks as commands (an empty brief made
  Astra reply "What would you like me to work on?"). In zsh, `$r:src` is a modifier — use `${r}:path`.
- Codex `workspace-write` blocks loopback sockets: run `tests/test_managed_obs.py` yourself.
- Peers: S2 follow-ups (Stage B, Q7 OBS) and the PDF page fix session coordinate windows by "need window"/"done".
