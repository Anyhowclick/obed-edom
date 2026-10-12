# Plan: producer-contract pass for the live-continuity instrument (S2)

**Owner decision (2026-10-11):** close the false-pass class with a producer contract instead of further folds.

**Base:** `claude/s2-detach-fix` at `c7d2d649`. `s2-glclock-fold1` was merged at `0617f24b`; its producer diff since `5fa7d48b` changes no key set or payload. The suite baseline must be re-measured at `c7d2d649`; 10280 passed at `5fa7d48b`.

**Method:** read-only planning. Scratch files live in `<session scratchpad>/contract/` (`proto.py`, `scan_*.py`, `contract_spy.py`, `spy2.json`) and `<session scratchpad>/contract/critic/`.

**Measured so far:**
- The prototype rejects none of 763 arms and takes, 460 managed reads plus 18 armed reads (26 runs), or 38 hand-back records. This covers only the prototype's subset of clauses; the oracle's acceptance scan with the real module is the actual proof (§5).
- Every retained sampler row has `isConnected: true` (580,549 of 580,549).
- No retained artifact holds schema-2 rows, pp/pv reads, sampler meta, paint-control records, carry-cover rows, or bridge-clock / pin-hold-start notes.

## 1. Goal and non-goals

**Goal:** state exactly what the producers emit:
- types, nullability and enums;
- required keys per generation;
- per-sample uniqueness;
- cross-field invariants, but only those **enforced by producer code**, never by browser timing.

Validate each record once, where it is ingested. Any violation makes the arm INCONCLUSIVE (INVALID for force-wrap takes and managed runs). After this pass, only producer-legal false passes block.

**Owner rules:**
- Integrity failures are never pass or fail.
- Complete readable records keep their outcome.
- Explicit nulls the producer emits stay readable.
- The 2280 retained verdicts do not change.

**Non-goals:**
- No threshold, window, mask or tolerance changes.
- No scorer rewrites. Fold 3–5 guards stay.
- No producer JS changes, and no `CONTINUITY_VERSION` bump.
- No `run_gates.sh` change.
- `stage_map_valid`'s rules and the intended stage-fit FAIL are unchanged.

**Exceptions (Q1):** three small producer-reachable false-pass fixes, N1, N2 and N3 (§4).

## 2. The contract

**Placement:** a new module, `scripts/live_evidence_contract.py`.
- It imports only `paint_instrument`, for `schema_problem` and its predicates.
- `stage_map_valid` moves from `probe:1787` into this module; the probe imports it under the same name, so there is no import cycle.
- The probe and `managed_obs_qualify` import the module.
- `p2_verdict` keeps its own `nullControl` table.

**Interface:** pure validators. Each returns `"<clause> at <path>"` messages, where the clause is `kind.field` or `kind:rule`.

**Conventions:**
- The contract checks what is present; whether *enough* evidence is present stays with the scorers.
- CDP drops `undefined`, so a key may be absent only where a table says so. NaN and Infinity arrive as `null`.
- Extra keys are ignored, except in sets matched exactly: decoder generations and the `nullControl` key set.

### 2.1 Sampler row (`SAMPLER_JS`, `probe:458`, push at `:547`)

| field | type | null / absent | rule |
|---|---|---|---|
| t | finite | — | non-decreasing over the stream |
| scene | int ≥ 0 | null when there is no scene (`runtime:154`) | absent only together with `playerState` and `busy` (`stateOf` → `{}`, `probe:465-466`) |
| playerState | one of: Starting, DownloadingScipt, ReadyToJump, SettingUpScene, Playing, WaitingToJump, Stopped, IdleAtInitialState, IdleAtFinalState | absent as for `scene` | `controller.state` or `'Starting'` (`runtime:112`); the literals are verified in players 7ef8ad49 and 962dffa7 |
| busy | bool, never null | absent as for `scene` | `!ready` (`runtime:152`) |
| videos | list of decoder rows | — | probe ids unique per row; non-null `elId`s unique per row |
| stageMap | STAGE_MAP | null | null ⇒ every `footprintOwner` is null (`probe:505`) |
| seq / ts / hash / sceneCount (S2) | int ≥ 1 / finite / str / int ≥ 0 or null | — | `ts` strictly increasing. Seq gaps and order stay with `sampler_self_check` |
| pp (S2) | PP | absent when the ResizeObserver missed the frame | `pp.seq == seq` and `pp.ts == ts` (`paint:172`); `pp.t ≥ t` (`paint:650`) |

