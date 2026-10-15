# Stage B instrument restructure (plan r3: critique r1 folded by the planner, critique r2 folded by the coordinator)

Owner scope approved 2026-10-15: **C6 → C1 → C2 → C3 + bounded C4 → C5 → C10 audit → verification → Q7 attempt 4 → Stage B closure**.

Planner: Codex GPT-6 Astra high (r1, r2). Critic: Opus 5.5 high.
- r1 was **NOT READY** (6 major, 7 medium, 5 low). The planner folded all 18 into r2; none was refuted.
- r2 was **READY** (0 blocker, 0 major; 2 medium, 4 low). The coordinator folded those six into this r3 without another round, because none changes a module boundary.

Baseline: `claude/stage-b-arch` at **`97304eb1380405b17694c68c5d0b1d566e93ea8d`**, including the reviewed `fc0a0726` merge of Stage B and main #288–#293. Implementation target: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e`.

Authority: `.agents/reviews/stage-b/architecture-review-2026-10-15.md`, supplied synthesis and Astra corrections, both 2026-10-15 handovers, Stage B rev 3.5 and Q7 hand-back r3. Retained owner decisions: report-wide producer-error rejection; `entryColdStart` report-only; feed-off host expectations decided when C5’s table is built.

Evidence root: `/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/stage-b-2026-10-13/`, accessible through this worktree’s `output/`. Planning was strictly read-only: no files edited, tests run, applications launched or captures made. All implementation and verification below remain future work.

**1. Scope, evidence and implementation approach**

Instrument and harness changes only. No product restructuring, movie remux, warm-next change, eligibility change or automatic pin update. C7–C9 and C11–C23 remain deferred except the approved C22 status-policy overlap. Alpha placement failures receive a separate diagnosis and owner disposition.

Paths and line numbers refer to the baseline. Follow the codebase-design and obed-edom skills: ordinary typed records and pure functions; no adapter framework, speculative generality or broad fake-browser framework. Sampler, feed and environment measurements are different inputs, not interchangeable adapters.

Choose **sequenced probe edits**, not a preliminary split of `live_continuity_probe.py`. C6 first establishes scoring inside the existing module; C2 owns pure validity, C3 extends paint interpretation, and C5 owns judgement. This avoids relocating the scorer’s dependency graph before its interface stabilizes.

| Stored evidence | Available proof | Limit |
|---|---|---|
| Attempt-3 Alpha `feed-20261015-150437.json` | Feed/feed-off contain 1,891/1,329 authored rows, pre-paint evidence, raw producer reports and derived feed records; partial C3/C4/C6 replay. | No saved sampler record, complete health record or boundary-observer evidence. Cannot establish new validity, sampling fidelity or retirement success. |
| Attempt-3 D7 ×3 and D7s feed runs | Rows and producer output, after checking each required field. | Capture completeness must be checked explicitly. |
| `q7-round2/headless/*.verdicts.json` | Verdict comparisons, derived feed records and historical inventory. | Inspected Alpha summary has no samples; `feedEvidence` retains verdicts without producer output. No phase/pixel replay. |
| `q7-round2/alpha-stall/ab-summary.jsonl` | Twelve records with callback-cost p95 and rounded scene cadence median/max; quantitative analysis in §4. | No raw captures, cadence p95, visit partition or settled/GL filtering. |
| Prior Astra contract replay | Alpha producer errors changed from 78/48 to 0/0 on HEAD; all eight entry records passed the contract. | Readability is not passing verdicts or valid instrumentation. |

The five attempt-3 **feed-run files** all report `valid=True`, `passed=False`; their separate summaries also do not pass. Inspected headless summaries are non-passing. Distinguish actual qualification passes, formerly valid runs and green subchecks.

Scratch probes, captures and comparisons belong in the session scratchpad, never main `output/`. Retain result tables, identities and concise findings; use small synthetic or trimmed interface fixtures instead of archiving complete captures.

**2. C6 — one scoring interface and complete OBS capture**

Module: `scripts/live_continuity_probe.py`.

```python
score_arm(capture: Mapping[str, Any],
          facts: Mapping[str, Any],
          expected_stage: Mapping[str, float]) -> dict[str, Any]

capture_arm(player, facts, *,
            continuous_expected: bool,
            host_kind: str,
            environment: Mapping[str, Any],
            census: bool = False) -> dict[str, Any]
```

`score_arm` owns authored conversion where required, wraps, stage-map diagnostics, stage fit, normalization from stored producer output, `score_verdicts`, aliases, verdict table and paint census; C2/C3 add validity and cold-start reporting. It performs no I/O, does not mutate inputs and never treats saved derived verdicts as raw evidence.

Runtime installation comes from captured continuity; sampler schema comes from its record, never hard-coded `True`/`2`. Full-deck and advance-leg captures identify scope. Preserve advance-leg passed-end and destination-reached constraints.

Freeze the shared capture contract before parallel C2 work:

| Field | Invariant |
|---|---|
| Samples, sampler, continuity, boundary evidence, feed producer, scope | Preserve actual observations and their provenance; absent historical evidence remains absent. |
| `continuousExpected` | Required boolean for fresh captures: headless `run_arm=True`, attach `False`, OBS receives the session’s value. Normalize from this field; no caller mutation of normalized records. |
| `hostKind` | Explicit qualification key: headless Chrome, qualified Chrome attach, managed OBS 25, managed OBS 30; controls identify their qualified profile. Never inferred from degraded cadence. |
| `environment` | Browser/engine version, git head and qualification identity; load/uptime and owned/foreign Chrome counts before/during/after; configured and observed OBS output/browser-source rates where applicable. |
| `instrumentCost` | Flat map `{hook: {count, p95, max, overBudget}}`, milliseconds. Hook names identify sampler/feed, phase and aggregate buckets. Includes sampler tick, pre-paint, feed rVFC, rAF/DOM, upload/draw and non-overlapping total work per browser frame. |
| Health applicability | Explicit required-hook inventory distinguishes observed zero calls from missing instrumentation. Statistics cover the whole capture, not a trailing window. |

