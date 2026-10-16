# Pre-draw rider exemption hardening (2026-10-16)

This follows `5422f4ec`, the owner's "skip pre-first-GL-draw frames" rule. Codex GPT-6 Astra critiqued that rule (relayed by the placement session; the full text is in the placement session's notes). The owner chose Python-only hardening now; the geometry work comes later.

## Rule (`scripts/mm_feed_instrument.py` `_visit_record`)
- The leading move frames with draws == 0 are exempt only when all of these hold:
  - a frame with draws > 0 follows them in the same visit;
  - `preDrawMs` ≤ `PRE_DRAW_GRACE_MS`;
  - no accepted stand-down for the visit has `t` ≤ the first drawn frame (stand-downs before the first frame count too).
- Otherwise every row is scored.
- A visit that never draws scores None.
- Coverage still requires every move frame.
- New fields: `preDrawMs`, `exempt`, `exemptedVisibleSamples`.
- **`PRE_DRAW_GRACE_MS = 320.0` (owner, provisional).** The stored D7 b0to1 cold-start prefixes are 47–60.5 ms (1 frame) and 176–315 ms (2 frames). Astra's 50 ms brought back 28 false reds. Tighten this after the F4 deck-load warm-up.

## Review
- Implementer: Codex GPT-5.6 Sol high. Reviewer: Opus 5.5 high.
- r1, on the 50 ms version:
  - major: the 50 ms budget brings back the cold-start false red. Owner set 320 ms.
  - medium, folded: a stand-down before the first move frame was ignored.
  - low, folded: an unreachable adjacency condition.
- r2: no major or blocker.

## Replay at 320 ms
- 114 carry-visits across 40 stored producer files, all identical to `5422f4ec`.
- Every departure-fixed carry is True and exempt. The closest margin is 5.0 ms (d7-on-A, 315.0 ms).
- `ctl-departure-early-hide` stays True; `ctl-overlay-ride` stays False (partial replay).
- Alpha `preDrawMs` can't be computed, because the stored frames were trimmed.

## Accepted limits (owner, provisional)
- The 5 ms margin is thin: a slightly slower cold start under load turns b0to1 red again.
- An overlay that occurs only during startup, for up to about 320 ms, is accepted until the geometry check lands.

## Deferred: plan through the roster
- Astra's 1 px source-rect check (rider `sourceRectError`), a JS context `firstDrawAt`, and the producer contract update.
- A red control for a moved decoder during startup only.
- Fresh Alpha/D7 captures to validate the tightened budget.
