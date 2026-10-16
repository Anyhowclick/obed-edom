# Suite speed-up — revision 2 (final before owner review)

## Owner decisions

S = summed Python test seconds; W = wall seconds. Live-gate job-seconds are separate. Only Pass G option A is approved; all other decisions below remain **OPEN**.

| Decision / status | Recommendation | Estimated saving |
|---|---|---|
| Multi-fault stub rounds — OPEN | Approve seven shared rounds for 33 cases on 11 stems (§A3); retain IDs and mapped per-arm obligations. Coupled defects remain a masking risk. | Additional main ≈310 S / 31 W; Stage B ≈480 S / 48 W; extra :829 saving ≈12 S unbanked |
| D5 diagnostic strengthening — OPEN | Add the one-line observed-red assertion (§A3): today's red-noself/red-nofloor reason checks are vacuous. | Correctness only |
| Live scheduling — OPEN | Approve any-slot refill + fixed long-group-first order, at most 3 concurrent; confirm group simulation and paired real round. | Simulated fixed-group order: main 1002→829 s (173 W), F4/Stage B 1396→1230 s (166 W); with option A main →724 s, F4/Stage B →1126 s |
| Pass G null subset option A — **APPROVED 2026-10-16** | Two null go-tos; armed matrix unchanged. Gate-product stream after Stage B merges, with Stage B session agreement; re-qualify. | ≈24–47 s/run; ≈316 job-s/round including red; ≈105 W at ideal packing, not additive to scheduling |
| GATE_JOBS=4 — OPEN | Do not adopt: unqualified measurement conditions. | Main ≈624 s simulated; excluded |
| Event-driven post-advance settle — OPEN | Do not adopt: changes burst/sample timing and needs re-qualification. | ≈29 s/Pass G run, ≈54 s/host run; no credit |
| Stage B feed dwell — OPEN | Stage B-owned plan change after merge: scored-departure dwell plus restricted expectations or 1.5 s evidence (§F); low priority. | ≈100 job-s/round, ≈35 W |
| Two inert restart arms — OPEN | Leave unless owner wants pruning. | ≈65 job-s/round; wall unmeasured |
| Temporary-directory retention — OPEN | Trial failed-only, one retained session; adopt only if total cleanup falls and failed artifacts survive. | Plausible ≈5 W (0–6 W), unbanked |
| Lazy imports / checker batching — OPEN | Profile lazy import first; batch only if residual cost justifies it. | ≈25–55 S / 2.5–5.5 W after consolidation; unbanked, not additive |

## Baseline and scope

Read `brief.md`, `brief-r1.md`, `brief-r2.md`, `measurements.md`, the coordinator-edited r1 plan and `critique-r2.md`; spot-checked the cited code read-only at `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/distracted-cartwright-b450e1`, HEAD `163ec812`. No pytest or benchmarks run for this revision. References are repository-relative at that HEAD unless marked Stage B. Savings are estimates from supplied measurements, critique and coordinator, not achieved results.

Main 3.13 / 3.10: **2427 / 2758 S**, **262 / 314 W**. Measured Stage B `1a56be4c`, 3.13: **2910 S / 350 W**. Current Stage B tip is **7746df27**, not the measured revision; no measured Stage B 3.10 baseline exists. Goal: each interpreter well under five minutes idle, robust under normal load. Keep `-n auto --dist worksteal`; distribution is already balanced.

Main has **58** arms (3+5+25+7+1+3+6+8); F4/Stage B has **85**, including 27 mm-feed arms (`scripts/run_gates.sh:34,45,54,68,76,87,94,103`). Gate subprocesses use the fixed main-checkout Python even in the floor suite (`scripts/run_gates.sh:152`, `tests/test_run_gates.py:85`), so their savings should be similar across interpreters.

Dashboard is **no change**, with no lever or stream: coordinator measured idle `test:ui` **14 s** (≈6 s tsc + 8 s vitest, 330 tests), `test:maps` **2 s**, `test:perf` **1 s**. Preserve current commands/typechecking.

## Ranked levers

Python estimates are **3.13 / 3.10**, W≈S/10. Measure combined benefits after integration; contention savings are not independently additive. Owner-dependent and conditional rows are excluded from the base projection.

