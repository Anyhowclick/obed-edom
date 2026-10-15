# Managed-OBS placement run restructure — rev 3

Status: approved by owner 2026-10-15, ready for implementation.

Owner decisions: placement qualification defaults to one 25+30 fps pair (`--takes 1`); the three-anchor/harness-injected-grant amendments to P §5/§11.6 are approved; the existing failure/cancellation recording mismatch is a separate follow-up; DEV is authorized. Delivery order: **instrumentation + DEV v1 → A → B**, with DEV adopting anchor/injection acquisition as soon as its fail-closed tests pass.

Baseline: `68b93b5c628db34ed81df3fcd14f5462a6abedd8`. This revision used read-only inspection; no files were edited and no applications or tests were run. New source citations were checked against this baseline.

Citation shorthand:

- **Q** — `scripts/managed_obs_qualify.py`
- **D** — `scripts/dissolve_probe.py`
- **H** — `src/obed_edom/live_host.py`
- **M** — `src/obed_edom/managed_obs.py`
- **P** — `.agents/plans/keynote_live_cef_placement.plan.md`
- **G** — `scripts/run_gates.sh`
- **I** — `.agents/reviews/cef-placement-2026-10-13/speed-investigation.md`
- **E** — `/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-14`

## 1. Target and evidence basis

**Target: ≤1320 seconds, approximately 22 minutes, for one cold 25+30 fps pair through durable final verdict.**

The owner’s approximately 45-minute unit is one pair. Live4 summaries specify `takes: 1`, rates `[25,30]`, and totals of 2691.70/2687.03 seconds. Live6 instead collected two takes per rate: four launches totaling approximately 5422 seconds. Its paired totals are 2711.74/2710.26 seconds. See I for the investigation and rev 2 §1 for the detailed live6 budget; do not add overlapping phase estimates.

One pair supplies two fresh CEF launches and two fresh Chrome launches per GPU setting, retaining both Chrome sessions within each OBS launch. P requires both output rates and two fresh launches, not two launches per rate (`P:362`; `Q:4051–4070`). Explicit `--takes 2` remains available. The accepted loss is same-rate repeat-launch evidence and a second opportunity to expose intermittent failures at each rate.

The current live summary does **not** enforce the offline fresh-launch rule: it aggregates per-run booleans (`Q:4288`). Factor `Q:4051–4070` into a shared launch-set check used by live placement summaries and `--score`, adding tier, completeness and both-rate validation. A complete `--takes 1` full invocation’s summary becomes the qualification verdict.

Measurement limits remain:

- Live6’s 196–205-second post-quit bracket is not function-level attribution.
- Nested DSK script time is omitted by the existing timing summary; restore it.
- Printed `decode: 0` excludes recording analysis and retirement decoding.
- Live6 retains records/logs, not the PNGs or recordings needed for independent pixel reproduction, and uses different commits across rates.
- OBS already launches once per rate/take. Shorter timeout ceilings and launch pooling offer negligible successful-run savings.

## 2. Design

### DEV: two fixed, dependency-complete profiles

Add placement-only `--tier dev|full`, default **full**, and `--dev-profile renderer|harness`, default **renderer** for DEV. Preserve existing defaults for other arms.

Placement defaults to `--takes 1`. Full runs both 25 and 30 fps; explicitly supplying `--rate` with full placement is a parser error. DEV uses one selected rate, default 25. Distinguish an omitted `--rate` from an explicit argument, update `--rate`/`--takes` help, and scale disk-preflight estimates to the actual profile, rates, takes and acquisition path (`Q:4159–4175`, `Q:4183–4184`, `Q:4252–4256`).

DEV v1 filters the existing per-context calibration path without introducing new acquisition machinery. It retains genuine calibration, preflight controls, recordings and persistence evidence for every selected renderer context, including the existing deliberate wrong-rule injection after calibration. After A, implement B; **DEV adopts three genuine anchors plus injected grants as soon as that acquisition passes its fail-closed tests**. Full qualification uses the same approved evidence composition.

Use D’s existing `Profile`, `reported` and control overrides (`D:2690–2709`). Filter `PLACEMENT_ARMS` in its existing order. Do not add arbitrary arm selection or a separate host profile.

#### Profile contents

Both profiles retain all seven live controls, both Chrome classifier sessions, the three genuine anchors and every selected arm’s required twins, references, capture coverage and thresholds.

