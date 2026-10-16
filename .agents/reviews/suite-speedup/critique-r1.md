# Plan critique r1: suite_speedup.plan.md

Read-only review against origin/main 163ec812. Evidence comes from the code, the `prof/*.junit.xml` files, `trace{1,3}.txt`, `cprof/dissolve.prof`, `gates/gates2-*.txt`, and one light import-timing snippet. No pytest was run.

Spot-checked citations are correct:
- `run_gates.sh:34,45,54,68,76,87,94,103,152,214,272,273,323,415,620`
- `test_run_gates.py:304–367,376,387,666,738,771,844,914,945,978,1010,1016–1060,1063`
- `dissolve_probe.py:1927,1970,1989,1997,2058`
- `test_p2_adversarial.py:6273,6328,6397,6640,6668`
- The 58-arm main count (3+5+25+7+1+3+6+8).

## Round inventory: test_run_gates today (main 3.13, junit)

A stub round costs ~12–13 s in-suite on main (≈20–34 s on Stage B, 85 arms). A dev round costs 2–3.6 s. Refusals cost ≤0.8 s.

| Rounds | Tests |
|---|---|
| 30 | carry-cover known-bad, 15 × good+bad (359 s) |
| 17 | broken-instrument, 1 each (214 s) |
| 5 | `gate_jobs_above_three_warns` (80 s) |
| 4 | load positive control (58 s) |
| 8 | jobs=1 rounds: 6 order/matrix tests + `fresh_round[1]` + `warns[1]` |
| ~14 | other single-round tests |
| 4 | dev rounds |
| 3 | partial hang rounds |

Total: **≈78 full rounds, 4 dev, 3 partial.**

The plan removes ≈17 rounds (6→1 order tests, 15→3 carry-cover controls, maybe the Pass G control). From the junit that is ≈**234 s**: 93.5→~18, 359→~215, ~12, ~3. The plan's central figure is 300 s.

---

## Findings

### 1. MAJOR: test_run_gates is under-banked; share completed rounds across workers instead of merging tests

The plan merges six order tests into one, and carry-cover cases into 3 loop-batches. That loses per-test failure isolation (the first failing assert hides the rest) and parametrize IDs. It also forces a heavy assertion map.

The per-worker caveat (plan §Baseline, A.3) has a standard fix, the pytest-xdist session-fixture recipe:
- a file lock in `tmp_path_factory.getbasetemp().parent`;
- `fcntl.flock`, which is already used by the sweep cache at `test_p2_adversarial.py:6350`.

With it, a round is computed once per **session**, not once per worker, and tests keep their bodies and IDs.

Rounds that are byte-identical in input today:
- **R1 (`GATE_JOBS=1`, default tier).** 8 consumers: `:376[1]`, `:594[1]`, `:666`, `:738`, `:771`, `:844`, `:978`, `:1063`.
- **R2 (default env, `--tier full`).** Consumers:
  - the 15 carry-cover good controls (`:1038`);
  - the Pass G good control (`:836`);
  - `:945`, which needs `--tier full`. `TIER=full` is the default at `run_gates.sh:18`, so the controls are unchanged in meaning;
  - `warns[None]` (`:594`).

**Fold:**
> "A1. Add a session-shared stub-round fixture: under xdist (`worker_id != "master"`), lock `getbasetemp().parent/gates-<key>.lock`. Compute a round once into `getbasetemp().parent/gates-<key>/`, keyed on (args, env). Persist rc, stdout, stderr, the events list and the outdir path as JSON. Later workers load the JSON. Under `-n 0`, compute directly and never reuse `getbasetemp().parent`: outside xdist it is shared across sessions. Consumers only read. Rounds: R1 = `GATE_JOBS=1`, R2 = `--tier full`.
> - Migrate the R1 consumers listed above.
> - Make R2 the good control for every carry-cover case and for `:836`, and the round for `:945` and `warns[None]`.
> - Keep each test function and parametrize ID; do not merge the order/matrix tests.
> - Assertion map = the diff. Each test's assert lines are byte-identical; only the `gates["run"](...)` producer line changes.
>
> Estimated saving: ~24 rounds ≈ 300 s summed on main 3.13, ~450 s on Stage B. Replaces A.2 and A.3."

### 2. MAJOR: tier-independent pre-launch assertions run full rounds; a dev round is ~5× cheaper