| Rank / lever | Measured basis | Estimated S → W | Risk / owner call |
|---|---|---|---|
| 1. A1+A2: session-shared gate rounds; dev tier for invariant assertions | `test_run_gates`: 1057 / 1084 S; ≈78 full + 4 dev + 3 partial rounds; main full ≈12–13 s vs dev 2–3.6 s | ≈400 / 410 → **40 / 41 W**; Stage B ≈600 / 615 → 60 / 61.5 W | Low–medium; no test merging; no owner call |
| 2. A3: seven multi-fault rounds | 33 cases on 11 stems including :829, max 7 cases/stem; 33→7 rounds | Additional ≈310 / 310 → **31 / 31 W**; Stage B ≈480 →48 W | Medium; **OWNER CALL** |
| 3. B: shared per-key sweep cache + dependency manifest | P2 file 269 / 377 S; per-worktree single-name cache evicts interpreter entries (`tests/test_p2_adversarial.py:6273,6336`) | Warm 180–240 / 250–340 → **18–24 / 25–34 W**; cold cache saving **0** | Stale-cache risk; guard + invalidation evidence; no owner call |
| 4. C: dissolve preparation + test image reuse | Dissolve 373 / 416 S; profile premul 86 s, fit 39 s, over 28 s; test media_run 85 s, mix 58 s, textures 9.9 s | Combined 130–210 / 150–240 → **13–21 / 15–24 W**, including product benefit in managed rescore | Float/aliasing risk; equivalence required; no owner call |
| 5. C: managed generation/PNG reuse | Managed 161 / 195 S; launch/rescore matrix ≈80 S (`tests/test_managed_obs_qualify.py:2661`) | Additional 15–30 / 15–35 → **1.5–3 / 1.5–3.5 W** after row 4 | Mutable records/relocation; no owner call |
| 6. D: handback PNG encode reuse | Handback 38 / 67 S; disk-rescore pair ≈12.6 S (`tests/test_mm_handback_probe.py:642`) | 3–8 / 4–10 → **0.3–0.8 / 0.4–1 W** | Low; no owner call |
| 7. D: tmp retention | ≈6 s serial startup cleanup, ≈50k files | **0–6 W**, unbanked | Artifact retention; **owner call** |
| 8. E: lazy import, then optional check batching | Isolated stub round 6.1 s: launch 1.15, checks 4.6; import ≈0.17 vs ≈0.02 s ×8 | Lazy ≈25–55 S / 2.5–5.5 W after A; batching unmeasured | Product equivalence / Stage B conflicts; conditional |
| 9. F: live scheduling | Validated queue simulation below | Python **0**; live main/F4 ≈171/161 W | Overlap changes; **owner call** |
| 10. F: approved Pass G null subset | 40 omitted null destinations × ≈7.9 s, including red; full armed matrix retained | Python **0**; ≈316 job-s, ≈105 W ideal, not additive to scheduling | Measurement change **approved**; probe/test edits after Stage B merge and agreement |
| Hold: Pass G / host settle wait | Profiled: Pass G D2 139 s = bursts 62 + go-to settle 29 + advance legs 17 + static control 10 + Chrome/warm-up/polls ≈22; host-1920 137 s = advance settle 54 + dwells 23 + bursts 23 + attach 21 | **0 banked** | Measurement change; **owner call, not recommended** |
| Hold: binary movie | One 18.40 s setup; remaining consumers 0.001–0.003 s; module fixture already exists (`tests/test_binary_counter_movie.py:24`) | **0** | No measured duplication; no merge |
| Hold: dsk_pill / golden plan | 54/69 S; golden slow case 20/38.4 S (`tests/test_dsk_pill.py:47,78`; `tests/test_golden_plan.py:183`) | **0** | Decode cache/APFS clones already present; retain real planner regression |
| Hold: sweep pool cap | cpu_count() children under xdist (`tests/test_p2_adversarial.py:6397`) | **0** | Measure only if cold full timing puts sweep on critical path; no default cap or planned cap experiment |

## A. Gate tests — `tests/test_run_gates.py`

**A1: once per session across workers, keeping tests and IDs.** Factor fake-tree construction/runner cleanup from `gates` (:304–367). Key on `(script path, args tuple, sorted explicit overrides)` only, never on the effective `os.environ`, which differs per worker (`PYTEST_XDIST_WORKER`, `PYTEST_CURRENT_TEST`) and would never share. Use `os.environ.get("PYTEST_XDIST_WORKER")` rather than the `worker_id` fixture, so `-p no:xdist` still works.

Under xdist, lock `tmp_path_factory.getbasetemp().parent/gates-<key>.lock` with `fcntl.flock`; use sibling `gates-<key>/` for artifacts. Recheck under lock, compute once, finish descendant cleanup, atomically publish JSON with rc/stdout/stderr/events/outdir and needed paths. On a failed compute (exception or `TimeoutExpired`), publish an error record under the lock so later consumers fail fast with the same error. Otherwise up to 17 R2 consumers serially re-run a 120 s-timeout round. In a `finally`, `pkill -KILL -f <that round's own dir>`, never `getbasetemp().parent`, which would kill other workers' live rounds. Consumers' `gates` teardown (`test_run_gates.py:367`) cannot reach the shared dir.

Waiting workers read completed records only; preserve sanitization, nonces/status artifacts and read-only observations. Bind consumers' `gates["out"]`/events to the shared result so path assertions stay unchanged. Under `-n 0` or `-p no:xdist`, use that session's own temp tree, never its cross-session parent. Keep fresh function-scoped runners for mutations, patched scripts, signals, stale status, refusals, prewarm faults and job-cap tests.

