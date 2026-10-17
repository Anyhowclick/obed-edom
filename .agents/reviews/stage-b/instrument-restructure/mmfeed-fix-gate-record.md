# MM-FEED fix: gate record, 2026-10-17

Branch `claude/stage-b-mmfeed-fix`, tip `adfeb552`.
It contains:
- the baseline fix `a25a5db5`, with r2/r3 test folds `72b33b38` and `628b4973`;
- merges of `claude/stage-b-arch` up to `9ede8e98` (C3 plus the owner decisions);
- `5664e960` (d): crossfade ambiguity is red;
- `adfeb552`: the strip2 counter-movie staging guard.

The earlier `a25a5db5` round was 13 red. Its raw outdir lived in /private/tmp and was lost in the 2026-10-17 reboot; only the log survives.

## Reviews
Implementer: Codex GPT-5.6 Sol high. Reviewer: Opus 5.5 high.
- (d) `5664e960`: r1 READY (2 medium and 4 low, all folded); r2 READY with no findings.
- Guard `adfeb552`:
  - r1 NOT READY. 1 major: the guard hashed every `*.mov` that existed, not the movies the plan references, so a missing referenced copy passed. 2 medium, 2 low. All folded.
  - r2 READY, 2 low, folded: the hint was moved before "; no run launched", and the key-set refusal was dropped because the plan-sha pin and the `wanted=None` mismatch already fail it closed.
- Mutants, each run and each failing `test_positive_control_an_existing_empty_outdir_is_accepted`:
  - (d): constant `crossfade: False`; `finish(False)` in place of `ok = False`; contract clause deleted.
  - Guard: `actual!=wanted` refusal deleted; missing-file refusal deleted.
- Real data, checked with the heredoc's `mdat_sha` and `_referenced_movies`:
  - strip2 D7 (4+4 copies) and D7s (3+3) are accepted.
  - The old `Continuity/D7{,s}-html` exports are refused (mdat 65da5343/f9a6201a against pins 71659a97/b37ffd93).

## Suites on `adfeb552`
| Suite | Result |
|---|---|
| 3.13 | 11393 passed, 38 skipped, 1 xfailed (130 s) |
| 3.10 floor | 11393 passed, 38 skipped, 1 xfailed (160 s) |
| Dashboard UI | 44 files, 331 tests passed |

## Gate round on `adfeb552`
- Command: full tier, GATE_JOBS=3, `QUAL_B_SOURCE=.../Continuity/strip2`. Ran 09:12:00–09:32:24, start load 2.72.
- Result: `failed=9` (was 13), `findings=133`.
- Evidence: `output/evidence/stage-b-2026-10-13/mmfeed-fix/round-adfeb552/` (88 result JSONs, the log and the window record).
- No longer red:
  - D7 and D7s from-only;
  - HOST red D2 `--strip pin@6`, which matched this round. Nothing on the branch touches D2, so last round's extra `b1to2 restart` was a flake;
  - Alpha `strip-bridge14-movie2`, whose redSet now equals the registered one.

### (d): owner decision, ambiguity in a crossfade read is red
- **Null.** The feed-on arms (D7 and D7s ×3 viewports) have 72 crossfade counter reads, 0 of them `ambiguous`. Alpha feed-on reads are alpha-kind, so there are no counter reads to test.
- **Positive.** All 8 D7/D7s from-only crossfade records score feedLive False. The checks are `(0.25, True)`, `(0.5, False, ambiguous)`, `(0.75, False)`. The non-crossfade b2to3 records stay True.
- **Re-registration of `MM_FEED_READ_EXPECTATIONS` for D7/D7s.** Old {0.25: True, 0.5: False, 0.75: False}; new is identical. No edit.
  - **0.25.** The fed from-unit dominates the blend, and the GL patch decodes the reference counter exactly (113=113, 218=218, …).
  - **0.5.** An even blend: markers pass and the coded levels sit mid-band (e.g. 80/80/…, 82/0/…), so the reason is `ambiguous`. That is now red.
  - **0.75.** The unfed to-unit dominates and decodes 0 against a reference of about 140 or 244, so the read is red.

### Alpha_DSK: the 9 red arms
None comes from this branch's change. These arms never scored real Alpha feed data before: the fixture had no movies until `a25a5db5` restored them. So every one is pre-existing and was exposed by the fix.

| Arm | Mismatch | Cause | Class |
|---|---|---|---|
| feed-off-2s, -5s, -12s, attach-once | holdFrame None ("a held-frame match is ambiguous") | Alpha hold reads mostly pick the target frame, but with margins of 0.0–5.0, under `ALPHA_HOLD_MARGIN` = 6. On near-static phone footage they pick a ring neighbour 1–5 frames off with a margin of about 0. Adjacent frames are not separable by the alpha patch. | instrument |
| feed-off-2s (b5to6), after-feed (b5to6) | posterHold False ("post-resume media time did not continue") | Media time advanced 2 (or 3) source frames while `presentedFrames` advanced 1 (or 2). Base: `lastUploadedFrame` 66 against `pauseFrame` 65. The source is constant 30 fps (wa0125 has 1351 deltas of 0.0333 and one of 0.0667), so this is not variable frame rate. It is either a real one-frame skip at resume or an off-by-one between the upload record's `presentedFrames` and media time. | undetermined (instrument or product) |
| ordinal, after-feed | feedLive True on b6to7 and b7to8 | `--feed-tamper-scene 10` tampers only b5to6 (atScene 10). The other carries feed normally, but `check_mm_feed` applies the control expectation to every row. Targeted b5to6 under ordinal: holdFrame None ("held target or its first/middle/last reads are missing", standDown). | expectation scope, plus instrument |
| from-only | first-crossfade feedLive[0.75] False, expected True | At 0.75: dVideo 149.6 against dPoster 4.7, so the GL patch matches the unfed to-unit's poster. The {0.5: False, 0.75: True} expectation was registered before Alpha had movies and has never been checked against real data. | expectation (re-register) |
| no-pause | posterHold None, expected False | With `--core-variant no-pause` and the feed off, the core feed seam emits neither a claim nor a departure, so every carry's mode is `unavailable` and the control never reaches the poster scorer. | instrument (control signal path) |
| mm-opacity-off | b5to6 labelsOverFeed True | b5to6 has no label over the feed (`expected 0`, `notApplicable`). The other 3 carries are False as intended. The expectation should exempt not-applicable rows. | expectation scope |

## Open, needs a decision
1. Alpha hold-frame matching on real footage. Options: a counter or texture path for Alpha, or a recalibrated margin. This is an owner call; it is a threshold.
2. The posterHold resume off-by-one: needs a focused per-frame diagnosis before anyone calls it product.
3. Scope `check_mm_feed` control expectations to the tampered or applicable carries (ordinal, after-feed, mm-opacity-off).
4. Re-register the Alpha first-crossfade read expectation from real data, the same way as D7.
5. A no-pause control signal path that survives the variant.

Do not merge on this round: 9 red remain.