What the warning, load and prewarm tests assert is printed before any tier-specific launch:
- `run_gates.sh:166–170` (GATE_JOBS warning);
- `:171` (load at start);
- `:284` (prewarm event);
- `:307` (load at launch);
- `:632` (end load/wall line).

All of these are also printed in `--tier dev` (`:161–165` adds only the DEV banner). Ten full rounds exist only to reach these lines:
- `warns[3,4,5]`;
- load positive ×4 (`:538`);
- load-stays-low (`:566`);
- empty-outdir accepted (`:413`; asserts `HOST 1920x1080: pass`, which dev also runs);
- the second `out2` round of `:471` (asserts only "cache hit").

**Fold:**
> "A2. Run these 10 rounds as `--tier dev`; assertion text unchanged. The map row states the input change (tier) and cites `run_gates.sh:161–171,284,307,632` as tier-independent. A reviewer verifies by reading those lines.
>
> Estimated saving: ~100 s summed on main, ~150 s on Stage B."

### 3. MAJOR (owner call): the plan wrongly says multi-fault rounds *must* weaken the +1 and singleton assertions; give the owner numbers instead

`fail()` increments `FAIL` and echoes exactly one `    GATE FAILED: <label>` line (`run_gates.sh:201`). Every check reads only its own `$O/<stem>.json` and `.rc` (`:323,398,454,517,577`).

So "+1 and singleton" (`test_run_gates.py:1041–1054,1125–1135`) is equivalent to: **bad GATE FAILED multiset == good multiset + {label}**. For k faults on distinct stems, two conditions together imply each singleton obligation, given per-arm check independence (true by construction):
- bad == good + {label₁…labelₖ};
- each `why` asserted inside its own arm's output block, from `[LABEL]` to the next header.

Scoping by block is stronger than today's global `why in stdout`. Today's global check would collide anyway: `status 'inconclusive' != 'fail'` appears for both linear-bridge and null.

Residual risk: a cross-arm coupling regression *and* a simultaneous detection loss on the coupled arm. That is theoretical, the class the owner wants brought to them with its gate cost.

Packing: the 32 cases sit on 11 stems, at most 7 cases per stem (`carry-cover`), so they need **7 rounds instead of 32**. That saves ~25 rounds ≈ 310 s on main 3.13 and ≈ 480 s on Stage B.

**Fold** into Owner decisions:
> "Multi-fault known-bad rounds: 7 shared rounds (A1 fixture), one fault per stem per round. Each parametrized case keeps its ID, reads its slot's round and asserts:
> - (a) its label's GATE FAILED line is present exactly once;
> - (b) its `why`, or the no-artifact line, inside its own block;
> - (c) at round level: GATE FAILED multiset == R2's + exactly the injected labels; DONE `failed` == that count; pending=0; findings=0; rc=1.
>
> For the host-redD5 cases, (c) also checks that no instrument label appears beyond the injected ones.
>
> Recommendation: approve. Saving ≈310/480 s summed. Residual: the theoretical two-bug masking above. Verify with a one-off fault-injection on a disposable script copy that cross-wires two checks; it must fail."

Delete A.4's sentence "neither preserves the original assertions".

### 4. MAJOR: the sweep cache lives per worktree, so every new worktree starts cold

`_cached_sweep` uses `root / ".cache" / "test-sweeps"` with `root=REPO` (`test_p2_adversarial.py:6336`). The owner works in a fresh worktree per task. This worktree has its own `bracket.json` (2.5 MB) and `main.json` (0.8 MB); the main checkout has none. Per-key files alone do not fix this. `fixture_paths.main_checkout()` (`src/obed_edom/fixture_paths.py:14–20`) is the existing resolver for shared main-checkout state.

The plan also lacks retention. Per-key files accumulate ~3.3 MB per (interpreter × scorer revision).

**Fold:**
> "B. The cache dir is `main_checkout()/.cache/test-sweeps/`. `root` is still injectable so the existing fake-root tests keep isolating; they pass the cache dir explicitly. Keep the flock and atomic replace (already concurrency-safe across processes). On store, keep the newest N=8 files per sweep name by mtime and unlink older ones."

### 5. MAJOR: the dependency manifest has no drift guard; state the hit rate honestly

