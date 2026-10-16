# C1 code review r3 (Opus 5.5 high; code + tests; target `23778293`, r2 fold) — READY

No confirmed findings; every r2 finding (C1–C6, T9–T17) fixed by class. Scratch: `/private/tmp/claude-501/c1-review-r3/`.

- **Cost.** The fold's `cellMean` is byte-identical to the r2 reviewer's verified per-cell variant; warm counter reads
  0.13 / 0.45 / 0.61 / 1.34 ms median (1:1, DSF 2, 10°, 30°). The fold's own 1.47–1.92 ms figures were cold (JIT) runs.
  GL reads run in `finalizePixels` inside the product's draw, not in the rVFC callback, so they affect scene cadence,
  never `callbackCostP95Ms`; real `readPixels` cost is measured at gate 2.
- **Mutants.** 57 killed / 15 survived reproduces; same survivor set as r2. Pre-existing gaps (not equivalences), accepted
  under the stop rule as not verdict-changing: `bootstrap_prop_not_restored`, `domframes_unbounded`, flip × later-draw
  coverage (`f_safeuv_noflip`, `f_countersafe_noflip`), and `counterSafe` / sub-pixel fallback / fractional `dataBits`
  rows (all fail closed to None).
- **For gate 2.** The kernel was measured only at the integer 10× downscale (1920×540 → 192×54); non-integer ratios rely
  on the gate-2 positive/red separation re-proof on real captures.
