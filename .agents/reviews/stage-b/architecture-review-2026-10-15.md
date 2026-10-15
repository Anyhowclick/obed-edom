# Alpha Keynote live: architecture review (2026-10-15)

Branch `claude/stage-b-arch` @ `fc0a0726`: Stage B plus `origin/main` #288–#293, merge reviewed READY by GPT-6 Astra high.
Method (`improve-codebase-architecture`):
1. Eight Opus readers: six subsystem slices, plus two cross-cutting lenses (tracing one Alpha move, and tests + change coupling).
2. One Opus synthesis, which produced 23 candidates.
3. Two GPT-6 Astra high verifiers: a refute lens and a risk/payoff lens.
4. A GPT-6 Astra high completeness critic.

Ratings below are the reconciled verified ones. The first pass rated 12 candidates Strong; 5 remain.
Vocabulary: `.agents/skills/codebase-design`.

**Owner decisions (2026-10-15):** scope approved as recommended. That is C6 scoring interface, C1, C2, C3, the bounded C4 slice, C5 and the C10 audit, then verification and Q7 attempt 4.
- C4 keeps the report-wide producer-error rule.
- The headless vs OBS feed-off expectation set is decided when the C5 registry is built.
- `entryColdStart` is report-only.

## Where the tangle is

**Already deep. Leave these alone:**
- the `derive_plan` refusal pipeline and its plan-sha pins;
- `live_session` over the `PlayerAdapter` seam;
- `live_codec`;
- the pinned `live_runtime` patcher;
- GL replay's arm-time proofs and the feed's GL binding core;
- `score_verdicts`;
- `paint_instrument`'s split, where the page records and Python decides;
- managed OBS supervision, `obs_websocket`, `ChromeCdp` and the dashboard's `LiveClient`.

**Shallow or leaking.**

1. **The instrument and qualification layer.**
   - One evidence kind spans the producer JS, the contract and a 230-line normaliser. All three changed together in 11 of 11 Stage B commits.
   - Validity is re-implemented in each status function, with different precedence.
   - Gate judgement lives in three places that have drifted apart.
   - Five pipelines each assemble the arm record.
2. **LiveOutputHost's undeclared seams.**
   - Harnesses swap about 20 product globals to build red controls.
   - About 30 mutable feature fields are set in a hidden order.
   - The pre-load route re-implements the same decisions and can disagree with the host.
3. **God files.** These are `live_continuity_probe.py` (9.6k lines), `live_host.py` (3.2k) and `managed_obs_qualify.py` (5.6k). They should split along the modules below, never on their own.

## This round: before Q7 attempt 4

### C1. Bound the feed instrument's pixel sampling (Strong, instrument; folds F1 and "feedLive unreadable")
- **Files:** `scripts/mm_feed_instrument.py`, `scripts/binary_counter_movie.py`, `scripts/obs_cadence_decode.py`.
- **Problem.** Since `1df31c33`, `riderTick` arms every planned decoder on every rAF (`mm_feed_instrument.py:399 → 53-61 → 94-112`). That arming also starts `capture()` on every presented frame of the settled source slide: 26 full-resolution `drawImage` calls plus a `getImageData` (`:179-189`), for a callback p95 of about 113 ms. This is the jitter you saw on slides 7→8→9.
  - GL reads take up to 81 + 17 `readPixels` per fed row.
  - The counter-strip layout is copied three times, even though `binary_counter_movie.py:47-58` owns it.
  - `counterFromGl` returns null with no reason.
- **Solution.** Separate observation (metadata, media events, departure attribution) from pixel sampling. Sampling becomes one module: one downscaled draw and one read, taken only for frames a verdict consumes (the pre-move ring, the fed draw, the poster upload). The strip layout comes from `binary_counter_movie`, and the decoder returns a reason and raw levels.
- **Wins:**
  - observer cost bounded in one module;
  - one counter layout and one decoder;
  - `feedLive` reads say why they failed;
  - a counting fake canvas catches a 1df31c33-class regression in milliseconds.