| Shared round | Existing consumers (main line numbers) | Preservation |
|---|---|---|
| R1: `GATE_JOBS=1`, default tier | `fresh_round[1]` :376, `warns[1]` :594; six order/matrix tests :666,738,771,844,978,1063 | Preserve assertions and IDs, including nonce/artifact/argv/start/check ordering; change producer/fixture binding only |
| R2: default env, explicit `--tier full` | 15 carry-cover good controls :1038; Pass G good :836; explicit-full :945; `warns[None]` :594 | Default is full (`scripts/run_gates.sh:18`); explicit CLI coverage remains. Baseline is not an all-green round |

Estimated ≈24 avoided rounds: ≈300/310 S main, ≈450/465 S Stage B. No five-test batches or merged matrix consumer: independent failures remain visible. Reuse a dev control only for identical args/env; no extra credit assumed.

**A2: ten full→dev rounds.** Change only producer calls to `--tier dev` in `warns[3,4,5]` (:594), four load-positive cases (:538), load-stays-low (:566), empty-outdir accepted (:413), and **only the second out2/cache-hit run** of :471. Keep the first prewarm run full: it asserts the full launch count. Assertion expressions stay unchanged. Warning/load/prewarm/end-load output is tier-invariant (`scripts/run_gates.sh:161–171,284,307,632`); dev includes the asserted HOST1920. Estimated ≈100 S main / ≈150 S Stage B. Preserve full-tier matrix, exit and concurrency obligations elsewhere.

A1/A2 assertion-preservation map = annotated diff: old node/parameter ID → unchanged assertion body, producer/fixture changes, tier changes and cited shell evidence. Include helper assertions. Reviewer checks no assertion or ID disappeared and runs the affected file against unchanged shell. coverage.py cannot prove shell obligations. No broad mutation campaign for producer-only changes.

**A3: OWNER CALL, seven shared multi-fault rounds.** 33 cases on 11 stems including `:829`'s bad round; still 7 rounds. The original 32 occupy 10 stems (five carry-cover, Pass G red, three paint controls, host-redD5); `passG-D3 g-error` is the 11th. Pack one fault per stem per round via A1. Keep every parameter ID, its exactly-one failure and its `why`/no-artifact obligation scoped to its arm block. Preserve pending=0, rc=1 and all no-pending checks. Retain the separate seven-arm Pass G bad round (:803–826).

Round-level: `findings` == the number of host-redD5 `red-*` faults injected in that round (each adds one endOfShow entry,
`run_gates.sh:390,444`). DONE `failed` == the count of GATE FAILED lines == R2's multiset with each injected stem's baseline
contribution replaced by its expected one. A block is the lines from a top-level `[` header up to and including the arm's own
tally/`GATE FAILED` line. Identify a host-red block by check order (`run_gates.sh:623–624`), never by header text: the header
omits the deck.

Preservation-map note for the owner: the `red-noself`/`red-nofloor` reasons also appear in R2's D5 block, so those two `why`
checks were and remain non-evidential. Their exactly-one-failure obligation is preserved. Optional strengthening (owner call,
one line): also assert `observed red: ['b0to1:A:carry']` inside the D5 block, which only the `red-*` stub writes.

Preservation argument: `fail()` increments once/prints one label (`scripts/run_gates.sh:201`); checks independently consume each stem's JSON/.rc (:323,398,454,517,577). Initially passing stems retain singleton/+1 obligations; D5 retains exactly one failure. Scoped reasons remove cross-arm collisions (including Pass G red `gr-nofloor`), subject to the D5 caveat above. Map every old assertion, including :829's good/bad controls and summary regex, to its slot or aggregate obligation. Reviewer checks the map against both versions and one disposable cross-wired-check mutation must fail. Residual: simultaneous cross-arm coupling and detection loss could mask a defect. Keep conservative **≈310 S main / 480 S Stage B** credit; packing :829 avoids one more round (≈12 S main), unbanked.

**Refuted (r1 critique 3, retained):** “R2 + every injected label” double-counts host-redD5: its default artifact already fails (`tests/test_run_gates.py:1121–1123`; `run_gates.sh:343–354,372,623–624`). Replace its baseline contribution as specified above; never waive singleton obligations or silently change R2.

Stage B conflict **high**: staging, mm-feed/deck matrix, cleanup and settle observation. Rebase against **7746df27**, regenerate the map against the merged baseline, and keep **1a56be4c's SLEEP_STUB / gates["sleeps"] settle test**. Fixed `sleep 5` **and** `sleep 4` mutants must still fail. Never restore the flaky elapsed-time assertion. Reserve `scripts/live_continuity_probe.py` and `tests/test_live_continuity_probe.py` for Stage B until its merge; approved option A transfers to the gate-product owner only with the Stage B session's agreement (§F).

## B. Sweep cache — `tests/test_p2_adversarial.py`

