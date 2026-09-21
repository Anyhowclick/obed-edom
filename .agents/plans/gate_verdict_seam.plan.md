---
name: Gate verdict seam — pure verdict logic out of scripts/
overview: >-
  Architecture-review candidate 1, re-verified against current code 2026-09-21. Pure,
  fail-closed gate verdict logic lives in one-off scripts while the scorers it calls sit in
  src/. Tests reach it by executing a 4,154-line script at collection. The plan moves the
  verdict layer into src/ in stages, smallest-risk stage first, and fixes the one latent
  defect the arrangement has already produced. Staged deliberately: a single 4,000-line
  relocation is not reviewable and the evidence does not justify it.
todos:
  - id: s1-extract-movie-motion
    content: >-
      Extract the frame-paths -> visible-movie-motion wrapper from
      scripts/p2_recovery_html_adversarial.py into src/ as the one call path, WITHOUT the
      caller-side empty-crop filter, so score_visible_movie_motion's "empty crop" hard reject
      is reachable from its only caller.
    status: completed
  - id: s1-retire-cross-script-private-import
    content: >-
      Point scripts/p2_recovery_html_decode_probe.py at the src entry point instead of
      importing the private _score_visible_movie_motion from another script.
    status: completed
  - id: s1-cover-fail-closed
    content: >-
      Test the restored fail-closed branch through the src entry point: an out-of-bounds ROI
      must yield reason == "empty crop" with emptyIndices/shapes, not "need >=3 frames".
    status: completed
  - id: s2-unhook-spec-loader
    content: >-
      Migrate the pure verdict functions that tests/test_p2_adversarial.py reaches via
      spec_from_file_location, so the test imports a module instead of executing the driver
      script at collection. Success measure - the loader shim shrinks.
    status: completed
  - id: s3-remaining-gates
    content: >-
      Apply the same seam to live_continuity_probe.py, write_gate_ab.py and offline_write_ab.py
      once the stage-1/2 pattern has been reviewed. Not scoped until then.
    status: pending
  - id: open-scenehash-prefilter
    content: >-
      OWNER DECISION 2026-09-21: LEAVE IT ALONE. _capture_1to2_snapshot drops frames whose sceneHash is None before
      score_motion_across_flip, shrinking the window. Looks deliberate. Do not change without
      separate evidence.
    status: completed
---

# Gate verdict seam

## STATUS — stages 1+2 DONE, on the re-do branch (2026-09-21)

Landed on `refactor/gate-verdict-seam-redo`, re-done against the freeze-control code after #187 merged
(owner decision: freeze first; see SEQUENCING, now resolved). `refactor/gate-verdict-seam` is the FIRST
attempt, kept only as a reference — never merge it.