**Stream rules:**
- One sampler schema per stream; schema 2 if and only if the sampler reported schema 2 (`probe:3224`).
- One decoder generation per stream.
- A probe id's `elId` is null zero or more times, then one int that never changes (`core:751-755`).

**Post-processing keys** (legal):
- Row level: `stageMapValid`, which must equal `stage_map_valid(stageMap)`; a converted `pp`, carrying `rectScreen`, `visibleRectScreen` and `stageBoxScreen`; `ppUnreadable`, which holds the **raw** pp and is validated as a raw PP; `rafTs`, which must equal `ts` (`detach_experiment:123`).
- Video level: `rectScreen` and `stageMapValid`, which must equal the row's (`probe:1834`, `:1838`).

### 2.2 Decoder row (`videos[]`, `probe:520-543`)

The key set minus `{rectScreen, stageMapValid}` must equal exactly one generation:

| Generation | Keys |
|---|---|
| G1 | currentTime, elId, footprintOwner, id, isConnected, paused, readyState, rect, src, videoWidth |
| G2 | G1 + duration, ended, loop |
| G3 | G2 + domId, facade, preserved, remounted |
| G4 | G3 + instance |

| field | type | null |
|---|---|---|
| id | int ≥ 1 | — |
| elId | int ≥ 1 | when untagged |
| src | str | — |
| currentTime | finite ≥ 0 | — |
| readyState | int 0..4 | — |
| videoWidth | int ≥ 0 | — |
| **isConnected** | **`true` (const)**: `document.contains(v)` over `document.querySelectorAll` (`probe:520`, `:536`) | — |
| paused (G2+: ended, loop; G3+: facade, preserved, remounted) | bool | — |
| rect | box, w,h ≥ 0. Converted: authored box, null **iff** `stageMapValid` is false | — |
| duration (G2+) | finite > 0 | null |
| domId (G3+) | non-empty str | null |
| instance (G4) | str | null |
| footprintOwner | OWNER | null |

- **OWNER:** `{elId, key, via, contextType: null}`, with `via` one of `footprint-video`, `ambiguous`, `unknown-key`, `none`, `no-stage-map`.
  - `footprint-video`: `key` is a non-empty str, and `elId` is an int ≥ 1 or **absent** (owner untagged, `core:347`).
  - Any other `via`: `elId` and `key` are both null.
- **STAGE_MAP:** `{s, sy}` finite > 0; `{ox, oy}` finite; `{offsetWidth, offsetHeight}` int ≥ 1 (`probe:344-353`).

### 2.3 Pre-paint (S2; source only)

**PP:** `{seq int, ts, t finite, videos [PV], stageMap STAGE_MAP|null, stageBox box|null, cover bool}` (`paint:177`). Non-null PV ids are unique, and so are non-null `elId`s (`paint:160`).

**PV:**

| field | type | null |
|---|---|---|
| id | int ≥ 1 | **null is legal** (`paint:94`, `:174`) |
| elId | int ≥ 1 | null |
| instance | str | null |
| src | str | — |
| connected, facade, suppressed, seeking, paused, ended | bool | — |
| readyState | int 0..4 | — |
| videoWidth, videoHeight | int ≥ 0 | — |
| currentTime | finite ≥ 0 | — |
| rect | box | — |
| parent, layer | str | null |

**Cross-field rules:**
- `connected` false ⇒ `checkVisibility`, `visibility`, `displayNone`, `opacity`, `hiding`, `effects`, `transform`, `visibleRect` and `clippedBy` are all null (`paint:104`).
- `connected` true ⇒
  - `checkVisibility` is a bool;
  - `visibility` is one of visible, hidden or collapse;
  - `opacity` is in [0, 1], or null;
  - `hiding` is null or `{node str, prop display|opacity, value 'none'|finite}`;
  - `visibleRect` is a box with w,h > 0, or null;
  - the other fields are str or null.