Change `_sweep_cache_key`, `_cached_sweep`, `_sweep_file` (:6273,6328,6629), for **main and bracket** sweeps (:6425,6884):

- Default storage: `fixture_paths.main_checkout()/.cache/test-sweeps/`, using the existing resolver (`src/obed_edom/fixture_paths.py:14–20`). If `main_checkout()` raises (no git) or its `.cache` is unwritable (a sandboxed session), fall back to today's worktree-local `.cache/test-sweeps`, not to compute-every-run. Otherwise the hit rate silently drops to 0. Hash **current-worktree** inputs. Keep injectable source `root` and explicit `cache_dir` for fake-root tests. Use `<name>-<hash>.json`, per-key flock/recheck, atomic replacement, exact path-set/type validation, corrupt-entry recomputation, cache-off and coverage bypass. If both cache locations are unwritable, compute safely without storage. Never cache assertions/allowlist checks.
- On store retain newest **N=8 JSON files per sweep name by mtime** (≈3.3 MB per main+bracket identity). `os.utime` the JSON on a hit, so mtime retention is LRU: a hot main-line key must not be pruned behind newer one-off keys. Serialize pruning; no locked-skip logic. A computing key has no JSON yet, and readers tolerate an unlinked file (`_load_sweep` → None → recompute under the lock, `test_p2_adversarial.py:6291–6313,6340–6357`). Prune JSON only, with tolerated races. Do not unlink lock inodes used by waiters. Touch/prune failures cannot fail the sweep.
- Manifest starts with `src/obed_edom/{__init__,p2_verdict,html_alpha_probe,live_continuity}.py`, this test, conftest and every byte of `tests/fixtures/p2_freeze_3to4/`; audit **both** sweep paths and add any executed result dependency. `_score_34` calls `_score_freeze_control` (:937–957); p2 imports image scoring/canonical naming (`src/obed_edom/p2_verdict.py:26–43`); naming is at `live_continuity.py:1291`. Retain full `sys.version`, normalized **all-distribution** versions, relative filenames/content hashes and manifest/schema identity. Do not narrow cv2 dependencies speculatively.
- Add **one cache-off drift guard**. Trace both scorers under `sys.setprofile`: `_score_34` on the three bracket snapshots plus one deletion per arm, and
`_advance_c_ok` on `_main_inputs()` plus one deletion. Assert that every executed file under `src/obed_edom/` (rglob) is in the
manifest. The second scorer is `p2._advance_c_ok` (:6893–6902). Expected <1 s, verify. Other deletion paths and non-call data dependencies still require review. Do not use `sys.modules`: xdist collects all modules; static closure already spans 46/86 src files.
- Extend cache tests (:6640,6668) in place: relevant edits miss, unrelated src hits, interpreter keys coexist, concurrent same-key fill computes once, distinct keys coexist, retention preserves recently hit entries, resolver failure/unwritable shared storage falls back locally, and invalid/corrupt/duplicate/partial/wrong-key cases recompute (both locations read-only still compute). Compare **complete indexed-path→bool maps** cold/warm/cache-off. Preserve serial/pool equality, worker-failure and duplicate-path checks.

**Hit rate:** 6/40 recent first-parent merges touched the three primary scorer modules, versus 20/40 touching any src. ≈85% is **source-only eligibility**, not a measured cache hit rate. Test/conftest/fixture/interpreter/distribution changes and retention also miss. Continuity PRs will mostly be cold (`live_continuity.py` is hot; Stage B adds ≈411 lines). Main-checkout storage removes compulsory fresh-worktree misses. Warm projection credit applies only when the complete identity survives.

Leave `_bracket_sweep_worker_count` (:6397) unchanged. Oversubscription alone does not prove excess work; gate rounds dominate process churn. Only if required cold full-suite timing identifies a sweep critical path should a cap be investigated, preserving explicit overrides and both-interpreter map equivalence. No default cap or planned cap experiment. Stage B textual conflict is low; its source changes correctly invalidate the key.

## C. Dissolve and managed rescore

`scripts/dissolve_probe.py:1927`: replace `np.asarray(..., dtype=np.float32).copy()` with one owned `np.array(..., dtype=np.float32, copy=True)` allocation. Preserve float32 conversion, operation order and fresh output storage. At `fit_frame` (:1997), prepare A/B premultiplication, screen slicing, difference, fit mask and denominator once per fixed A/B/keep/screen tuple in `score_fade` (:2058,2073) and after-show loop (:2854). Reuse prepared inputs in `far_mask`/`over` (:1970,1989) only within a scoring call. Keep reduction/traversal order, residuals, NaNs, validation and public behavior. No global ndarray-identity cache.

`tests/test_dissolve_probe.py`: target **textures/mix/media_run**, not only fade: just 90/3180 mix calls originate in fade; media_run accounts for 85 s, mix 58 s, unpremul 23.6 s, deterministic textures 9.9 s. `functools.cache` textures and its premultiplied canonical pair, arrays `writeable=False`; mutating callers take `.copy()` (dents/garbage :103–117).

