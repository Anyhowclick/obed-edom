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
- **Correction to the census note above:** `output/source-decks/` (F2-html, F2.key, Minimal Alpha_DSK.key) is not a foreign export. It was moved there on purpose by main #299 (`source_deck()`). c4c5 is based on `stage-b-arch`, which predates #299, so its real-export censuses count those files. Expect the two census failures to clear once c4c5/arch is brought up to date with main; re-check then.

## Pre-5a integration round, NON-PIXEL part (2026-10-17 21:00–21:25; owner: "stop before pixel discovery")

Evidence is git-ignored in `stage-b-c4c5/.cache/gates/`:
- `pre5a-6639d4f0/` + `.log`: the full round. Run from a clean pinned worktree `stage-b-gate-6639d4f0` (since trashed), `GATE_JOBS=3 run_gates.sh … --allow-record --tier full`.
- `calib-red-6639d4f0.{json,log}`.
- Copy the finished evidence into main `output/evidence/` when it is reviewed.

**Round facts**
- exit 1, wall 1366 s; load 2.74 at start, 3.86 at launch, 5.03 at end.
- `ROUND BUILD MATCH chromeBuild=155.0.8059.80`, and every P2 report is "build not recorded (validity N/A)", per N3.
- runtime sha `838eeedf…` unchanged start to end.
- `DONE failed=77 pending=0 findings=137` (paint census, report only).
- `failed=77` is by design: every judged arm is INVALID for cadence-open (§7 final class). The candidate classes and the non-cadence reasons are what count.

**§7 acceptance**

| Check | Result |
|---|---|
| Judged artifacts carry `runValidity`, build matches | MET |
| Calibration red INVALID for measured cost (`arms.A: cost: hook p95 exceeds 8 ms: feed.rvfc, frame.total`) | MET |
| D7 departure-early-hide RECORDED | MET |
| Host gates, host reds, deck reds, Pass G (+red), paint control, carry-cover: candidate MATCH with cadence-only INVALID | MET, except D4 wrong-instance (below) |
| GL-replay host red: only "GL intervals unavailable (GL replay)" | MET |
| **Clean-null cost True** | **NOT MET** (below) |
| **Only cadence-open / GL-replay None reasons** | **NOT MET** (below) |
| **Candidate lines equal the table** | **NOT MET**: 9 MISMATCH (below). Unexplained mismatches block the merge (§7). |

**Clean-null cost is not True.** `frame.total` p95 is over 8 ms on EVERY D7/D7s mm-feed arm:
- the null feed-on arms at 2560, 1600 and 1920, plus from-only, no-linger, interim-delay, startup-moved-decoder, departure-early-hide and attach-once;
- p95 is a steady 9.9–10.8 ms, with 123–226 frames over budget;
- Alpha mm-opacity-off is also over (8.7 ms);
- every other Alpha arm stays at 3.5–7.6 ms.

The D7 level is uniform across viewports and arms, which looks systematic rather than load noise. It still needs a quiet-machine rerun of one D7 feed-on null before blaming the instrument or the deck. Never relax the `> 8` gate (owner gate-4 decision 3).

**"GL intervals were not supplied" (integration gap, not a permitted reason).** It appears on three Alpha arms:
- `hold-upload-killed` (`arms.A`);
- `ordinal` (`arms.A`);
- `strip-bridge14-movie2` (`arm`).

These are not GL-replay arms. Find which producer path omits the GL intervals for these arm kinds.

**Candidate MISMATCHes**

| Arm | Mismatch |
|---|---|
| HOST D4 `--core-variant wrong-instance` | Status inconclusive; contract `unknown` for `b0to1:counter-a.mov#2->counter-a.mov#1:carry` and `b1to2:counter-a.mov#1->counter-a.mov#1:carry`. Only the two duplicates were observed. |
| Alpha feed-on-1920 | `b7to8 wa0125 handbackContinuity False != True`. The 2560 and 1600 runs MATCH. |
| Alpha feed-off-2s | holdFrame None for b6to7 wa0125, b7to8 wa0121 and b7to8 wa0125 |
| Alpha feed-off-5s | holdFrame None for b7to8 wa0121 and wa0125 |
| Alpha feed-off-12s | holdFrame None for b6to7 wa0125 and b7to8 wa0125 |
| Alpha attach-once | holdFrame None for b5to6 wa0125, b7to8 wa0121 and wa0125 |
| Alpha after-feed | holdFrame None for b5to6 wa0125 |
| Alpha ordinal (fresh v3) | `b5to6 wa0125 holdFrame None != False` |
| Alpha no-pause (fresh v3) | `posterHold None != False` for b6to7 and b7to8 wa0125 |

- Per §7, "Unseparated None stays open, never triggers threshold changes". The holdFrame/posterHold Nones may be legitimately unseparated holds, which become documented open items needing an owner disposition. Each still needs its per-frame reads checked first, using the artifacts in `pre5a-6639d4f0/mm-feed-Alpha_DSK-*.json`.
- The D4 inconclusive and the 1920 handback False are real deviations: rerun interleaved on a quiet machine before attributing them.