| Profile | Renderer captures |
|---|---|
| **renderer**, default — 20 captures | `opaque-off`, `off`, `noblend`, `on2`, `on`, `m-snap-cef`, `m-snap-cef-twin`, `wrongrule-cef`, `wrongrule-cef-twin`, `perfect-shift`, `m-tone-cef`, `m-tone-cef-twin`, `m-geo-scale`, `m-paused-cef`, `m-off-cef`, `m-fg-cef`, `m-hold-cef`, `m-fg-omit-cef`, `m-fg-swap-cef`, `m-snap-cef-underlay-omit` |
| **harness** — 26 captures | Renderer set plus `m-snap-cef-nooffset-x`, its twin, `m-snap-cef-nooffset-y`, its twin, `m-geo-base`, `m-snap-cef-dsk` |

These lists define membership; acquisition follows the original arm order.

Retain `on`/`on2` for CvC (`D:4111`, `D:4893`). Retain `m-tone-cef` and its twin for the launch-local measured colour map and enforced tone-observation check, although tone acceptance remains REPORTED; `m-tone-cef` also supplies a mask positive (`D:4836–4845`, `D:2754`; `Q:3241–3242`). Omitting `opaque-on` removes the report-only matched comparison (`D:2652`, `D:4895–4900`).

#### DEV budgets

Live6’s two 25 fps runs measured the following subset acquisition sums. These are script durations, not standalone end-to-end profile measurements.

The r2 critique’s event analysis estimates approximately **12.2 seconds removed per injected row**, excluding positioning. For planning, retain rev 2’s approximately 65-second surrounding-work allowance and provisional finalization/scoring allowances of 115–140 seconds for renderer and 150–180 seconds for harness. B’s finalization credit is approximately 2.1 seconds per removed calibration row.

| Profile | Measured script sum | DEV v1 total estimate / target | Injected rows | Script sum with B alone | Total estimate with B alone | A+B target |
|---|---:|---:|---:|---:|---:|---:|
| Renderer | 554.97 / 556.70 s | 735–762 s / ≤13 min | 17 | 347.57 / 349.30 s | 492–519 s, ≈8.2–8.6 min | ≤7 min |
| Harness | 766.63 / 766.97 s | 982–1012 s / ≤17 min | 23 | 486.03 / 486.37 s | 653–683 s, ≈10.9–11.4 min | ≤9 min |

For example, renderer’s lower B-only estimate is `554.97 − 17×12.2 + 65 + 115 − 17×2.1 = 491.87 seconds`.

B-only columns isolate its estimated contribution; implementation still proceeds A before B. Finalization credits, injection overhead and all subset totals remain hypotheses. Count cold preparation, retries and durable reporting in actual measurements. Single-launch DEV receives no cross-launch cache credit.

#### Non-vacuous DEV gates

Define explicit DEV control maps rather than deleting missing entries from the full map.

**Exclude every NOT RUN family from enforcement through `Profile.reported`, and render its status as NOT RUN.** Absent arms alone are insufficient: `score_round` can return PASS when synthetic controls pass and its candidate set is empty (`D:4105–4109`). Cost without DSK is the concrete case: its live candidate is `m-snap-cef-dsk`, while its controls are synthetic (`D:477`, `D:519`).

For each profile, test that every enforced family has at least one live PASS-expect candidate and all required live controls. Synthetic controls alone cannot establish live coverage.

| Family | Required evidence and controls |
|---|---|
| Probe/classifier and grant lifecycle | Genuine startup/next-take candidates; existing freshness, failed-recalibration, boundary, wrong-rule and software controls |
| Isolation, Program wire and alpha | Existing local leak, alpha-only, flash/audio and Program-toggle controls in both anchor placements |
| Persistence | Actual clean-quit evidence and existing `check_persistence` unit tests, as in full; no new DEV runtime control |
| Fade, curve, handoff and CvC | `off`, `noblend`, `on`/`on2`; existing curve, monotone, handoff and CvC scorer cases |
| Holder pixels, reference, mask and geometry | `m-snap-cef`/twins, wrong-rule, shifted perfect, malformed-evidence cases and `m-geo-scale` |
| Frozen-frame/region and foreground | Paused/off, foreground/hold, omit/swap |
| Cost and DSK | Harness only: actual two-holder DSK candidate plus existing 50 ms/50 ms+ε scorer controls |
| Offset paths | Harness only: x/y nooffset defects and their own twins |

Control definitions: `D:504–525`, `D:2745–2757`. Persistence checker and existing accepted/rejected/stale snapshot tests: `M:568`; `tests/test_managed_obs.py:2208–2223`.