`live_run_validity` owns qualification constants keyed by `hostKind`; `score_arm` looks up that qualification and calls `run_validity(capture, qualification)`. Unknown host or missing required fields cannot qualify. Producers use the same qualification budget when counting `overBudget`; preserve `callbackCostP95Ms` as a compatibility diagnostic.

`capture_arm` owns observer installation, driving, draining/stopping the sampler, sampler metadata, feed report and actual continuity capture. The caller supplies host/environment context and completes final environment observations before final scoring. `run_arm`, `run_attach_arm` and OBS feed sessions use it; advance legs retain navigation but construct the same capture shape.

Keep `FEED_CONTROL`, `FEED_DWELL_S`, `SAMPLER_JS` and `drive_and_sample` **late-bound at invocation**. Do not capture them in defaults or import-time aliases: `detach_experiment.instrumented()` monkeypatches the latter two at `scripts/detach_experiment.py:619`. Preserve existing driving/dwell semantics.

Complete facts once through existing derivation: arrivals, DOM IDs, source fps, identity and explicit off/on selection. Scoring never probes media or selects facts by Python object identity. Preserve OBS `sampleRows`, `feedEvidence`, `feedVerdicts` as compatibility views of the same scored record; additive fields do not rename existing artifact keys.

Retirement evidence has a concrete home: `capture_arm` installs `boundary_observer(player, facts, evidence)` before driving and passes it through the every-slide callback, including retirement destinations. Both Alpha `b8to9 …->end:retire` entries must be captured in **each** OBS session. Missing observer evidence stays `None`; dashboard press-past-end remains a separate owner check.

Touched locations:

- Probe `:1142`, `:1662`, `:1673`, `:1741`: facts preparation/selection; `:1929`, `:1998`, `:2107`, `:3193`: collection, metadata, conversion and observer.
- Probe `:4313`, `:4498`, `:4537`, `:4727`, `:6455`: assembly/callers; `:8449`, `:8521`: any-deck replay and removal of unconditional `facts["asset"]`.
- `managed_obs_qualify.py:1929`, `:2264`: facts and feed sessions; `detach_experiment.py:1504`: completed facts, retaining its instrumented-drive hook.
- Audit `mm_handback_probe.py:494`; its screenshot/geometry scorer is distinct and stays unless a consumed helper changes.

Deletion test: remove five assembly paths, OBS `{}` evidence/hard-coded schema, post-normalization `continuousExpected` mutation and replay’s feed omission. Deleting `score_arm` should recreate this knowledge across callers.

Tests/proof: one parameterized interface family for P2/D7/D7s/Alpha covers complete/missing sampler, retirement, producer and fps evidence; flag-on facts; aliases; non-mutation; caller parity. One fake-host collection case covers observer installation and late-bound detach hooks. Migrate probe tests `:6498`, `:8078`, `:11982` and OBS tests `:1346`; retain independent scorers and legacy P2 oracle. Delete internal assembly tests only after equivalent interface coverage.

Red: dropped observer/sampler/producer evidence. Null: the same complete capture through every caller. Acceptance: comparable fields agree, no unexplained schema changes, replay works for every deck, **zero fabricated historical successes**. Complete OBS parity and retirement require fresh capture.

**3. C1 — bounded sampling, fresh references and shutdown**

Module: `scripts/mm_feed_instrument.py`, retaining bootstrap/configure/report.

```javascript
sample(source, geometry) -> {vectors, counter, levels, reason}
decodeCounter(levels, layout) -> {counter, levels, reason}
```

First action: scratch timing split on identical Alpha export/product bytes. Separately time `drawImage`, `getImageData`, DOM reads and total callback work; vary **`willReadFrequently` on/off and source size**. Compare parent `24b1c91d`, the `1df31c33` instrument and the fixed candidate in clean serialized runs.

History establishes that `1df31c33` added per-rAF `decoderForEntry` arming; the capture body already existed. Current capture makes **26 draws**, not the handover’s approximate 21. `113/26 ≈ 4.35 ms` is only a crude warning, not an isolated per-draw measurement. Test the hypothesis that CPU-backed canvas draws read back full video frames.

Observation tracks decoder identity, media events, visits, departure and placement independently of pixels. Pixel capture occurs only for rolling departure references, consumed fed-draw reads and relevant poster uploads. Each source sample uses **one downscaled draw and one small readback**; reuse only within the same logical sample/task with identical identity/timing.

Start with a small aspect-preserving whole-frame buffer; choose dimensions from measured patch/strip discrimination. Fallbacks, in order:

1. GPU-canvas downscale, then one small `getImageData`, if the CPU-backed path misses cost.
2. Decimated rolling-ring sampling while preserving the required reference time span, latest departure coverage and hold discrimination.

Acceptance remains unchanged. If neither works, report the measured blocker; do not relax cost or readability thresholds. The ring opens at hash `atScene-1`, retains up to **18** references and refreshes through `moveLive`. It cannot simply stop after its first 18 frames: departure is later, and `holdMatch` consumes the reference set. This explicitly departs from the handover’s “capture only as many frames as the ring needs” to preserve freshness; decimation needs positive/red proof.