The plan audits executed dependencies once (B, 2nd bullet). After that, a new executed import inside `p2_verdict`/`html_alpha_probe`, or a helper they start calling, silently goes stale and yields false cache hits.

Runtime `sys.modules` closure is not a viable alternative:
- Under xdist every worker imports every test module at collection.
- The static `obed_edom` import closure of `p2_verdict` is already **46 of 86** src files, because `live_continuity` imports widely.
- It would barely narrow the key.

Hit rate over the last 40 first-parent merges:
- 20 touched `src/obed_edom`: the all-src key misses;
- 6 touched `{p2_verdict, html_alpha_probe, live_continuity}`.

`live_continuity.py` is in the manifest only for `canonical_asset_name` (`live_continuity.py:1291`). It is the hottest file: Stage B adds +411 lines. Continuity-workstream PRs will mostly run cold.

**Fold:**
> "B. Add one guard test, cache off: run `_score_34` on the three base snapshots plus one deletion per arm under `sys.setprofile`. Assert that every executed `src/obed_edom/*.py` file is in the manifest (<1 s). Document the residual: branches reached only on other deletion paths.
>
> In the projection, label the warm credit as applying to PRs that do not touch the manifest (≈85% of recent merges, fewer in the continuity workstream)."

### 6. MAJOR: the verification burden is disproportionate and partly conflicts with the machine-load rule

The coverage recipe (plan §Coverage) is a whole serial suite, cache off, `OBED_TEST_SWEEP_WORKERS=1`, under coverage, on **both** interpreters, for baseline and candidate:
- 2,427–2,758 summed s × coverage overhead, plus a serial cold sweep (~8+ min alone);
- that is roughly 4–6 heavy hours on a shared machine with one heavy job allowed.

Also:
- The A mutation-injection matrix is heavy.
- The "controlled loaded pair" means deliberately loading the machine.
- Timing is required as 3.13→3.10→3.13→3.10 plus cold plus loaded runs.

**Fold:**
> "The coverage diff covers only the test files whose tests are dropped or merged. With A1/A2 in place, that is binary-movie only if kept (see 10), else none. Measure their production targets with `-n auto` plus coverage parallel/combine on 3.13. Add 3.10 only if the touched code has a version branch.
>
> The A assertion map is the diff (see 1). Fault injection is only for the owner-approved multi-fault rounds (see 3).
>
> Timing acceptance per interpreter: one cold run and one warm run of the exact worksteal command, plus the existing baseline.
>
> Drop the loaded pair."

### 7. MEDIUM: the dissolve test-side lever is mis-targeted

From `cprof/dissolve.prof` (180 s single-process):

| Function | Cumulative | Calls |
|---|---|---|
| `media_run` (`test_dissolve_probe.py:420`) | 85 s | 300 |
| `mix` (`:87`) | 58 s | 3,180 |
| `unpremul` | 23.6 s | |
| `textures()` (`:73`) | 9.9 s | 318, deterministic |

Only 90 of the `mix` calls come from `fade` (10 × 9). The plan's "hoist out of fade→mix loops" therefore misses ~97% of `mix` cost.

**Fold:**
> "C (test side): `functools.cache` `textures()` and the premultiplied A/B pair, with arrays set `writeable=False`, so any in-place mutation raises. If every `mix` caller passes the canonical pair (verify), memoize `mix` by (e, kind) the same way. Callers that mutate frames take `.copy()`. Bit-identical by construction."

Replace the committed "old-formula differential case" with a one-off differential in the PR evidence: full scorer dict equality, NaN-aware, over the existing CASES and the managed rescore matrix, on both interpreters. A permanent oracle copy of the old formula violates minimal tests.

### 8. MEDIUM: the gate scheduling estimate does not match its proposal

A FIFO-oldest-PID simulation (`run_gates.sh:272`) on `gates2-*.txt` reproduces the measured span: 1396 / 1444 s simulated vs 1385 / 1389 s measured.

| Option | Span | Saving |
|---|---|---|
| Plan's proposal: move only the two positive bracket P2 arms forward | 1363–1373 s | −25 to −35 s |
| LPT (longest-first) order, unchanged FIFO queue | 1274–1276 s | −110 to −120 s |
| Work-conserving wait, current order | 1274–1281 s | |
| Both | 1235–1238 s | |

The plan's 60–150 s figure is not reachable by the plan's proposal.