### 2.4 Reads and nested records

| kind | contract |
|---|---|
| painting (`probe:401-430`) | `{error: str}`, or a list of `{src str, elId int≥1\|null, rect box w,h>1}`; non-null `elId`s unique |
| pool / preserve snapshot (`core:166-204`) | `null`, `{error: str}`, or a list of `{key str, movieKey str\|null, elId int≥1, currentTime finite, paused/ended/inDocument bool, readyState int 0..4, videoWidth/videoHeight int≥0}`. `instance` (non-empty str or null) is absent on **every** entry or on none. `fromDom` is absent or `true`. `key ''` only with `fromDom`. `elId` unique among pool entries and among `fromDom` entries; one decoder in both is legal (Vgl hand-backs in green artifacts, red armed reads) |
| core note (`core:746-750`) | `{kind non-empty str, detail object with sceneHash str, t finite}`; `t` non-decreasing within a list; kinds match the read's filter (`probe:375`, `:452`). Module events have the same shape without `sceneHash`. `facade-error` and `dom-swap-error` details are digit-keyed (`core:1842`, `:1896`) |
| note identity | `elId`/`newElId`/`oldElId` int ≥ 1 (null only on `glreplay-release`); `elIds` a non-empty list of int ≥ 1; `key`/`movieKey`/`instance`/`src`/`dst` str or null |
| per-kind payloads | see the list below |
| GL read (`probe:362-387`) | `{t finite, hash str, ready bool\|null, api, coreEvents: null\|{error}\|[note], pool: null\|{error}\|POOL, facades: [{elId, forElId}] int≥1\|null}`. `api` is null, `{error}`, or `{version 1, state ∈ {IDLE, ARM-PRE, ARM-POST, LIVE, STANDDOWN, RETIRED}, standDowns [str], events [event], stats null\|{epoch, iter, uploads, glErrors int, …}}`. RETIRED ⇒ `standDowns` non-empty; IDLE/ARM-*/LIVE ⇒ `[]` |
| containers | refusal read: `{stageMap, painting, poolSnapshot, coreEvents}`. Armed evidence: exactly 2 reads `{stageMap, painting, poolSnapshot, glReplay}`, or `{reason: str}`. Hand-back record: `{status ok\|inconclusive, reason, targetHash int, expectHandoff bool}` plus whichever GL reads are present (`before`, `polled`). With `status: ok` it also has `before`, `stageMap`, `painting`, `preserve` (POOL) and `after` (GL). The live-ring `capture_live_frame` stage map is a STAGE_MAP or null |
| force-wrap (`probe:621-682`) | **select:** `{domId str, count int≥0, t}`; with `count == 1` either `error str` or `{duration finite>0\|null, loop bool, playbackRate finite, seekFrom finite, target finite\|null}`. **status:** null or `{t, seekedT finite\|null, framesAfterSeek int, last frame\|null, duration, playbackRate}`. **recorder:** null or `{t, seekedT, seekFrom, target, frames, id str, elId/probeId int≥1\|null, loop/ended/paused/isConnected bool, duration, playbackRate}`; frames `{now strictly increasing, mediaTime finite ≥ 0, presentedFrames int non-decreasing}`. **pageErrorNotes:** null or a list of `player-build-error` notes |
| carry-cover (`probe:7907-7971`) | **read:** `{rows: null\|[row], notes: [bridge-motion-start or bridge-clock]}`. **row:** `{ts strictly increasing; tick int in [0, 4096), contiguous mod 4096; pre [vid]; vids [vid] absent only on a trailing suffix; readAt finite iff vids}`. **vid:** `{elId int≥1 unique per list, x, y finite, w, h finite ≥ 0, readyState int 0..4, opaque bool}` |
| managed OBS | session read `{wall, gl GL, painting, videos [{src str, paused bool, rs int 0..4, t finite, loop bool}]}`; phase `{hash str, videos, raf}`; `handedBack [{elId, loop, isConnected, facade, paused bool, t finite}]`; `slide1Videos`, `postHandbackVideos` (videos); `loseContext` object; precheck samples. Armed evidence as above |
| P2 `nullControl` | exactly `status()`'s 41 keys, or the 40 without `pollTimes` (172 retained). `preAdvanceDepartureAt` finite or null; `error` str or null; `advanceKeyRejected` int; `triggerFramesAfterAdvance` int or null; `pollTimes` finite and strictly increasing; `motionStartedFrame` int or null, ≤ the trigger frame. `rafLog[]` entries `{t, elementFromPointIsCover bool, ownerResolved bool, coverRect box\|null, measuredRect box(w,h>1)\|null, boundDecoderId int\|null}` |

