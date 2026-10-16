# Plan critique r2: suite_speedup.plan.md (revision 1 + coordinator §F edits incl. Pass G null subset)

Read-only review against origin/main 163ec812 plus the Stage B copy at 1a56be4c. Evidence comes from the code, the `probeprof` and real
Pass G artifacts (main checkout `output/evidence/s2-dev/instr-v-ecf1b553/final/C1-gates-j3/passG-*.json`), and two tiny zsh
snippets. No pytest was run.

## Round-1 folds

All 13 round-1 findings are folded. Both "Refuted" notes are **correct**:

- **A3 host-redD5.** The default host-red stub artifact has no `redArm`/`arm`/`paintFloor` (`tests/test_run_gates.py` generic tail of
  PROBE_STUB). Every host-red arm therefore fails in R2, D5 no-pin-hold included (`scripts/run_gates.sh:343–354,372,623–624`).
  "R2 + injected labels" would double-count it. Baseline-aware replacement is the right correction.
- **Dissolve canonical pair.** `mix` is called with `with_holder` and device-scaled pairs (`tests/test_dissolve_probe.py:374,537,645`),
  so a global `(e, kind)` memo is wrong. The critique's lever was conditional ("verify"), and the plan verified it.

Arithmetic in §Projection checks out row by row (807/932/962/1074; 181/221/254/275; cold 202/250/272/301; −31/−48).
Verification is now proportionate.

---

## Findings

### 1. MAJOR: A3's spec is wrong in two places the owner is asked to approve

**(a) `findings=0` is false for host-redD5 slots.** The `red-noself`/`red-floor`/`red-nofloor` stub artifacts carry one `endOfShow`
paint-census entry (PROBE_STUB `red-*` branch). `paint_report` runs on every host-red arm whatever its verdict
(`run_gates.sh:390`) and appends that entry (`:441–444`). A round packing one of those faults therefore prints `findings=1`. Today's
carry-cover `count()` regex (`test_run_gates.py:1049`; the Pass G one at :832) requires `findings=0`, so a packed round would fail it.

**(b) Block scoping cannot key on the header for deck host-red arms.** `check_host_red`'s Python header is `[HOST {label}]`, with
label = the args only and no deck (`run_gates.sh:332,383`). D2, D3 and D5 `--core-variant no-pin-hold` all print the identical
`[HOST --core-variant no-pin-hold]`. A "from [LABEL] to the next header" scope is ambiguous there.

**(c) Two host-redD5 `why` obligations are vacuous today, and block scoping does not change that.** R2's own D5 block already
contains:
- `arm.sampler is not schema 2 with selfCheck.ok`, because the default artifact has no `arm` (`:353–354`);
- `paintFloor missing (a no-pin-hold red arm needs at least 60 frames)` (`:372`).

So `red-noself` and `red-nofloor` pass their `why` check even if the stub ignored the mode. (Block scoping does fix the same
vacuity for Pass G red `gr-nofloor`: today that text is satisfied globally by the D2/D3/D5 host-red blocks.)

**Fold (A3):**
> "Round-level: `findings` == the number of host-redD5 `red-*` faults injected in that round (each adds one endOfShow entry,
> `run_gates.sh:390,444`). DONE `failed` == the count of GATE FAILED lines == R2's multiset with each injected stem's baseline
> contribution replaced by its expected one. A block is the lines from a top-level `[` header up to and including the arm's own
> tally/`GATE FAILED` line. Identify a host-red block by check order (`run_gates.sh:623–624`), never by header text: the header
> omits the deck.
>
> Preservation-map note for the owner: the `red-noself`/`red-nofloor` reasons also appear in R2's D5 block, so those two `why`
> checks were and remain non-evidential. Their exactly-one-failure obligation is preserved. Optional strengthening (owner call,
> one line): also assert `observed red: ['b0to1:A:carry']` inside the D5 block, which only the `red-*` stub writes."

### 2. MEDIUM: Pass G null subset touches the wrong files and has an ownership gap