**Fold:**
> "Owner call with three options and their simulated spans (above), on F4 data. Each changes the overlap of long arms (Pass G 86–135 s) and so measurement conditions. Recommend LPT order only (no queue-policy change), then paired real rounds."

### 9. LOW: the check phase dominates a stub round

`trace3.txt` (GATE_JOBS=3, alone): launch phase 1.15 s, sequential checks 4.6 s, out of a 6.1 s round.

`expect` (`run_gates.sh:214`) imports `p2_verdict` → numpy/PIL/cv2 for `build_continuity_plan` only:
- measured 0.17 s vs 0.02 s without it;
- ×8 per round, ≈1.2 s.

That is a cheap, behaviour-identical candidate: a lazy import, as a product change. After findings 1–3 only ~20–45 rounds remain, so the saving is ≈25–55 s summed. Keep it conditional with row 11; do not bank it.

### 10. LOW: binary-movie merge has no measured basis

`main313.log` shows one 18.40 s setup on `test_movie_matches_the_p2_pattern_container`. The other `full_movie` consumers take 0.001–0.003 s, so no duplicate setup happened.

**Fold:**
> "Row 5 → hold; remove its 10 s from the projection."

### 11. LOW: arithmetic

- **Stage B floor extrapolation.** Other work = 1,289 × (1,674 / 1,370) = **1,575**, not 1,614. Total ≈ **3,237**, not 3,276 (≈4 s wall).
- **Row 1.** The plan's own changes are ≈234 s on main, not a 300 s central.

### 12. LOW: the sweep pool cap should be neither a default nor a planned experiment

Oversubscription by CPU-bound children leaves total CPU work unchanged; the load ~106 is driven mainly by gate rounds (≈170 processes each). A serial or capped cold sweep risks becoming the tail. With the shared cache (finding 4), cold runs become rare.

**Fold:**
> "Row 7 → measure only if a cold full run shows the sweep on the critical path."

### 13. LOW: tmp retention

At session start the controller does the cleanup serially. A `failed` policy moves the unlinks into per-test teardown across 10 workers, so a real ~5 s wall gain is plausible. Keep it as the owner call it already is.

---

## Revised projection (estimates; plan's other rows unchanged except row 5 = 0)

Gate savings scale ×1.5 on Stage B for the 85-arm round.

| Scenario | Savings | Remaining S → wall | Wall with multi-fault rounds (owner call) |
|---|---|---|---|
| Main 3.13 warm | gates A1+A2 ≈ 410, + 210 + 170 + 22 + 5 = 817 | 1,610 → 161 + 19 = **≈180 s** | **≈149 s** |
| Stage B 3.13 warm | gates ≈ 615, + 180 + 155 + 22 + 5 = 977 | 1,933 → 193 + 59 = **≈252 s** | **≈206 s** |
| Stage B 3.10 warm (3,237 base) | gates ≈ 630, + 253 + 174 + 25 + 7 = 1,089 | 2,148 → 215 + 59 = **≈274 s** | **≈226 s** |

Stage B is then under 5 min without the owner call, and well under it with the call.

## Verdict

Most of the plan's cache, dissolve and rescore content is correct and safe, and its citations check out. But it is too conservative on the dominant file and too heavy on verification:
- **Gates.** test_run_gates runs ≈78 full rounds. The plan banks ~17 of them by merging tests, which costs isolation and needs a mutation-tested assertion map. Session-shared rounds (xdist file-lock recipe) plus dev-tier rounds for tier-independent assertions remove ~34 rounds with assert lines byte-identical. The "multi-fault must weaken" claim is wrong: a per-label multiset diff with block-scoped `why` preserves each singleton under the script's per-arm independence. It should go to the owner with ≈310/480 s attached.
- **Sweep cache.** It is per worktree, so it is cold in every new worktree; share it via `main_checkout()` with retention. The manifest needs a self-maintaining guard, not a one-time audit.
- **Dissolve.** The test-side lever must target `textures`/`mix`/`media_run`, not `fade`.
- **Gate scheduling.** The 60–150 s needs LPT order, not the two-arm move.
- **Verification.** Shrink coverage and timing to the touched files plus one cold and one warm run per interpreter, and drop the loaded pair.

Folding findings 1–8 makes the plan fit for implementation.
