# Review live3 r2 — W6 fold 1 (Opus 5.5 high), 2026-10-14

Verdict: not ready for the live rerun; far/near positives and cut/tone profile ready.

- B1 blocker: `edgefg` (`_edge_foreground` → `_foreground`) puts inset textures + translucent square over the counter strip
  (strip 109.4–450.3 × 795.0–818.8); product draws foreground into the holder; `media_integrity` exempts only literal "fg" →
  m-snap-cef / wrongrule-cef (+twins) strip undecodable → INCONCLUSIVE live. Historic m-fg-cef holder strip is None. Synthetic
  painter paints only "fg" so the test can't catch it. Fix: move inset layers clear of strip rows/cols, one straddling a video edge
  by several device px; painter handles edgefg; assert strip decodes + interior and edge kept.
- B2 major: displaced attribution compares at integer jround(d); defect is fractional (phase ≈0.37 px on corrected near-x).
  Synthetic d=5.37 → worst 90 FAIL; historic residual 5–6 on 710 px at periodic vertical edges (phase artefact, not old geometry);
  τ is 4 (report said 2). Fix: per-channel bracket of live at floor/ceil(P+d_exact) ± τ; keep a discriminating check (d±2 FAIL);
  scorer row at d=5.37.
- M1 medium: nooffset-y degenerate (d_y≈795 > 268 content) → empty overlap → attribution PASS "clipped by geometry"; expected FAIL
  rests on 0.036 px y-phase (≤9 LSB) — may MISMATCH. Attribute explicitly that the holder matches the integer-phase backing, or
  owner accepts a weak y-negative.
- M2 medium: base cell no longer has a foreground crossing the holder edge (square crosses top by 0.5 css px → 0 device px);
  fold into B1.
- L1: m-tone-raw-cef now only REPORTED — report wording "identity negative" overstated. L2: near_clip_outcomes MATCH row synthetic
  (acceptable). L3: `_clip_near` assumes parent bounds origin 0 and no parent transform.
- DSK: reject recording-derived frames; alias both decoders to counter only with distinct frame identity (distinct seek offsets or
  two pinned counter movies), else swapped bindings undetectable; counter movie may be opaque vs alpha clips. Fallback: lengthen
  the DSK transition via the existing slide override; never lower the five-frame rule.