Preserve bounded pre-closure DOM buffering and the closure-frame read required for **three** hand-back frames. Consolidate GL spatial reads only at the same draw point; label-before and final-after remain separate. Do not change product replay.

Inject layout from `binary_counter_movie.layout()`. Source/GL use one instrument decoder; Python recording decoding shares format/constants and conformance vectors. Preserve numeric `counter`; add raw levels and `bounds`, `marker`, `ambiguous`, `parity`, source/read-failure reasons.

`report()` finalizes once, stops rAF/rVFC rescheduling, removes listeners, safely disables/restores owned wrappers and releases retained DOM/GL references. Repeated reports return the frozen result; queued callbacks perform no subsequent reads/writes.

Touched: `mm_feed_instrument.py:53`, `:94`, `:179`, `:190`, `:196`, `:274`, `:300`, `:398`, `:419`; `binary_counter_movie.py:47`, `:64`; `obs_cadence_decode.py:112`; probe configuration `:1917`, `:1946`; contract `:683`.

Deletion test: remove capture-on-arm coupling, repeated source draws, strip literals, duplicated decoding and silent null-only failures; retain departure references and closure observations. Callers stop knowing buffer geometry and decoding policy.

F moves the realistic fake-GL case from probe tests `:12169` into **`tests/test_mm_feed_instrument.py`**, replacing private `81×30` assumptions with a dimension-aware counting canvas. Cover idle observation, late mount, rollover, `moveLive`, poster/fed samples, fallback reference coverage and post-report callbacks; preserve verdict assertions. One JS/Python conformance table covers decoder outcomes. P deletes the old case only after this replacement passes.

Performance red: unchanged `1df31c33`-era instrument. Null: C1-fixed instrument on identical product/fixture bytes. Fresh D7/D7s/Alpha runs preserve every applicable feed-control colour. Acceptance: Alpha headless **`callbackCostP95Ms ≤ ~4 ms`**, scenes **8/10/12 medians ≤ ~33 ms**, one source draw/read per sample, capacity 18, no observation after report. Pixel thresholds change only from demonstrated positive/red separation.

**4. C2 — validity first, with cadence policy honestly unresolved**

Module: new `scripts/live_run_validity.py`.

```python
run_validity(capture: Mapping[str, Any],
             qualification: Mapping[str, Any]) -> dict[str, Any]
```

Return `{ok: True | False | None, reasons, measured, policy}`. `False` means observed cost/cadence/environment invalidity; `None` means validity is unproven. Neither permits green qualification. Only **cost, settled cadence and environment** enter this run-validity decision.

Feed errors and `mediaOverflow` remain within C4’s feed-evidence scope. Sampler self-check/coverage errors, execution errors and unexpected wraps retain their existing integrity/scoring handling; planned force-wraps stay distinct. Do not promote them into new whole-run validity categories.

Qualification constants, owned here and selected from `capture["hostKind"]`:

| Host profile | Qualified output period `P` | `2P` cadence boundary | Separate provenance |
|---|---:|---:|---|
| Headless Chrome 60 Hz | `1000/60 = 16.6667 ms` | `33.3333 ms` | Exact Chrome build and qualification identity. |
| Qualified Chrome attach 60 Hz | `16.6667 ms` | `33.3333 ms` | Verify qualified display/timing profile; other profiles unproven. |
| Managed OBS output 25 Hz | `40 ms` | `80 ms` | Product browser source configured 50 Hz. |
| Managed OBS output 30 Hz | `33.3333 ms` | `66.6667 ms` | Product browser source configured 60 Hz. |

OBS defaults are grounded in `src/obed_edom/managed_obs.py:49`; record actual output and source settings separately, including explicit source-rate controls. Calibration must establish that page-sampler cadence is interpreted against the named output-period policy; do not substitute observed rAF/source cadence for `P`.

Chrome **other than `155.0.8059.79` is environment INVALID** for this Chrome qualification. Missing build is unproven. Preserve existing CEF qualification policy; the Chrome version requirement does not relabel CEF as Chrome.

Proposed cost gate: **8 ms p95** for every applicable hook/phase and aggregate bucket. Record whole-run count, p95, max and over-budget count, including early expensive work and non-rVFC hooks. Aggregate concurrent-decoder work without double-counting nested spans.

**Offline M1 analysis — actual `ab-summary.jsonl`**

Naming correction: this round’s **old-on instrument red** is stored as `new-on-1/2`, `new-off-1`, `hyb-newscripts-oldsrc`, `bis-1df31c33`. Stored `old-on-1/2` are clean older-instrument runs. `new-on-nocap-1` is a cheap **proxy**, not a C1-fixed capture; disabling capture cannot prove pixel correctness.

Groups below: R = those five clean red runs; N = no-capture proxy; O = `old-on-1/2`, `hyb-oldscripts-newsrc`, `hyb-new-oldinstrjs`. Each cell is **median / max**, milliseconds, with ranges across records.

| Sampler scene | R: expensive instrument | N: fixed-cost proxy | O: old clean |
|---|---|---|---|
| 4 | 16.7 / 16.8 | 16.7 / 16.8 | 16.7 / 16.8 |
| 8 | 100 / 133.4–133.5 | 33.3 / 33.4 | 33.3 / 33.4–33.5 |
| 9 | 33.3 / 133.2–133.4 | 16.7 / 33.4 | 16.7 / 33.3–33.4 |
| 10 | 100–116.7 / 133.4–166.7 | 16.7 / 16.8 | 16.7 / 16.8–33.3 |
| 11 | 33.3 / 100–133.4 | 16.7 / 116.7 | 16.7 / 33.3–116.7 |
| 12 | 200–233.3 / 233.4–266.7 | 33.3 / 33.4 | 33.3 / 33.4–33.5 |
| 13 | 33.3 / 233.3–300 | 33.3 / 33.4 | 16.7–33.3 / 33.4–133.3 |
| 14 | 33.3 / 33.4–66.6 | 33.3 / 33.4 | 33.3 / 33.4–33.5 |

