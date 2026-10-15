# CEF/OBS placement calibration — follow-ups after merge (2026-10-14)

Landed in #278 (merge `b768f3f9`). Plan: `.agents/plans/keynote_live_cef_placement.plan.md` rev 3.3 (§11.5 amended 2026-10-14,
§12 status + review log). Evidence (results only) `output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-1{3,4}/`;
the qualifying run is `cef-placement-live-2026-10-14/live6` (25 fps ×2, 30 fps ×2). Run-time measurement:
`.agents/reviews/cef-placement-2026-10-13/speed-investigation.md`.

## Open items

1. **DeckLink field test** with a configured device: Keyer output → Recalibrate, then a movie-slide freeze. The configured-device
   `decklink_preview_output` response is untested (the precheck only knows the no-device 600 response).
2. **Qualification run time** (~45 min for both rates): the measured plan for ~22 min needs a §5/§11.6 evidence-model change (three
   genuine calibration anchors, other rows with harness-injected grants, shared invariant controls) — owner sign-off first. No
   committed fast tier (owner). One rate: a scratch wrapper setting `managed_obs_qualify.MMO_RATES` (kept as
   `cef-placement-live-2026-10-14/live6/qualify_rates.py`).
3. W5 tone map / non-identity application (the take stays identity; `tone` is REPORTED). DX-1 `cut` capture timing (dissolve
   follow-ups; `cut` REPORTED). Frac letterbox-offset rounding: the frac quad rounds `cy-r.top`; no arm checks frac pixels with a
   fractional letterbox offset (DSK 43-video).
4. Unfolded review lows (harness/scorer, none can MATCH a defect):
   - offline `score_placement_runs` skips a listed-but-missing DSK attempt record — add an INCONCLUSIVE row; `placement_gates` drops
     missing attempt paths before the per-attempt evidence check; a genuine attempt mismatch is labelled INCONCLUSIVE not FAIL;
     attempts scored without `identity`; `timing_summary` omits DSK attempt script time.
   - nooffset overlap census lists only build-event textures (misses movie-group siblings and slide canvases; 3F22 overlaps the x
     holder harmlessly); no offline end-to-end x-axis nooffset outcome test (roll all four channels).
   - private `_ffprobe` import; misleading "holder frame indices are missing" when fps is unavailable; rVFC rows trimmed at 900.
5. Parent items: r13 #3 Chrome stale grant with the O4 CEF residual; scaled stages; Q6 bridge.

## Gotchas

- `managed_obs_qualify.py --arm placement` runs both rates; to split, SIGINT the **python** pid after the 25 fps take line (its
  finally quits OBS cleanly) and move the aborted stub run JSON aside — it reads `valid: true` with no sessions.
- Write Codex briefs with the Write tool or a quoted heredoc: an unquoted heredoc runs backticks as commands. In zsh, `$r:src` is a
  modifier — use `${r}:path`. Codex `workspace-write` blocks loopback sockets: run `tests/test_managed_obs.py` yourself.