`run_gates.sh` needs **no** change:
- `check_passg` reads only `pass`/`status`/rc (`:398–410`);
- `paint_report`'s loop (`:424–429`) and `check_passg_red`'s sha loop (`:479–480`) iterate whatever destinations exist;
- the floor loop is armed-only (`:494`);
- PROBE_STUB already writes `nullControl.destinations: []` (`test_run_gates.py:139`).

Stage B is the same (`:533–536,588,603`).

The real edits are:
- `scripts/live_continuity_probe.py` (`overall_status_g` :5997–6006, `run_pass_g` :6113–6153);
- `tests/test_live_continuity_probe.py`. The pinning tests are `TestOverallStatusG` :3586–3620,
  `test_overall_status_g_counts_against_the_recorded_matrix` :8117–8121, the deck-parametrized matrix test :8090–8107, and
  `_g_leg_result` :10225–10227.

Both files are reserved to the Stage B session (§A line 69). §Streams 4 gives the serialized gate-product owner only
`run_gates.sh`/`test_run_gates.py`/`p2_verdict`.

Soundness, checked against the last full real round's artifacts (C1-gates-j3):
- Every deck has ≥3 slides. D4 and D5 have exactly 3, matrix `(1,2),(1,3),(3,1)` + legs. So `(1,3)` and `(3,1)` fit all seven, and
  the "first fitting base case" fallback is dead code today.
- Both kept destinations carry ≥1 live-expected movie on every deck. The armed `expectedRects` at the two kept destinations
  (slide 3, then slide 1) are:

| Deck | Slide 3 | Slide 1 |
|---|---|---|
| D1 | 1 live | 1 live |
| D2 | 1 live | 1 live |
| D3 | 1 live | 2 live |
| D4 | 1 live | 1 live + 1 dead |
| D5 | 1 live | 1 live |
| D6 | 1 live | 2 live |
| P2 | 2 live | 2 live |

- At both kept destinations the null control reads all-dead, with uniqueShas 1 and 0 `<video>`.

So the null discriminates at both kept destinations on every deck. Nothing slide-2-specific is lost, because `require_no_consumption`
is armed-only (`:6069`) and the characters region is DEAD in both arms (`goto_rect_expectations` :5372–5376).

`passg_red_ids`/`PASSG_RED_EXPECTATIONS` register only armed `G…` ids (`:290–293`), so dropping null legs cannot change the
registered set.

**Fold (§F null subset):**
> "Files: `scripts/live_continuity_probe.py` and `tests/test_live_continuity_probe.py` only. No `run_gates.sh`/`test_run_gates.py`
> change: the checks are length-agnostic (`run_gates.sh:398–410,424,479,494`), and the stub already writes an empty null list
> (`test_run_gates.py:139`).
>
> `overall_status_g` compares `len(off)` with `result["nullMatrix"]` when it is a list, else with `matrix`, so older artifacts and
> the existing unit tests stay valid. Extend `test_overall_status_g_counts_against_the_recorded_matrix` with one nullMatrix
> length-mismatch → `error` case. In the deck-parametrized test (:8090), assert that the null matrix is `((1,3),(3,1))` and that
> each null destination's slide has ≥1 LIVE `V` expectation in the committed plan. That is the property that keeps the null
> non-vacuous if a deck changes. Drop the untested fallback, or cover it in the same test.
>
> Owner: the Stage B session, or the serialized gate-product owner after Stage B merges with these two files added to its list.
> Never in parallel with Stage B probe edits (Stage B moves these functions to :6538/:6741)."

### 3. MEDIUM: Pass G null-subset arithmetic

Null destinations saved per deck: D1 6, D2 6, D3 6, D4 3, D5 3, D6 6, P2 4 (matrices 8/8/8/5/5/8/6). The Pass G red arm (D1, 8
cases) saves 6 more. That is 40 × 7.9 s ≈ **316 job-s**, not 7 × 47 = 330. Per run the saving is 24–47 s, not a flat 47 s. Wall is
≈105 s only under ideal packing, so it is not additive to the scheduling row.