**Refuted (canonical-pair assumption in critique 7, not its caching lever):** global `mix(e,kind)` caching cannot cover every caller: `reference_block` uses `with_holder` (:374); `media_run` uses device-scaled `A_d/B_d` or `with_holder/B_d` (:537,645). Cache `(e,kind)` only for the canonical pair. In media_run/reference generation, prepare each actual fixed pair once locally and reuse across frames; local blend memoization is valid only while that pair remains fixed. Preserve holder/device-scale/letterbox/arm/mutation distinctions. Keep every CASES entry (:1947), resolution, frame count and threshold.

`tests/test_managed_obs_qualify.py:2661,2680,2721`: within the launch matrix, generate `media_run(name)` once per equivalent arm/configuration, deep-copy records before updates, reuse immutable pixels/encoded PNG bytes, and write all original files into independent run folders. Retain both rates, full/legacy/dev, real renderer rescore, relocation, missing PNG and failed→pass rescore (:2863–2893). Only residual generation/encoding savings beyond the dissolve row count separately.

Verification is a **one-off PR differential**, not a permanent old-formula oracle: both interpreters, bit-identical arrays and full scorer dictionaries NaN-aware over existing CASES and managed matrix; unchanged inputs/no output aliasing; identical decoded PNGs/records/reports. Include alpha/threshold boundaries and uint8/float32, read-only/noncontiguous, empty/identical-fit and screen cases. Match NumPy/Pillow within each before/after pair. Stage B conflict low in dissolve, medium/high in managed matrix; retain added cases. No product edit to `scripts/managed_obs_qualify.py`.

## D. Smaller files and retention

`tests/test_mm_handback_probe.py:642`, `write_runs`: encode each distinct already-reused ndarray once per invocation, retaining strong references for a local identity lookup; write immutable PNG bytes at every original path. `_FRAMES` (:285) already reuses renders. Preserve independent records and real saved-frame re-derivation (:654,665); compare decoded pixels and complete verdict JSON. Low Stage B conflict; product luma reuse waits for residual profiling.

Hold binary movie: setup measured once; retain module fixture, all **1381** decoded frames, container checks and corruption tests (:24–66), no merge or savings. Hold dsk_pill: independent unpickled dictionaries/APFS clones already address reuse (:47–78); retain mutation/cache equivalence checks (:277–312). Hold golden plan: slow case performs actual capture/framing/build checks (:183–229); proposal caching exists (:283), nine other gold cases are skipped. Do not cache the verdict or bypass the planner.

If approved, the retention trial owns `pyproject.toml:69`: `tmp_path_retention_policy="failed"`, `tmp_path_retention_count=1`. Moving unlinks into worker teardowns can plausibly save ≈5 W versus serial controller startup. Compare **two consecutive complete runs including exit cleanup**, preferably the acceptance cold/warm pair; retain failed artifacts and existing `tests/conftest.py:27` cleanup. Session-shared gates may still require session cleanup. No uncleared global basetemp, zero banked savings. Low Stage B conflict.

## E. Conditional check-phase cost

First profile a **lazy import** on the plan-only checker path: `scripts/run_gates.sh:214–238` imports `p2_verdict.build_continuity_plan`; `src/obed_edom/p2_verdict.py:23–43` eagerly imports NumPy/PIL/image scorers/live-continuity helpers. Defer scoring-only imports to scoring call sites where feasible without changing module API/constants, plan hashes or diagnostics. Moving the shell import lower while still executing it eight times saves nothing. Opportunity ≈1.2 s/round, but after A only ≈20–45 full rounds remain: **≈25–55 S unbanked**. Prove fresh-process plan JSON/hash, checker stdout/stderr/rc and scoring equality on both interpreters. Review the cache manifest; p2_verdict has high Stage B conflict.

If still worthwhile, batch pure post-run checks (`run_gates.sh:176,214,323,398,415,454,517,577`) without logic changes; extract a small Python helper only if simpler. Preserve ordered output, per-arm error boundaries, reports, missing/stale nonce status, tallies, RECORD/dev exits and continued checking after malformed artifacts. Differential existing stub scenarios against old/new checks. Launcher changes held: process groups, traps/cleanup and atomic .rc publication (:265–274) must remain equivalent. No batching/launcher credit; serialize with A/F.

## F. Live gates

**Scheduling-only owner call.** `queue` waits on the oldest PID (`scripts/run_gates.sh:272`) even if another slot completed. Coordinator simulation validates **1396 s simulated vs 1385 s measured** F4 capture span:

| Policy at GATE_JOBS=3 | Main 58 arms | F4/Stage B 85 arms |
|---|---:|---:|
| Today: oldest-PID wait, listed order |1002 s|1396 s|
| Any-slot refill, listed order |872 s|1274 s|
| Longest-first, today's queue |884 s|1276 s|
| **Any-slot + longest-first** |**831 s**|**1235 s**|
| Ideal job-seconds / 3 |824 s|1227 s|