- **Astra caveats:**
  - Keep departure references fresh: the ring opens at atScene−1, and capture also runs during `moveLive`.
  - Observation must stop at `report()`. Today it never stops (`:36, 111, 225, 398-423`).
  - Time the `drawImage`/`getImageData` split first.
- **Proof:** a fresh headless A/B on D7, D7s and Alpha, with every feed control keeping its colour. Acceptance: p95 ≤ ~4 ms and scene 8/10/12 medians ≤ 33 ms.

### C2. One run-validity module, where INVALID is never excused (Strong, instrument, pure; folds F2 and supersedes 47bc3698's cadence excuse)
- **Files:** `live_continuity_probe.py`, `paint_instrument.py`, `mm_feed_instrument.py`, `managed_obs_qualify.py`, `run_gates.sh`.
- **Problem.** Nothing turns an observer effect into an invalid run.
  - `callbackCostP95Ms` (`mm_feed_instrument.py:423`) and `readCostMs` (`paint_instrument.py:956`) are recorded but never gated.
  - `settledCadenceReportOnly` (`live_continuity_probe.py:2846-2860`, from 47bc3698, which is in HEAD) rewrites cadence inconclusives to ok. That is the excuse you rejected.
  - Validity precedence differs per mode: `overall_status` 7148-7166 vs `red_arm_status` 7482-7486, plus copies in paint_control_status, Pass G and force-wrap.
- **Solution.** One pure validity function with one precedence. It takes three inputs:
  - the sampler: tick cost, and settled cadence against 2× the qualified period outside GL intervals;
  - the feed instrument: cost over all hooks and phases, not only the tail rVFC p95;
  - the environment: load, foreign Chromes, browser version and git head.

  Every status function, the gate judge (C5) and the OBS take read validity first. Delete the cadence excuse.
- **Wins:**
  - F2 lands once;
  - red control = the 1df31c33 instrument, null control = the C1-fixed one;
  - browser version is recorded in every artifact (Q3/Q5 on Chrome 155 needs it).
- **Astra caveats:**
  - Keep retrospective validity separate from the launch load guards.
  - Calibrate the ~8 ms budget against the qualified output period, never against degraded cadence.
  - You see the list of historical greens that turn INVALID before the gate freezes.
  - Unifying the 3.0/3.5/4.0 load thresholds is your call, and out of scope.

### C3. One phase reader for carry windows (Strong, instrument, pure; folds F3 with entryColdStart report-only)
- **Files:** `live_continuity_probe.py`, `paint_instrument.py`.
- **Problem.** The carry start is derived at six sites using four rules: `find_boundary_window` 2327, `continuity_window` 2436-2476, the clip in `score_continuity`, `paint_start` 2750-2771, `carry_window_clip` 3695-3709 and `forced_window` 7887-7895.
  - `continuity_window` grounds at the from-slide's first settled row whether or not it is decoded. The legacy clock checks (2656-2669) therefore still score slide 4's 200–340 ms entry cold start, which is why b3to4 fails.
  - The atScene−1 arithmetic is re-encoded at about 10 sites.
  - The sampler reads the snapshot's sceneId while the instrument reads `location.hash`. They differ by one at the source idle.
- **Solution.** One phase reader over sampler rows. Per row it gives the phase; per decoder mount it gives the mount, the first decoded row and the not-decoded run. It feeds one carry-window value whose start is the first settled source row on which the carried decoder is decoded. The clip and forced-seek rules stay, as distinct fields of that value. The mount-to-decode span becomes `entryColdStart`, report-only, and never enters combine() or validity. A source that never decodes stays INCONCLUSIVE.
- **Wins:**
  - F3 is one edit;
  - the legacy and paint checks cannot disagree;
  - tests use an Alpha-shaped red and a D7 null case;
  - stock Keynote's cold start stays visible without failing runs.
- **Astra correction:** the cold start is excluded from paint but is still inside the legacy clock checks. The scan's "scored nowhere" was wrong.

