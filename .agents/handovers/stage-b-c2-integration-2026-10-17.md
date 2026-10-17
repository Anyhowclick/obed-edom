# Handover: Stage B C2-integration checkpoint (paused before phase-3 round 3, 2026-10-17)

**This file supersedes the "Resume here" section of `stage-b-instrument-restructure-2026-10-15.md`.** That file still holds the full owner-decision log and the open-item lists; read its "Owner decisions" section too.

- **Coordinator:** session `local_4b825e27-26e0-4d7b-a4af-de1cc7d9d4c2`, worktree `funny-pasteur-751a72`. This session cannot write into other worktrees with the file tools. Work detached at `origin/claude/stage-b-arch` here, push, then fast-forward `stage-b-coord`.
- **Owner instruction (2026-10-17):** pause and hand over before the phase-3 round-3 reviews. Nothing has started since.

## Resume here

**Plan:** `.agents/plans/keynote_live_continuity_stage_b_c2_integration.plan.md` (r3, owner-approved). It has three phases, then the full suites, then the pre-5a integration round, then a merge to `claude/stage-b-arch` on the owner's explicit go.

**Branches**

| Branch | SHA | State |
|---|---|---|
| `claude/stage-b-arch` | `207d7838` (+ handovers) | Integration target. Untouched by C2-int code. |
| `claude/stage-b-c4c5` | `6639d4f0`, pushed | Integration branch: C4-F + C5-G + phases 1–3. Full suites run (below). |