Renderer does not claim DSK cost or x/y nooffset coverage. Malformed mask/reference cases retain their specified INCONCLUSIVE outcome; they never satisfy an expected FAIL. Fail-closed controls remain mandatory. `cut`, `tone` and incomplete W5 remain REPORTED. Unit-test coverage is not described as live product observation.

#### DEV cannot qualify

Follow G’s convention: **DEV success exits 10; full qualification success exits 0; failure/inconclusive exits nonzero other than 10** (`G:4–10`, `G:638`).

- Keep tier selection outside `calibration_gate`.
- Run, summary and child records carry `tier`, plus `devProfile` for DEV, including controls, Chrome sessions and DSK attempts. Derive evidence mode from record content; do not add a duplicate mode field.
- Any launch containing a DEV record is DEV. A bundle containing DEV can never exit 0.
- Emit **DEV — NOT A QUALIFICATION PASS**, with a distinct `devPassed` result. Never set DEV’s qualification `passed` field true.
- Validate the selected profile’s complete expected set for every launch. DEV reports full qualification rate/fresh-launch requirements as unmet.
- Live and offline scoring inspect acquisition tier before counting sessions or launches. Combining DEV runs across profiles or rates cannot qualify.
- Offline scoring derives scope from records, not CLI flags or directory names. Mixed DEV/full bundles cannot qualify.
- Full requires both rates, distinct fresh launches, complete arms/twins/controls and every listed attempt. Reject empty/aborted launches.

Implement this boundary before releasing subset acquisition; today’s offline discovery and launch counting are broad (`Q:3976–3988`, `Q:4051–4070`).

#### DEV scorer-only iteration

`--score` on a retained DEV output directory must rerun its live renderer scoring, including PNG-backed arm/twin checks, launch-local LUT, controls and DSK attempts. Reuse the existing loading/LUT/scoring seams (`Q:3229–3242`, `Q:3269–3297`; `D:4803–4821`).

Resolve evidence relative to the retained bundle so relocation works without acquisition caches or live apps. Missing images or attempt records are INCONCLUSIVE. Preserve original acquisition records and write rescore results separately.

This saves one whole acquisition per scorer iteration. It remains DEV, exit 10 at best. Qualification-bundle offline rescoring retains the product/control scope below; full renderer-pixel rescore for those bundles remains outside scope.

### A. Changes preserving the evidence model

#### A1. Faster positioning with warm-path equivalence

Use `goTo` to the earliest predecessor preserving the target transition’s prerequisites, then perform necessary ordinary builds. Retain the old path for any arm that fails equivalence.

Gate this explicitly to placement invocations, including DEV, through a Q-supplied driver parameter. Arm names are insufficient because D also serves DX-1/DX-2 (`D:4457`).

Compare pending scene/build, automatic playback, decoder identity/presented frame, URL fragment, continuity/carry state, foreground, texture inventory, holder admission and destination readiness. Preserve measured transitions, live/reference pairs, perfect captures, twins and DSK’s two directed counter identities/fragment offsets.

Estimate: **130–160 seconds saved per full launch**, excluding fixed-wait savings. Instrument navigation separately.

#### A2. Fixed sleeps → verified readiness

Within placement scope, replace initial/final settling with bounded predicates for the correct scene, decoder and OBS-painted state (`D:4450–4482`). Busy/readiness timeout becomes INCONCLUSIVE.

Paused readiness requires the intended presented frame and stable captured pixels. Moving readiness requires advancing presentation evidence; pixel equality could accept a frozen decoder.

Preserve ≥300 ms probe paint waits, capture spacing, independent live/reference samples, five-mid-frame/handoff coverage, reference animation inventory, seek readbacks, perfect captures and sufficient defect exposure. Record predicate results and duration; DOM readiness alone is insufficient.

Estimate: **55–70 seconds per full launch**, excluding navigation and recording tails.

#### A3. Invocation-wide scratch preparation cache

Reuse generated movies, transcodes and stripped assets across fresh launches within one invocation, extending existing preparation seams (`D:1210`, `D:1222`, `D:1247`).

Key by full source hashes and generator/transform inputs, including encoding, dimensions, media fps, frame count/duration and relevant fragments. Verify output hashes on reuse, fill atomically and keep assets immutable. The toolchain is fixed within the invocation; no persistent cache or new provenance schema.

Prewarm outside capture but count preparation in end-to-end time. Never cache grants, contexts, calibration captures or verdicts.

Credit approximately **24 seconds on the second launch of one pair**, based on I’s DSK preparation measurement. Explicit four-launch runs may save approximately 72 seconds. Live6 has no separate preparation timer.

#### A4. Reuse pure scoring work

