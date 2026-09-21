# Handover — codebase-architecture seams round, state at 2026-09-21 01:30

Owner rules (AGENTS.md wins): accuracy and code quality over speed · plan first for anything complex ·
never weaken a gate · minimal natspec, no inline comments in src (tests may be verbose) · no merge /
auto-merge without an explicit owner request · hands off Keynote. Roster this round: Opus planned and
coordinated, Sonnet implemented in subagents, Codex `gpt-5.6-sol` reviewed.

## Where things are (verified with `gh pr view` / `git log`, 2026-09-21 ~01:30)

| Branch | What | PR |
|---|---|---|
| `main` | carries this round as of `44680a9e` | — |
| `fix/plan-report-and-live-verify-seams` | this round | **#184 MERGED** 2026-09-21 |

Seven commits, `f2c6bdce`..`0b0a4926`. Nothing else from this round is outstanding.

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

### 2. The JXA slide-digest bank for Gold is stale (BLOCKED on owner)

- **Symptom.** `tests/test_golden_plan.py:391` skips: deck digest drift against the banked JXA
  digests.
- **Expected.** The offline kind-index read stays cross-checked against a real Keynote read.
- **Evidence / fix.** `scripts/bank_jxa_slide_digests.py --deck Gold_Wall_Input.key
  --accept-input-drift`. Needs a **real Keynote read** (Gold peaked at 2.29 GB); `Full_Report_Card_Wall.key`
  is deliberately never banked on this machine. Awaiting the owner's go — do not run it unprompted.

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

A full scan produced ten deepening candidates; this round took the top two. The HTML report was written
to a temp dir and is gone, so the rest are recorded here. Each was evidenced against real code at the
time; re-verify before acting.

1. **Gate verdicts live in `scripts/`** — ~2,700 lines of pure, fail-closed verdict logic in one-off
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

## Commands

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
