# C1 gate 2 record (partial), 2026-10-16

Trees: C1 = `claude/stage-b-c1` @ `a71229e4` (r3 READY + `claude/stage-b-arch` @ `69c84865`); pre-C1 = `69c84865`.
Chrome 155.0.8059.80 headless, AC power. Results: `output/evidence/stage-b-2026-10-13/c1-gate2/`.

## Timing pairs: PASS
Alpha feed-on 1920 (q7 Alpha fixture), serialized and interleaved old/C1 ×3, each start gated on 1-min load < 4 (20:52–20:59).

| | `callbackCostP95Ms` | scene 8 / 10 / 12 median (max) |
|---|---|---|
| pre-C1 | 106.3 / 108.7 / 108.9 | 100 (133) / 100 (133) / 200 (233) |
| C1 | **3.7 / 3.0 / 3.2** | **33.3 (33.4) / 16.7 (16.8) / 33.3 (33.5)** |

Both trees report the same two status reasons in all six runs (Alpha arm A b6to7 / b7to8 `wa0125` carry=False,
`missingSamples` inside the glInterval: C3's GL-excuse fold), so C1 changes no Alpha continuity verdict.

## Full run_gates round on C1 (full tier, GATE_JOBS=3, 20:59–21:20, wall 1251 s): 25 FAILED, all MM-FEED
Every host gate, host red arm, Pass G, paint control, carry-cover and P2 arm MATCHed. The 25 failures are the MM-FEED arms.
A same-fixture baseline on the pre-C1 tree (D7 feed-on-1920, D7 from-only, Alpha_DSK feed-on-1920, Alpha_DSK feed-off-5s,
on this round's staged `D7-html` and `alpha-dsk-repaired`) reproduces them identically:
- **D7/D7s:** `feedLive` None on every counter carry in both trees. GL counter reads are `coveredByLaterDraw: true`
  with flat 66.7 levels (`marker`): the open F4 item (2). C1's cost fix does not change it; it is coverage, not cost.
- **Alpha_DSK (repaired gate fixture):** every carry inconclusive in both trees: `untitled-h264` "movie never decoded",
  the rest "the core feed seam did not identify a feed or departure mode". The q7 Alpha fixture scores normally.

## Open (blocks C1 gate 2 completion)
The feed-control colours cannot be re-proved, and the holdMatch/poster separation cannot be re-shown, until the MM-FEED
baseline is green on the pre-C1 tree. Root cause not yet diagnosed (fixture, Chrome .80, or a stage-b-arch regression).
D1 obligations (D7 crossfade/from-only, a positive GL counter decode) stay open for the same reason.