Compute immutable classification/control results once per input within a scoring invocation. Recheck inputs affected by quit snapshots, telemetry or recording retirement; never use stored verdicts as evidence.

Add a bounded decoded-image cache to `RunImages`, which currently decompresses each access (`D:4803–4810`). Keep arrays immutable and release memory promptly.

Defer combined RGB/native-framemd5 decoding. B reduces approximately 76 calibration recordings to six per full launch; reconsider only if post-B profiling identifies more than approximately 10 seconds/launch of avoidable decoding. Preserve RGB/native-frame distinctions, PCM checks and retirement rules. Give no independent savings credit before measurement.

### B. Approved evidence composition

Retain three genuine anchors per launch, each with complete existing preflight controls:

| Anchor | Product evidence |
|---|---|
| `opaque-off` | Off-canvas, full sampled RGBA; first for noise calibration |
| `off` | Preview, full sampled RGBA |
| `m-snap-cef` | Preview, existing product-timing sampling; genuine grant enables measured next take |

These match the current adapter distinctions (`Q:2167–2172`). Full retains original arm order, **38 captures, nine twins, seven live controls and two Chrome sessions per launch**.

Keep complete schema-1 anchors. Do not introduce shared-control records, a schema-v2 envelope, manifest, generic EvidenceRef, configuration hash or separate-verdict framework. Complete local controls cost approximately 11 seconds/launch more than sharing one set.

For the remaining 35 full-tier rows, or selected non-anchor DEV rows:

- Construct the script-only probe-mode channel without a calibration adapter. Product status remains unsupported/invalid (`H:132–141`, `H:1563–1565`).
- Inject **before positioning** using the existing privileged seam (`Q:2211–2214`, `D:4673–4677`). Renew at intervals ≤3 seconds through final capture, using the same value and a lease ≤15 seconds (`H:79–80`).
- Verify original connection, unique context, engine and fingerprint before renewal. Expiry, late renewal, failed readback or changed binding aborts the attempt. Never revive an expired attempt or silently retarget it.
- Revoke in `finally`, verify `invalid`, and stop/join renewal before releasing the host.
- Record every commit/read, the take-time page getter read and revocation. The document getter is authoritative for lease validity (`P:775–780`, `P:801–802`).
- Use `arm.placement_value` when set, otherwise `CEF_PLACEMENT.placement`.
- All anchors must independently classify `frac`. Only `wrongrule-cef` and its twin deliberately use `snap` (`D:455–457`). Acquisition need not wait for another anchor’s result; scoring enforces launch consistency.
- Compare `m-snap-cef` with its injected twin using existing pixel checks, retaining their distinct grant origins.

#### Approved amendment to P §5

> **Placement qualification evidence composition and repetition.** Qualification defaults to one take at each of 25 and 30 output fps (`--takes 1`), with the existing prescribed source rates: two fresh managed-OBS launches, one per rate. Each launch retains all 38 renderer captures, including nine twins, the seven existing startup/failed-recalibration/freshness control sessions, and one fresh Chrome classifier session for each GPU setting. This supplies two fresh CEF launches and two fresh Chrome launches per GPU setting. Explicit additional takes repeat the complete pair. Preserve all numerical thresholds, arm expectations and capture coverage. `cut`, `tone` and incomplete W5 observations remain REPORTED.
>
> One pair replaces the historical two-takes-per-rate repetition. It retains cross-rate fresh-launch coverage but does not establish same-rate repeat-launch reproducibility.
>
> Each launch collects three genuine product-calibration anchors in existing arm order: `opaque-off` with off-canvas/full sampled-alpha calibration; `off` with preview/full sampled-alpha calibration; and `m-snap-cef` with preview/product-timing calibration. Every anchor retains complete preflight controls, product transaction, context-bound commit, recording and cleanup/persistence evidence. The product-timing anchor must demonstrate that its genuine product grant enables the measured next take.
>
> Other renderer rows use explicitly recorded harness-injected grants in their own fresh contexts. The injected value is the arm’s explicit `placement_value`, or the CEF placement profile value when unset. Injection begins before positioning and is renewed through final capture within the existing 15-second lease and three-second renewal cadence. These rows prove renderer behavior under the selected rule; they do not prove fresh product calibration, renewal or isolation in their contexts.
>
> Product gates derive only from genuine anchors and existing control sessions. Every dependent renderer row requires all three same-launch anchors to pass their applicable enforced product gates and classify `frac`. Renderer pixel, geometry, foreground, reference, mask, fidelity and cost gates retain their own captures, twins and thresholds. Detector controls remain local to each anchor.
>
> Program-wire coverage is unchanged from #278: candidate recordings cover successful anchor transactions in both placements; failure/cancellation coverage remains the live controls’ existing checks and `CALIBRATION_FAULT_TESTS`. This does not establish continuous failure/cancellation recording coverage; the discrepancy with §5’s broader recording requirement is a separate follow-up outside this plan.
>
> Product §2.5, §11.3 and O4 remain unchanged. An injected grant never counts as fresh product evidence or transfers an anchor’s grant/request identity. Missing, malformed, stale or incompatible evidence is INCONCLUSIVE and cannot satisfy an expected FAIL. Qualification requires complete launch/session/attempt coverage and all applicable enforced gates.
>
> A separately marked DEV tier may select one rate and a named dependency-complete subset and may use anchor/injection evidence. It always reports DEV, never qualification PASS, and contributes no evidence toward qualification.

