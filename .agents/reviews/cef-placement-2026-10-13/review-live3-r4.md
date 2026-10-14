# Review live3 r4 — W6 fold 3 (Opus 5.5 high), 2026-10-14

Verdict: not ready (1 blocker, 1 medium). Targeted 313 passed. BL1, BL2 mechanism, M1 verified (nooffset-y on real p2bin: near-side
clip kept, strip outside canvas, defective holder luma diff 214 with attribution PASS, correct holder → INCONCLUSIVE; `#t=5`
reaches <video> src unmodified, served path/SHA unchanged, byte ranges served).

- BL-A blocker: `record_dsk_counter_timing` (`dissolve_probe.py:3181`) writes every `dump.vids` decoder (historic: 13, ids 0–12)
  but `media_integrity` (`:3262`, `:3282`) compares only the 2 bound decoders → always "missing or inconsistent" → DSK INCONCLUSIVE
  on every live run. Fixture has only 2 decoders. Fix: record only outgoing decoders (region + detach; historic 9/10), compare by
  paired decoder ids; table row with extra prior-slide decoders.
- M-A medium: one-frame tolerance too tight (`:3286`); historic decoder 9 first rVFC at 0.0333 (presentedFrames 2) → delta 4.9667
  passes only by rounding. Widen (≤0.25 s) or skip preroll; better also require the two holder strips' decoded frames to differ by
  150 ± a few frames.
- Lows (not folded per owner rule): synthetic correct-holder row overstates (live → INCONCLUSIVE); abs() delta not tied to clip
  1000002; anchor counts prove presence not call path; rv trimmed at 900 entries.
