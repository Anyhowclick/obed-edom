---
name: Gate verdict seam — pure verdict logic out of scripts/
overview: >-
  Architecture-review candidate 1. Stages 1+2 landed in #191: the P2 verdict layer lives in
  `src/obed_edom/p2_verdict.py`, `tests/test_p2_adversarial.py` imports only from src and the
  driver-reaching tests sit in `tests/test_p2_adversarial_driver.py`. Open: stage 3 (the same seam
  for the remaining gate scripts) and the backlog below. Stage 1+2 history:
  `git show 0f0a70aa:.agents/plans/gate_verdict_seam.plan.md`.
todos:
  - id: s3-remaining-gates
    content: >-
      Apply the same seam to live_continuity_probe.py, write_gate_ab.py and offline_write_ab.py
      once the stage-1/2 pattern has been reviewed. Not scoped until then.
    status: pending
---

# Gate verdict seam

## Standing owner decisions (2026-09-21)

1. **Placement** — flat `src/obed_edom/p2_verdict.py`. A `gates/` package is deferred; revisit
   only if stage 3 happens.
2. **`sceneHash` pre-filter** — leave it alone. `_capture_1to2_snapshot` drops frames whose
   sceneHash is None before `score_motion_across_flip`, shrinking the window. It looks deliberate;
   do not change it without separate evidence.
3. **Docstring hygiene** in `p2_verdict.py` (Codex Standards 2) is deferred: "correctness first".

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
  implemented and merged in PR #187 (branch `feat/p2-freeze-control-3to4`); its plan
  (SS2 hold/trigger/geometry, SS4 tiers, SS9
  correction, SS10 measurements rounds 4-7), Codex reviews r1-r5 (raw rounds pruned
  after merge; in git history). There the freeze control is re-bracketed at 3->4 with
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

## Stage 3 method (learned on stages 1+2)

A move lands with **no test assertion added, removed or changed** except new coverage the plan names.
Keep the mechanical move and any comment pruning in SEPARATE commits so each proof stays checkable.

**Driver boundary.** Browser/CDP/async entry points and injected-JS strings stay in the script and are
passed to the closure tool as `--stop`. Tests that reach driver code move to a separate driver test
file that keeps the by-path loader. Detection that only matches `p2.<name>` attribute access MISSES
tests that reach the driver by other routes — importing a script module, mutating `sys.path`, reading
a script's source text, spawning a subprocess, or using `ChromeCdp` directly. Sweep for every route.

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

## Backlog (from the 2026-09-21 seams handover, deleted; `git show 6fc85b78:.agents/handovers/codebase-architecture-seams-2026-09-21.md`)

### `replay_round` has no test (Codex r1, open)

- **Symptom.** Nothing exercises `scripts/replay_live_verify.py::replay_round`, so a call-site drift
  there can pass the whole suite — which is exactly how the drift fixed in `245403ab` survived.
- **Evidence.** Codex r1 finding 6. `live_verify` and `live_verify_routing` are now unit-tested; the
  script's own wiring is not.

### Deferred from #191, not bugs

- Codex Standards 2: verbose, history-laden docstrings in `src/obed_edom/p2_verdict.py` (e.g.
  `_derive_movie_texids`). Hygiene only — deferred by the owner, "correctness first".
- Stage 3: the same seam for `live_continuity_probe.py`, `write_gate_ab.py`, `offline_write_ab.py` and
  their by-path test loaders. Not scoped.

### Architecture review — the candidates NOT taken

A full scan produced ten deepening candidates; the #184 round took the top two and the second round
took **candidate 1** (below — done, #191). The HTML report was written to a temp dir and is gone, so the
rest are recorded here. Each was evidenced against real code at the time; re-verify before acting —
candidate 1's own figures were understated by roughly a third when re-measured.

1. **TAKEN — DONE, #191.** **Gate verdicts live in `scripts/`** — ~2,700 lines of pure, fail-closed verdict logic in one-off
   scripts while the pixel scorers they call sit in `src/`; ~4,000 lines of tests load them by file
   path. Already cost one real bug: the P2 gate filters empty crops before a scorer whose interface
   calls them hard rejects, so that fail-closed branch is unreachable from its only caller.
2. **The maps deck rules exist twice**, once per runtime, with no interface between them — 13 rule
   pairs, 12 self-declared "Mirrors …" comments, zero cross-runtime assertions, and two evidenced
   divergences (`slide_hidden_layers` vs `parseHiddenLayers`; `coerce_link_kinds` vs
   `suggestedHopKind`).
3. **The maps document model and its transactional store live inside the HTTP router** —
   ~1,400 of `web/maps.py`'s 2,059 lines are not HTTP; `_COMMIT_HOOK` is a test hook in production
   code; `app ↔ maps` is a cycle broken by a lazy import.
4. **The continuity plan is hand-transcribed into the P2 gate** — the gate does not call
   `to_runtime()`, and the tie-breaking test regex-scrapes a literal out of another test file's source
   and `eval()`s it. The injected plan carries `transparentBackground`, which `to_runtime()` never
   emits, so it cannot match the qualified-plan allowlist.
5. **`export_slide_clips` re-implements `LiveBatch`'s lifecycle** — 21 private imports from
   `dsk_live`, plus nine `public = _private` aliases maintained so other callers need not.
6. **The spec's `w`/`h`-presence rule is re-derived at ~45 sites**, and the two fallback expressions in
   `framing.py` and `map_remap.py` still differ in the `line` arm. The SKILL already names this rule as
   a past crash.
7. **Eight offline post-passes** sequenced by statement order inside a 180-line `try` in
   `dsk_assemble`, nine deck decodes, two dead `warnings` params, and a "reorder must be last" rule
   held only by luck.
8. Duplicated overlap/scene-hash predicates between product and gate; `onExport` as a 507-line runner
   inside a React component; a `remap_keynote` Keynote port (111 monkeypatches stand in for one seam).