**Update 2026-10-17 evening (resumed session, same worktree):**
- **Phase 3 LANDED on c4c5:** P-c `77341530`, F-c `ab5a789b`, V-c `c01aec98`; merges `3bc6ef50`/`a3f1eaa8`/`6639d4f0`. The hard `score_departure_pixels` import was done inside P-c's fold, so no separate fixup commit. The merged tree is byte-identical to the reviewed integration tree. Targeted files: 2473 passed.
- **Reviews:** r3 (Opus 5.5 high) folded all severities; r4 found no blocker/major on any stream, so the loop is closed. Reviews and folds are in `.cache/reviews/{pc,fc,vc,fcvc}-review-r{3,4}.md` and `{pc,fc}-fold-r3.md` / `vc-fold-r4.md` (V-c's round-3 fold).
- **New coordinator decisions (reversible):**
  - V-c derivation re-scores reds with `exposedFrames` recounted under the derived `redMin`, so threshold-free calibration captures derive. This supersedes the r2 red-count case.
  - The tamper is keyed on feed config `oneFramePosterEntryId`. P-c sets it for red runs and errors the entry unless `oneFramePoster.fired` holds with a matching `entryId` and `contextSerial`.
  - Frame `t` is stored unrounded.
  - Poster reference = SOURCE slide's poster at the pre-draw ROI (srcRect), not dstRect. The key name `references.poster.dstRect` is kept and holds the rendered screen rect. No silent resize; the persistent null is pinned at the candidate ROI.
  - P-c now runs F-c's discovery contracts per entry and records an `arm` object.
- **r4 ignored (recorded):**
  - the poster is resized to the ROI at the same aspect without provenance (fail-safe → None);
  - the tamper `rafTimestamp` is not checked against `[hideMs, firstDrawMs]` (fail-safe: derivation → None);
  - a theoretical `press_ms` read race;
  - judged contamination only reaches `contractErrors`;
  - some untested branches;
  - three cosmetic F-c/V-c lows.
- **Full suites on c4c5 `6639d4f0`** (outside the sandbox, so the `pgrep` tests ran). Logs are in `stage-b-c4c5/.cache/suites/`.

  | Suite | Result |
  |---|---|
  | 3.13 | 11713 passed, 3 failed |
  | 3.10 floor | 11714 passed, 2 failed |
  | UI | 331 passed |
  | maps | 542 passed |
  | perf | 2 passed |

  - Both interpreters fail the two real-export census tests (`test_mm_opacity_census_mirror…`, `test_handback_census_mirror…`). They reproduce on `0ec8d143` and are caused by a new export at main `output/source-decks/F2-html` (written 11:55 today by another session). It was not moved: the owner decides.
  - The third 3.13 failure, `test_run_gates::test_known_bad_the_dev_tier…`, was an xdist-load timeout: it passes alone in 24 s.
- **Next:** step 5 (pre-5a integration round), then a merge only on the owner's go.

**Phases**
- **Phase 1 LANDED on c4c5:**
  - P-a `58174a93`, F `e50a16ee`, V `9edb2d70`, G-a `74eb8e6a`, O-a `7aee6698`;
  - co-landing `f4cf7dc2`.
- **Phase 2 LANDED on c4c5:**
  - P-b `8acc55b4`, F-b `6b8db3d6`, O-b `aff79f80`, G-b `43fa57bf`;
  - co-landing `0ec8d143`.
- **Phase 3 (pixel discovery), IN PROGRESS.** Three worktrees off `0ec8d143`, each with UNCOMMITTED changes:

| Stream | Worktree / branch | Sol session | Status at pause |
|---|---|---|---|
| **V-c** pure scorer (`paint_instrument.py` + tests) | `stage-b-vc` / `claude/stage-b-vc` | `01a148e7-92be-7a30-aa53-fa71e2ffb64a` | r1 and r2 folded and r2 READY. Hide-before-start alignment done (188 passed). Needs a round-3 review. |
| **F-c** pixel contracts + discovery-only tamper (`live_evidence_contract.py`, `mm_feed_instrument.py`, tests) | `stage-b-fc` / `claude/stage-b-fc` | `01a148e7-934c-7f22-b282-d912fda3a940` | r1 and r2 folded (r2 fold completed after the pause: departure-keyed tamper, `frameN < firstDrawFrameIndex`, judged rejection of `oneFramePoster`; 313 passed on Node 16.0.0). Needs a round-3 review. |
| **P-c** discovery capture (`live_continuity_probe.py` + tests) | `stage-b-pc` / `claude/stage-b-pc` | `01a148e7-91c8-7033-9f70-bf9bc69bc5de` | r1 and r2 folded (r2 fold completed after the pause: amended `hideMs` rule, poster reference from the export; 1967 passed, 1 skipped = the real-scorer test pending co-landing). Needs a round-3 review. |

- **Where things are kept.** Each stream worktree holds `.cache/sol/` (git-ignored, persistent): `brief.md`, `fold-*.md`, `report.md`, the codex logs and the test logs. The coordinator's fold texts are in `funny-pasteur-751a72/.cache/reviews/`.
- **Reviewer findings are not saved as files.** The Opus reviewer agents and their context end with the session. Their findings survive as the fold files (exact fix wording) plus each stream's updated `report.md`. A new session spawns fresh reviewers and points them at the brief, the fold files and the report.

**Next steps, in order**
1. Both r2 folds completed after the pause (confirmed: no usage-limit errors). All three streams are ready for round 3.
2. **Round-3 reviews** (Opus 5.5 high; the LAST all-severity round), for P-c, F-c and V-c. Each must cross-check the others' REAL code. These must hold:
   - P-c records → V-c `score_departure_pixels` → F-c `departure_pixels`/discovery envelope;
   - the null scores True, the one-rAF red scores False, the hide-before-start exposure scores False, and the threshold derivation succeeds on a null/red pair.
   - Fold the findings with the same Sol sessions. From round 4 on, only majors and blockers count.
3. **Phase-3 co-landing on c4c5:**
   - commit each stream on its branch, merge `pc`, `fc` and `vc` with `--no-ff`;
   - fixup: P-c's guarded `score_departure_pixels` import becomes a hard import, and the skipped real-scorer test then runs;
   - re-run the targeted files outside the sandbox on Node 16.0.0 (the default here) and commit.
4. **Full suites** on c4c5: 3.13, 3.10 floor, UI and maps, plus the `pgrep` kill-the-queue tests outside the sandbox.
5. **Pre-5a integration round** (plan §7). Live headless Chrome on a QUIET machine, so coordinate windows with the other sessions first. Use `--allow-record`, because `departure-early-hide` is RECORDED discovery. Accept the round on:
   - every judged artifact carrying `runValidity` with the correct hostKind;
   - cost and environment True on clean nulls;
   - cadence-open as the only None reason (plus "GL intervals unavailable (GL replay)" for GL-replay arms);
   - the judge's candidate lines equal to the expected table.

   Also run:
   - the calibration red (`feed.rvfc` and `frame.total` over budget → `ok` False);
   - the pixel feasibility pair: the persistent-decoder null, and the live one-frame red via the discovery tamper;
   - a fresh v3 Alpha ordinal at scene 10.

   Watch items:
   - Pass G destinations now run the full sampler during screenshot bursts, and burst spacing and verdicts must not move;
   - no OBS feed take can pass before Q2 (cadence is measurement-only).
6. **Merge to `claude/stage-b-arch` only on the owner's explicit go.**

## Coordinator decisions in this checkpoint (reversible; the owner can overturn any)

**Phase 1**
- **Canonical `instrumentCost` hook-row grammar.**
  - Zero calls ⇒ `p95`/`max` are None (never 0.0) and `overBudget` 0.
  - Not applicable ⇒ not installed.
  - Applicable but uninstalled ⇒ well-formed, but validity unproven.
  - `frame.total` must be applicable.
  - Shared fixture: `tests/fixtures/instrument_cost_rows.json` (V-owned).
- Every `REPORT:` line prints regardless of class. REPORT never changes an arm's class.
- P calls the feed `report()` BEFORE `__obedCost.stop()`. A recorder method returning non-true counts as a failure.
- A malformed `hookHealth` stays report-wide.

**Phase 2**
- **Top-level `runValidity` aggregate (frozen):**
  ```
  runValidity = {ok, reasons, policy: {hostKind}, measured: {environment: {chromeBuild}}, holders: {...}}
  ```
  - Written only when the holders share one hostKind.
  - `chromeBuild` is None when the holders' builds differ.
  - There is no top-level `hostKind` key.
- **Round Chrome-build check.**
  - These invalidate the round: an unreadable artifact, absent `runValidity`, and a missing, mixed or zero recorded build.
  - Only explicitly registered P2 reports are "validity N/A", an unreadable P2 included.
- **Cadence is NOT a paint-verdict input.** It's judged only in `runValidity`.
- A `replay` scope can never be `ok=True`.
- P-b keeps None holders as unproven.

**Phase 3 (pixel discovery; evidence only, never wired into `departureExposure` or gates)**
- **Frozen pixel record:**
  ```
  departurePixels = {entryId, visit, contextSerial, decoderId, atScene, startMs, hideMs, firstDrawMs,
    roi:{x,y,w,h}, frames:[{t, tick, sha256, path, distances:{lastDecoder, poster, background}}],
    references:{lastDecoder:{sha256, provenance}, poster:{sha256, dstRect, provenance},
                background:{sha256, provenance}, pairwise:{lastDecoder_poster, lastDecoder_background, poster_background}},
    expectedTicks, deliveredTicks, missingTicks:[...], ambiguousFrames, exposedFrames}
  pixelVerdict = {verdict: True|False|None, reason, coverageComplete, exposedFrameCount}   # stored with thresholds
  thresholds = {margin, redMin, provenance}                                                 # derived, never chosen
  ```
- **Distance metric.** All distances are the mean absolute difference (`metric: "mad"`), never MSE. The verdict is None if any pairwise reference distance is < margin, or if two references share a sha256.
- **Conservative False.** A frame is "exposed" only when its lead is ≤ −redMin. Leads in between give None. (The owner may revisit this at classification.)
- **Thresholds.** Thresholds come from `derive_pixel_thresholds` (measured null/red separation). The derivation returns None unless the null re-scores True and the red re-scores False. With none supplied, the verdict is None, "thresholds not supplied".
- **Ticks.** Ticks are UNWRAPPED non-negative ints. `expectedTicks`/`deliveredTicks`/`missingTicks` cover only the inclusive hide→first-draw interval; bracket frames (`lo−1`, `hi+1`) are a separate requirement.
- **`hideMs`** (amended at P-c r2):
  - It is the FIRST sampler row after the press, at or before `firstDrawMs`, where the decoder isn't visible.
  - It is never clamped to `startMs`, so the hide may precede the ride start.
  - If there is no such row, it is `min(startMs, firstDrawMs)`.
  - The only order check is `hideMs ≤ firstDrawMs`.
- **Poster reference** (P-c r2): the export's poster image, rendered at `dstRect` at the screencast scale. Never a tamper frame.
- **Screencast scale:** quantized to {0.5, 0.75, 1.0}, so the sync bar decodes.
- **The live red tamper** (F-c r2):
  - It hides the held decoder for exactly ONE rAF, keyed on the departure pause, strictly before the first-draw frame, with the first draw unchanged.
  - It records `oneFramePoster.fired`, and is stamped `instrumentVariant: "one-frame-poster"` only when it fired.
  - It is discovery-only: it lives in `DISCOVERY_INSTRUMENT_VARIANTS`, and judged artifacts reject the stamp and any `oneFramePoster` key.
- **Accepted deviation:** the plan §6 frame-gap check (`CARRY_COVER_MAX_GAP_FRAMES`) is not applied in the scorer. Tick contiguity covers it, because a poster change needs a rAF tick.

## Owner decisions recorded 2026-10-17 (also in the older handover)
- D7 from-only: ambiguity in a crossfade read counts as red.
- C3 carry-window deviation: confirmed.
- Gate 4 decisions:
  - (1) Chrome .80 requalified;
  - (2) inventory accepted after the 155.x re-count (1,075 / 299 / 0);
  - (3) cost gate `> 8`;
  - (4) the narrowed wrf rule.
- Merged the MM-FEED fix, and folded the 9 Alpha arms into C4/C5.
- Alpha holdFrame on near-static footage is a neighbourhood match.
- C5 host-feed rows: feed-on holdFrame is an explicit N/A record, and REPORT never changes the class.
- All-hidden pre-draw positives are measured in pixels first; `departureExposure` stays out of `combine()` until the owner classifies them.
- Gate attach-once is judged as headless Chrome.
- Plan r3 is approved and launched. The weekly Codex reset was applied, so Sol stays the implementer.
- Follow-up, not urgent: the player skips one source frame at resume after a feed-off hold.

**Gate 5a owner list:**
- Q1 host rows, including real-display attach;
- Q2 cadence statistic plus its scope applicability (Pass G legs, paint control, carry-cover, visible passes, the GL-replay interval source);
- OBS exact rate matching;
- departure pixel classification.

## Roster and operations
- Until 2026-10-27: Codex GPT-5.6 Sol high implements, and Opus 5.5 high reviews (Agent tool). The review-stop rule applies: rounds 1–3 fold every severity; from round 4, only majors and blockers.
- **Sol:**
  - It doesn't commit, because its sandbox can't write git metadata. The coordinator commits after checking.
  - Its sandbox blocks `pgrep`, so the kill-the-queue tests are rerun outside.
  - It has newer Node; this machine's default is 16.0.0, so the JS harness must avoid `Array.prototype.at` and similar.
- **Folds:** write fold texts with the Write tool into `funny-pasteur-751a72/.cache/reviews/`, then `cp` them into the stream's `.cache/sol/`. A shell heredoc with backticks failed silently once.
- **Freezing Sol:** if another session needs quiet timed windows, freeze the whole Codex process tree with SIGSTOP (save the PIDs) and resume with SIGCONT. This worked mid-run.
- **Gate output dirs** go in a persistent, git-ignored location: a reboot wiped `/private/tmp`.
- **Worktree cleanup:** the finished stream worktrees (`stage-b-{c4f,c5g,pa,f1,v1,ga,oa,pb,fb,ob,gb}`) are merged and can be trashed once the owner agrees; check no session uses them as cwd first. `nifty-antonelli-b34c21` is still the cwd of a DeckLink sub-session.