| Commit | What |
|---|---|
| `ea1ebeaa` | the move: 142 names, 2,940 lines, into `src/obed_edom/p2_verdict.py`; test split |
| `9d6ed9cd` | `--reuse-export` refuses instead of falling back to a real Keynote export (both scripts) |
| `6c4d33ee` | merge origin/main (#187) |
| `e89c2e70` | Codex r1 fold: complete test split, real defence in depth, 5 reattached comments |

Verified: 141/142 definitions byte-identical to their originals (the one exception is the intended
empty-crop fix); `src` has no async code, no `ChromeCdp`, no import from `scripts/`, no `sys.path`
mutation; pytest 5236 passed / 93 skipped / 2 xfailed, `test:ui` 187, `test:maps` 542, `test:perf` 2;
Codex r1 (4 findings, verified and folded) then **r2 clean**; **live P2 gate green** on `e89c2e70` —
host x3 pass, P2 fast 14/14, bridge-off 13/14 (only `continueThroughMovingMagicMove3to4` red: the correct
negative control), slow 14/14; Keynote down before and after.

Final split: `tests/test_p2_adversarial.py` 560 pure tests import only from src;
`tests/test_p2_adversarial_driver.py` 19 (16 that reach driver code + 3 new `--reuse-export` tests).
Deferred by owner ("correctness first"): Codex Standards 2, the non-minimal docstrings in `src`.
Still open: stage 3 (`s3-remaining-gates`).


## Re-verified evidence (2026-09-21)

The handover said to re-verify before acting. Numbers below are from current code, and two of
the handover's figures were wrong in a way that matters.

| Claim (handover) | Re-verified |
|---|---|
| ~2,700 lines of verdict logic in `scripts/` | ~4,355 driver-free function lines across 10 gate scripts |
| ~4,000 lines of tests load scripts by file path | 5,918 lines across 4 test files |
| P2 gate filters empty crops before a hard-rejecting scorer | **Confirmed**, and the consequence is worse than recorded |
| (not recorded) | 6 scripts import **40 private names** from each other via `sys.path.insert` |

`src/obed_edom/html_alpha_probe.py` holds 13 scorers with 43 fail-closed `"reason"` branches.
The scripts hold the verdict logic that calls them.

## The defect, precisely

`scripts/p2_recovery_html_adversarial.py:1798`:

    patch = arr[y + inset : y + h - inset, x + inset : x + w - inset]
    if patch.size == 0:
        continue
    patches.append(patch)
    scored = score_visible_movie_motion(patches)

`score_visible_movie_motion` (`html_alpha_probe.py:1071`) documents empty crops as hard
rejects and returns `{"ok": False, "reason": "empty crop", "emptyIndices": ..., "shapes": ...}`
at line 1094. The `continue` makes that branch unreachable from its only real caller, and
does not merely hide it — it **shrinks the sequence**:

- The script's own guard at :1800 checks the UNFILTERED `len(frame_paths) >= 3`.
- So 5 frames of which 3 crop empty pass that guard, 2 patches reach the scorer, and the
  verdict becomes `{"reason": "need >=3 frames", "n": 2}` — a different reason, and `n` no
  longer matches the input.
- With an ROI fully out of bounds every patch is empty, `patches == []`, and a misconfigured
  ROI is reported as insufficient frames instead of `empty crop` + shapes.

**It is latent, not active.** `MOVIE_ROI = (109, 795, 952, 268)` with `inset = 8` slices
`arr[803:1055, 117:1053]`, so the patch is always 252x936 and the filter never fires today.
Captures are 1920x1080 because `ChromeCdp` (`scripts/p2_alpha_spike.py:114`) defaults to
`width=1920, height=1080` and enforces it via `Emulation.setDeviceMetricsOverride`, and the
decode probe specifies the same. **Correction (Codex r1):** an earlier draft of this plan cited
`EMPTY_CORNERS` as the proof. That was wrong — `_score_empty` skips empty corner crops, so
`EMPTY_CORNERS` does not establish the frame size. The conclusion stands on the CDP evidence. Removing it is therefore
behaviourally inert on current evidence and strictly strengthens the gate — it never weakens
one. It becomes active the moment capture resolution or the ROI changes, which is exactly
when a silent mis-verdict costs the most.

## Scope decision

The audit deliberately looked for a *class* of this defect and did not find one: of the
scorer call sites with caller-side filtering, only `_score_visible_movie_motion` masks a
fail-closed branch. `score_motion_across_flip`'s equivalent branch at :1193 IS reachable,
because the `_crop` path feeding it does not filter. So the payoff here is one latent bug
plus preventing recurrence — not a bug harvest. That is why stage 1 is small and stages 2-3
are gated on review rather than pre-committed.

## Behaviour-preservation contract

Follows the precedent this round set with `plan_payload`: the extraction lands with **no test
assertion added, removed or changed** except the new fail-closed coverage in `s1-cover-fail-closed`.
`tests/test_p2_adversarial.py` must pass untouched. Banked evidence under
`output/p2-recovery/` is not regenerated and not required.

## Owner decisions (2026-09-21)

1. **Placement** — flat `src/obed_edom/p2_verdict.py`. A `gates/` package is deferred; revisit
   only if stage 3 happens.
2. **Depth** — stage 1 **and** stage 2 this round.
3. **`sceneHash` pre-filter** — leave it alone.

## Stage 1+2 manifest (exact, computed 2026-09-21)

> **Superseded.** This is the FIRST attempt's manifest, against pre-#187 code. The re-do's manifest was
> recomputed on the landed code with the closure tool (see RE-DO DESIGN) and is recorded in `ea1ebeaa`.

Move to `src/obed_edom/p2_verdict.py` from `scripts/p2_recovery_html_adversarial.py`:

**29 functions, 1,338 lines** — the transitive call closure of everything
`tests/test_p2_adversarial.py` reaches. All are pure except the two evidence-loading entry
points, which belong in this layer:

- Entry points doing I/O: `_score_visible_movie_motion` (Image.open), `_derive_movie_texids` (read_text)
- Verdicts: `liveContinuity1to2`, `movingContinuity3to4`, `refusedCarry1to2`, `neverPooledEvidence`,
  `footprintFullyLive`, `_score_freeze_control`, `carryCensusVerdict`, `poolCensusVerdict`,
  `frozenCompositeAfterFlip`, `frozenIndexAfterFlip`, `build_continuity_plan`, `_times`
- Helpers pulled in transitively (all pure): `_after`, `_event_scene`, `_extract_movie_layers`,
  `_hash_num`, `_in_window`, `_isolation_view`, `_layer_identity`, `_mae_rgb`,
  `_presented_time_advances`, `_strict_hash_num`, `_target_elids`, `carryEvents`,
  `refusalEvents`, `size_matches`, `walk`

**Plus 9 constants** the test reads off the script module, without which the shim cannot go:
`MOVIE_ROI`, `MOVIE1_KEY`, `BURST_OFFSETS_MS`, `RETIRE_ZONE_MIN_HASH`, `SLIDE2_MIN_HASH`,
`SLIDE3_MIN_HASH`, `SLIDE4_MIN_HASH`, `SLIDE4_CONTROL_RECT`, `SLIDE4_MOVIE_RECT`

**Dependents to repoint:**

- `tests/test_p2_adversarial.py` — delete `_load_adversarial_module()` and the
  `spec_from_file_location` shim outright; import from `obed_edom.p2_verdict`. All 18 `p2.*`
  names are covered by the manifest, so the shim can go entirely rather than shrink.
- `scripts/p2_recovery_html_decode_probe.py` — imports `_hash_num` and
  `_score_visible_movie_motion` privately from the other script; repoint at src.
- `scripts/p2_recovery_html_adversarial.py` — imports its own moved names back from src.

Out of scope: the other three by-path test loaders (`test_live_continuity_probe.py`,
`test_live_continuity_js.py`, `test_maps_admin1.py`) target different scripts. Stage 3 territory.

## Retained notes from the moved commentary (2026-09-21 comment-pruning pass)

`src/obed_edom/p2_verdict.py`'s comment count (149/1468, ~10%) was pruned toward the
0-4% neighbour range; most of what was deleted was already redundant with named tests
(each mapping verified before deletion). A few historical/provenance notes had no test
to fall back on and are kept here instead of in source.

**Scene maps and measured Phase-0 values** (were on `SLIDE3_MIN_HASH`/`SLIDE4_MIN_HASH`):
slide 3 begins at hash `#6` (2 + 4 events before it); slide 4's magic-move destination is
`#8`. Full scene map: `s1=#1, s2≈#2-5, s3=#6-7`, the 3->4 moving Magic Move lands slide 4
at `#8` and settles at `#8`/`#9`.

**Burst-cadence rationale** (`BURST_OFFSETS_MS`): the visible-content pass uses
deliberately unequal gaps (130/160/210/270 ms) rather than an evenly spaced burst, so a
periodic two-state animation cannot alias into "static."

**Presentation-lag measurement** (behind tying the freeze control's frozen composite to
`coverPatchMean` rather than the currentTime-derived `staleIndexExpected`): the decoded
composite is compared to the cover's own painted pixels because `staleIndexExpected` runs
ahead of the presented frame by the video's presentation lag — measured at ~9 frames.
Tying the frozen check to the cover's own pixels is lag-immune and proves the composite
actually shows the cover; the decoder staying live (`rvfcRanThroughHold`) separately
proves the counter would have advanced were it not covered.

**Fable consult (2026-09-19)**, `_score_freeze_control`:
- A per-rAF hold-log gap is not disqualifying on the STATIC 1->2 footprint: the cover is a
  `position:fixed` canvas painted once, so a rAF stall — caused by the very CDP screenshots
  that observe the frozen counter — cannot lift it. Observation continuity is proven
  instead by the composite screenshots + `coverPatchStable` + 100% `elementFromPoint`-on-
  cover over the frames that did log + `loopLive`; `maxRafGapMs` is a diagnostic only.
  **Superseded — owned elsewhere, do not duplicate.** The moving 3->4 case IS scoped and
  implemented on branch `feat/p2-freeze-control-3to4`, plan
  `.agents/plans/p2_freeze_control_3to4.plan.md` (SS2 hold/trigger/geometry, SS4 tiers, SS9
  correction, SS10 measurements rounds 4-7), Codex reviews r1-r5 in
  `.agents/reviews/freeze-3to4/`. There the freeze control is re-bracketed at 3->4 with
  per-screenshot attestation: the cover is re-painted and tracked per rAF against the bound
  owner (`coverTracksFootprint`), each screenshot carries an in-page badge encoding the rect
  that produced it (CRC-8 + monotonic seq, `_fill_badge_coupling`), and in the 3->4 scorer
  `maxRafGapOk` (100 ms) is a DISQUALIFYING integrity key rather than a diagnostic. The
  static 1->2 argument recorded above is therefore retired, not open. Confirmed by that
  session 2026-09-21.
- Two verdict tiers, motivated by the same consult: tier-1 hold INTEGRITY (did the control
  actually fire, hold, and get observed) — any failure is INCONCLUSIVE, because a control
  that misfired makes the freeze arm look exactly like a passing positive and would be
  misread as "the gate is vacuous." Tier-2 is the VERDICT proper (did the counter catch the
  freeze, isolated to just the counter) — PASS/FAIL only once tier-1 integrity holds. The
  same consult is also the source of the integrity checks (`firedAfterAdvance`,
  `ownerReadyAtTrigger`, `staleFrameFromPlayback`, `loopLive`, etc.) that implement tier-1.

## SEQUENCING — owner decision 2026-09-21: re-do this work AFTER `feat/p2-freeze-control-3to4` lands

> **Resolved 2026-09-21.** #187 merged; the re-do was started optimistically on main + the freeze branch
> (owner go) and its base proved code-identical to what landed. Kept below as the record of why.

`refactor/gate-verdict-seam` is **parked, not abandoned**, at `70248561` (four code commits +
this doc). All suites were green when parked: pytest 4701 passed / 93 skipped / 2 xfailed,
`test:ui` 186, `test:maps` 536, `test:perf` 2. Nothing is pushed.

**Why it waits.** `feat/p2-freeze-control-3to4` changes the same region and is gate-qualified per
commit, so it cannot be re-verified after a mechanical move without another live Keynote gate
round. This refactor has no live-gate dependency, so it is the cheaper side to move. Measured
overlap against that branch's merge-base (`8f7600f4`):

| File | their branch | this branch |
|---|---|---|
| `scripts/p2_recovery_html_adversarial.py` | 2,208 changed lines | -1,454 (moved to src) |
| `tests/test_p2_adversarial.py` | 1,944 changed lines | shim deleted, header rewritten, 2 tests added |
| `src/obed_edom/html_alpha_probe.py` | 33 | untouched |

Both files this branch changes most are the two that branch changes most. This does not resolve
as a merge; the second one in gets re-done.

**This is a RE-DO, not a rebase.** Their branch rewrites the source region, so the manifest below
is stale the moment they land. Recompute it against their tip.

### How to recompute the manifest (the part that cost this round three corrections)

A call-graph closure is NOT sufficient. Four dependency classes must be closed over, and only the
first is a call edge:

1. **Call edges** — transitive `ast.Call` closure from the names the test file uses.
2. **Def-time free variables** — module-level constants referenced in function bodies. Missing
   these cost 13 constants on the first attempt.
3. **Default-argument values** — e.g. `def _score_visible_movie_motion(..., roi=MOVIE_ROI)`.
4. **Cross-script imports** — names the moved code takes from OTHER scripts. Missing these is what
   made the new src module `sys.path.insert` into `scripts/` and import from it, inverting the very
   dependency this refactor exists to remove. Also missed `MOVIE2_TOKEN`, which `_movie_key`
   branches on but no call edge reveals.

Close over all four to a fixed point, then assert the new module imports with `scripts/` absent
from `sys.path` and pulls in zero driver modules.

### How to prove it behaviour-preserving

Parse the pre-move revision and the new module, and compare each moved definition's source text;
the diff must contain ONLY the intended changes. Separately, `ast.dump` with docstrings stripped
must be identical across a comments-only pass. Both were used this round and both caught real
drift. Keep the mechanical move and any comment pruning in SEPARATE commits so each proof stays
checkable on its own.

**Blind spot, found by Codex on the re-do: both proofs compare statement spans, and comments are not
AST nodes.** Where a moved constant carried a multi-line trailing comment, only its first line moved;
the indented continuation lines stayed behind and read as annotating UNRELATED constants (5 were
stranded; e.g. `DRAIN_PRESS_LAND_S` lost its "at 2.0 s presses went UNLANDED" rationale). The span
proof still passed. Add a third check: for every moved statement, the indented comment-only lines that
followed it in the ORIGINAL must follow it in the new module and appear nowhere in the source. Use the
original file as the authority, never adjacency in the new one — Codex misattributed one by adjacency.

### Carry these forward

- The empty-crop fix (`_score_visible_movie_motion`): drop the caller-side
  `if patch.size == 0: continue`. **Verified 2026-09-21 against `origin/feat/p2-freeze-control-3to4`
  at `de0cedfd`:** their only change mentioning this function DELETES one call site
  (`visible_motion = _score_visible_movie_motion(mm_paths, MOVIE_ROI)`); the function body is
  untouched, and that session confirmed it will not touch it further. So the fix carries unchanged —
  but note the call-site census shrinks by one, so re-derive the callers rather than reusing this
  round's list.
- `test_live_continuity_fails_closed_on_a_split_cumulative_rewind`, values
  `[10.00, 9.96, 9.92, 10.10]`. Verified load-bearing: with the running-max rule replaced by an
  adjacent-delta check this test fails while the pre-existing regression test still passes.
- The comment-pruning pass and the "Retained notes" section above.

### TRIGGER — how to know the park is over, without relying on a ping

> **Fired 2026-09-21** (#187 merged). Kept as a reusable pattern for any future park.

The owner arranged (2026-09-21) for the freeze-control session to ping when its work lands. Do NOT
depend on that: the session holding this context will probably be gone by then, and a ping into a
dead session is lost. Detect the condition directly instead.

The park ends when the freeze-control work is on `main`. Check:

```bash
git fetch origin
# has their work landed? (branch merged, or its scorer changes present on main)
git log --oneline origin/main | head -20
git branch -r --contains de0cedfd            # de0cedfd was their tip on 2026-09-21
grep -c coverTracksFootprint scripts/p2_recovery_html_adversarial.py   # >0 on main => landed
```

If `coverTracksFootprint` appears in that script on `origin/main`, their work landed and the re-do
starts. If it does not, the park still holds — do not merge or rebase this branch in the meantime.

First three steps of the re-do, in order:

1. `git fetch origin && git log --oneline -1 origin/main` — confirm their work is in.
2. Recompute the manifest against the NEW `scripts/p2_recovery_html_adversarial.py`, closing over all
   four dependency classes above. Do not reuse this branch's manifest; it is stale by construction.
3. Diff this branch to recover the three artefacts to carry forward (empty-crop fix, the split-rewind
   test, the comment-pruning + retained notes):
   `git diff origin/main...refactor/gate-verdict-seam`

This branch is a reference, not a base. Expect to redo the move and cherry-pick the artefacts, not to
rebase.

## RE-DO DESIGN — owner decision 2026-09-21: split the driver tests out

Dry-running the closure against their branch (tip `bbc7c91a`, round 8) found that on THEIR code,
"move everything the test touches" would move a **browser driver into src**:
`_settle_bound_owner_rect` is `async` and drives Chrome through `ChromeCdp`, and the test calls it
(via its `_settle()` helper). Three injected-JS strings are also read by the test directly.

Only **10 of 231 tests** are involved, in two tight clusters. Owner chose to split them out:

> **As landed (`c0d03487`, not `bbc7c91a`):** the boundary grew to 9 async/driver functions and 6
> injected-JS constants, and 16 tests turned out to reach driver code, not 10 or 12. Detection that only
> matches `p2.<name>` attribute access MISSES tests that reach the driver by other routes — importing a
> script module, mutating `sys.path`, reading a script's source text, spawning a subprocess, or using
> `ChromeCdp` directly. Codex r1 found 3 such tests in the "pure" file. Sweep for every route.

- **Move to `src/obed_edom/p2_verdict.py`:** the closure computed WITH the driver boundary below.
  On `bbc7c91a` that was 49 defs / 40 constants / 2,130 lines — **recompute at landing**, it moves.
- **Driver boundary — stays in the script, never moved:** `_settle_bound_owner_rect`,
  `_read_bound_owner_rect`, `ChromeCdp`, `FOOTPRINT_BADGE_JS`, `NULL_CONTROL_JS`, `SPLIT_EVAL_JS`.
  (`OWNER_SETTLE_POLL_S` / `OWNER_SETTLE_S` fall out with them automatically — only the settle
  driver uses them.)
- **New `tests/test_p2_adversarial_driver.py`** takes the 10 driver tests plus their three helpers
  `_settle`, `_run_badge_js`, `_run_pin_js`, and KEEPS the `spec_from_file_location` loader. It may
  import pure names from `obed_edom.p2_verdict` too.
- **`tests/test_p2_adversarial.py`** (221 tests) imports only from `obed_edom.p2_verdict` and no
  longer executes the driver script at collection. That is stage 2's actual goal, fully met.

The 10 driver tests on `bbc7c91a`:
`test_split_eval_js_is_one_evaluation_with_the_same_shape_in_both_branches`,
`test_split_eval_js_returns_the_same_keys_on_both_branches`, `test_footprint_badge_js_parses`,
`test_null_control_js_parses`, `test_owner_rect_settle_rejects_a_still_moving_hash_7_build`,
`test_owner_rect_settle_accepts_a_stopped_build`,
`test_owner_rect_settle_fails_closed_without_a_bound_owner`,
`test_footprint_badge_js_paints_what_python_decodes`,
`test_footprint_badge_js_rehandoffs_behind_a_fresh_runtime_pin`,
`test_footprint_badge_lands_behind_a_later_runtime_pin_callback`. **Re-derive at landing.**

Watch for: the three moving helpers may depend on OTHER module-level helpers or fixtures that the
pure tests also use. Those must be shared, not silently duplicated into drift.

### The closure tool — `.agents/plans/gate_verdict_seam.manifest_closure.py`

Committed next to this plan so the re-do does not depend on any one session's scratchpad. It closes
over all four dependency classes. **Validated by positive control:** run blind against `origin/main`
(pre-refactor) with `--extra _score_visible_movie_motion`, it reproduces the shipped manifest
EXACTLY — 27 defs, 26 constants, 1,344 lines, the same external imports — i.e. everything that took
three manual correction rounds. Run it at landing:

```bash
python .agents/plans/gate_verdict_seam.manifest_closure.py origin/main \
  --extra _score_visible_movie_motion \
  --stop _settle_bound_owner_rect,_read_bound_owner_rect,ChromeCdp,FOOTPRINT_BADGE_JS,NULL_CONTROL_JS,SPLIT_EVAL_JS
```

Re-check the driver boundary against the landed code first: list every `async` def and every
`ChromeCdp` user reachable from the seed, and add any new one to `--stop`.