**Per-kind payloads:**
- `glreplay-carried`: `elId` int ≥ 1, `delta` in [0, 1].
- `glreplay-release`: `ok` bool, `mode` retire|handoff|null, `retired` [int ≥ 1].
- `glreplay-zone`: `key` str; `from` ∈ {pending, armed, released}; `to` ∈ {armed, released, retired}; `reason` str.
- `remount-done`, `remount-footprint-rect`: `elId` int ≥ 1.
- `preserve-refused`: `scene` int or null; `via` ∈ {stash, remount, src-clear, removeAttribute, reuse}.
- `retire-boundary`: `key` str, `elIds` non-empty, `atScene` int, `instance` str or **absent** (`b.src.objectId`, `core:1606`).
- `reuse-decoder` and `bridge-3to4`: `key`, `src`, `dst` str; `newElId`, `oldElId` int ≥ 1.
- `bridge-motion-start`: `durationSeconds` > 0; `srcRect` and `rect` are boxes.
- `bridge-clock`: `via` gl|fallback; `lagMs` finite (≥ 50 when fallback, `core:1135-1139`).
- `player-build-error`: `errorType` error|unhandledrejection; `message` str.

**Unchanged** (these already are the contract): `sampler_self_check` (`paint:842`), `control_record_problem` (`paint:529`), `telemetry_problem` (`probe:5443`), `score_settled_position` (`:5370`), `inpage_oracle_result` (`:4223`).

## 3. Where validation runs

Each record is validated once. Violations do not mutate the evidence; they add `contractErrors`.

| # | Ingestion point | Validates | Violation becomes | Rescore path |
|---|---|---|---|---|
| 1 | `score_verdicts` (`probe:3799`), first statement | rows (with `schema`) and every `evidence[...]` value | every verdict of the arm is `_inconclusive("evidence contract: …", contractErrors=…)` | `rescore_generated` (`:7808`) now passes `schema=` |
| 2 | `rescore_artifact` (`:7729`) | rows, before `score_boundaries` | the arm reads `{identical: None, reason}` and `ok` is False (today it crashes) | itself |
| 3 | `score_force_wrap_run` (`:7589`) | rows, reads, recorder, `select`/`status`, `pageErrorNotes` | `status: invalid`, with every key the CLI and rescore read still populated | `rescore_force_wrap` (`:7678`) |
| 4 | `score_carry_cover` (`:8242`) | rows, notes, stage map | the bridge is inconclusive, so `carry_cover_status` is inconclusive | stored statuses only |
| 5 | `score_handback_carry` (`:5087`), `score_forced` (`:5216`), `score_live_ring` (`:5063`) | the hand-back record, the refusal read, the live-frame stage map | carry or ring None; forced `inconclusive` | same functions |
| 6 | `visible_slide_record` (`:4573`), `score_census` (`:3913`) | stage map, painting | slide verdict None; census entry unknown | live only |
| 7 | `managed.arm_gates` (`:1857`) **and** `score_mmo` (`:1951`, which calls `mmo_gates` directly) | session reads, phase records, armed reads, `handedBack`, `slide1Videos`, `postHandbackVideos`, `loseContext`, precheck samples | `invalid.append(...)`, so the run is INVALID and `passed` is False (`:1844-1849`) | `score_mmo` |
| 8 | `p2._score_freeze_control` (`:3560`) | `b.nullControl` | new integrity key `nullControlSound` in `integrity_keys` (`:4051`) | same function |

