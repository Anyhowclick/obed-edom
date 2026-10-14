# Review live3 r5 — W6 fold 4 (Opus 5.5 high), 2026-10-14

Verdict: 0 blocker, 0 major, 1 medium; ready for the live rerun after M-1. Targeted 313 passed. BL-A verified on the real
13-decoder dump (ids 9/10, holder 0→9, 1→10; no wrong-binding path); `#t=5` link, directed delta, preroll skip (≤1 frame bias),
no counter wrap (1381 frames, 12-bit), ffprobe present (30.0 fps, fails closed if absent). Arms vs HEAD: intended only.

- M-1 medium (`dissolve_probe.py:237`, `:3339-3347`): holder-spacing ±3 frames only measures playback start skew (identity per
  holder already proven) and is tighter than the ±0.25 s time proof; a `#t=5` seek starting ~100 ms late makes a correct run
  INCONCLUSIVE. Fix: tolerance round(DSK_COUNTER_TIME_TOLERANCE_S × fps) (=7) and include both decoders' first rVFC presentation
  times in the problem message.
- Known deferred risk: DSK "4 mid frames < 5" — check first if DSK is INCONCLUSIVE live.
- Lows (not folded): private `_ffprobe` import; misleading "holder frame indices are missing" when fps unavailable; KeyError on a
  holder without `rect` in `record_dsk_counter_timing`; 900-row rVFC trim.
