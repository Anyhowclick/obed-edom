# Keynote alpha HTML playback — handover 2026-09-17

Worktree: `p2-alpha` (`feat/keynote-alpha-p2-html-mm` draft). No Keynote edits this session.
Owner fixture: adversarial Minimal Alpha_DSK. P3 stays unwired.

## OPEN 1 — first TODO for the next agent

> **RESOLVED 2026-09-18** — all three findings below are addressed; see “RESOLVED 2026-09-18”
> and “OPEN 2” further down. Kept here for the record.

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

## RESOLVED 2026-09-18 — the three OPEN 1 findings are addressed

Live re-run on the same adversarial export (source unchanged), then Codex gpt-5.6-sol L3 review.

1. **Restart gate** — `score_restart_movie_from_observations` now requires the near-zero clock to
   be observed on `sceneHash >= slide_min_hash`; selection prefers an identified decoder that both
   near-zeros and progresses (a stalled first candidate no longer masks a genuine restart); id-less
   rows can no longer stitch a stalled + a continued decoder into a pass. 34 offline tests
   (null + positive + competing-candidate + id-less controls).
2. **Overlay** — remount restores the measured authored rect (authored-footprint fallback for
   origin-only boxes), restores the authored z-index instead of max z, appends to the top-level
   stage (no authored-parent drift), and the hashchange listener self-removes after its own
   transition. Movies land at `109,795` / `109,500`; green shape + black sentinel visible; no
   max-z blanket, no `0,0` pinning, no drift (`runs/primary/after-1to2.png`).
3. **Through-MM capture** — fire ArrowRight (no blocking wait) + one nudge, dense-capture through
   the cut, confirm the hash flip after (ChromeCdp has no concurrent recv).
   `visibleColourPatternThroughMagicMove` = **True**.

Live scorecard: decode True, through-MM True, reachedSlide3 True, restartBoundaryPerMovie
**inconclusive** (deliberate Start-Movie restart still unwired — honest, not a false pass).

## OPEN 2 — for the next agent (Codex residuals, not regressions)

- **Composition, not just placement.** A detached `<video>`’s stacking context is gone; the remount
  still occludes the green shape where they overlap. Needs true stacking-context restoration.
- **Through-MM motion is not tied to the flip.** Continuously-playing bars could satisfy the gate
  via pre-nav motion + a late nav. Fix: record per-frame hash inside the *shared* dense window
  (`_dense_after_click` in `p2_recovery_html_adversarial.py`) and require motion across the flip.
- **Motion scorer gap.** `score_visible_movie_motion` accepts a mid-window disappearance (45%
  changing pairs) — does not prove continuous visibility.
- **Listener ordering (live-only).** If detach runs after a transition’s `hashchange`, the
  self-removing listener can still remount once on the next, unrelated transition.
- **Deliberate restart still unwired** — the only red scorecard line; tie it to Start Movie.

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