Against headless `2P = 33.3333 ms`:

- **Per-scene median:** R clearly exceeds on 8/10/12; all other R and all N/O medians are below or effectively at the boundary. N/O scene 8/12/14 medians of 33.3 have only nominal **0.0333 ms** margin, smaller than rounding uncertainty. Scene 13 also reaches 33.3.
- **Per-scene maximum:** R exceeds on every scene except 4. N exceeds on every scene except 4/10. O exceeds on 8/12/13/14 and in some runs on 9/11; 4/10 remain below or at the rounded boundary. A max gate would reject clean evidence.
- **Per-scene p95:** not stored. It is bounded by median and max: R must exceed on 8/10/12; scene 4 is below; the remaining R scenes are indeterminate. N is below on 4/10 and indeterminate elsewhere. O scene 4 is below; scene 10 is below/rounding-adjacent; all remaining cases are indeterminate. Do not fabricate p95 from the endpoints.
- **Per-settled-visit median, p95 and maximum:** none is recoverable. `alpha-stall/compare.py:12–16` pools adjacent timestamp deltas by destination `scene`, with no visit partition, settled-state filter or GL exclusion. The table is a scene-level diagnostic, not proof of any settled-visit rule.

Load-overlapped `bis-ca39b819`/`bis-dd16db52` are excluded from calibration: cost p95 **124.64–126.98 ms**; scene 8/10/12 medians **100 / 100.1–133.3 / 233.3 ms**, maxima **166.7–266.7 / 133.4–166.7 / 266.7–299.9 ms**. Their other scene medians are 16.7 or 33.3; they add no clean-null proof.

Cost separates with substantial margin: R **110.35–128.30 ms**, N **2.40 ms**, O **2.50–2.90 ms**; at 8 ms, clean-side margin is at least **5.10 ms**, red-side **102.35 ms**. This is historical rVFC cost only, not proof of the new all-hook gate.

Scene-10 median also separates this dataset: null **16.7 ms**, red **100–116.7 ms**, margins approximately **16.63/66.67 ms**. It is a useful diagnostic, **not a substitute for the all-settled-scenes requirement**. Maximum per-scene median separates numerically, but its clean value 33.3 has no robust threshold margin.

Therefore withdraw r1’s per-visit p95 proposal as an accepted policy. **The general cadence statistic remains Owner Q2, unresolved with these numbers.** Fresh C1-fixed and old-red captures must record per-visit median/p95/max, sample counts, GL exclusions and rounding-free timestamps. Do not change `P` without an owner decision. Present raising `P` and a 30 Hz headless profile as Q2 options, each with its fail-closed consequences. Never freeze a rule that rejects the clean null merely to obtain separation.

**Interim behaviour until the owner freezes Q2.**
- V implements cost and environment validity, plus cadence *measurement* only: per-visit median, p95, max, sample counts and GL exclusions go in `measured`.
- The cadence gate lands as a separate small V checkpoint after the owner freezes Q2 at gate 5a.
- Until then, cadence neither passes nor excuses a run. No gate from 7 on starts before 5a.

One precedence everywhere: known validity failure; then execution/integrity errors or unproven validity; only then expected pass/red matching. Keep diagnostic verdicts even for INVALID runs. Missing GL evidence cannot excuse cadence. Delete `settledCadenceReportOnly`; retain ordinary evidence-completeness checks.

Touched: probe `:584`, `:1998`, `:2846`; status functions `:6518`, `:6730`, `:7140`, `:7305`, `:7470`, `:7623`, `:8072`, `:8313`, `:9154`; paint `:160`, `:890`; feed `:110`, `:274`, `:398`, `:423`; OBS collection/take finalization; contract health fields.

Deletion/test surface: remove reason-string cadence rewriting and duplicated precedence. One pure matrix covers equality/exceedance, expensive beginning/cheap tail, non-rVFC work, GL exclusions, missing qualification/environment, wrong Chrome and expected-red plus invalidity. Separate scope assertions ensure feed overflow stays feed-local and wraps retain existing handling. A small consumer matrix proves every status/take/judge reads validity first; retain mode-specific outcomes and sampler tests.

Red: old instrument on clean hardware. Null: C1-fixed instrument on the same qualification. Acceptance: old observer effect INVALID, fixed null satisfies frozen budgets, unknown historical health never valid. Historical impact review in §10 precedes policy freeze.

**5. C3 — arm-wide phases, per-spec carry windows**

Module: `scripts/paint_instrument.py`.

```python
read_phases(rows: Sequence[Mapping[str, Any]],
            plan: Mapping[str, Any]) -> Phases
carry_window(phases: Phases, spec: Mapping[str, Any], *,
             forced_seek: Mapping[str, Any] | None = None) -> CarryWindow
```

Read phases **once per arm**, yielding row phases and per-mount lifecycle/cold starts. Build one carry-window value per spec: decoded-source start, padded crossing/end, chain clip, forced-seek constraint, GL segments and unreadability reasons. Clip and forced seek remain distinct.

Start at the **first settled source row where the carried decoder is decoded**. Later decode loss, replacement or remount stays inside scoring. Never-decoded source remains INCONCLUSIVE; no fallback to the old padded start.

