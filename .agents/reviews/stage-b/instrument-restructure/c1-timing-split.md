# C1 timing split (plan §3 first action, gate 2), 2026-10-16

**Setup**
- Tree: `claude/stage-b-arch` @ `1a421de2`, on Chrome 155.0.8059.79 headless.
- Deck: the repaired Alpha (`q7-fixtures/Alpha`), feed on, arm A only (`--skip-arms B,C,V,Voff,attach`).
- 12 serialized runs, one Chrome at a time.
- Load average (1 min): the first run started at 36.9, while my full suites were winding down. The other runs started at 2.9–12.2. `10-head-repeat` reproduces `01-head` at low load.
- The harness was scratch only: an exact-string swap of `mm_feed_instrument.INSTRUMENT_JS`, with `performance.now()` splits per capture. Codex GPT-5.6 Sol high wrote it and the coordinator reviewed it. Every replacement matched once, and `node --check` passed.
- Source sizes seen: 484×272, 582×327, 714×402, 715×402, 824×463 and 1280×720.

| Run | Capture | `willReadFrequently` | `callbackCostP95Ms` | drawImage p50 / p95 (ms) | getImageData p95 | Scene 8 / 10 / 12 cadence median (ms) |
|---|---|---|---:|---|---:|---|
| head (2 runs) | 26 draws into 81×30 | true | **115.6 / 112.6** | 0.2 / **114.4** | 3.2 | **100 / 100 / 200** |
| old `1df31c33` | 26 draws | true | 115.0 | — | — | 100 / 100 / 217 |
| parent `24b1c91d` | none before move | — | 2.6 | — | — | 33.3 / 16.7 / 33.3 |
| wrf-off | 26 draws | false | 5.7 | 0.2 / 0.7 | 4.2 | 33.3 / 16.7 / 33.3 |
| single-96 | 1 draw, 96 px wide | true | 7.6 | 0.1 / 6.8 | 1.7 | 33.3 / 16.7 / 33.3 |
| single-192 (2 runs) | 1 draw, 192 px wide | true | 7.2 / 7.1 | 0.1 / 6.7 | 1.7 | 33.3 / 16.7 / 33.3 |
| single-384 | 1 draw, 384 px wide | true | 8.0 | 0.1 / 7.3 | 1.7 | 33.3 / 16.7 / 33.3 |
| **single-192-wrf-off** | **1 draw, 192 px wide** | **false** | **2.5** | 0.1 / 0.2 | 2.7 | **33.3 / 16.7 / 33.3** |

DOM reads (p95 0.1 ms) and decode/maths (p95 0.1 ms) are negligible in every variant.

**Fidelity**
These runs computed head and single-W in the same callback, so their timing is invalid.
- `counter` agrees on 483/483 comparisons at 192 px and 472/472 at 96 px.
- The patch `vectors` differ by up to 113 (192 px) and 146 (96 px). This is expected, because the single-draw footprint is a different area from the 9×9 patch draws.
- So `holdMatch`/poster separation has to be re-proven with positive and red controls before the single-draw vectors replace the current ones (plan §3: "Pixel thresholds change only from demonstrated positive/red separation").

**Findings**
1. The observer effect comes from `willReadFrequently:true`. That canvas is CPU-backed, so each `drawImage` of a video frame can stall for about 115 ms. getImageData, DOM reads and decode are not the cost. This confirms the plan's hypothesis that CPU-backed canvas draws read back full video frames.
2. Turning `willReadFrequently` off restores the parent's cadence even with 26 draws, but the p95 of 5.7 ms misses the ~4 ms target.
3. Only **one 192 px draw + one read with `willReadFrequently:false`** meets both targets: p95 2.5 ms (≤ ~4) and scene medians ≤ 33 ms. 96 px and 384 px give no advantage.
4. A single draw with `willReadFrequently:true` still costs about 7 ms at p95, so both changes are needed.
5. The unbriefed branch `claude/stage-b-c1-unbriefed` (`0abf8772`) made exactly these choices: 192 px, a single draw, `willReadFrequently:false`. Its choices are now justified by measurement. Its code still needs review, and the vector/hold separation must be re-proven.

Every run's probe status was fail or inconclusive (for example, head arm A b3to4 / b6to7 / b7to8 carry=False). These are scoring outcomes outside this timing split.
