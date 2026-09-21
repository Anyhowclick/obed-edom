# Handover — codebase-architecture seams, state at 2026-09-21 11:45

Covers TWO rounds: the seams round that merged as #184 (01:30), and a second round the same day
that closed the digest banks (#185) and took architecture candidate 1.

Owner rules (AGENTS.md wins): accuracy and code quality over speed · plan first for anything complex ·
never weaken a gate · minimal natspec, no inline comments in src (tests may be verbose) · no merge /
auto-merge without an explicit owner request · hands off Keynote. Roster this round: Opus planned and
coordinated, Sonnet implemented in subagents, Codex `gpt-5.6-sol` reviewed.

## Where things are (verified with `git log` / `git ls-remote`, 2026-09-21 ~11:45)

| Branch | What | State |
|---|---|---|
| `main` | `0b630e99` | carries both merged rounds |
| `fix/plan-report-and-live-verify-seams` | seams round, 7 commits `f2c6bdce`..`0b0a4926` | **#184 MERGED** |
| `fix/refresh-gold-jxa-banks` | both Gold JXA banks re-banked | **#185 MERGED** |
| `refactor/gate-verdict-seam` | candidate 1, stages 1+2, 7 commits at `988980df` | **pushed, PARKED, no PR** |
| `docs/architecture-seams-handover-2026-09-21` | this document | unpushed |
| `feat/p2-freeze-control-3to4` | ANOTHER session's, remote tip `de0cedfd` | in progress, Codex r5 FAIL open |

`refactor/gate-verdict-seam` has no PR **on purpose** — see SEQUENCING below. Opening one invites an
out-of-order merge.

## What shipped (detail in the commits, not here)

- `f2c6bdce` — **shipped defect.** `remap_keynote` allocated `hidden` for the planner's skipped slide
  NUMBERS, then rebound the same local to the framing rows carrying `excludedOffCanvas`. The operator
  line "Left N skipped slide(s) alone" stringified dicts and never fired unless some slide had
  off-canvas overlays; `skippedSlidesLeftAlone` carried those dicts through `web/app.py` into the
  dashboard API. No dashboard code reads that field, so the cost was the lost operator report.
- `3510abf1` — `plan_payload_transforms` → `plan_payload`, returning a `Plan` dataclass instead of
  mutating nine caller-allocated report bags. Hard cut, no wrapper. 62 call sites, 12 fakes, **no test
  assertion added, removed or changed.**
- `245403ab` + `93c05856` — `offline_write.live_verify` is the one call path for the live-verify
  routing, with `live_verify_routing()` shared by `live_verify` and the replay's partial path.
  Previously the rule was derived at each call site and the two had drifted: the Keynote-free replay
  gated the AppleScript-fallback buckets the real gate deliberately excludes.
- `e110b963` / `01ebd472` / `0b0a4926` — fixture work the above un-masked; see open items.

## Open items — symptom · expected · evidence

### 1. `propose_framings` models two of the planner's four framing arms (OPEN, operator-facing)

- **Symptom.** On a slide the planner frames by reusing a sibling's affine, the dashboard's framing
  proposal shows `autoRects` computed from a fresh `learn_recipe` — a layout the run will not produce.
  The operator pins framing against that preview. Reproduces on `Full_Report_Card_Wall.key` slides 58
  and 93.
- **Expected.** The proposal and the apply plan agree on every slide: what the operator sees is what
  will run.
- **Evidence.** `tests/test_golden_plan.py::test_propose_auto_rects_match_apply_transforms`, currently
  `@pytest.mark.xfail(strict=True)` with the full root cause in its reason string. Planner arms:
  `src/obed_edom/map_remap.py` ~3755-3800 (pinned template · sibling-affine reuse via
  `_recipe_reusing_affine` when `_framing_unusable` · unpinned photo-only backdrop carry ·
  fit-to-frame fallback). Proposer: `src/obed_edom/framing.py` ~485-520 (template trial · fitted
  fallback, plus a hand-inlined copy of the `_framing_unusable` predicate).
- **Pre-existing**, not from this round: reproduced identically at the pre-refactor revision. It had
  been invisible because the test was skipping on golden-fixture digest drift.
- **Constraint.** `.agents/skills/obed-edom/SKILL.md`: "Framing is an editorial decision, not a metric
  problem." The SET of arms must not change, merge or gain a member as part of the fix — the proposer
  comes to agree with the planner, not the reverse. `strict=True` forces the marker's removal when it
  lands.

### 2. The JXA digest banks for Gold were stale — CLOSED, #185 merged 2026-09-21

Owner freed Keynote; both banks re-banked from live reads at deck digest `9e012210` (24 slides, was
19 at `c7f870ed`). **It was TWO banks, not one** — this handover originally named only
`jxa-slide-digests`, but `jxa-kind-counts` was stale on the same digest and skipped at
`test_iwa_kindindex.py:498`. Both bankers refuse `--payload` together with `--accept-input-drift` by
design, and no `reader='jxa'` payload was cached for the current bytes, so each needed its own real
Keynote read.

Facts worth keeping: Gold now peaks **~2.60 GB** (was 2.29 GB at 19 slides), closer to the 3 GB
watchdog default. The source deck was byte-identical across both reads. The instrument was validated
by tampering one banked slide and confirming BOTH tests fail — the cross-checks are live, not
vacuous.

### 3. `replay_round` has no test (Codex r1, open)

- **Symptom.** Nothing exercises `scripts/replay_live_verify.py::replay_round`, so a call-site drift
  there can pass the whole suite — which is exactly how the drift fixed in `245403ab` survived.
- **Evidence.** Codex r1 finding 6. `live_verify` and `live_verify_routing` are now unit-tested; the
  script's own wiring is not.

## Deck numbering moved (2026-09-21) — read before touching a gold oracle

The owner edited `Gold_Wall_Input.key` mid-round: slides inserted, then two removed. Net effect on the
pinned region, established by CONTENT not by guesswork:

| | before | after |
|---|---|---|
| wall pin-continuity block | 14-19 | **12-17** |
| roster keep / drop | `{20,21}` / `{22..26}` | **`{18,19}` / `{20..24}`** |
| 2-name-column roster slide | 23 | **21** |

Every asserted VALUE survived unchanged (`template-layout` vs `sibling-affine`, pairQuality 1, the
`-1111.0/0.0` post-clamp placement, `onCanvas 0.5` / `excluded 13` / `excludedOffCanvas 11`), which is
the evidence the edit was structural. Both goldens were re-baselined with owner approval; the **CG base
template changed too** (`bbb0d1d4` → `975689e1`), which is why `asGeomSha` moves on slides the decks
did not touch.

## Architecture review — the candidates NOT taken

A full scan produced ten deepening candidates; the #184 round took the top two and the second round
took **candidate 1** (below, now parked). The HTML report was written to a temp dir and is gone, so the
rest are recorded here. Each was evidenced against real code at the time; re-verify before acting —
candidate 1's own figures were understated by roughly a third when re-measured.

1. **TAKEN (parked, see SEQUENCING).** **Gate verdicts live in `scripts/`** — ~2,700 lines of pure, fail-closed verdict logic in one-off
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

## Candidate 1 taken — the gate verdict seam (round 2)

`refactor/gate-verdict-seam`, 7 commits at `988980df`, pushed, all suites green when parked:
pytest 4701 passed / 93 skipped / 2 xfailed, `test:ui` 186, `test:maps` 536, `test:perf` 2.

**What it does.** `src/obed_edom/p2_verdict.py` (+1,344) owns the P2 gate verdict layer — 25
top-level functions, 4 nested, 28 constants — moved out of the 4,154-line
`scripts/p2_recovery_html_adversarial.py` (-1,460). Five scripts repointed. The
`spec_from_file_location` shim in `tests/test_p2_adversarial.py` is **deleted outright**, so that
test no longer executes the driver script at collection. `src` imports nothing from `scripts/` and
mutates no `sys.path`.

**The defect it fixes was latent, not active.** The caller-side `if patch.size == 0: continue` made
`score_visible_movie_motion`'s `"empty crop"` hard reject unreachable from its only caller, and
shrank the sequence so a bad ROI read as `"need >=3 frames"` with a wrong `n`. But `MOVIE_ROI` with
`inset=8` slices `arr[803:1055, 117:1053]` and `ChromeCdp` enforces 1920x1080, so it never fired.
Removing it strengthens the gate and moves no verdict. (`EMPTY_CORNERS` does NOT prove the frame
size — `_score_empty` skips empty corner crops. Codex corrected that.)

**Read the plan before restarting** — it carries the manifest, the retained commentary notes, the
re-do recipe and the trigger condition. It lives ONLY on the parked branch, not on `main`, so read it
without checking out:

```bash
git fetch origin
git show origin/refactor/gate-verdict-seam:.agents/plans/gate_verdict_seam.plan.md
```

The re-do does **not** depend on anyone remembering to ping. The plan's TRIGGER section gives a
detectable condition: if `coverTracksFootprint` appears in `scripts/p2_recovery_html_adversarial.py`
on `origin/main`, the freeze-control work has landed and the re-do starts. If it does not, the park
still holds — do not merge or rebase the seam branch in the meantime.

### SEQUENCING — owner decision: RE-DO this after `feat/p2-freeze-control-3to4` lands

Another session owns that branch. It is gate-qualified per commit and cannot be re-verified after a
mechanical move without another live Keynote gate round; this refactor has no live-gate dependency,
so it is the cheaper side to move. Measured overlap against its merge-base `8f7600f4`:

| File | their branch | seam branch |
|---|---|---|
| `scripts/p2_recovery_html_adversarial.py` | 2,208 changed lines | -1,460 |
| `tests/test_p2_adversarial.py` | 1,944 changed lines | shim deleted, 2 tests added |

Both files the seam changes most are the two they change most. It will not resolve as a merge, and
it is a **RE-DO, not a rebase** — their branch rewrites the region, so the manifest is stale the
moment they land. Their Codex r5 is a four-item FAIL with all four open in round 8, so the park may
be long. That session confirmed it will not touch `_score_visible_movie_motion` further (its only
change there deletes one call site), so the empty-crop fix carries — but re-derive the caller census.

### The lesson from this round

**A call-graph closure is not enough to move a module.** Three separate corrections came from
missing: def-time free variables (13 constants), default-argument values, and cross-script imports.
The last made the new `src` module `sys.path.insert` into `scripts/` and import from it — inverting
the exact dependency the refactor existed to remove. Close over all four classes to a fixed point,
then assert the module imports with `scripts/` off `sys.path` and pulls in zero driver modules.

Two proofs that each caught real drift, worth reusing: compare each moved definition's source text
against the pre-move revision (the diff must contain only intended changes), and for a
comments-only pass compare `ast.dump` with docstrings stripped. Keep the mechanical move and any
comment pruning in SEPARATE commits so each proof stays checkable alone.

## Commands

Keynote gotcha found 2026-09-21: **`osascript ... tell application` LAUNCHES Keynote — it is not a
read-only probe.** A document-count query meant to confirm a stray was documentless instead started a
fresh Keynote that truthfully answered "0 documents". `pgrep -x Keynote` first, address the app only
if pgrep says it is up, re-check pgrep after, and quit what you started.

```bash
# venv lives in the MAIN checkout, not a worktree
PYTHONPATH=src /Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python -m pytest tests/ -q
cd dashboard && npm run test:ui && npm run test:maps     # test:maps chains test:perf

# prove a planner change is behaviour-preserving without trusting the committed golden
PYTHONPATH=src .venv/bin/python scripts/golden_plan.py capture --deck Gold_Wall_Input.key --out /tmp/after.json
# ...same from a throwaway worktree at the pre-change revision, then `cmp` the two

# the golden sha tests SKIP on deck/template digest drift -- read the skip counts, not the headline
PYTHONPATH=src .venv/bin/python -m pytest tests/test_golden_plan.py -q -rs
```