### C6. Arm record from one scoring function (Strong, instrument, pure; enables offline proof of C1–C4 and OBS parity)
- **Files:** `live_continuity_probe.py`, `managed_obs_qualify.py`, `detach_experiment.py`, `mm_handback_probe.py`.
- **Problem.** Five pipelines glue the arm record together:
  - `run_arm` 4567-4587 and `run_attach_arm` 4727-4747 are verbatim duplicates;
  - the OBS `feed_script` (`managed_obs_qualify.py:2264-2281`) hard-codes `evidence={}` and skips the sampler self-check, wraps, stage fit and census;
  - `run_advance_leg`;
  - `rescore_generated` 8473-8476 drops feed evidence, and rescore only works on P2 (`facts['asset']`, 8535).

  Ground truth is finished in about 9 different subsets. `bind_feed_source_fps` is called at 3 sites, and a missed call fails hand-back closed. qualify imports about 25 probe names, 6 of them private.
- **Solution.** One pure `score_arm(capture, facts, expected_stage)` returns the whole record: wraps, stage fit, verdicts, census, entryColdStart and validity. The artifact keys stay as today. Every runner, the OBS session and rescore call it, so rescore works for any deck.
- **Wins:**
  - qualify imports one function instead of about 25;
  - headless and OBS score identically;
  - stored captures become offline fixtures;
  - callers cannot skip a binding step.
- **Astra caveats:**
  - Missing historical evidence stays unreadable.
  - The stored OBS Alpha run has rows and producer output, but the headless summaries do not, and the stall's raw captures were not kept. Some proofs therefore need fresh captures.

### C5. One gate judge with an explicit expectation registry (Strong, instrument, pure; propagates F2 and adds report-only rows)
- **Files:** `run_gates.sh`, `live_continuity_probe.py`, `managed_obs_qualify.py`, plus a new `scripts/gate_checks.py`.
- **Problem.** Feed expectations live in three places that have drifted apart:
  - the probe's `MM_FEED_GATE_EXPECTATIONS` (349-365), read by a run_gates heredoc that walks the JSON, substring-matches ids and accepts exit 0 or 1 (line 791);
  - qualify's own `feed_gates` table (4911-4932);
  - the probe's red/passg statuses.

  run_gates.sh holds 12 heredocs, about 430 of its 819 lines. `check_host_red` re-implements the paint floor, and the D7 pins are read by ast-parsing the probe.
- **Solution.** One `judge(artifact, gate, arm, host)` returning MATCH, RECORDED, MISMATCH, INVALID or REPORT, over one registry keyed by arm × host. It reads C2's validity first. run_gates.sh keeps only the queue, nonce, process groups and `.rc` files.
- **Wins:**
  - headless vs OBS differences become explicit rows that you decide;
  - entryColdStart and the feed-off 1-frame resume drop become REPORT rows;
  - tests pass dicts in and get verdicts out.
- **Astra caveats:**
  - OBS omitting `holdFrame` differs from headless requiring "not None"; it is not the same as requiring success.
  - The feed-off sets genuinely differ. Keep host-specific rows explicit.
  - Missing hold evidence never becomes green.
  - Printed lines and exit codes stay byte-stable.

### C4 (bounded slice). Feed-evidence attribution (Worth exploring as a whole; slice this round)
- **Files:** `mm_feed_instrument.py`, `live_evidence_contract.py`, `live_continuity_probe.py`.
- **Problem.**
  - `wrap()` records every WebGL context, even when no planned entry matches (`:347-350`).
  - The visit counter increments but never resets `artworkDone` (`:226, 406-413`), so repeat visits read inconclusive (`probe:3768-3772`).
  - objectId case is carried in both spellings.
- **Slice this round:**
  - contexts with no planned entry are counted but never emitted as frames;
  - visit state resets per visit;
  - add the departure-exposure reader (handover item 3).

  Keep the report-wide rejection of producer errors, which you approved. Defer per-entry error scope and the full read/judge split.
