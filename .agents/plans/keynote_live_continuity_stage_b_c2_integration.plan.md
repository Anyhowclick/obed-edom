# Stage B checkpoint: C2 integration + P's C4/C5 wiring + pixel capture (plan r3)

Planner: Codex GPT-6 Astra high (r1, r2). Critic: Opus 5.5 high. r1 was NOT READY (5 majors, 9 mediums, 6 lows; all folded into r2). r2 was READY (0 majors, 5 mediums, 5 lows); the coordinator folded those into this r3 without another round, because none changes a module boundary.
- Base: `claude/stage-b-c4c5` @ `5b475129` (`claude/stage-b-arch` + C4-F `fd64e85e` + C5-G `b5f7430d`).
- Parent plan: `keynote_live_continuity_stage_b_instrument_restructure.plan.md`.
- Owner and coordinator decisions applied:
  - D-M1: merge on full suites plus one pre-5a integration round.
  - D-M5 (owner): gate attach is judged as headless Chrome.
  - D-m3: O's judge migration waits for Q1.
  - D-m9: carry-cover keeps its own sampler.

---

**C2 integration + P’s C4/C5 wiring — r2**

Target: `claude/stage-b-c4c5` at `5b475129`. Instrument/harness checkpoint only; preserve product bytes, pins and legacy evidence. Use ordinary typed records and pure functions.

Merge to `claude/stage-b-arch` after full suites and **one pre-5a integration round**. Post-5a cadence enforcement and the gate-7+ qualification matrix are outside this checkpoint.

**1. Ownership and sequence**

Whole-file ownership includes tests; no shared-file editing.