**Fold:**
> "≈24–47 s per Pass G run (D4/D5 ≈24, P2 ≈32, 8-case decks ≈47); ≈316 job-s per round including the Pass G red arm; ≈105 W at
> ideal packing (an upper bound, not additive to scheduling)."

Also note that the null session's history changes. Under the subset, `(3,1)`'s source goTo 3 is a same-slide goTo after `(1,3)`;
today it follows `(1,4)`. The re-qualification round covers this, and it is worth one line in the plan.

### 4. MEDIUM: the sweep drift guard does not cover the main sweep

The plan's guard traces `_score_34` only. The `main` sweep scores through `p2._advance_c_ok` (`tests/test_p2_adversarial.py:6893–6902`),
a different code path behind the same manifest. A new dependency there goes unguarded.

**Fold (B guard):**
> "Trace both scorers under `sys.setprofile`: `_score_34` on the three bracket snapshots plus one deletion per arm, and
> `_advance_c_ok` on `_main_inputs()` plus one deletion. Assert that every executed file under `src/obed_edom/` (rglob) is in the
> manifest."

### 5. MEDIUM: the any-slot refill needs a concrete zsh design and an explicit list of changed launch-order assertions

Two zsh facts, both tested here:
- zsh 5.9 has no `wait -n` (`wait: job not found: -n`).
- `$jobstates` counts running jobs correctly in the current shell (3 → 2 → 0), but it is **empty inside `$(...)`**.

The simple, robust design keeps the existing trap/`stop_jobs` (`run_gates.sh:265–269`), which already reads `$jobstates`:
`queue` polls `N=${#${(M)${(v)jobstates}:#running:*}}` in the current shell until `N < GATE_JOBS`. It sleeps with
`zmodload zsh/zselect; zselect -t 10` rather than forking `sleep`. Forked `sleep` would also be recorded by Stage B's SLEEP_STUB.
`PIDS` becomes unnecessary.

Longest-first:
- Per-arm "measured duration ranks" are machine-dependent data that must be maintained for every new arm (Stage B adds 27 mm-feed
  arms). Group-level order is simpler and stable. Ask the coordinator to simulate it; it should land close to 831/1235.
- Today launches are interleaved with function definitions (`:308,391–392,411,506,567,615,620`), so reordering means one launch
  section after all definitions. That is a high Stage B textual conflict.
- The GATE_JOBS=1 order tests assert today's listed launch order (`test_run_gates.py:738,771,978,1063`).

**Fold (§F):**
> "Refill: poll the `$jobstates` running count in the current shell (never in `$(...)`), with a `zselect` sub-second wait; keep
> `stop_jobs`/traps unchanged. Order: a fixed group order in one launch section (P2 freeze-bracket arms, Pass G, host, Pass G
> red, mm-feed, remaining P2, host red, carry-cover, paint control; coordinator to confirm by simulation), the same for every
> GATE_JOBS. Checks keep the listed order.
>
> Assertion map: the start-order assertions in :738, :771, :978 and :1063 become one exact expected launch sequence. The
> check-order assertions stay byte-identical. Add one parametrized case to an existing stub test proving a later run launches
> before the oldest one finishes, so a regression to oldest-PID wait is visible. Update the `run_gates.sh:259–262` comment."

### 6. MEDIUM: Stage B 3.10 residual is optimistic; give the sensitivity

On main, residual doubles from 3.13 to 3.10 (19.3 → 38.2 s). Stage B 3.10 uses 59 s. With main's ratio it would be ≈117 s:
- warm Stage B 3.10 ≈ 216 + 117 = **333 s** without multi-fault, ≈ 285 s with it;
- cold ≈ 358 s / 310 s.

The residual may also shrink once the cold sweep tail goes. It is unknown in both directions.