- **Astra critic (verified):** the blanket Alpha `atScene` unreadability is already fixed on HEAD. Replaying the stored owner run `feed-20261015-150437.json` gives 78/48 contract errors under the 03a35b28 contract and 0/0 on HEAD (47bc3698's exemption, `live_evidence_contract.py:709`), and all eight stored per-entry records pass. That proves contract readability only, not passing verdicts. So the slice is the visit-state fix, unplanned contexts and departure exposure, and the exemption is reviewed as part of it.

### C10 (audit slice). Qualification-deck pins (Worth exploring for the registry; audit this round)
- **Problem.** `D7_PLAN_SHA256` (`probe:201`) was never re-derived after the Stage T repair. Fixture identity (`probe:1114-1128`) hashes the header and slide JSON but not the movie bytes, so a remux (F4) would leave both identity and plan sha unchanged.
- **This round:** re-derive and deliberately re-pin D7, and add media provenance to fixture identity. Never auto-bless a new hash. The nine-caller registry waits until after Stage B.

## After Stage B merges

| id | candidate | verified | why |
|---|---|---|---|
| C7 | Served program page as a value: one assembly path, a variant seam replacing ~20 monkeypatched globals, a manifest of served sha256 | Worth exploring | Real duplication: start, placement install, `_program_html` and reconnect (bug class 1c95d5f1). Byte equality alone misses install-order changes, so prove it with transport traces too. No F1–F3 unblock. |
| C8 | Output feature decisions as pure functions shared by the host and `web/live.py`; per-capability Chrome qualification | Worth exploring | The pre-load "qualified" can disagree with the host (codec gate, GL env parsing, 16:9 tolerance), and one pin admits both the freeze and the feed. Separate the pure extraction from the behaviour fixes, which are your calls. |
| C13 | F4: movie preparation targets | Worth exploring | Measure first: remux a scratch copy of Untitled-H264, then read entryColdStart headless. Our H.264 encode omits `+faststart`, while every instrument movie sets it. A remux that drops `colr` silently disables the Dissolve freeze. |
| C9 | Move ledger derived once | Worth exploring | The joins are real, but a broad record risks a new wide interface. Plan pins cannot prove refusal equivalence. |
| C11 | Live output target seam (launch / attach / OBS CEF) | Worth exploring | C6 gives scoring parity first. Dissolve is not duplicated wholesale. |
| C16 | Core↔feed seam | Worth exploring | A real-core + real-feed contract test is cheap; the restructure is not. |
| C19 | Named player patch set | Worth exploring | Low risk, and the pins prove it instantly. No F1–F3 payoff. |
| C20 | One spec per OBS arm | Worth exploring | Do it after C5/C6/C11 so the feed arm moves only once. |
| C22 | Retire the P2 legacy scorer | Worth exploring | Fold its status policy into C5/C6. Keep the historical oracle until parity is proven. |
| C12 | One export-preparation module | Speculative | In-place cache repair and converted fixtures are behaviour changes. |
| C14 | Page JS as `.js` files + shared fake page | Speculative | Moving strings adds no depth. C1 takes the counting canvas alone. |
| C15 | One placement owner per carried decoder | Speculative | The flags are not interchangeable, and this risks hand-back timing. |
| C17 | GL oracle sampled on demand | Speculative | Unmeasured, and the readback also detects GL errors on the same tick. |
| C21 | One export-tree reader | Speculative | Its consumers have deliberately different strictness. |
| C18 | Placement channel out of the host | Drop | No proof is possible without you; it was just qualified (#278, #291). |
| C23 | Split html_alpha_probe | Drop | File splitting alone adds no depth. |

## Where F1–F4 and the Stage B open items land

| item | home |
|---|---|
| F1: instrument capture cost | C1; its acceptance becomes a C2 gate |
| F2: validity gate | C2, propagated by C5 and recorded by C6 |
| F3: carry window + entryColdStart (report-only) | C3, recorded by C6 and classified REPORT by C5 |
| F4: faststart / warm-next | C13, measured first; deferred. Fixture media provenance comes first (C10 slice) |
| Alpha verdicts unreadable (`mmFeed.*.atScene`) | Contract readability is already fixed on HEAD (critic replay). The C4 slice reviews that exemption and fixes repeat-visit state |
| OBS feed run: `b8to9 …->end:retire` inconclusive ×2 per session | C6: the OBS `feed_script` (`managed_obs_qualify.py:2264`) has no observer and scores with `{}` evidence, and `feed_gates` (4911) checks only under-artwork carries. Feed qualification therefore does not establish whole-deck retirement. Found by the critic |
| Feed-off never green headless | Split: holdFrame → re-check after C1+C4; the resume drop → C5 REPORT row; headless vs OBS set → C5 registry (your call); footprint mismatches → diagnose first |
| Alpha b6to7/b7to8 artworkAbove false, decoder on `#body` at hand-back frame 2 | A standalone product fix, not architectural; C6 turns stored runs into replay reds |
| feedLive unreadable (`counterFromGl`) | C1 |
| 47bc3698 (unreviewed, in HEAD) | Superseded piece by piece: paint start → C3, cadence excuse → deleted in C2, empty-context/attribution → C4 |
| Departure fix (core 302c218d) never run | Standalone headless validation in the verification step |
| D7_PLAN_SHA256 after Stage T | C10 audit slice |
| Q3/Q5 feed arms on Chrome 155 | Ops step in verification; browserVersion recorded via C2 |

## Recommended sequence (Astra risk lens, reconciled)

1. **C6 scoring interface.** Keep the artifact keys, and route replay through one function.
2. **C1, then C2.** Time the capture split, bound sampling while keeping departure references fresh, then enforce validity everywhere.
3. **C3 plus the bounded C4.** Unify carry grounding, report cold starts as report-only, fix context/visit attribution, and add departure exposure.
4. **C5.** Wire validity and scoring into headless and OBS, with host-specific rows kept explicit.
5. **C10 pin audit.** This covers D7, the D7-unrepaired refusal control and the repointed Stage T export path.
6. **Fresh, serialized headless verification:**
   - the departure fix;
   - D7, D7s and Alpha with their existing reds;
   - the feed-off and readability gaps;
   - Q3/Q5 on Chrome 155.0.8059.79 with browserVersion recorded.

   Diagnose the Alpha b6to7/b7to8 placement on its own; architecture does not fix it.
7. **Q7 attempt 4 (you):**
   - rebuild the `stage-b-q7` worktree;
   - run all three decks, waiting for placement to leave `probing`;
   - check slides 7→8→9 by eye;
   - then step 3: dashboard D1, Alpha through to the end, and pressing past the end.
8. **Close Stage B:** Q2–Q6, full suites (3.12 + 3.10 lockfile venv + dashboard ui/maps, with known load-flake handling), then the PR.

Product restructuring (C7, C8, C9, C11, C13, C19 and the C16 contract test) is reconsidered after Stage B merges.

**Top recommendation: C1 + C2.** They fix what you saw on slides 7→8→9 and guarantee that an observer effect can never again pass as a result. The 1df31c33 instrument is a ready-made red control.

## Completeness critic (Astra)

- **Coverage.** Thinly read: `managed_obs.py` (summarised, without implementation evidence), `dashboard/src/live` (no check of preparation, command order, placement readiness or end-of-deck behaviour), and `live_host_probe.py` / `live_fixture_session.py`. Not read: `probe_movie_poster.py`, which investigates native Keynote posters and is legitimately out of scope.
- **Unproved assumptions:**
  - F1's costly line, downsampling fidelity and departure-reference freshness are unmeasured. Counting canvas calls cannot establish a millisecond budget.
  - The ~4 ms and 8 ms thresholds need clean calibration.
  - C7/C8 byte equality cannot prove reconnect order or refusal equivalence.
  - C10 plan equality excludes movie bytes.
  - Nothing shows the Alpha placement failures disappear under the departure fix.
- **Orphans** (now steps 7–8 of the sequence): dashboard D1, Alpha press-past-end, Q2–Q6, suites, PR.
- **Missed risk:** OBS feed qualification does not establish whole-deck retirement (`b8to9 …->end:retire` inconclusive ×2). It is now homed in C6.
- **Scope.** The critic agrees with the sequence above. On ratings: C4 is Worth exploring with the evidence fixes only now; C7/C8 narrow extractions are strong but deferred; C10's pin audit happens now and its registry later; C14 and C15 are Speculative; C16's test slice only; C18 is out of this round.

Raw reports (session scratchpad, not kept): reader/synthesis JSON, `astra-refute.md`, `astra-risk.md`, `astra-critic.md`.