**Propagation:**
- Unknown precedes pass in every status function, and in `overall_status` and `generated_status` inconclusive precedes the stage-fit FAIL.
- `red_arm_status` never matches an unknown.
- `run_gates` requires exact statuses. Every P2 arm expects an empty inconclusive set, and `check_cc` needs an exact status.
- No reorder.

## 4. How each finding class closes

**C1–C8, closed by the contract:**
- C1: ill-typed identity.
- C2: non-Boolean or non-enum state.
- C3: duplicates.
- C4: nested fields missing or ill-typed.
- C5: unreadable clocks or geometry.
- C6: cross-field impossibilities. This now includes **`isConnected: false` on a sampler row**, which hid a restart leak (`probe:3382`, `:3401`; `tests:7337-7343`).
- C7: missing keys read as clean (`nullControl`).
- C8: rescore bypass.

**L1–L7, still reachable with producer-legal evidence.** Fold guards cover these, and a false pass here **blocks**:
- L1: unplaced rows.
- L2: cleared or swapped sources.
- L3: `{error}` or null containers.
- L4: notes that cannot be placed.
- L5: aggregation precedence.
- L6: partial carry-cover evidence.
- L7: rare legal shapes (PV id null, connected opacity null, owner `elId` absent, release `elId` null) are INCONCLUSIVE today.

The refusal and retire reads carry no read timestamp, so note `t` cannot be bounded there without a producer change; this is out of scope.

**Scored deliberately:** `_armed_pool` scores a pool entry plus a `fromDom` copy of the carried decoder as False (`probe:3014`). The retained armed-read cases are all red-arm `armed1to2` reads.

**Fixed in this pass (Q1):**
- **N1.** `movie_painting` (`managed:1480`) iterates over a legal `{error}` painting read, so "painting movie count == off" (`:1511`) passes as 0 == 0.
  - **Fix:** return None for a non-list read, and require both counts to be readable.
- **N2.** `find_execute_record` (`probe:5341`) returns the newest *matching* goTo record. goTo 3 runs three times (`GOTO_MATRIX`, `:317`), and the logger drops records when its queue is full or a write fails (`live_host:239-255`), so a lost record lets an older one stand in.
  - **Fix:** take `issued = time.time()` before `execute("goTo", to)` (`:5744`). Thread `since=issued` through `wait_for_execute_record` into `find_execute_record`, so the poll keeps waiting for a record with `ts ≥ issued`; otherwise None, which reads inconclusive.
- **N3.** The failsafe KB "fail-bogus does not read as retired-with-expected-reason" (`managed:1533`) passes when fail-bogus's `after.gl.coreEvents` is `null` or `{error}`, or the read is missing (`_notes` returns `[]`, `probe:2824`). `failsafe_gates` has no invalid path.
  - **Fix:** the KB also requires that `coreEvents` to be a list.

## 5. Regression oracle

**Setup:**
- OLD worktree at `c7d2d649`, NEW at the contract head.
- One script, `<session scratchpad>/contract/oracle.py`, built from `<session scratchpad>/realscore.py`, `<session scratchpad>/rescore_cmp.py` and `<session scratchpad>/obs-rescore/rescore.py`.
- Two separate processes, each with its own `PYTHONPATH`; the probe is loaded by file path.
- Each run dumps every verdict, status and check set to JSON. Diff the two dumps.

**Families and expectations (counts measured):**

| Family | Count | What is compared |
|---|---|---|
| host and attach | 166 files; realscore subset 162 files / 613 arms / **2280 verdicts** | `score_verdicts`, `score_boundaries`, `unplanned_wraps`, statuses (with the schema-2 stub) |
| red arms | 96 | `score_verdicts`, `red_arm_status` |
| force-wrap | 54 | `score_force_wrap_run`, `rescore_force_wrap` |
| hand-back carry | 38 | `score_handback_carry` |
| gl-forced-fail | 5 | `score_forced` |
| carry-cover | 24 | statuses, plus a scan of the stored notes |
| managed OBS | 26 runs | g2 runs: `g2_gates` (as `obs-rescore` does); mmo runs: `score_mmo`. Failsafe and soak are scan-only unless their decodes and shots are retained. N1 and N3 must change no retained gate |
| P2 freeze | 178 reports | `_score_freeze_control`, with the bridge and curve as derived at `p2_adv:4599` |
| Pass G | 28 | scan only |