Mount identity uses element identity/generation and lifecycle evidence, not asset name alone. Report mount/first-seen, first decoded row, visible undecoded duration/count and missing endpoints. `entryColdStart` never enters `combine()`, failure aggregation or validity. Correct the historical description: cold start currently remains in legacy clock checks at probe `:2656–2669`.

Clock resolution: sampler `scene` uses snapshot `sceneId`; feed `atScene` uses `location.hash`. Stored Alpha has settled `(scene=8, hash=#9, IdleAtFinalState)`, so global subtraction is wrong. Interpret sampler scene/state/busy against plan source/transition scenes; correlate streams by page time, visit, entry and context. Preserve both clocks and add `nextSceneId` to fresh sampler rows. Missing historical disambiguation remains unreadable; product hash reads stay unchanged.

Touched: probe `:609`, `:2258`, `:2327`, `:2436`, `:2480`, `:2656`, `:2750`, `:2780`, `:3695`, `:7887`; paint `:287`, `:305`, `:547`, `:690`, `:967`; C6 cold-start assembly and sampler contract.

Deletion test: replace independent start calculations in `find_boundary_window`, `continuity_window`, `paint_start`, clipping and forced-window assembly; callers consume one value rather than reconstructing scenes.

One parameterized fixture covers Alpha 200–340 ms cold start, D7 decoded-source null, never decoded, later loss, remount, chain clip, forced seek and differing clocks. Exercise `score_arm`/`score_carry`; replace private-window tests at probe tests `:10179`, `:11434`, `:11933`, `:11973` only after coverage. Retain clock-wrap, motion and paint outcomes.

Offline OBS replay proves attribution changes with health unproven. Fresh runs establish full outcomes. Reds: later decode loss, no-pin-hold and strip controls. Null: decoded-source D7/P2. Acceptance: legacy clocks and paint share starts, initial cold start is REPORT, **no later failure disappears**.

**6. C4 slice — attribution, visits, departure and resume evidence**

Module: `scripts/mm_feed_instrument.py`; retain `verdict_records(report, entries, *, continuous_expected)` and shared normalization.

```python
score_departure_exposure(record: Mapping[str, Any]) -> dict[str, Any]
score_resume(record: Mapping[str, Any]) -> dict[str, Any]
```

F adds raw/normalized departure evidence and its contract. P publishes the reader’s result as **`underArtwork.departureExposure`**. It covers attributed ride start through first GL draw: no visible rider above authored labels and no source-poster exposure caused by hiding the decoder early. Record endpoints, decoder/visit/context identity, ordering and interval coverage. Missing evidence returns `None`; fully observed exposure returns `False`.

`departureExposure` is a required applicable verdict in every mode where a ride start is attributed, and it enters `combine()` in `score_under_artwork` (probe `:3763-3811`).

G registers its value for every existing `MM_FEED_GATE_EXPECTATIONS` row, attach-once included: `True` for feed-on/feed-off on both hosts, `False` for the new **`D7 departure-early-hide --core-variant departure-early-hide`** arm. Add that arm to `MM_FEED_ARMS`. It runs once as RECORDED discovery; its full outcome set is then registered by review before gate 7. Use the same expectation for an explicitly scheduled OBS control.

Count unplanned contexts diagnostically; emit no frame records for them. Retain lightweight lifecycle tracking for later attribution; a context becoming planned without complete required evidence remains unreadable.

Reset `artworkDone`, DOM/hand-back buffers, ring ownership and attribution per visit, independently of decoder-observation lifetime. **Repeated-visit aggregate verdicts remain INCONCLUSIVE this round**: probe `:3768–3772` requires per-visit continuity intervals, which are deferred. Acceptance is independent visit evidence, not newly green repeat visits.

Bump the producer report to **version 3**. Extend version-aware normalization/contracts, including hand-back handling currently gated on version 2. Keep the empty/unbound null-`atScene` exemption **only for version 2** at contract `:709–726`; v3 counts unplanned contexts without emitting exempt frames. Preserve legacy replay and reject populated unattributed frames.

Preserve owner error scope exactly: malformed producer report nulls all feed entries; malformed normalized record nulls only its entry. Feed errors/overflow stay here, not in C2’s run invalidity.

F splits resume observation out of `score_poster_hold:1056–1105`; P integrates the additive `underArtwork.resume` result and G consumes it. Required poster-hold checks still cover pause, stationary clock, no seek/restart and readable resume continuity. Only the fully evidenced owner-approved **one-frame drop** becomes REPORT. Missing resume evidence, inconsistent clocks, non-advance or larger drops cannot be hidden by REPORT.

Touched: feed `:217`, `:226`, `:347`, `:398`, `:406`, `:507`, `:1056`; contract `:683`, `:709`, `:726`; probe `:3754`, `:3763`, `:4329`.

Deletion/test surface: remove unplanned frame production, lifetime-long artwork completion and duplicated departure interpretation. Keep shared attribution. Extend F’s fake page with second visit, unplanned context, departure order and resume cases; extend contract tests `:406`/`:431`. P retains report-wide/record-local rejection coverage at probe tests `:12140`.

Offline Alpha producer replay retains **0 contract errors**, without asserting pass; absent v3 evidence remains unknown. Reds: early hide, overlay ride, ambiguous attribution, malformed report, larger resume drop. Null: repaired departure and approved readable resume case. Fresh acceptance: zero unplanned frames, independent visits, zero observed rider-above-label/poster-exposure frames on positives; hand-back **≤2 source frames** with readable fps.

**7. C5 — one judge, complete inventories and explicit host policy**