Recording discrepancy: `P:347`, `Q:1883`, `Q:1965`, `Q:233`. No additional failure/cancellation recordings are included in this performance budget.

#### Evidence changes by gate

| Family | Evidence lost | Retained |
|---|---|---|
| Probe/classifier | 35 repeated successful context calibrations per full launch | Three genuine anchors, freshness/Chrome controls, launch consistency |
| Isolation, wire and alpha | Calibration-time observations and repeated detector controls in those contexts | Both placements, sampled/product-timing distinction, complete local anchor controls |
| Product lifecycle/channel | Fresh product acquisition before every renderer case | Genuine grants, next-take engagement, controls/fault tests, unchanged O4 |
| Persistence/worker | 35 successful installation/removal cycles and snapshots | Complete retained-transaction evidence and authoritative clean quit |
| Renderer | Product calibration before every renderer case | All full captures, twins, thresholds and defects; explicit value/context/lease evidence |
| Launch repetition | Second launch at each individual rate | Two cross-rate CEF launches; two Chrome launches per GPU setting |

Raw/preview boundaries and report-only scope remain unchanged. DEV’s additional omissions are declared by profile.

#### Approved amendment to P §11.6

> **Tier and factored placement records.** New run, summary and child records carry acquisition `tier` and `devProfile` when DEV. Evidence mode is derived from record content. Live and offline scoring preserve acquisition scope: any launch containing a DEV record is DEV, and a bundle containing DEV can never exit 0 or produce qualification PASS.
>
> Anchor rows `opaque-off`, `off` and `m-snap-cef` retain schema-1 `placementCalibration` unchanged, including local preflight controls and FileRefs. Each other factored CEF renderer row omits `placementCalibration` and records:
>
> ```text
> placementInjection = {
>   schemaVersion: 1,
>   value: "frac" | "snap",
>   leaseMs: integer,
>   engine: EngineIdentity,
>   targetId: string,
>   uniqueContextId: string,
>   commits: [{at: number, committed: boolean, read: string}],
>   takeRead: {at: number, value: string},
>   revoke: {at: number, read: string}
> }
> ```
>
> No token is recorded. `at` follows the existing Unix-seconds convention; lease enforcement uses the bound document clock and actual getter readbacks. Acquisition accepts commits only in the originally verified connection/context/engine/fingerprint. Changed binding, expired renewal or unverified revocation makes the attempt INCONCLUSIVE.
>
> A launch is its existing `shots/placement-<timestamp>/` directory. Anchor roles and expected full/DEV session sets are code constants; no manifest or new cross-record reference format is introduced.
>
> Live and `--score` scoring validate each launch independently:
>
> 1. Require its tier/profile’s complete expected session set and acquisition scope. Emit explicit INCONCLUSIVE rows for missing/unreadable sessions and listed-but-missing DSK attempts. Reject empty/aborted launches.
> 2. Score anchors and controls with existing product checks and reverify FileRefs. Never source missing evidence from another launch.
> 3. An injected row is eligible only when its value matches the arm/profile rule; the lease is valid; all commits succeed with matching reads; `takeRead` agrees with the existing pre-advance placement read under an uninterrupted valid lease; revocation reads `invalid`; its engine matches every anchor; and all three anchors pass applicable enforced product gates and classify `frac`.
> 4. Missing, contradictory, expired or incompatible evidence is INCONCLUSIVE. Renderer algorithms and expected outcomes remain unchanged; integrity failure cannot satisfy expected FAIL.
>
> Existing run records supply rate, take, acquisition identity and lifecycle checks; these must agree with child records. A shared launch-set check serves live placement summaries and `--score`. Full qualification additionally requires both rates and the prescribed distinct fresh launches. A complete legacy launch whose renderer rows all carry `placementCalibration` retains its scoring semantics after complete legacy validation.
>
> Offline qualification-bundle rescoring retains its current product/control scope and adds tier, launch completeness and injection/anchor validation. Resolve retained evidence relative to the bundle without acquisition caches or live applications. Reports identify this scope and must not label a product-only rescore as fresh full renderer qualification.
>
> DEV-only `--score` additionally reruns the selected profile’s renderer-pixel scoring from retained records and images, including its LUT, twins and attempts. It remains DEV and exits 10 at best; missing required evidence is INCONCLUSIVE.
>
> Preserve recording retention and framemd5/telemetry rules. Keep non-PASS recordings. An injected row receives no product-calibration PASS of its own.