**Fold (Projection):**
> "Stage B 3.10 residual is unmeasured: 59 s (as 3.13) gives 275 s warm; main's 3.10/3.13 residual ratio (×2) gives ≈333 s warm
> / ≈285 s with multi-fault. 'Under five minutes on the floor' is not claimed for Stage B until measured."

### 7. MEDIUM: A1 key, failure and cleanup details

- **Key.** Key on `(script path, args tuple, sorted explicit overrides)` only, never on the effective `os.environ`, which differs per
  worker (`PYTEST_XDIST_WORKER`, `PYTEST_CURRENT_TEST`) and would never share.
- **Failure.** On a failed compute (exception or `TimeoutExpired`), publish an error record under the lock so later consumers fail
  fast with the same error. Otherwise up to 17 R2 consumers serially re-run a 120 s-timeout round.
- **Cleanup.** In a `finally`, `pkill -KILL -f <that round's own dir>`, never `getbasetemp().parent`, which would kill other
  workers' live rounds. Consumers' `gates` teardown (`test_run_gates.py:367`) cannot reach the shared dir.
- **Worker detection.** Use `os.environ.get("PYTEST_XDIST_WORKER")` rather than the `worker_id` fixture, so `-p no:xdist` still
  works.

**Fold** these four sentences into A1.

### 8. LOW: A3 counts

The 32 cases sit on **10** stems, not 11: 5 carry-cover + passG-red + 3 paint controls + host-redD5. The max per stem is still 7, so
there are 7 rounds.

The `:829` errored-Pass-G bad round (`passG-D3 g-error`) fits as an 11th stem in the same 7 rounds (≈12 S more).

**Fold:** "33 cases on 11 stems including `:829`'s bad round; still 7 rounds."

### 9. LOW: sweep cache robustness and simplicity

- If `main_checkout()` raises (no git) or its `.cache` is unwritable (a sandboxed session), fall back to today's worktree-local
  `.cache/test-sweeps`, not to compute-every-run. Otherwise the hit rate silently drops to 0.
- `os.utime` the JSON on a hit, so mtime retention is LRU: a hot main-line key must not be pruned behind newer one-off keys.
- Drop "skip actively locked computations". A computing key has no JSON yet, and readers tolerate an unlinked file (`_load_sweep`
  → None → recompute under the lock, `test_p2_adversarial.py:6291–6313,6340–6357`). Prune JSON only, with tolerated races.

### 10. LOW: confirmation-round confounding

Using one real round for both scheduling and null-subset qualification is fine if everything matches. If any verdict or timing
differs, rerun the two changes separately before attributing it.

---

## Spot checks that passed

- **A2 tier-invariance holds for all 10 rounds on main.** Warning `:166–170`, start load `:171`, nonce `:263`, prewarm and
  "cache hit" `:278–296`, launch load `:307`, end-load/wall `:632` all print before the dev exit at `:638`. Dev runs HOST
  1920x1080 (`:35`) and launches runs, so "a non-prewarm event" holds.
- **The same holds on Stage B.** Dev also skips QUAL_B staging there (`MM_FEED_ARMS=()` `:129`).
- **R1/R2 consumers.** Every consumer reads `gates["out"]`/`events`/stdout only. Path assertions use `gates["out"].resolve()`
  (`:792,987,1071`), so binding `out` and `events` to the shared round keeps the assert lines byte-identical.
  `TIER=full` is the default (`:18`).
- **xdist and tmp layout.** Under xdist, `getbasetemp().parent` is the per-session `pytest-N`. Under `-n 0` it is the
  cross-session `pytest-of-$USER`, which the plan correctly forbids.

## Verdict

No blockers. Findings 1 (A3 spec), 2 (null-subset files and ownership) and 5 (refill design and order-assertion map) must be
folded: they would otherwise send implementers to the wrong files, or produce failing or ambiguous assertions in owner-approved
work. 3, 4, 6 and 7 are small wording folds; 8–10 are optional polish. After folding, the plan is ready for the owner.
