# Gate record r2: Chrome 155.0.8059.80 (patch auto-update), 2026-10-16

**Why:** Chrome auto-updated 155.0.8059.79 → 155.0.8059.80 at 08:53 on 2026-10-16 (found by Stage B gate 4). Owner:
"Requalify", and minor/patch builds auto-qualify (Stage B plan §4 amended; `live_run_validity.QUALIFIED_CHROME_MAJORS`).

**Product freeze:** `QUALIFIED_SNAP_MAJORS = (154, 155)` already grants 155.x, so nothing changes in code.
`scripts/chrome_requal.py --chrome <Stable 155.0.8059.80>` on `claude/stage-b-arch` @ `823acbef`, headless, AC power,
Low Power Mode off, run alone on the machine (19:30–20:16): **PASS**, all 32 arms ok (grant, channel, life-grant,
on/off/noblend, m-paused/off/on/hold/raw, the full `m-snap` matrix with twins). Gate-by-gate identical to the .79 fixture (`tests/fixtures/chrome_requal/verdict-155.0.8059.79.json`): PASS model, complement, no_dip, curve, monotone, handoff, frozen_frame, frozen_region, cost, grant, cvc; the same out-of-scope gates INCONCLUSIVE (overall INCONCLUSIVE in both, as at #262's merge). Output (results only):
`verdict.json` copied beside this record's evidence in `output/evidence/stage-b-2026-10-13/c1-timing/requal-155.0.8059.80-verdict.json`.

**Stage B kernel fact (same window):** video `drawImage` 1920×540 → 192×54 on a `willReadFrequently:false` canvas matches
an area average per cell (MAE box / bilinear / point: 3.9 / 23.0 / 47.3 on per-pixel noise; box lowest in every band).
Record: `output/evidence/stage-b-2026-10-13/c1-timing/kernel-155.0.8059.80.json`. C1 keeps the GL cell box average.