## 3. Further improvements and target ledger

Savings are hypotheses unless identified as measured; overlapping estimates are not additive.

| Priority | Improvement | Saving / constraint |
|---|---|---|
| 1 | Detailed preparation, acquisition, finalization and scoring timers | Establish actual partitions, nested DSK costs and residual |
| 2 | DEV-only pixel rescore from retained output | Avoid one acquisition per scorer iteration; requires retained PNGs |
| 3 | Pure result reuse and bounded PNG cache | Unmeasured; no independent budget credit |
| 4 | Conditional bounded post-quit process pool | Only if profiling justifies it; initially at most four workers, bounded memory and deterministic results |
| 5 | Verified recording stop/finalized output | Before B, 76 explicit seconds/full launch; after B, approximately six seconds gross maximum |
| 6 | Codec/DSK preparation reuse | Approximately 24 seconds on the second launch, already credited under A3 |
| 7 | Reuse authoritative quit reads/normalization; cheaper DSK retry preparation | Unmeasured; preserve local FileRefs, baseline/removal checks and fresh attempt contexts |

Record monotonic inclusive/exclusive durations, subprocess wall/CPU time and useful byte counts. Separate PNG decoding, classification, pixel scoring, recording analysis, framemd5, collection copying, retirement and report writes.

A scoring pool belongs to one post-quit job and finishes before the next acquisition. Workers perform pure reads/computation; finalization and writes remain serialized. Do not overlap heavy scoring with acquisition. Keep one heavy job machine-wide, at most three headless Chromes, and serialize Chrome/OBS measurement (`P:363`).

Verified recording stop requires sufficient post-restoration frames, inactive recording state and readable finalized output, not acknowledgment alone (`Q:866`, `Q:1558`). Retain DSK’s sole-coverage-shortage retry trigger and maximum three fresh attempts (`Q:2066`). Never retry away a genuine defect.

Reject fewer full-tier Chrome sessions, arm reordering, live navigation-state reuse, launch pooling, concurrent calibration, reduced qualification rates/twins/coverage, relaxed thresholds and deferred scoring advertised as a faster verdict.

### Qualification ledger

| Item | Default one cold pair | Explicit `--takes 2` |
|---|---:|---:|
| Live6 baseline | 2711 s | 5422 s |
| B: removed acquisition envelopes, net of retained local controls | −798 s | −1596 s |
| B: removed-recording finalization | −150 s | −300 s |
| A1: navigation, excluding fixed waits | −280 s | −560 s |
| A2: waits, excluding navigation/recording tails | −120 s | −240 s |
| A3: later-launch preparation reuse | −24 s | −72 s |
| **Illustrative result** | **1339 s ≈22.3 min** | **2654 s ≈44.2 min** |

The ledger is nineteen seconds above the ≤1320-second target. Instrumentation must establish actual partitions and injection overhead. Give no extra credit to caches, pooling or combined decoding before measurement; do not weaken evidence to close the gap.

An invalid launch leaves the pair incomplete. No resume or cross-invocation stitching is added: budget a complete pair retry, approximately 22 minutes after A+B versus approximately 45 minutes today. DSK’s two additional internal attempts can currently add approximately 144 seconds plus finalization; measure optimized retry cost separately.

## 4. Acceptance and machine-time budget