Module: new `scripts/gate_checks.py`.

```python
judge(record: Mapping[str, Any], gate_kind: str,
      arm: str, host_kind: str, *, rc) -> GateResult
```

Return `MATCH | RECORDED | MISMATCH | INVALID | REPORT`, ordered printed lines and existing exit/status mappings. `rc` carries actual execution status, including unavailable status; malformed/missing required inventory cannot match.

Derive deck from `groundTruth.planSha256`, never filename or caller label. Registry key: **`(plan SHA | explicitly registered deck class, arm, host kind)`**. Preserve GL mode in arm identity or its exact registered subkey so existing `(plan, arm, gl)` red sets cannot collide. Gate kind selects required checks.

Move **all plan pins and expectation tables** into `gate_checks.py`, owned by G: P2/deck/Alpha/D7/D7s pins, red/strip sets, read-point expectations, paint floors and feed/REPORT rows. Probe imports them; judge imports validity but never probe. `run_gates.sh:340–352` AST-reads `gate_checks.py`. P migrates assertions at tests `:8276–8503`, `:12497`, `:12513` in the same checkpoint.

Join exact spec IDs, not recursive walks/substrings. Duplicate/missing/extra IDs fail. OBS feed judgement requires **every plan verdict**, including both Alpha `b8to9 …->end:retire` entries per session; expected red subchecks remain explicit exceptions, not omitted inventory.

| Row | Headless baseline | OBS baseline | Proposed owner decision |
|---|---|---|---|
| Feed-off `feedLive` | False | False | Keep explicit red. |
| Feed-off `holdFrame`, `posterHold`, `handbackContinuity` | True | True | Keep required/readable. |
| Feed-off `noRiderAboveCanvas`, `artworkAbove` | Omitted | True | Require True on both after evidence closes. |
| Feed-off `labelsOverFeed` | Omitted | Omitted | Preserve omission unless separately qualified. |
| Feed-on `holdFrame` | Exactly `None` | Omitted | Explicit evidenced N/A for continuous mode; missing applicable hold never N/A. |
| Feed-on/off `departureExposure` | Absent | Absent | Require True on both hosts. |
| D7 `departure-early-hide` | Unregistered | Unregistered | Require `departureExposure=False`; one RECORDED discovery run, then register the full outcome set by review before gate 7. |
| Feed-off approved one-frame resume drop | No dedicated row | No dedicated row | REPORT from F’s separate resume result. |
| `entryColdStart` | No dedicated row | No dedicated row | REPORT per mount; never acceptance. |

Headless baseline truly expects `None` (`run_gates.sh:784–791`), not “not None.” REPORT cannot suppress missing holds, seek/restart, larger discontinuities or placement failures. Validity precedes matching; invalid expected-red is never MATCH. `RECORDED` remains discovery-only.

Touched: probe `:201`, `:220`, `:304`, `:349`, `:6685`, `:6710`, `:6730`, `:7470`, `:7623`; OBS `:4911`; shell locations below.

Port **seven judgement heredocs**, preserving their existing stub cases: `check_mm_feed:734` first, then `expect:246`, `check_host_red:434`, `check_passg:507`, `check_passg_red:564`, `check_paint_control:626`, `check_cc:687`.

Keep five bodies in place: `summ:208`, H.264 prewarm `:311`, D7/D7s staging `:340`, Alpha repair `:393`, `paint_report:524`; only required pin-source/provenance wiring changes. No unrelated CLI extraction. `summ` consumes validity-aware status and retains inventory reporting.

Shell retains queue, nonce, process groups, `.rc`, load handling, staging and main-venv/gate-worktree-src behavior at **`:185–186`**.

G updates the `gates` test fixture (`tests/test_run_gates.py:322-331`):
- symlink `gate_checks.py` and `live_run_validity.py` into the fake gate worktree;
- move the D7 pins out of `PROBE_STUB` (`:134-136`).

The sha-mismatch case (`:470-481`) keeps its independent literal.

Deletion/test surface: remove duplicate wanted tables, recursive discovery, shell paint-floor/red-set policy and repeated status decisions. Move stub cases into judge tests; retain orchestration assertions. Replace probe shell-text tests `:8395`/`:12491` and adversarial regex policy tests `:270` only after outcome coverage.

Reds: invalid expected-red, absent hold/retirement/departure evidence, wrong paint floor, duplicate/substr-colliding IDs and nonmatching rc. Null: valid complete inventories matching frozen rows. Acceptance: byte-stable printed lines/exits except explicitly reviewed semantic migrations with updated snapshots; preserve discovery/full/dev distinctions, including dev success **10**.

**8. C10 audit — deliberate pins and movie provenance**

Retain the existing probe harness interface:

```python
feed_fixture_identity(export_root: Path,
                      slides: Sequence[Mapping[str, Any]]) -> dict[str, Any]
```

Keep `exportRoot`, `headerSha256`, `slideJson`; add deterministically ordered referenced-media asset/path, byte count and SHA-256. Hash actual served movie bytes once per unique file. Missing/unreadable referenced media refuses qualification; replay cannot replace absent historical provenance with today’s bytes.

Re-derive repaired D7/D7s plans from staged exports. Report old pin, derived pin, structural difference, Stage T repair evidence and movie identity. If unchanged, record the audit without editing pins. If changed, G deliberately edits **only `gate_checks.py` pins after review**. D7-unrepaired remains the refusal control; no automatic blessing or fixture registry migration.

Touched: probe identity `:1114`, `:1131`; shell staging `:340–390`; OBS identity `:1929`; pin assertions in deck tests `:494`, shell tests `:135`/`:478`, migrated probe test `:12513`. Original probe pin location `:201` has already moved under C5.