**Not run (owner stop):**
- the pixel feasibility pair (`--departure-pixels --departure-pixel-persistent-null`, then `--departure-pixel-one-frame-poster`), both threshold-free;
- `derive_pixel_thresholds` by hand, writing the JSON for `--departure-pixel-thresholds`;
- the discovery captures over D7/D7s departures and the Alpha b5to6, b6to7 and both b7to8 carries.

## Root causes of the three open issues (2026-10-17 21:40–22:40)

Three Opus 5.5 high investigators worked read-only; the coordinator spot-checked their code claims.
- Reports: `funny-pasteur-751a72/.cache/reviews/pre5a-debug-{cost,glint,mismatch}.md`. The brief is in `pre5a-debug-common.md`.
- Scratch scripts and rerun artifacts are under this session's scratchpad (`dbg-*`). Copy what's needed before that is cleared.
- Every live rerun was a single headless Chrome under a shared lock, at load 2.3–4.2. No machine was truly quiet.

**1. Cost, `frame.total` > 8 ms on D7/D7s. ROOT CAUSE: the feed instrument's own per-GL-frame pixel verification. OWNER DECISION.**
- **Cost per GL frame:** 7.5–11 ms on BOTH decks. The parts:
  - `sample()` video→canvas→`getImageData`, ×2 under feed.draw and ×2 under feed.rvfc (`mm_feed_instrument.py:349→227`, `:133`);
  - two mid-frame `gl.readPixels` GPU syncs (`:341`);
  - `labelStats` (`:272`).
- **Why only D7 fails:** the gate is a whole-capture p95, so idle frames dilute it.
  - D7 captures are 45–53 % GL frames.
  - Alpha is 86–95 % idle, yet about 35 % of its GL frames are also over 8 ms. Alpha feed-on-1920 reruns failed too, at 8.48–8.8 ms.
- **Ruled out:**
  - load: reruns match within 0.5 ms;
  - viewport: the over-budget count is flat across 1600 / 1920 / 2560;
  - double counting: per-hook sums equal `frame.total` exactly.
- **History:** `frame.total` was never measured on D7 before this round. The 8 ms budget came from per-rVFC history (`gate4-historical-impact.md`).
- **Prototypes (scratch only):**
  - `labelStats` with running sums: 10.8 → 10.2 ms, sound but insufficient;
  - plus reusing the rVFC ring sample: 9.7 ms, UNSOUND (7 of 642 counter reads mismatch).
  - Getting under 8 ms needs ≥3 ms of synchronous readback removed per GL frame. That is a design change.
- **Owner question (the gate stays at 8 ms):**
  - (A) Restructure the reads: copy the pre-label regions to a scratch texture, do one end-of-frame readback, slim `labelStats`. This touches GL state in the product context, so it needs a plan, review and feed re-registration.
  - (B) Fully verify only a fixed subset of GL frames: roughly half the cost, less per-frame evidence.
  - Sub-question: should clean-null cost also require the GL-frame cost under budget, so Alpha cannot pass by dilution?
- **Live check after a fix:** D7 and Alpha feed-on-1920, interleaved, both ≤ 8 ms with feed verdicts unchanged.

**2. "GL intervals were not supplied". ROOT CAUSE: a conflict in the frozen rule. COORDINATOR FOLD PROPOSED (not applied).**
- `gl_intervals_for` (`live_continuity_probe.py:2011-2034`, P-b `8acc55b4`) builds the intervals only from each spec's scored `underArtwork.interval`. If any spec lacks one, it returns None for the whole holder.
- That interval exists only when an expected-ordinal upload was fed (`mm_feed_instrument.py:793`, deliberate).
- The three arms are exactly the registered reds that suppress those uploads:
  - hold-upload-killed: 0 uploads;
  - ordinal: no upload at the scene-10 ordinals 4/5;
  - strip bridge@14:movie2: b7to8 wa0121 unbound.
- §7 expects cadence-open as their only reason.
- **Proof:**
  - null control: re-deriving `runValidity` reproduces all 18 saved Alpha holders exactly;
  - positive control: a monkeypatched fix changes only the 3 bad holders, which become cadence-open only (`ok=None`) and still pass the contract.
- **Proposed fold (P-owned, `live_continuity_probe.py` only):**
  - When a spec has no interval, fall back to that entry's measured GL context window: `feedEvidence.producer.contexts`, exactly one match, `lost=False`, `evidenceComplete=True`, finite `createdAt`/`closedAt`. Otherwise keep None.
  - GL replay, repeated visits and lost or incomplete contexts stay None.
  - Do NOT relax the producer gate at `:793`.
  - Red-first test: extend `test_gl_intervals_are_never_empty_for_replay_or_unreadable_feed` (`tests/test_live_continuity_probe.py:13921`).
  - Amended frozen-rule wording is in the report.
