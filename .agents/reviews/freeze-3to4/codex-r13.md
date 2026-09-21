Verdict: `FAIL`

## BLOCKER

None.

## MAJOR

1. [p2_recovery_html_adversarial.py:4251](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4251), [p2_recovery_html_adversarial.py:4582](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4582), [p2_recovery_html_adversarial.py:4625](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4625) — **(b), r12 MAJOR 1 retained-evidence class.** `captureId` is minted once inside `_capture_3to4_snapshot` and copied into the snapshot header and raster evidence. Both copies can therefore be stale together. Replacing B’s complete `footprintFullyLive` block and header ID with A1’s produces `PASS`: all raster numbers, hashes, and IDs agree, while isolation compares only the derived green Boolean. A dead B burst can be hidden by a co-stale pair.

   Smallest sound fix: mint expected arm identities in `_run_freeze_bracket`, retain an arm-labelled bracket manifest outside the snapshots, pass the expected ID into capture, and require manifest agreement plus three distinct arm IDs. Add the complete-block-plus-header swap regression.

2. [p2_recovery_html_adversarial.py:1972](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1972), [p2_recovery_html_adversarial.py:4703](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4703), [p2_recovery_html_dissolve_live.py:251](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_dissolve_live.py:251) — **(b), r12 MAJOR 3 / r11 MAJOR 2 incomplete-evidence class.** The page-side paint rules themselves are sound: detached, `display:none`, zero-size, zero ancestor-opacity product, engine-hidden, and wholly offscreen elements cannot paint the on-screen footprint. Decoder 6 is genuinely supported by captured evidence—opacity product 0, `checkVisibility == false`, destination-sized rect, and `suppressed34 == true`.

   Python nevertheless trusts the derived `videos[*].visible` Boolean. An overlapping entry with `attached=true`, opacity 1, `checkVisibility=true`, a non-zero on-screen rect, but stale `visible=false, hiddenBy="hidden"` is skipped and the bracket still returns `PASS`. `hiddenBy:"detached"` on pool entries is likewise stamped rather than derived.

   Smallest sound fix: retain the necessary raw CSS/viewport fields and rederive `visible`/`hiddenBy` in Python, requiring exact agreement. Accept pool `detached` only with retained `inDocument == false`; synchronously attached pool entries must be corroborated by their DOM census entry.

3. [p2_recovery_html_adversarial.py:3881](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3881), [p2_recovery_html_adversarial.py:5003](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:5003), [test_p2_adversarial.py:4104](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:4104) — **(b), r12 MAJOR 2 positional-null class.** The total/run limits have no count headroom, but position does: one null is accepted anywhere, and edge nulls require no bracket. A pure probe moving the sole null from position 0 to pre-flip position 10, between indices 57 and 63, still returns `PASS`. If the missing value was 0, both restart deltas are erased while the endpoint bridge appears as a plausible `+6`.

   The normal leading null also has no decoded pre-key bracket, so an immediate seek/reset can disappear before sample 1. `NULL_BRIDGE_MAX_STEP=60` additionally has deliberate semantic headroom over the measured maximum 12.

   Smallest sound fix: admit only the measured position-0 shape, capture a decoded pre-key badge sample, and validate the leading miss against that sample. Reject trailing/interior nulls unless adjacent full-series evidence proves the omitted transitions individually.

## MINOR

1. [p2_recovery_html_adversarial.py:334](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:334), [p2_recovery_html_adversarial.py:1999](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1999), [p2_recovery_html_dissolve_live.py:214](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_dissolve_live.py:214) — **(b), r12 MINOR 4 minimal-comment class.** The two old narratives were removed, but this range adds new production calibration transcripts, review IDs, and extended failure histories.

   Smallest fix: retain concise behavioural contracts and move measurements/history to plan §10.17–§10.18.

2. [p2_recovery_html_adversarial.py:1694](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:1694) — **(c), edge-case/hygiene.** PNG decoding is fail-closed as claimed, but the alternate `zlib-u8` path performs unbounded decompression before checking the expected pixel count. A corrupt compressed artifact can exhaust memory instead of returning `None`.

   Smallest fix: use `decompressobj().decompress(blob, h * w + 1)` and reject excess output, tails, or incomplete streams.

## r12 disposition

- MAJOR 1: fixed contract constants and complete tolerance-zero comparison closed; arm provenance remains open via MAJOR 1 above.
- MAJOR 2: count/run and settled-window limits closed; positional/edge absence remains open via MAJOR 3.
- MAJOR 3: owner-gap length, identity brackets, and geometry are closed; the trusted paint decision remains open via MAJOR 2.
- MINOR 1, 2, 3, and 5 are closed: PNG checks, list-based exact-one clock, captured `advanceSettle`, and the single positive allowlist are present.
- MINOR 4 remains open.

For suite time, derive moving continuity once per arm per `_score_freeze_control` invocation and pass those three local results into `_moving_continuity_ok` and `_isolation_view`. Re-derive on every new scorer invocation because the sweep mutates snapshots in place; do not use a cross-call identity cache. The content-keyed raster cache can remain, preferably with a contract fingerprint in its key.

The remaining risk is **not edge-case-only**.