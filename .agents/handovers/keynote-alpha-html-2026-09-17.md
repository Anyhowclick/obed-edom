# Keynote alpha HTML playback — handover 2026-09-17

Worktree: `p2-alpha` (`feat/keynote-alpha-p2-html-mm` draft). No Keynote edits this session.
Owner fixture: adversarial Minimal Alpha_DSK. P3 stays unwired.

## OPEN 1 — first TODO for the next agent

Real progress, but “fully green” does **not** hold. Three blocking findings:

1. **Restart still falsely passes.** The accepted decoder starts before the target
   boundary: `0.297s` on `#5` → `1.958s` on `#6`. Owner reproduced a passing result with
   uninterrupted playback and no target restart.
   Gate: [`score_restart_movie_from_observations`](../../src/obed_edom/html_alpha_probe.py)
   (near-zero allowed pre-`slide_min_hash`). One unit test explicitly blesses that pattern.
2. **The overlay breaks the composition.** Hardcoded remount slots + `z-index: 2147483000`
   cover ~55% of the black test rectangle, obscure the green translucent shape, and leave
   an extra movie upper-left. See
   `output/p2-recovery/html-decode-probe/runs/primary/after-1to2.png`.
3. **“Through Magic Move” samples start too late.** Capture begins after waiting for
   `#1→#2`, remounting, and another `0.35s`
   ([`p2_recovery_html_decode_probe.py`](../../scripts/p2_recovery_html_decode_probe.py)
   ~line 358). Moving frames afterward cannot prove uninterrupted visibility *during* the
   transition.

**Established:** H.264 decoding and visible moving pixels *after* remount.
**Next implementation:** preserve the authored movie’s placement, layering, and lifetime;
tie restart to its actual Start Movie event — not pre-boundary clocks or fixture overlays.

## What landed (keep; do not treat as green)

- HEVC Untitled.mov = audio-only (`videoWidth=0`); disposable H.264 under same filenames
  proves decode.
- MM tears `<video>` out of the DOM; street poster / WebGL texture remains.
  Remount-after-detach is an overlay workaround, not Keynote restoring the layer.
- Gate hardenings that stay: fixed `EXPECTED_MOVIE_KEYS`, mandatory decoded width,
  wall/media-spaced progression, prefer `w>0` over null-width dupes, empty-crop motion
  reject, `preserveGeneration` on `clear()` so pre-clear continue clocks cannot
  `reuse-decoder` into a later createElement.
- Scripts: `p2_recovery_html_adversarial.py`, `p2_recovery_html_decode_probe.py`,
  preserve path in `p2_recovery_html_dissolve_live.py`.
- Plan: `.agents/plans/keynote_alpha.plan.md` (corrected: not fully green).

## Do not

- Touch Keynote / owner source decks.
- Wire P3.
- Call the decode probe “fully green” until OPEN 1 is closed.