- **Twin:** `managed_obs_qualify.feed_gl_intervals` (`:2326-2340`, O) has the same all-or-nothing rule. Mirror the fold there, or record it as a follow-up.
- **Alternative reading:** cadence intervals mean fed substitution only. §7 would then permit a "feed suppressed" reason for the registered reds instead.

**3. The 9 MISMATCHes. Four causes, none a phase 1–3 regression.**

| Item | Classification | Action |
|---|---|---|
| Alpha feed-off 2/5/12s, attach-once, after-feed: holdFrame None | LEGITIMATELY UNSEPARATED on moving footage. The producer is complete (3 reads, 18 ring candidates, target at distance 0, one poster). The poster is 38–142 MAD away, so the canvas is not showing it. On moving footage the nearest distinguishable frame is 6.1–13 MAD from the target, so separation stays −1.78…5.60 < 6. Static-stretch carries in the same artifacts score True. Round adfeb552 had these as None too. | **Owner disposition:** documented open item "unseparated on moving footage" (parent INVALID), or another evidence source. Follow-up observation: some reads match a frame 2–11 before the target (never past −6). Next step is an exact-frame check on a counter deck, never a threshold change. |
| Alpha ordinal (fresh v3) b5to6 wa0125: holdFrame None, expected False | INSTRUMENT DEFECT. The target read is present. The tamper adds 1000 to `feed.from.upload` (`live_continuity_probe.py:1724`), so no poster row is sampled or emitted (`mm_feed_instrument.py:313`, `:386`). The scorer returns None at `:1448-1449`, before separation. The candidates alone decide False (separation −6.67). | **Fold (F-owned scorer):** with no poster row, still compute separation from the candidates; return False when it is ≤ −`ALPHA_HOLD_MARGIN`, else None. True still requires exactly one poster. Red-first case next to `tests/test_mm_feed_instrument.py:830`. |
| Alpha no-pause (fresh v3) b6to7/b7to8 wa0125: posterHold None, expected False | EXPECTATION TOO BROAD. The core detaches wa0125 during those carries (~107 frames), and the browser pauses a detached media element. `holdPauseMissing: True` with `clockStill: True`, and the scorer correctly gives None (`:1502-1504`). The connected carries (b5to6 wa0125, b7to8 wa0121) turn False as registered. | **Coordinator/owner:** register no-pause `posterHold False` only on the connected carries and record the detached ones as None. |
| Alpha feed-on-1920 b7to8 wa0125: handbackContinuity False | LOAD FLAKE. One missed vsync (33.3 ms) gave a 3-frame media jump against a limit of 2, at round load 3.9–5.0. Interleaved quiet reruns 1920→1600→1920 all MATCH (12/12 hand-backs True). | None. |
| HOST D4 wrong-instance: inconclusive, carry lines `unknown` | ONE-OFF. "row:ts not increasing at samples[1]" (`live_evidence_contract.py:990-992`): two pre-press sampler rows 1.5 ms apart carried the same `document.timeline.currentTime`. Seen 1/71 sampler arms this round and 0/7 earlier D4 artifacts. The check and the timestamp source predate phase 1. Two quiet reruns MATCH. | Optional hardening (coordinator): the sampler skips a row whose timestamp equals the previous row's (`live_continuity_probe.py` ~474-491). |

**Update 2026-10-17 ~23:30: decisions taken.**
- The owner chose cost option (A), and "the rest as per rec", including dilution = yes.
- Fold plan r2: `.agents/plans/keynote_live_continuity_stage_b_pre5a_folds.plan.md`.
  - It folds critique r1 by Codex GPT-6 Astra high and by Fable; their critiques are in `.cache/reviews/pre5a-folds-critique-{astra,fable}.md`.
  - F5 (sampler duplicate timestamp) is deferred, a reversible coordinator call.
  - F6 is split into step 0 (`willReadFrequently`), F6a (pixel-identical) and F6b (an independent decoder reference via an instrument-owned texture), plus `frame.gl`.
- Steps 2–4 below are superseded by that plan's Sequencing. Step 1 still applies.

**Next, in order:**
1. Bring c4c5 up to date with main (#299 and later) and re-run the census tests.
2. Owner decisions:
   - cost reduction (A) or (B), plus the GL-frame sub-question;
   - disposition of the unseparated Alpha holds;
   - the no-pause expectation narrowing;
   - whether to take the GL-interval fold as proposed.
3. Folds with Sol: GL-interval fallback (P, plus the O twin), ordinal scorer False path (F), and optionally the sampler ts dedupe. Run the r1–3 review rule on each.
4. The cost redesign per the owner's choice. It needs a plan.
5. Re-run the affected arms interleaved.
6. Pixel round.
7. Merge only on the owner's go.

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