Confirm Stage T audit source is `~/Desktop/Convert wall to 16x9 CGs/Continuity/stage-t-exports`; distinguish it from qualification-export paths.

Deletion/test surface: remove duplicated identity construction in touched harness paths. Keep independent expected pin literals in tests. Extend one identity case: movie-only change alters provenance while header/slide hashes and possibly plan SHA remain equal; retain missing-media and unrepaired refusal cases.

Reds: changed movie bytes, mismatched pin, unrepaired D7. Null: unchanged repaired export. Acceptance: all served referenced movies accounted for, zero unexplained plan changes, reviewed old→new pin record if needed, refusal retained. Offline filesystem proof needs no browser or Keynote.

**9. Disjoint streams and atomic integration**

One Codex GPT-5.6 Sol high implementer per stream; Opus 5.5 high reviews checkpoints and integrated changes. Whole-file ownership includes tests; never concurrently edit different regions of the probe or its test file.

| Stream | Exclusive files | Ordered responsibilities |
|---|---|---|
| P | Probe, detach experiment, conditional hand-back probe; corresponding tests/replay fixtures | C6 → C1 config → C2 integration → C3 consumption → C4 aggregate → C5 wrappers/test migrations → C10 identity. |
| F | Feed instrument, binary-counter layout, OBS decoder, evidence contract; corresponding tests and new feed test file | C1 → C2 feed health → C4 v3/departure/visits/resume; authors every contract patch. |
| V | New validity module, paint instrument; validity/paint tests | Freeze qualification/health interface → C2 cost/environment validity + cadence measurement → C3 phases → (after owner gate 5a) cadence gate checkpoint. |
| O | Managed OBS qualifier and its tests | C6 capture → C2 environment/take validity → C5 whole-deck judge → C10 identity propagation. |
| G | New gate judge, run_gates, gate/shell/adversarial tests | C5 tables/pins/CLI → reviewed C10 pin changes and staging. |
| Coordinator | Deck tests, approved review/result documents, external audit, `.agents/skills/obed-edom/SKILL.md` | Contract integration scheduling, C10 audit evidence and serialized verification; at closure, updates SKILL.md's pin, judge and validity references (e.g. `:828`, "beside `ALPHA_DSK_PLAN_SHA256` in" the probe); never owns pin edits. |

Contract changes are **F-authored patches co-landed in one integration commit with their producer**, not independent commits awaiting repair:

| Checkpoint | Producer owners co-landing with F contract |
|---|---|
| C6 | P/O capture fields, `continuousExpected`, host/scope and observer/sampler evidence. |
| C1 | F sampling diagnostics/layout and P configuration; F replacement fake-GL test, then P deletion. |
| C2 | P sampler health, V pre-paint health, F feed health, O environment/OBS health and V qualification consumer. |
| C3 | P `SAMPLER_JS.nextSceneId`, V phase interpretation and P cold-start output. |
| C4 | F version 3, context/visit/departure/resume records and P aggregate keys. |
| C10 | P/O media identity plus F contract changes if identity validation requires them. |

Start P/O C6 after capture fields freeze. C1 follows reviewed C6; C2 follows C1 measurements and the frozen schema. C3 V/P and bounded C4 F can progress concurrently, with P integrations serialized. C5 follows reviewed C2–C4 outputs. C10 follows C5; G alone edits pins after the audit review.

P alone removes old monolithic tests after replacements pass. No stream edits another’s owned file. Resolve checkpoint/integration findings before fresh qualification.

**10. Verification, historical impact and owner decisions**

One heavy job machine-wide, **≤3 headless Chromes**, uptime/load/browser identity recorded. Suites are heavy jobs. Never overlap red/null captures or calibration with suites.

| Order / host | Gate | Acceptance |
|---|---|---|
| 1 / offline | C6 replay/schema checks | Comparable outcomes preserved; missing evidence unknown; legacy P2 oracle retained. |
| 2 / headless scratch | C1 timing matrix and paired Alpha captures | Explain operation/frequency costs and canvas mode; fixed p95 ≤~4 ms, scenes 8/10/12 medians ≤~33 ms; fallback fidelity proven. |
| 3 / headless scratch | C2 clean red/null calibration | All-hook evidence complete; old instrument INVALID; fixed null meets cost; unresolved cadence statistic presented with per-visit data, not silently frozen. |
| 4 / offline | Historical impact review | Inventory, classifications and counts delivered before validity freeze. |
| 5 / offline | C3/C4/C5 interface checks | Never-decoded inconclusive; cold-start REPORT; v2 replay/v3 strictness; repeat visits remain inconclusive; exact judge/rc behavior. |
| 5a / owner | Freeze Q1 host rows and the Q2 cadence statistic, together with the historical impact list | Owner decision recorded. Gates 7–14 do not start before 5a; the V cadence-gate checkpoint lands after it. |
| 6 / offline | C10 audit | Reviewed pins/media; unrepaired D7 refused; Stage T source verified. |
| 6a / full suites | Integrated Python 3.12 and isolated 3.10 from `uv.lock` | Full suites pass **before gate 7**; required fixtures present, no silent skip substitution; root-cause failures. |
| 7 / headless | Existing departure fix, core `302c218d`, previously unrun | Positive `departureExposure=True`; D7 early-hide control `False`; exact judge inventory, valid instrumentation. |
| 8 / headless | D7 → D7s → Alpha positives/reds | Readable positives and exact registered reds: no-linger, interim-delay, early-hide, no-pin-hold, settle-on-stage, overlay-ride, ordinal/after-feed/from-only/no-pause/kill/opacity/strip. |
| 9 / headless | Feed-off/readability and Q3/Q5 | Applicable hold/counter evidence readable; approved resume REPORT only; Chrome 155.0.8059.79; full viewport/loop scope. |
| 10 / separate diagnosis | Alpha b6to7/b7to8 artwork/frame-2 `#body` placement | Reproduce and disposition independently; owner decision before any product edit. |
| 11 / agent hidden managed OBS | Fresh feed/feed-off D7/D7s/Alpha | No owner projector session here. Validity established; hand-back ≤2 source frames; departure/labels/artwork correct; every plan verdict present, including both Alpha retirements per session. |
| 12 / owner | Rebuilt `stage-b-q7`, Q7 attempt 4 | All three decks; placement leaves `probing`; inspect 7→8→9, departure and hand-back by eye. Required Chrome Q3/Q5 precede attach. |
| 13 / owner | Q7 step 3 | Dashboard D1; Alpha through end and press past end once; record separately from retirement instrumentation. |
| 14 / closure | Q2–Q6 | Q2 P2 fast/slow/auto equals S3; Q3 full host/Pass G matrix; Q4 G2 plus four force-fail arms; Q5 full L1/L2; Q6 existing OBS arms plus feed/exact hold at **25/30**, preserving controls/limits. |
| 15 / suites/review/PR | Dashboard UI/maps, final integrated review and PR | Python results from 6a cover final bytes; rerun affected/full suites if later changes invalidate them. Run UI/maps with isolated performance checks; results-only gate record, then PR. |