| Stream | Exclusive files |
|---|---|
| P | `scripts/live_continuity_probe.py`, `scripts/detach_experiment.py`; corresponding tests |
| F | `scripts/mm_feed_instrument.py`, `scripts/live_evidence_contract.py`; `test_mm_feed_instrument.py`, `test_live_evidence_contract.py`, `test_live_mm_feed_js.py` |
| V | `scripts/live_run_validity.py`, `scripts/paint_instrument.py`; corresponding tests |
| O | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` |
| G | `scripts/gate_checks.py`, `scripts/run_gates.sh`; corresponding tests and gate fixtures |
| Coordinator | Review/result records, integration and serialized verification |

F authors every contract patch. Co-land contracts with their producers and consumers; never enforce a new contract before its producer exists.

Freeze §2 first. V supplies the recorder foundation, then:

1. **P-a:** C4/C5 wiring and pre-navigation plumbing; co-land G’s resume/discovery rows and O’s import switch. F/V C2 producer work proceeds in parallel.
2. **P-b:** C2 capture, validity and artifact integration; co-land F contracts, V health/validity changes and O finalization.
3. **P-c:** dedicated pixel discovery capture; co-land F’s live tamper/contract and V’s pixel scorer.

G can prepare judge/round changes and O can prepare finalization independently. P’s three checkpoints are strictly serial. Integrate reviewed checkpoints onto `claude/stage-b-c4c5`; no intermediate branch claims qualification.

**2. Frozen accounting and artifact contracts**

Keep `REQUIRED_HOOKS`:

| Hook | Owner and producer anchors |
|---|---|
| `sampler.tick` | P: `SAMPLER_JS.tick/frame`, `CARRY_COVER_SAMPLER_JS.tick` |
| `paint.prePaint` | V: `PREPAINT_FN_JS.installPrepaint` observer |
| `feed.rvfc` | F: `INSTRUMENT_JS.armDecoder` callback |
| `feed.raf` | F: `riderTick`, `settledArtwork`, scheduled observation |
| `feed.draw` | F: upload/draw observation, `finalizePixels`, `collectRiders` |
| `frame.total` | V recorder; P installation/finalization |

V places `COST_RECORDER_JS` in **`paint_instrument.py`**. Freeze:

```text
window.__obedCost.install(hook)
window.__obedCost.enter(hook)
window.__obedCost.leave(hook)
window.__obedCost.stop()
window.__obedCost.read()
```

`install` records successful installation; nested `enter/leave` calls must balance. `stop` closes accounting and flushes the final frame; repeated `stop/read` is stable.

Recorder output:

```text
{
  version: 1, stopped, errors,
  hooks: {hook: {installed, count, chunks}},
  frames: {count, chunks}
}
```

Chunks are append-only typed duration buffers, serialized as ordinary numeric arrays by `read()`. Hook durations are exclusive of nested hook work; frame durations are the union of instrument spans. Use an O(1) current-frame accumulator. Pre-first-frame work belongs to frame 0; subsequent timer, observer and task work uses the current `document.timeline.currentTime` frame.

P derives applicability **in Python from configuration**:

- `feed.*`: iff `feed_specs_for(facts)` is non-empty;
- `paint.prePaint`: iff `SAMPLER_JS` is installed;
- `sampler.tick`: iff either sampler is installed;
- `frame.total`: always.

P writes each final hook record as `{applicable, installed, count, p95, max, overBudget}`. Applicable/uninstalled means `None`. Zero calls are valid only for an applicable, installed hook; explicitly inapplicable hooks are excluded, not represented as measured successes. Missing/malformed applicability is unproven.

Use whole-capture linear percentiles and strict `p95 > 8 ms`. Never add p95s, average decoder costs, or count one callback per entry. Preserve early expense and concurrent-decoder totals.

Each capture holder owns `runValidity`: `arms.<X>`, `attach`, `arm`, every Pass G destination/leg, and each carry-cover bridge capture. Top-level:

```text
runValidity = artifact_run_validity(required holders for this gate kind)
```

Write it only for holders sharing one `hostKind`. Preserve member measurements and reasons; do not average them. The judge reads **top-level only**. Mixed-host host-viewport artifacts are evaluated per holder through P’s status functions, never relabeled.

**3. F/V producer and policy work**

F instruments actual work blocks in `armDecoder`, `wrap`, `riderTick`, `settledArtwork`, `finalizePixels` and `collectRiders`, using `try/finally`. Include upload sampling, draw bookkeeping and the rVFC body; exclude native product calls and trivial GL state wrappers (`bindTexture`, `activeTexture`, `pixelStorei`, `uniform*`, `getUniformLocation`).

Stop accounting before `report()`, sampler drain and metadata reads: harness extraction is never a span. Remove trailing `S.costs` truncation; preserve `callbackCostP95Ms` as a whole-capture compatibility diagnostic. Retain frozen reports, callback shutdown, feed errors and overflow scope.

V extends `installPrepaint()` and **`sampler_self_check()`**, co-landed with P’s health fields. Retain missing reads, mismatch/duplicate counts, sequence reconciliation and coverage. Record observer lifecycle and disconnect at teardown. P supplies sampler installation/start/stop, full-run counts and accounting completeness.

V changes `_cost()`, `_environment()`, `_cadence()` and `run_validity()`:

- enforce the frozen applicability/accounting contract;
- update stale cost-policy wording to the approved strict threshold;
- retain cadence measurement-only and `ok=None`;
- import no probe policy;
- leave real-display attach qualification pending Q1.

`gl_intervals` is frozen as follows:

- `[]` only when facts contain no under-artwork feed spec **and** `gl_replay == "off"`;
- feed intervals come from scored `underArtwork.interval`; any unreadable interval gives `None`;
- GL-replay arms without measured intervals give `None`.

Preserve strict-overlap exclusion and post-GL stalls. Missing intervals cannot excuse cadence or be rewritten as an empty list.

**Tests and acceptance:** extend the existing validity matrix, feed harness and paint tests. Mutants truncate early costs, omit a decoder, double-count nesting, omit final flushing, or report an uninstalled feed hook as zero calls. Complete installed accounting is the null; observed over-budget cost is `False`; incomplete accounting is `None`. Feed integrity remains outside C2 validity.

F adds a calibration-only instrument variant restoring the old expensive `armDecoder` capture body under the new recorder. Serial red/null runs must show red `feed.rvfc` and `frame.total` over budget, hence `runValidity.ok=False`; clean C1 null cost/environment must pass. No suites overlap calibration.

**4. P-a: C4/C5 wiring and shared installation**

Add `instrument_pre_navigation_scripts(facts)`, always including the recorder and conditionally the feed instrument. Use it for **every host**, including Pass G, carry-cover and attach. O switches its independently assembled host kwargs to this helper.

In `score_under_artwork()`:

- accept `evidenceVersion in (2, 3)` for hand-back;
- publish F’s `score_departure_exposure()` and `score_resume()` results;
- leave departure entirely outside **`mm_feed_instrument.combine()`**;
- combine resume for departure/stand-down modes, preserving `report`, `reason`, `dropSize`;
- emit continuous `holdFrame={"verdict": None, "notApplicable": True}`, excluded from combination;
- preserve repeated-visit aggregate `None`, report-wide producer rejection and entry-local normalized rejection.

Remove probe table re-exports, scorer aliases and duplicated `mm_feed_control_aggregate_problems`. Use owning modules directly. O changes `P2_PLAN_SHA256` to import from `gate_checks` in the same integration commit.

G adds `resume: True` to `feed-off`, `attach-once`, and targeted `after-feed`/`ordinal` rows; explicitly exempt `no-pause` and `hold-upload-killed`. Emit `REPORT: <id> resume dropSize=1` without changing arm class. Larger drops mismatch.

G registers `D7 departure-early-hide --core-variant departure-early-hide` in **`run_gates.sh.MM_FEED_ARMS`**, with a separate exact discovery registration. Candidate RECORDED, departure `None`; no empty acceptance row or promised red.

Extend `test_departure_poster_hold_pass_fail_inconclusive`: `+2/30` becomes posterHold True plus resume True/REPORT/dropSize 1. Preserve compatibility-key tests. Mutants reject v3, omit resume/N/A, combine departure prematurely or let REPORT conceal larger drops. Move `test_feed_gate_registrations_are_data_and_run_gates_names_every_control` to G; remove duplicate tests only after replacement coverage passes.

**5. P-b/O/G: validity through every judged path**

P changes `capture_arm()`, `sampler_record()`, `drive_and_sample()` and `score_arm()`. Discard saved validity and recompute on every path, including malformed samples. Add pure `artifact_run_validity()` with failure-before-unknown precedence over explicit required holders.

Wire:

- host/MM-FEED: `run_arm`, `run_attach_arm`, `run_cli`;
- host-red: `run_red_arm` and serializer;
- Pass G/red: `run_advance_leg`, `_run_goto_arm`, `run_pass_g`, destination acquisition and serializers;
- paint control: `run_paint_control`;
- carry-cover: `capture_carry_cover`, `run_carry_cover`.

Carry-cover retains **`CARRY_COVER_SAMPLER_JS`**, recorder-wrapped, adding only environment and cost; do not install the full sampler there.

Gate attach-once is **`HOST_HEADLESS_CHROME`** by owner decision. Record `--headless=new` launch arguments, device-metrics response and innerWidth/innerHeight/DPR read-back proving 1920×1080 configuration. The shell keeps passing headless Chrome. Reserve `HOST_QUALIFIED_CHROME_ATTACH` for real-display/Q7 attach; invent no display profile.

Import canonical host constants from `live_run_validity`; delete V’s `probe.HOST_KINDS` drift test. Remove `settledCadenceReportOnly` reason rewriting while preserving coverage/integrity failures. Preserve detach’s late-bound hooks.

P2 host captures participate normally. Keep the separate P2 adversarial `expect` harness’s explicit validity N/A: it has no instrument capture.

O changes `feed_environment`, `feed_script`, `run_take` and validity handling in `arm_gates`: finalize environment before scoring, preserve configured/read-back OBS rates, versions, load/uptime/browser observations, and make missing/invalid session validity prevent take success. **Defer `feed_gates()` judge migration and Q1-dependent whole-plan enforcement.**

G makes the pre-precedence candidate class reportable alongside existing candidate lines, without weakening `_with_precedence`. Add one round pass in `gate_checks.py` over `runValidity.measured.environment.chromeBuild`: missing/mixed exact builds invalidate the round. Homogeneous artifact aggregation retains that build explicitly.

Extend caller/status/take matrices and `test_gate_checks::test_minimized_adfeb552_old_heredoc_comparison`. Mutants drop top-level validity, retain stale results, substitute hosts, ignore invalid children or promote candidates past cadence-open INVALID. Nulls preserve candidate lines and exact inventories. Shell tests retain nonce/process/exit semantics.

**6. P-c: dedicated pixel discovery**

Pixels are captured **only in separate discovery invocations**, never inside judged MM-FEED artifacts.

P adds `capture_departure_pixels()` using `_screencast()` and carry-cover synchronization; V adds pure `score_departure_pixels()`; F supplies contracts and a discovery-only instrument tamper that exposes the real poster for exactly one frame.

Capture from preroll before the press through first GL draw plus two frames. Downscale `maxWidth/maxHeight` to preserve the measured ROI. Compare delivered sync-bar ticks with sampler rAF ticks; reuse `CARRY_COVER_MIN_FPS`/`CARRY_COVER_MAX_GAP_FRAMES` coverage semantics and require **no missing tick across hide → first draw**.

References, with provenance:

- last decoder: ROI from the last frame with the decoder visible;
- poster: export poster rendered at recorded `dstRect`;
- background: same-session ROI with decoder and poster hidden.

Before the integration round, prove complete coverage on a persistent-decoder null and detection of the **live one-frame poster red**. Derive discrimination thresholds from that separation; failed feasibility remains open, never a guessed threshold.

Capture all attributed D7/D7s feed-on/off/attach departures, D7 early-hide, and Alpha b5to6, b6to7 and both b7to8 carries across positives and targeted controls. Include the pre-context hide interval.

Record exact entry/visit/context/decoder identity, start/hide/first-draw timestamps, screenshot hashes/paths, ROI, reference distances, expected/delivered ticks, gaps, ambiguity and exposure counts. Complete persistence supports pixel True; demonstrated poster/background flash supports False; uncertainty gives None. Departure remains unclassified pending owner review.

Fresh v3 Alpha ordinal at scene 10 must retain target/upload identity and first/middle/last hold reads. Expected target hold False; non-targets satisfy feed-on/N/A. Saved v2 missing reads cannot prove the producer fix.

Extend existing pixel/Node harnesses; mutants delete an intermediate frame or substitute poster/background. `test_live_mm_feed_js` exercises the recorder on **Node ≥16.0**, including this machine’s 16.0.0: no `Array.prototype.at` or newer-only conveniences.

**7. Pre-5a integration round and merge**

Acceptance:

- Every judged capture/envelope carries correctly scoped validity and matching host policy.
- Clean null cost/environment are True.
- Their only unresolved validity reason is cadence-open; missing hooks, intervals or provenance remain failures to complete integration.
- Candidate classes and retained problem lines match the table; final cadence-dependent class remains INVALID.
- Calibration red is INVALID for measured cost, not merely cadence-open.
- Discovery is reported separately; no qualification claim.

| Item | Candidate class / evidence expectation | Final class |
|---|---|---|
| Alpha feed-on ×3 | MATCH; explicit hold N/A | INVALID: cadence-open |
| Feed-off 2/5/12s, attach-once | MATCH expected; holds True expected. Unseparated None stays open, never triggers threshold changes | INVALID: cadence-open |
| b5to6 feed-off-2s / after-feed | MATCH expected; poster True, resume REPORT | INVALID: cadence-open |
| Ordinal | MATCH expected from fresh v3; target hold/feed False, non-targets green | INVALID: cadence-open |
| From-only | MATCH; 0.5/0.75 remain False | INVALID: cadence-open |
| No-pause | MATCH prediction, unproven until fresh v3 posterHold False | INVALID: cadence-open |
| mm-opacity-off | MATCH; exact target N/A, applicable labels False | INVALID: cadence-open |
| Existing kill/overlay/settle/strip controls | MATCH to unchanged registered reds | INVALID: cadence-open |
| All-hidden/leading-hidden departure | None diagnostic, excluded from combination | Parent INVALID |
| Repeated visits/unreadable legacy holds | None; never promoted | Parent INVALID |
| D7 departure-early-hide | RECORDED; departureExposure None | INVALID: cadence-open |

Unproven predictions require fresh evidence; unexplained candidate mismatches block merge. Legitimately unseparated holds remain documented open items requiring disposition, not automatic fixes.

Run focused tests/review, serialized calibration and pixel feasibility, then full Python 3.13, Python 3.10 floor, UI/maps suites and the integration round. Re-run sandbox-blocked queue signal tests. One heavy job machine-wide, ≤3 headless Chromes. Merge only after reviewed results; later changes reopen affected checks.

Never relax **`ALPHA_HOLD_MARGIN` or `PRE_DRAW_GRACE_MS`**, fabricate coverage, rewrite historical validity or silently update pins. Recheck F4 Alpha flips.

Gate 5a owner decisions:

- Q1 host rows, including real-display attach;
- Q2 statistic **and scope applicability**: full-deck/MM-FEED, Pass G legs, paint control, carry-cover;
- OBS exact observed-rate matching;
- departure pixel classification.

After classification, separately co-land F scoring/contracts, P departure combination and G exact expectations, then reverify. Post-5a enforcement/qualification remains outside this checkpoint.

**Folded**

| Finding | Location in r2 |
|---|---|
| M1 / D-M1 | §7 pre-5a acceptance, candidate/final table and merge criterion |
| M2 | §2 recorder API, output and artifact validity shape |
| M3 | §2 Python-derived applicability and installed-zero rules |
| M4 | §6 isolated pixel capture, references, coverage and live controls |
| M5 / D-M5 | §5 headless attach policy and provenance |
| m1 | §§4–5 universal pre-navigation helper and O import switch |
| m2 | §1 serial P-a/P-b/P-c |
| m3 / D-m3 | §5 deferred O judge migration; exact-build round pass |
| m4 | §4 resume rows, exceptions and REPORT line |
| m5 | §3 exact GL-interval rules |
| m6 | §7 conditional predictions and D7 discovery row |
| m7 | §§2–3 recorder timing, exclusions and storage |
| m8 | §3 named expensive-instrument calibration red |
| m9 / D-m9 | §5 carry-cover scope; §7 Q2 applicability |
| l1–l2 | §3 V-owned recorder and sampler self-check |
| l3 | §4 registration-test migration and separate discovery registry |
| l4 | §7 both immutable thresholds |
| l5 | §§3–6 named test surfaces and Node 16 compatibility |
| l6 | §5 drift-test deletion |
| Anchor corrections | §4 names F’s `combine()` and G’s shell `MM_FEED_ARMS` |
---

## Coordinator fold of critique r2 (binding; it overrides r2 where they differ)
- **N1. Visible-pass holders.**
  - Add `visible.<V|Voff|Vgl>` to the holder list.
  - They get the recorder (`frame.total` applies) and environment. The sampler and feed hooks are inapplicable by configuration, and cadence is not measured.
  - "Visible passes" joins the Q2 scope-applicability item.
- **N2. GL intervals for GL-replay arms.** "GL intervals unavailable (GL replay)" is a SECOND permitted pre-5a `None` reason, for GL-replay arms only (`--gl-replay auto` host red, `visible.Vgl`). It never becomes `[]`. Naming a GL-replay interval source joins the Q2 applicability item.
- **N3. Round build pass.**
  - It covers only artifacts that carry `runValidity`.
  - P2 adversarial artifacts print `build not recorded (validity N/A)` and don't invalidate the round.
  - Coordinator gap: `p2_recovery_html_adversarial.py` has no owner in this checkpoint, so recording its build is a follow-up.
- **N4. O scope.**
  - O uses `instrument_pre_navigation_scripts` only for sessions that use the feed script today (`feedFacts`).
  - Validity precedence in `run_take`/`arm_gates` applies only to `arm == 'feed'` sessions. All other OBS arms are unchanged.
- **N5. Applicability comes from capture-kind configuration, never from a runtime install result.**
  - `capture_arm`, Pass G and paint control: `sampler.tick` and `paint.prePaint` apply.
  - Carry-cover: `sampler.tick` applies; `paint.prePaint` does not.
  - Visible passes: neither applies.
  - An absent `window.__obedCost` is "not installed", and producers must not throw on it.
  - The recorder is the FIRST pre-navigation script.
- **L1.** `run_attach_arm` serves both MM-FEED attach-once and the host `attach` arm, and both use `HOST_HEADLESS_CHROME`. Pass G `--attach` (`HOST_QUALIFIED_CHROME_ATTACH`) is ungated and stays unproven.
- **L2.** The recorder is read in chunks, `read(hook, offset, n)`, following the `drain_samples` precedent.
- **L3.** The §7 ordinal row is "unproven until fresh v3", like no-pause.
- **L4.** A failed pixel feasibility proof does NOT block the merge. The pixel round stays open and is reported.
- **L5.** P adds probe-only CLI flags for F's calibration-red variant and for the one-frame poster tamper. Neither is selectable from `run_gates.sh`.
- **Gate 5a owner list (final):**
  - Q1 host rows, including real-display attach;
  - Q2 statistic plus scope applicability (full-deck/MM-FEED, Pass G legs, paint control, carry-cover, visible passes, GL-replay interval source);
  - OBS exact observed-rate matching;
  - departure pixel classification.