**Out of scope:** 245 `s2-dev/detach-*/raw/*.json.gz` files. They hold projected rows that only `detach_experiment.build_record` rescores.

**Contract-acceptance scan:** run the real NEW validators over every retained record of every kind; expect 0 rejections. The prototype's 0 does not cover the enum, `isConnected`, S2, the recorder, carry-cover or `nullControl`.

**Oracle controls:** inject one violation per family into an in-memory copy, including `isConnected: false` and a fail-bogus `coreEvents: null`. NEW must turn it inconclusive or invalid; OLD must be unchanged.

**Acceptance:** 0 changes. Any change is either a producer fact the contract missed (fix the table and cite the producer line) or a real defect (report it to the owner; never tune it away).

## 6. Tests

**Measure first.** Re-run the spy over **all 8** ingestion points (plus N1–N3), recording **every** clause per test. The fallout is larger than "about 40 tests":
- 59 carry-cover tests go through `_cc_scene`, whose rows have no `readAt` and use float stage maps.
- The managed and P2 test reads have not been checked.

**New file `tests/test_live_evidence_contract.py`, with three parametrized tests:**
1. **`test_producer_shapes_are_legal`.** Positive controls come from one fixture, `tests/fixtures/live_continuity/contract/legal.json`: excerpts of retained artifacts with source paths. It covers every generation and the rare legal shapes (runtime-absent row, PV id null, connected opacity null, owner `elId` absent, `{error}` reads, a trailing row without `vids`, a digit-keyed detail, pool + `fromDom`, the 40-key `nullControl`, a hand-back inconclusive record without `before`).
2. **`test_each_clause_rejects_its_violation`.** One mutation per clause class per kind, including `isConnected: false`.
3. **`test_producer_js_meets_the_contract`.** Real producer output under Node:
   - paint `_run_js` (`test_paint_instrument.py:405`) for **pp and the control record only**;
   - the SAMPLER_JS harness (`tests:7571`), **extended** with a realistic HTMLMediaElement stub (every property the sampler reads) and a `__obedLive.snapshot()` stub, for rows and meta;
   - the core harness `_run_full_core_in_node` (`test_live_continuity_js.py:880`) for notes and the snapshot.

   It skips when Node is missing.

**Wiring test:** one parametrized test in each file where the fixtures live (probe, managed, P2). A single violation reaches each §3 outcome. It also carries N1, N2 and N3.

**Existing tests are made producer-realistic, never weakened.** Expected verdicts do not change.
- Integer stage maps (`tests:62-64`).
- `video()` emits G2 (add `ended`), and emits no owner, or `via: none`, when `el_id` is None.
- `_cc_scene` adds `readAt`.
- `_fw_reads` gets full pool entries and RETIRED with `standDowns`.
- Re-minify `3to4_750.min.json` from `output/evidence/loop-gates/l2r2/3to4_750.json`.
- Plus whatever the re-run spy names.
- Direct-scorer fold classes are untouched; `tests:7337` stays as a direct-scorer case.
- Only asserted reason strings may change.

## 7. Work stream and acceptance

**Precondition:** branch from `c7d2d649`. Re-derive the tables from any producer diff since then:

`git diff c7d2d649..<base> -- src/obed_edom/live_continuity_js.py src/obed_edom/live_gl_replay_js.py src/obed_edom/live_runtime.py scripts/live_continuity_probe.py scripts/paint_instrument.py scripts/p2_recovery_html_adversarial.py`

**One implementer** (Opus MEDIUM; Codex review), branch `s2-contract`:
1. Spy re-measure.
2. The module (with `stage_map_valid` moved), its tables, and tests 1–3.
3. Probe wiring, rows 1–6.
4. Managed wiring (row 7), plus N1 and N3; Pass G N2.
5. The `nullControlSound` integrity key.
6. Builders and the fixture.
7. The oracle.
8. Suites.
9. One line in `.agents/skills/obed-edom/SKILL.md`: a change to any `*_JS` producer or note payload updates `live_evidence_contract.py` in the same commit.