Preserve CEF qualification/default policy. Instrument work does not independently enable a product default. A later product-byte change reopens affected qualifications.

If gate 10 reproduces the placement defect, gates 11–13 cannot be marked passing. Agent hidden-OBS diagnostics may document it; a known-failure owner Q7 proceeds only under Owner Q3’s disposition. Do not consume owner time as an implied repeat of gate 11.

Historical impact procedure: inventory qualification passes, formerly valid runs and green subchecks separately. Record path/hash, deck/arm/host, original head/browser/status, available fields, proposed outcome and measured threshold/reason. Classify **proved INVALID**, **still valid**, or **not re-evaluable**; missing health never proves validity. Recorded over-budget cost can prove invalidity despite other missing fields. Do not infer historical browser/rate from today’s machine.

Deliver the complete available-artifact list and counts before freeze, including load-overlapped exclusions and the five attempt-3 `valid=True`/`passed=False` feed runs. Preserve original artifacts; no grandfathering or historical rewrites.

Owner questions are implementation decision points, **not questions for this non-interactive planning turn**:

1. **C5 host rows.** Recommend §7’s explicit rows:
   - add headless feed-off rider/artwork checks, and departure exposure on both hosts;
   - preserve required holds, the explicit feed-live red and only the approved resume REPORT;
   - a separate row: **the OBS feed judge requires every plan verdict**. That turns gate 11 into whole-deck CEF qualification of sampler paint/continuity checks that have never been qualified at OBS rates; the alternative is underArtwork plus retirement only.

   Freeze after fresh readable evidence.
2. **Validity statistic and historical impact:** recommend the 8 ms cost proposal, subject to all-hook clean calibration. Cadence remains unresolved: clean scene medians reach 33.3 ms against 33.3333, maxima reach 133.3, and per-visit p95 is absent. Present fresh visit statistics and the historical impact list together; require demonstrated clean-null margin before selecting the general cadence statistic.
3. **Alpha product blocker:** if gate 10 requires product work, choose known-failure Q7 recording or fix-before-Q7. Recommend **owner go before any product edit**, followed by a concrete minimal patch review and affected requalification; no failing gate becomes a pass.

**11. Risks and rollback**

| Risk | Containment and rollback |
|---|---|
| One draw still exceeds cost | Measure canvas backing/source size; GPU downscale then decimated-ring fallback. Acceptance unchanged; unresolved cost blocks qualification. |
| Downsampling/decimation loses discrimination | Compare levels, departure coverage and every positive/red control. Revert sampling if unproven; never disable its checks. |
| Cadence rule rejects clean runs | Keep Q2 unresolved until fresh visit evidence establishes margin. No period change without an owner decision, and no historical inference. |
| Shared carry windows hide later defects | Retain later-loss/remount/no-pin-hold/strip reds. C3 can revert independently while C2 remains enforced. |
| C4 broadens error scope or claims repeat-visit success | Contract tests lock report-wide/record-local rejection and repeat-visit INCONCLUSIVE; revert the bounded attribution checkpoint if violated. |
| C5 changes shell lifecycle or acceptance | Port all seven stub sets; retain queue/process/nonce checks and reviewed output snapshots. Never restore rc-only acceptance that bypasses validity. |
| Cycles, hidden globals or schema skew | Pure judge/validity never import probe; retain late-bound controls/hooks; co-land F-authored contracts with producers. |
| Historical evidence becomes unusable | Preserve originals and classify missing evidence honestly; no automatic requalification. |
| Fixture changes silently move pins | G alone changes reviewed pins; compare media/JSON/plans separately and preserve unrepaired controls. |
| Alpha requires product work | Record exact frame/entry failure; obtain owner disposition before edits, with served-byte/plan-SHA proof and reopened gates. |

Keep each candidate separately reviewable. Before closure, verify product core/feed/player/G2 bytes and runtime plans remain unchanged except deliberately reviewed fixture-pin consequences. Any instrument-forced product edit must identify changed bytes, plan effects, refusal implications and every reopened qualification.