Recommend any-slot refill with fixed long-group-first order. Coordinator simulation of the fixed group order below (any-slot, jobs 3, both F4 rounds): **main 829/832 s, F4/Stage B 1230/1234 s**, matching per-arm longest-first (831/836, 1235/1238). With approved option A on top: **main 724/727 s** (ideal 719/724), **F4/Stage B 1126/1129 s** (ideal 1122/1125). Launches currently interleave definitions (:308,391–392,411,506,567,615,620); consolidation has high Stage B conflict.

Refill: poll the `$jobstates` running count in the current shell (never in `$(...)`), with a `zselect` sub-second wait; keep
`stop_jobs`/traps unchanged. Order: a fixed group order in one launch section (P2 freeze-bracket arms, Pass G, host, Pass G
red, mm-feed, remaining P2, host red, carry-cover, paint control; simulated above), the same for every
GATE_JOBS. Checks keep the listed order.

Assertion map: the start-order assertions in :738, :771, :978 and :1063 become one exact expected launch sequence. The
check-order assertions stay byte-identical. Add one parametrized case to an existing stub test proving a later run launches
before the oldest one finishes, so a regression to oldest-PID wait is visible. Update the `run_gates.sh:259–262` comment.

Implement the poll as `N=${#${(M)${(v)jobstates}:#running:*}}` until `N < GATE_JOBS`, with `zmodload zsh/zselect; zselect -t 10` (0.1 s). No `wait -n` (unsupported in zsh 5.9), command substitution for the count, or forked `sleep` (also observed by Stage B's SLEEP_STUB); remove obsolete `PIDS`. Keep final `wait`, argv/membership, sampling, fixtures/controls, prewarm/load guards, nonces, process groups/signals and at most three concurrent jobs unchanged. The refill case must check an actual launch/completion ordering, not a wall-time threshold.

Confirm with **one paired real baseline/candidate full round** at jobs3: same arm multiset/argv, cap, cleanup, prewarm-before-capture, per-arm timings/verdicts and measurement meaning. Simulation is queue span, not whole-round wall (F4 whole rounds 1412–1415 s); other phases remain. Main jobs4 ≈624 s is unqualified and not recommended.

**Pass G / host-gate time — profiled (coordinator, cProfile wall, main 163ec812, idle).** The sampler-span table that
suggested "≈117 s outside sampling" was misleading: it omits screenshot-burst liveness measurement.

| Run | Wall | Phase breakdown |
|---|---:|---|
| Pass G D2 | 139 s (121 s `time.sleep`) | `capture_burst` 62 s (19 destinations × 8 shots over `G_BURST_OFFSETS_MS` 0–3180 ms, `:340,4566`) · `run_goto_destination` fixed `POST_ADVANCE_SETTLE_S` 1.8 s × 16 = 29 s (`:5821`) · `run_advance_leg` 17 s · `score_static_control` 10 s · DevTools port wait 5.6 s, warm-up 3 s, settle polls ≈8 s |
| host-1920 | 137 s (110 s sleep) | `advance_until_original_slide` 54 s (30 advances × 1.8 s settle, `:1622`) · `drive_and_sample` dwells 23 s · `capture_burst` 23 s · attach arm 21 s |

≈85–90% of each run is deliberate pacing or measurement. The one fixed non-measuring wait is the 1.8 s post-advance/go-to
settle; making it event-driven (the existing `wait_until_settled`) would move burst/sample start relative to arrival, which
can turn a slow decoder start into a frozen-video read and shift registered red sets. Owner call with a re-qualification
round; **not recommended in this work** and no credit. Chrome start/warm-up (≈9 s per Pass G run) is too small to justify
browser reuse across arms (cross-arm state leakage).

**Pass G null-control subset (owner-approved option A, 2026-10-16).** In `run_pass_g` (:6113–6153), run autoplay-off `Goff` only on `null_matrix = ((1,3),(3,1))`; record `nullMatrix` alongside `matrix`. Keep the full armed matrix, every advance leg, all verdicts, null DEAD checks and output visibility. All seven committed decks have ≥3 slides, so drop the first-fitting-base-case fallback. Both kept destinations have ≥1 LIVE movie expectation on every deck; real C1-gates-j3 artifacts show all-dead nulls, uniqueShas 1 and zero `<video>`. Slide-2 consumption checks are armed-only (:6069), and the characters region is DEAD in both arms (:5372–5376).

Files: `scripts/live_continuity_probe.py` and `tests/test_live_continuity_probe.py` only. No `run_gates.sh`/`test_run_gates.py`
change: the checks are length-agnostic (`run_gates.sh:398–410,424,479,494`), and the stub already writes an empty null list
(`test_run_gates.py:139`).

`overall_status_g` compares `len(off)` with `result["nullMatrix"]` when it is a list, else with `matrix`, so older artifacts and
the existing unit tests stay valid. Extend `test_overall_status_g_counts_against_the_recorded_matrix` with one nullMatrix
length-mismatch → `error` case. In the deck-parametrized test (:8090), assert that the null matrix is `((1,3),(3,1))` and that
each null destination's slide has ≥1 LIVE `V` expectation in the committed plan. That is the property that keeps the null
non-vacuous if a deck changes. Drop the untested fallback, or cover it in the same test.

Owner: the Stage B session, or the serialized gate-product owner after Stage B merges with these two files added to its list.
Never in parallel with Stage B probe edits (Stage B moves these functions to :6538/:6741).

**Assigned owner:** the serialized gate-product stream **AFTER Stage B merges and with the Stage B session's agreement**, adding both probe files to its ownership. This selects the second ownership option above; these files are Stage B-heavy. The length comparison means `len(off) == len(result["nullMatrix"])` for a list, else `len(off) == len(matrix)` (including when absent); armed length still uses `matrix`. Retain `TestOverallStatusG` (:3586–3620) and `_g_leg_result` (:10225–10227) compatibility and extend the cited tests in place.

`PASSG_RED_EXPECTATIONS`/`passg_red_ids` register only armed `G…` ids (:290–293,6166–6214); confirm no registered `Goff…` id. One real full round must show all seven positive Pass G runs passing, both null destinations DEAD per deck and the red arm's registered set unchanged. The subset changes session history: `(3,1)`'s source goTo 3 becomes a same-slide goTo after `(1,3)`, instead of following `(1,4)`; re-qualification covers this.

≈24–47 s per Pass G run (D4/D5 ≈24, P2 ≈32, 8-case decks ≈47); ≈316 job-s per round including the Pass G red arm; ≈105 W at
ideal packing (an upper bound, not additive to scheduling). Omitted destinations: D1/D2/D3/D6 six each, D4/D5 three each, P2 four, plus red D1 six = 40 × 7.9 s ≈316 job-s.

Using one real round for both scheduling and null-subset qualification is fine if everything matches. If any verdict or timing differs, rerun the two changes separately before attributing it.

Do not shorten `FIRST_CLICK_DWELL_S=3`, `POST_ADVANCE_SETTLE_S=1.8`, `CLICK_DELAY_S=1.5` (`scripts/live_continuity_probe.py:140–144`): these define red-arm measurements; owner agreed to retain them.

**Stage B-only, Stage B session owns it (its review, 2026-10-16):** `--feed-dwell` replaces every dwell in
`drive_and_sample` (Stage B `scripts/live_continuity_probe.py:1985,1993`), and `check_mm_feed` (Stage B `run_gates.sh`
≈766–788) applies the feed-off expectations (`holdFrame`/`posterHold`/`handbackContinuity` True) to **every** underArtwork
record, so every Alpha carry is gated at its dwell; two Stage B plans freeze dwell semantics (restructure plan :70, Q7 plan
:91). Viable version, as an **owner plan change**: dwell only before the scored departures, AND either restrict the dwell
arms' expectations to those carries (relying on feed-off-2s + feed-on for the rest) or show with a headless run that the
non-scored carries pass at 1.5 s; same for D7 attach-once; plus an arm-level check that the scored departures got the dwell.
Estimate ≈100 job-s/round (≈35 W). Implemented by the Stage B session through the roster if approved; not this branch.

Two self-described core-v6 inert arms (`scripts/run_gates.sh:121–122`, P2 `--strip restart@6` and host twin) offer ≈65 job-s. Recommend leaving them; pruning is an explicit owner decision, no projection credit.

## Streams and integration order

1. Pin fixture identities and main/Stage B baselines; inventory assertions. No heavy verification during planning.
2. Disjoint implementation streams: **A** only `tests/test_run_gates.py`; **B** only `tests/test_p2_adversarial.py`; **C** `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py`, `tests/test_managed_obs_qualify.py`; **D** `tests/test_mm_handback_probe.py` and, if approved, `pyproject.toml`. Leave conftest unchanged. No binary/dsk/golden/dashboard stream.
3. Integrate B/C/D/A, run affected checks, then combined timings. Stage B rebase preserves 7746df27's matrix/staging and 1a56be4c's settle/child cleanup. Refresh assertion map against merged baseline; source changes legitimately miss the shared cache.
4. After A, **one serialized gate-product owner** takes `scripts/run_gates.sh`, `tests/test_run_gates.py`, conditional `src/obed_edom/p2_verdict.py`/checker helper for E, and F scheduling. Separate lazy-import/check patches from scheduling. **After Stage B merges and with its session's agreement**, add `scripts/live_continuity_probe.py` and `tests/test_live_continuity_probe.py` for approved option A; do not edit them in parallel with Stage B. Stage B session owns the separate, still-open feed-dwell change and coordinates file handoff; no overlapping ownership.

## Verification

- A1/A2 retain functions, IDs and assertion bodies: annotated diff is the shell assertion map. A3 needs owner-approved mapping and one cross-wire mutation. Verify one R1/R2 invocation under xdist, cached failure propagation and round-local cleanup, plus isolation under `-n 0`/`-p no:xdist`; no full serial coverage run to prove fixture reuse.
- **Any Python test drop/merge requires zero lost line+branch coverage.** None is currently planned (binary held). If later introduced, measure only affected test files and production targets before/after, with identical linked fixtures, cache off, `-n auto` and coverage parallel/combine on 3.13. Compare executed lines/branch-edge sets, not percentages; map moved code and configure subprocess coverage where necessary. Add 3.10 coverage only for a touched version branch. Missing fixtures/skips cannot make zero-loss proof vacuous.
- Both-interpreter affected-file correctness and the specified full-map/image/scorer equivalence evidence remain required. Keep all real saved-evidence rescoring, sweep cases, tolerances and thresholds. Extend existing cases; no permanent duplicate oracle/framework.
- Timing acceptance: **one cold and one warm run per interpreter**, plus existing baseline, using exact `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` in each explicit interpreter environment. Targeted alternating-key checks prove coexistence; no extra four-run warm sequence. Record wall/summed times, cache hits/misses, setup/round counts, longest item, load/process/RSS and skips. Reuse consecutive runs for retention accounting. If shared-lock wait/cold sweep becomes the tail, S/10 is insufficient; report it.
- **One heavy job at a time**; no overlapping full suites/live gates/perf jobs and **no deliberately loaded pair**. Record natural load; robustness under load remains unproven until observed. Scheduling gets its paired real round, optionally combined with null-subset qualification; any verdict or timing difference requires separate reruns before attribution.

## Projection

Use `W = remaining S/10 + residual`; main measured residuals are **19.3/38.2 s** (262−242.7 / 314−275.8), Stage B 3.13 **59 s** (350−291). Conservative A1+A2 credits: main **400/410 S**, Stage B **600/615 S**. Warm credits (gate + sweep + dissolve + rescore + handback): main 3.13 `400+210+170+22+5=807 S`; main 3.10 `410+295+195+25+7=932 S`; Stage B 3.13 `600+180+155+22+5=962 S`; Stage B 3.10 `615+253+174+25+7=1074 S`. Cold restores sweep credits of **210/295/180/253 S**; multi-fault subtracts **310/310/480/480 S**. Extra :829 credit remains unbanked.

Stage B floor baseline is extrapolated: gate `1621×1084/1057≈1662`; other work `1289×1674/1370≈1575`; total **≈3237 S**. Floor sweep credit `180×295/210≈253`. These project the measured Stage B shape, not current-tip timings.

Stage B 3.10 residual is unmeasured: 59 s (as 3.13) gives 275 s warm; main's 3.10/3.13 residual ratio (×2) gives ≈333 s warm
/ ≈285 s with multi-fault. 'Under five minutes on the floor' is not claimed for Stage B until measured. At ≈117 s residual the cold floor estimates become ≈358 s / ≈310 s with multi-fault. Residual may shrink as the sweep tail disappears; neither direction is measured. Warm applies only when the full cache identity survives (≈85% recent source-only eligibility, lower for continuity changes). No pool-cap, binary, retention, lazy-import, batching, dashboard or live-gate credit enters these suite numbers. Lock waits/contention, current-tip growth and load may change the model; do not claim the idle-and-loaded goal from estimates.

| Suite / interpreter | Baseline S | Warm remaining S | Residual | Warm W, no multi-fault | Cold W, no multi-fault | Warm W, with multi-fault | Cold W, with multi-fault |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main 3.13 |2427|1620|19.3 s|**181 s**|**202 s**|**150 s**|**171 s**|
| Main 3.10 |2758|1826|38.2 s|**221 s**|**250 s**|**190 s**|**219 s**|
| Stage B 3.13, measured baseline shape |2910|1948|59 s|**254 s**|**272 s**|**206 s**|**224 s**|
| Stage B 3.10, optimistic extrapolation |3237|2163|59 s, unmeasured|**275 s**|**301 s**|**227 s**|**253 s**|
| Stage B 3.10, residual sensitivity |3237|2163|≈117 s, unmeasured|**333 s**|**358 s**|**285 s**|**310 s**|

Live-gate projection: main queue span is 1002 s today; any-slot + measured per-arm longest-first simulates 831 s versus 824 s ideal (F4/Stage B 1235 s versus 1396 s today). Fixed-group order simulates 829 s (main) / 1230 s (F4/Stage B). With approved option A (≈316 job-s removed) it simulates **724 s main** (ideal 719 s, ≈12 min) and **1126 s F4/Stage B**, i.e. queue span −28% main / −19% Stage B versus today; confirm with the paired real round. Setup/check phases remain outside queue span; if combined confirmation differs in verdict or timing, rerun each change separately before attribution.