**Acceptance:**
- **Python 3.12 full:** `OBED_EDOM_CACHE_DIR=… uv run pytest tests/ -n auto --dist worksteal` → 0 failed (baseline re-measured at `c7d2d649`).
- **Python 3.10 floor:** `<session scratchpad>/suites/floor310-files.txt` plus the new file → 0 failed.
- **Dashboard:** `npm run test:ui && npm run test:maps` unchanged.
- **Oracle:** the OLD-vs-NEW diff is empty and the acceptance scan shows 0 rejections.
- **If Q3 is approved:** the headless smoke run shows 0 `contractErrors`.

## 8. Astra r12 criterion

1. **CLOSED BY CONTRACT** (non-blocking): name the clause.
2. **CONTRACT SLACK:** the producer cannot emit the input (cite the line). Blocks only if it yields a false pass; the fix is to tighten the table.
3. **FALSE PASS** (blocks): producer-legal evidence scores PASS, True or a matching red. Give a reproduction with producer citations.
4. **FALSE REJECTION:** blocks only if a retained verdict would change; otherwise MINOR.

**Scope:** the base..head diff plus L1–L7.

## 9. Risks

1. **Source-only kinds** (S2 rows, pp/pv, meta, carry-cover rows, bridge-clock, pin-hold-start). The guards are the extended Node harness and the Q3 smoke run; the failure mode is INCONCLUSIVE. Browser-timing clauses are deliberately left out.
2. **Pinned generations and enums.** A new player or a new producer key makes arms INCONCLUSIVE until the tables are updated; the same-commit rule and test 3 catch this.
3. **PV id null** (a video inserted by a player rAF callback after the sampler's tick) is legal, but `PV_FIELDS` keeps that carry INCONCLUSIVE. This may be frequent at scene setup. It is pre-existing; Q3 would show it before GL-1.
4. **Arm-wide scope** turns one bad read into a whole inconclusive arm. This is by design (owner).
5. **Fixture churn is larger than drafted.** Measure it first; the reviewer checks that no expected verdict changed.
6. **The contract and the kept guards can disagree on reason text,** never on verdicts.
7. **Oracle blind spots:** Pass G legs, carry-cover rows, and managed failsafe/soak runs without retained decodes get scans only.

## 10. Critique log (summary)

- Added `isConnected == true`, which closes a contract-slack false pass on restart leaks.
- Added N3 (failsafe KB).
- Corrected test 3's coverage (no real S2-row or meta harness before); added Q3.
- Spy fallout is to be re-measured over all points.
- N2's bound moved into the poll.
- Dropped `t ≥ ts` and ids ⊆ pp.
- Moved `stage_map_valid` to break the import cycle.
- Rebased on `c7d2d649`.
- Listed the extra managed reads and the `score_mmo` wiring.
- Hand-back inconclusive records, retire-boundary `instance`, post-processing keys, cite drift, the pool-duplicate counts and the oracle scope are corrected.

---

## 11. Owner questions

**Q1. Include N1, N2 and the newly found N3 in this pass?**
- All three are producer-reachable false passes, each a change of about 1–3 lines with one wiring case.
- **Recommendation: yes.** Without them, r12 blocks on them.

**Q2. Admit the rare producer-legal shapes in the contract, and keep today's fail-closed guards?**
- The shapes: runtime-absent rows, PV id null, owner `elId` absent, release `elId` null.
- **Recommendation: yes,** as drafted. The outcome is INCONCLUSIVE either way, and the contract stays an exact statement of what the producers emit.

**Q3 (new). Before GL-1, run one headless-Chrome smoke as a positive control for the source-only clauses?**
- What it is: a P2 host arm plus one D1 carry-cover arm through the probe CLI. No OBS, no Keynote, no `run_gates`.
- Why: Node stubs cannot produce real SAMPLER_JS rows or meta, and no schema-2 evidence is retained. A wrong source-only clause would turn every GL-1/2/3 arm INCONCLUSIVE and waste a live session. The smoke would also show early how often PV id null occurs (risk 3).
- **Recommendation: yes.** The acceptance is 0 `contractErrors`, and the run's artifacts are retained as the first schema-2 positive controls.