1. **Instrumentation + DEV v1:** ship tier separation, two complete profile maps, CLI/preflight changes and timings together. Verify exit 10 on DEV success, never on missing/failed controls; placement defaults to one pair, while full evidence collection initially remains per-context.
2. **Legacy baseline:** collect one complete instrumented 25+30 pair before A.
3. **A comparison:** collect one pair with genuine calibration in every context. Require positioning/readiness equivalence and unchanged enforced outcomes.
4. **B acquisition:** pass renewal, binding, expiry, take-read and revocation fail-closed tests, then adopt immediately in DEV. Use DEV to exercise renewal during positioning and genuine-anchor/injected-twin parity before the final full pair.
5. **Final qualification:** run A+B on final bytes. Freeze product/player/fixture/toolchain identity across comparisons; record intended harness checkpoints. Retain 38 captures, nine twins, seven live controls, two Chrome sessions and 29 scored renderer outcomes per launch.
6. **Shared aggregation:** exercise both live and offline launch-set validation: absent rate, duplicate launch identity, missing Chrome GPU session, aborted/empty launch, DEV contamination and DEV bundles assembled across rates cannot qualify.
7. **Profile coverage:** every enforced family has live PASS-expect evidence and complete controls. Renderer cost is NOT RUN; harness cost requires actual DSK evidence. Preserve all specified defect outcomes and INCONCLUSIVE malformed-evidence cases.
8. **Integrity:** test missing anchors/controls/sessions/attempts, cross-launch substitutions, failed/late renewals, expired take reads, changed context, failed revocation and corrupt cached outputs.
9. **DSK:** propagate `identity`; retain every attempt. Missing evidence is INCONCLUSIVE; genuine observed mismatch is FAIL (`Q:2105`, `Q:3235`, `Q:4007`).
10. **Offline:** relocate retained bundles and remove preparation caches. Require product/control and injection/anchor parity, complete-legacy compatibility and preserved DEV status. DEV pixel rescore must match live DEV scoring and reject missing images/attempts. Qualification-bundle pixel rescore remains excluded.
11. **Product regression:** retain managed transaction/fencing and host lease/state-machine tests. O4, cancellation, cleanup, pinning and admission semantics remain unchanged.
12. **Performance:** report cold preparation, profile, acquisition path derived from records, rate/take, retries, OBS release and durable-verdict time. Slow valid evidence remains valid; the performance objective remains unmet.

Schedule approximately **112 minutes** for full comparisons: 45 baseline, up to 45 A-only and approximately 22 final. Allow approximately **25 minutes** for an early renderer DEV v1 smoke and a final renderer DEV smoke. Use full captures and targeted tests for harness dependencies/DSK routing. Reserve approximately 30 minutes for suites/offline checks: **about 2¾–3 hours**, excluding debugging, additional profile benchmarks or invalidated runs.

## 5. Implementation streams and ordering

Use **Codex GPT-5.6 Sol implementers** with disjoint file ownership. These are future assignments; this revision starts no implementers or live jobs.

### Instrumentation + DEV v1

One implementer temporarily owns Q, D and their tests:

- Add tier/profile selection, placement defaults/help and profile-aware disk preflight.
- Implement acquisition-tier propagation and shared live/offline launch-set validation.
- Define both profile/control maps and explicit NOT RUN reporting.
- Add detailed timers and nested DSK accounting.
- Add retained-bundle DEV pixel rescoring.
- Keep genuine calibration in every selected context.

Run targeted tests, release DEV v1 and collect the instrumented full baseline. The coordinator then freezes placement driver options, cache location, tier/profile propagation, injection records and launch validation before transferring ownership.

### A, then B

| Stream | Exclusive files | Work |
|---|---|---|
| W1 — orchestration/evidence | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | Shared aggregation, profile-aware orchestration/rescore, pure score reuse, verified recording stop; then anchors/injection lifecycle, completeness and attempt validation |
| W2 — driver/preparation | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | Placement-only positioning/readiness, invocation cache, bounded image cache; then take-time read support and profile scoring integration |

W1 owns orchestration wiring; W2 owns shared driver helpers. Parallel work within a stage must respect file ownership. Complete A’s comparison before B acquisition integration. DEV adopts B when its fail-closed tests pass; full then uses the approved §2B composition. No further owner sign-off is required.

No product changes are planned in M, H, runtime files or G. No separate decode stream or new framework is needed.

Prefer a few behavioral test matrices for profiles, tier isolation, launch completeness, renewals, relocation and cache corruption. Match local style; minimal documentation and no unnecessary inline comments.

After integration, run targeted regression files and required checks serially:

```sh
uv run pytest tests/test_managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs.py tests/test_live_host.py tests/test_placement_probe.py
env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal
env -u PYTHONDONTWRITEBYTECODE uv run --python 3.10 pytest tests/ -n auto --dist worksteal
```

From `dashboard/`, with bundled Node on PATH:

```sh
npm run test:maps
npm run test:ui
```

