# Stage B review r5 — Opus 5.5 high, commit 3ee6f7f9

Round 5 is the last round that folds mediums and lows this session. Scope: `git diff c047e271 3ee6f7f9`.

What I ran:
- Targeted suites: 115 probe/contract feed, hold, instrument and `score_verdicts` tests, all green.
- The Node end-to-end test with every verdict printed, in four variants:
  - as committed;
  - with the hash moved to `atScene` at context creation (chain moves and hold moves);
  - with a realistic mid-move stand-down (the after-feed path: claim at idle, two fed frames, decoder presents
    `last upload + 1`, stand-down and pause, two unfed frames, resume);
  - with a fake GL that snapshots the uploaded frame instead of referencing the live decoder.

## r4 findings
| r4 | Status | Evidence |
|---|---|---|
| Major 1 claim attribution | **closed** | `entryForObject` picks the upcoming scene's entry (`mm_feed_instrument.py:330-333`). Claim/stand-down `serial` is set only when the decoder's move matches that `atScene` (`:337-338`). `wrap()` patches null serials in claims and stand-downs (`:186`). Contract `_id_or_null` (`contract:811-814`). E2E claims at idle before `getContext`, plus a @10→@12 chain: serials `chain-10 → 4`, `chain-12 → 5`. In my variants, attribution holds when the hash reads `atScene` during the move. |
| Med 1 after-feed expiry | **closed** | No cap; polls from `atScene-1` (`:314-316`). `finishContext` marks the tamper failed when the target context finishes untriggered (`:286-289`). E2E runs 601 ticks first. Residual: Low 1. |
| Med 2 contract not run | **closed** | `score_verdicts` validates the producer once and each record per entry; feed errors null only feed entries (`probe:4219-4241`). Test `test_score_verdicts_validates_feed_contract_per_entry`. |
| Med 3 e2e hold path | **partially** | Departure exact hold, kill switch, pre-departure stand-down, pixel-read red with full coverage, D7 counter and chain are all added and assert real verdicts. But the fake GL texture is a live reference to the decoder, so the test cannot show retention (Medium 1). |
| Low 1 pre-move stand-down | **closed** | Only stand-downs at or after the move's first frame select `standDown` (`:494`, `:517`). E2E `carry-hold` (stand-down before departure) scores departure: `holdFrame` True, `posterHold` True. |
| Low 2 dropped media | **closed** | `mediaDropped` per scene (`:360`, `contract:792-797`); a non-zero count sets `media_complete` false (`:540-542`). Test included. |

## Printed verdicts

**As committed:**

| Entry | Mode | `feedLive` | rider | labels | artwork | `holdFrame` | `posterHold` |
|---|---|---|---|---|---|---|---|
| alpha | continuous | True | True | True | True | — | — |
| broken | continuous | **False** (via the reads, with full coverage) | — | — | False | — | — |
| counter | continuous | True (counter reads) | — | — | — | — | — |
| chain-10 / chain-12 | continuous | True | — | — | — | — | — |
| hold | departure | — | — | — | — | True | True |
| killed | departure | — | — | — | — | **False** | True |

Tamper: `applied` True on `alpha`.

**Hash = `atScene` during the move, no tamper:** identical verdicts, so attribution does not depend on hash timing.
**With the after-feed tamper:** the tamper never triggers. It fails, and every entry is `unavailable` (Low 1).

**Realistic mid-move stand-down (chain-14):**

| Fake GL | `holdFrame` | `posterHold` | `feedLive` |
|---|---|---|---|
| Committed (live reference) | **False**: matched 73 = the decoder's current frame, target 72 | True | — |
| Snapshot at upload | **True**: matched 72, 72, 72 | True, `resumptionDiscontinuity 1`, `exactHeldPlusOne False` | False (mode `standDown`) |

The instrument is correct here. The committed fake is the problem (Medium 1).

## Blocker
None.

## Major
None.

## Medium
1. **(test fidelity: the fake hides retention)** `tests/test_live_continuity_probe.py`, fake `texImage2D`
   (`sources.set(bound[active], source.drawSource || source)`). The fake texture keeps a reference to the live decoder,
   and `paintSource` asks it for its pixel at draw time. So the GL always shows the decoder's current frame, never the
   uploaded one.
   - The departure hold passes only because the decoder stays paused.
   - The kill switch goes red only because nothing was uploaded.
   - The registered `after-feed → holdFrame True` path scores **False** under this fake. With a snapshot fake it scores
     True.

   So the test cannot catch any defect where the GL shows a frame other than the one uploaded (late or extra uploads,
   uploads after resume).
   Fix:
   - In the fake, snapshot the frame at upload:
     `const s0 = source.drawSource || source; sources.set(bound[active], Object.create(s0, {__obedPresentedFrames: {value: s0.__obedPresentedFrames}}))`.
   - Add the mid-move stand-down case: claim at `atScene-1`, two fed frames, `present(last+1)`, `onStandDown` +
     posterHeld pause, two unfed frames, resume at `last+2`.
   - Assert `holdFrame True`, `posterHold True` with `resumptionDiscontinuity 1`, and `feedLive False`.

## Low
1. **(edge, timing-dependent)** `afterFeedTamper` (`:314-316`) looks for uploads only while `scene() === atScene-1`. If
   the hash reads `atScene` during the move, the tamper never triggers and the after-feed arm comes back all
   `unavailable` (reproduced). This is fail-closed, and the core's comments suggest the hash settles after the move, so
   it is unverified rather than wrong.
   Also, the rVFC trigger callback (`:321-324`) can set `applied: true` after `finishContext` has already set `failed`.
   The tamper then counts as applied although it acted outside the target move.
   Fix:
   - Gate polling on the target context being live (`S.live` has a `G` with `atScene === tamper.atScene` and
     `!G.closed`), not on the hash.
   - In the trigger callback, return without applying if `S.tamper.failed` or the target context is closed.
2. The e2e chain reuses one `objectId` (`alpha`) for the @10 and @12 entries. Real chains use the destination
   instance's id as the next source. Using distinct ids per hop would exercise the realistic path, including
   `decoderFor` re-resolution across the hop.

## Scorer inventory — how missing/ambiguous input scores (after this fold)
| Scorer | Missing / unreadable | Ambiguous | Partial / unattributed | Notes |
|---|---|---|---|---|
| `score_feed_live` | mode None/unavailable, reads, bound, < 2 presented, gap → None | dSep < floor → None | `complete` / contract → None | red via reads or coverage only on readable evidence |
| `score_no_rider_above_canvas` | unreadable → None | — | coverage / `complete` → None | — |
| `score_labels_over_feed` | null slope → None unless a readable red | low spread → None | coverage / `complete` → None | — |
| `score_hold_frame` | bound, target, reads, re-upload census, overflow → None | margin < constant → None | `complete` → None | instrument correct for mid-move stand-down; untested by a retaining fake (M1) |
| `score_poster_hold` | fields, overflow, dropped callback, unreadable clock → None | — | `complete` / dropped media → None | missing pause → red only if the clock moved |
| `score_artwork_above` | `v` absent / no rows → None | — | `complete` → None | — |
| `verdict_records` / `score_verdicts` | tamper not applied → `unavailable` | — | visits → None; contract per entry | after-feed gated on hash (L1) |

Evidence-as-verdict sweep: no path turns missing, partial or unattributed evidence into a green or a red. Moving
claims, stand-downs and departures to their real times changes no verdict; only the after-feed trigger depends on hash
timing.

Verdict: no major or blocker. Remaining items are one test-fidelity medium and two lows. Counts: blocker 0, major 0,
medium 1, low 2.
