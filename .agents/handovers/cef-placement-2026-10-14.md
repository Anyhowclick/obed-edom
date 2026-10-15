# CEF/OBS placement calibration — follow-ups after merge (2026-10-14)

Landed in #278 (merge `b768f3f9`). Plan: `.agents/plans/keynote_live_cef_placement.plan.md` rev 3.3 (§11.5 amended 2026-10-14,
§12 status + review log). Evidence (results only) `output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-1{3,4}/`;
the qualifying run is `cef-placement-live-2026-10-14/live6` (25 fps ×2, 30 fps ×2). Run-time measurement:
`.agents/reviews/cef-placement-2026-10-13/speed-investigation.md`.

## Open items

1. **DeckLink field test** with a configured device: Keyer output → Recalibrate, then a movie-slide freeze. The configured-device
   `decklink_preview_output` response is untested (the precheck only knows the no-device 600 response).
2. **Qualification run time:** restructured 2026-10-15 (plan `.agents/plans/keynote_live_obs_run_restructure.plan.md`,
   status at its end): one 25+30 pair now qualifies live in ≈19.6 min (was ≈45.6 per pair); DEV renderer loop ≈6 min.
   Open: post-quit scoring pool (≈85 s/rate pixel scoring) if more speed is wanted; P §5 failure/cancellation recording
   mismatch (owner: separate follow-up).
3. W5 tone map / non-identity application (the take stays identity; `tone` is REPORTED). DX-1 `cut` capture timing (dissolve
   follow-ups; `cut` REPORTED). Frac letterbox-offset rounding: the frac quad rounds `cy-r.top`; no arm checks frac pixels with a
   fractional letterbox offset (DSK 43-video).
4. Unfolded review lows (harness/scorer, none can MATCH a defect):
   - (fixed by the restructure, 2026-10-15: listed-but-missing DSK attempts and aborted stubs are INCONCLUSIVE rows; a genuine
     attempt mismatch is FAIL; attempts carry `identity`; `timing_summary` includes nested DSK time.)
   - nooffset overlap census lists only build-event textures (misses movie-group siblings and slide canvases; 3F22 overlaps the x
     holder harmlessly); no offline end-to-end x-axis nooffset outcome test (roll all four channels).
   - private `_ffprobe` import; misleading "holder frame indices are missing" when fps is unavailable; rVFC rows trimmed at 900.
5. Parent items: r13 #3 Chrome stale grant with the O4 CEF residual; scaled stages; Q6 bridge.

## Gotchas

- `--arm placement` runs one 25+30 pair (`--takes 1`); `--tier dev [--dev-profile renderer|harness] [--rate N]` is the fast
  DEV loop (exit 10, never qualifies); `--score DIR` on a DEV out dir re-scores renderer pixels without re-acquiring.
- A fresh worktree must symlink `output/{fixtures,evidence,bank}` to the main checkout before a placement run
  (`dissolve_probe.DECKS` reads the worktree's `output/fixtures`).
- Write Codex briefs with the Write tool or a quoted heredoc: an unquoted heredoc runs backticks as commands. In zsh, `$r:src` is a
  modifier — use `${r}:path`. Codex `workspace-write` blocks loopback sockets: run `tests/test_managed_obs.py` yourself.