Every-code-PR requirements: `.agents/skills/obed-edom/SKILL.md:42–51`; Python 3.10 compatibility: `P:409`. Verify fixtures and account for skips. Run socket-dependent tests in the coordinator’s suitable environment. Do not overlap suites, encodes or live measurement.

The coordinator updates P with the approved amendments and updates `.agents/handovers/cef-placement-2026-10-14.md`, superseding its old sign-off requirement, “no committed fast tier” instruction and historical takes guidance without rewriting live6 history.

## 6. Risks and exclusions

Accepted evidence tradeoffs are reduced repeated product-integration sampling under B and loss of same-rate repeat-launch coverage. DEV additionally omits documented matrix coverage and remains non-qualifying.

Principal implementation risks are vacuous subset gates, DEV entering qualification, incorrect launch aggregation, wrong-frame readiness, changed decoder warming, lease expiry during positioning, incomplete attempt discovery, stale assets and excessive scoring memory.

Retain existing residuals: unchanged-fingerprint GPU fallback, transient alpha between samples, identity-tone application, fractional letterbox offsets, scaled stages and physical DeckLink/keyer proof. Do not expand cut/tone acceptance or add failure/cancellation recordings within this task.

## 7. Owner decisions (2026-10-15)

1. **One pair approved:** placement qualification defaults to one 25+30 fps pair with `--takes 1`. Explicit additional takes repeat complete pairs. Same-rate repeat-launch coverage is knowingly reduced.
2. **B approved:** retain the substantive P §5/§11.6 three-anchor/harness-injected-grant amendments in §2B, with the clarified DEV wording and metadata/rescore changes above. Delivery order is instrumentation + DEV v1 → A → B. DEV adopts B as soon as acquisition passes its fail-closed tests.
3. **Recording mismatch deferred:** the pre-existing P §5 failure/cancellation recording mismatch is a separate follow-up outside this plan. Existing controls/tests must not be described as continuous failure/cancellation recordings.
4. **DEV authorized:** ship the renderer and harness profiles with strict non-qualification boundaries and retained-output scorer iteration.

## Review log

- r0 Astra high → r1 Opus 5.5 high: APPROVE-WITH-CHANGES, 4 major / 6 medium / 3 low.
- rev1: incorporated r1 changes.
- rev2: owner inputs — DEV tier + one pair.
- r2 Opus 5.5 high: APPROVE-WITH-CHANGES, 1 major / 3 medium / 5 low.
- rev3: incorporated M1–M4 and L1–L5; recorded all 2026-10-15 owner decisions.- rev3: folded r2 (DEV adopts anchors/injection once fail-closed tests pass; Profile.reported for NOT RUN families; shared live/offline launch-set check; DEV scorer-only rescore; two profiles); owner decisions recorded.

## Implementation status (2026-10-15)

Landed on `claude/obs-run-restructuring-3d0b30`: stage 1 `8899c71c` (DEV tier, shared launch-set verdict, `--takes 1`,
timers), stage A `f71f0f18` (goTo positioning, verified readiness, caches, verified recording stop), stage B `3268d95c`
(three anchors + injected grants). Implementers Codex GPT-5.6 Sol high; reviews Opus 5.5 high (stage 1 r1–r3; stage A two
streams r1–r3; stage B r1–r2). P §5.1 and §11.6.1 carry the approved amendments.

Live results (pinned detached worktree, results-only evidence under
`output/evidence/s2-dev/obs-run-restructure-2026-10-15/`):

| Run | Commit | Result | Time |
|---|---|---|---:|
| `baseline-8899c71c` full pair | stage 1 | PASS, qualified | 2738 s (45.6 min) |
| `devA-renderer-f71f0f18` | stage A | DEV pass, 17/17 MATCH | 595 s |
| `pairA-f71f0f18` full pair | stage A | PASS, verdicts identical to baseline | 2108 s (35.2 min) |
| `devB-renderer-3268d95c` | stage B | DEV pass, 17/17 MATCH | 363 s (6.1 min) |
| `pairB-3268d95c` full pair | stage B | PASS, qualified, 45/45 verdict items per rate identical to baseline | 1173 s (19.6 min) |

Stage B pair: 70 injected rows, 204 renewal gaps 2.23–2.78 s, 70/70 revokes `invalid`, 76/76 captures via goTo.
Remaining per-rate cost: acquisition ≈465–504 s, scoring ≈85 s (pixel scoring; the conditional post-quit pool, §3 item 4, is
the next lever), finalization ≈5 s. Known unrelated flake under full-suite load:
`tests/test_live_host.py::test_managed_probe_state_machine_renews_suppresses_and_stops` (#278 race; passes alone).
