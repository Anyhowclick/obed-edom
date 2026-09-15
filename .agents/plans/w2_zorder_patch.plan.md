## Status (2026-09-15)

Pieces 1-3 of this plan landed on `feat/w2-zorder` (commits `6c7c10e`, `a4ad76c`,
`1adb4e4`), each with a Codex review verdict. Piece 4 (`scripts/offline_write_ab.py`
A/B extension for z-order, plus two isolated follow-ups) shipped separately as
PR #126 by another agent. `OBED_ZORDER_WRITE` defaults to `off` until the live gate
(see "Gates" below) goes green. Owner decisions taken 2026-09-15: the extra Keynote
open for post-patch export (R2) is accepted; badges stay in tranche 1 (C6); slide
reuse eligibility is dropped from scope (#124) — since reuse slides are never
addressable, every remaining slide is addressable; the live gate deck/slide set is
RAISE10 slides `40,55,56,109,110` plus `123-128`, and Gold.

---

I have enough evidence. Here is the plan of record.

---

# W2 `w-zorder-patch` — PLAN OF RECORD (corrects `w2-draft-sonnet.md`)

All paths below are relative to the worktree root
`/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster` (HEAD `e2f2e69` on `8bd6197`), except the banked artefacts, which are in the main checkout `/Users/anyhowclick/Desktop/work/obed-edom`.

## Premises verified

| # | Premise | Evidence |
|---|---|---|
| P1 | Pipeline order is copy → plan → `_run_jxa` → `run_offline_write` → `restore_card_stroke_widths` → `_run_stat_finalize` → `restore_source_builds`. | `src/obed_edom/remap_keynote.py:1314, 1389, 1462, 1467, 1531, 1608` |
| P2 | **Pass 2 is one AppleScript session that ends: font sizing → `save` → raises → `save` → EXPORT → `close saving yes`.** The export is *inside* pass 2, *after* the raises. | `src/obed_edom/keynote.py:1526` (`save theDoc`), `:1540-1549` (`obedRaiseSlide`/`obedBadgeSlide`), `:1550-1554` (2nd save), `:1555-1563` (export), `:1564-1567` (close saving yes) |
| P3 | After pass 2 the deck **is closed and saved on disk**, so an offline IWA patch there is physically legal — `restore_source_builds` is itself an offline IWA write at that exact slot. | `remap_keynote.py:734-748` ("Offline IWA write, unconditional … after stat-finalize"), `:1608` |
| P4 | `obedRaiseSlide` raises **`group` kind only**, and drains `_rem` by repeatedly picking the **minimum remaining index** — final stacking = **ascending original group kindIndex**, all targets above all non-targets. | `keynote.py:959-1021`, esp. `:968` (`obedTopReal(…, "group", …)`), `:970-974` (min-scan), `:983` (`group _mn of slide`), `:1002-1006` (decrement arithmetic) |
| P5 | The raise targets are **not** a planner list. They are appended live inside `obedStatJob` from the **signature-resolved** group index `_gi` returned by `obedResolveGroup` — one raise target per successfully-resolved stat job. | `keynote.py:931-934` (`set end of raiseTargets to {sl:slideNo, idx:_gi}`), `:869-929` (`obedResolveGroup`, sig match + `allowFallback` 0/1/2) |
| P6 | The badge raise is a separate, per-slide, **all-or-nothing** pass over planner rows `{kind, index, x, y, w, h}`; it raises members **in list order** (first = plate = bottom of the raised set). | `keynote.py:1262-1283` (`obedBadgeSlide`), `:1199-1261` (`obedRaiseItem`), `:1528-1549` (row emission, `_BADGE_MATCH`) |
| P7 | Badge rows are minted in the planner as `{"kind": …, "index": kind_index + 1}` — a **1-based WALL kindIndex** — plus the item's **planned destination** frame. So they are bridgeable exactly like geometry specs. | `src/obed_edom/map_remap.py:2490-2491`; rows consumed at `remap_keynote.py:1073, 1091, 1377, 1537` |
| P8 | Both raise phases go through `obedFront`, which clicks `Arrange ▸ Bring to Front` via System Events → **Accessibility**. Any surviving GUI raise keeps the Accessibility dependency. | `keynote.py:1321-1356` (`_keynote_process_tell()` + `click menu item "Bring to Front"`) |
| P9 | `derive_kind_index` assigns kindIndex by walking `drawablesZOrder` (0-based), placeholders omitted; so a reorder invalidates every `(kind, kindIndex)` on that slide. | `src/obed_edom/iwa_kindindex.py:98-125`; SKILL.md:518-521 |
| P10 | `_resolve_positional` = `bridge_kind_index(kind, wall_ki, hide_specs)` then lookup in `comp_by_key[(kind, saved_ki)]`. Bridging is subtractive over same-kind hides with lower index. | `src/obed_edom/iwa_write.py:486-491`, `:159-167` |
| P11 | `patch_deck_geometry` **already exposes an `extra_member_edits` hook documented "e.g. W2 stylesheet/z-order"**, one zip rewrite, per-slide refusal, and raises `ValueError` on member collision with a slide edit. | `iwa_write.py:786-800, 828-833, 880-884` |
| P12 | Offline slide eligibility today = `planned − reuse_slides − donors`, `&= wanted`; refusals are reported per slide. | `src/obed_edom/offline_write.py:74-95`; `run_offline_write` returns `"refused": sorted(...)` at `offline_write.py:751` (region printed above) |
| P13 | `OBED_OFFLINE_WRITE` **defaults to `on`** now (W1 default flip), unknown tokens → `on`, forced `off` without `as_geometry_enabled()`. | `remap_keynote.py:85-96` |
| P14 | `remap_and_inspect` already exports as a **fallback when pass 2 did not**: `if export_dir and not info.get("exported"): export_slide_images(...)`. | `remap_keynote.py:1720-1724`; `info["exported"]` sourced from `child_resize_result["exported"]` at `:1633`; export-fold contract locked by `tests/test_export_fold.py` |
| P15 | `inspect.export_slide_images` opens, exports, and **`close theDoc saving no`** — an export pass cannot re-scramble the deck on disk. | `src/obed_edom/inspect.py:33-36, 55-78, 143-148` |
| P16 | Probe `99771bf` is real and its shipped form *is* `scripts/probe_zorder_patch.py` + `tests/test_probe_zorder_patch.py`. `permute_front_within` is a **rotation** used to make the live canary's render change; it is not a raise-to-front. | main checkout `git show --stat 99771bf`; `scripts/probe_zorder_patch.py:44-56` |
| P17 | The banked SAME_ORDER method is **full `drawablesZOrder` id-list equality per output ordinal** across two decks. | `output/bank/2026-09-11/badge-retry/zorder_compare.py:61-67` |
| P18 | **On RAISE10, z-order is run-to-run reproducible**: `zorder_compare.py` run1 vs run2/run3/ctrl1/ctrl2/ctrl3 gave `SAME_ORDER=yes` on all 7 ordinals, 5/5 comparisons. | `output/bank/2026-09-11/badge-retry/results.md`, "Offline z-order oracle" |

---

## Corrections to the draft

**C1 — The chosen pipeline slot is wrong, and fatally so: pass 2 exports after the raises.**
The draft places the z-order patch after `_run_stat_finalize` and stops there. Per P2, `_run_stat_finalize` exports the previews at `keynote.py:1555-1563`, *inside* the same session, after the raises. So the draft's arm B ships a deck whose bytes carry the new z-order and a preview set rendered from the **old** z-order. That is exactly failure mode (a) in the brief, and it silently invalidates the A/B gate's pixel comparison — the gate would compare A's real render against B's stale render and report a spurious diff (or, worse, a spurious *match* on slides where the raise was a no-op). The slot is salvageable, but only with an explicit export move (see Pipeline order).

**C2 — "an IWA patch needs the deck closed" is satisfied post-pass-2; the draft never established it.**
P3: `restore_source_builds` is already an offline IWA write at that exact slot and has shipped since PR #59. So option (c) "is fine" holds for the *patch*; only the *export* is the problem. The draft asserted the slot was safe without citing this, and would have been right by accident.

**C3 — Raise targets do not come from the plan; they are live sig-resolved.**
The draft says targets are `plan_out["badgeRaises"]` / `(kind, kindIndex)` "computed against the plan's own transform state". P5: stat raise targets are appended inside `obedStatJob` from `obedResolveGroup`'s result, which matches a **child signature** against `obedSlideSigs` and may take a `sigFallback`/`sigTwin` branch. The planner's `groupIndex` (`gi`, 1-based, already bridged for group hides and voided to 0 on reuse slides by `map_remap.adjust_child_resize_indexes:3148-3180`) is only a *hint*. Consequence: the offline resolver cannot mirror the GUI's resolution exactly; it must resolve from the plan's `groupIndex` + `bridge_kind_index`, and the **set of slides where the two disagree must be excluded from tranche 1** (see Contract, "eligibility").

**C4 — The raise order is ascending-by-kindIndex, not "queued order".**
P4: `obedRaiseSlide` min-scans `_rem` each iteration. The draft's "same relative order they were queued in" is only accidentally true when the plan emits jobs in ascending `gi`. The offline permutation must sort targets by **saved-deck `drawablesZOrder` position**, not by job order. (For badges, P6, it *is* list order — two different rules, and the draft conflated them.)

**C5 — `permute_front_within` is the wrong primitive.**
The draft proposes promoting it as a production function. P16: it *rotates* the back-most member of a subset to the subset's front-most slot, in place, leaving non-subset slots untouched. Production needs the opposite: **remove the target ids from the order and append them at the end (front)**, which moves them past non-targets. Promoting `permute_front_within` would produce a permutation that never raises anything above a non-target — the single most common real case (a stat group buried under the map). Promote `read_zorder` and `reorder_slide_zorder`'s member mechanics; write the ordering primitive fresh.

**C6 — Deferring badge raises to the GUI forfeits the item's stated headline win.**
The plan of record scopes W2 as "replacing 699 GUI clicks + the Accessibility dependency". P8: `obedFront` is the single click path for both phases, so leaving badges on GUI keeps System Events, keeps Accessibility, keeps `OBED_RAISE_SETTLE_MAX`, keeps `frontErr`/`raiseBlind`, and keeps the strict pass-2 bar's whole failure class. And P7 shows the deferral is unnecessary: badge rows are `(kind, wall kindIndex)` + planned frame — the same address shape `_resolve_positional` already handles. The fuzzy `obedBadgeFind` re-probe exists because the *live* index can be stale after live operations; offline, against the saved deck, `derive_kind_index` is exact and positions are irrelevant. **Badge raises are in tranche 1.** The honest win statement: tranche 1 removes Accessibility from the *remap* path only for decks whose eligible slides are 100 % of their raise-bearing slides; any slide that hard-misses falls back to GUI and re-arms Accessibility for the whole run. State this in the run log.

**C7 — "default off / unknown tokens fall back to on" was flagged as a subtlety; it is simply the shipped W1 behaviour and the default is now `on`.**
P13. `OBED_OFFLINE_WRITE` default is `on` since the W1 default flip (`8bd6197`'s ancestry, PR #119 region). W2's knob should mirror the *mechanism* but ship **default `off`** until the live gate is green — that is a deliberate difference, not a copy.

**C8 — The Keynote-scrambling caveat is real on Gold but empirically false on RAISE10.**
P18: six RAISE10 runs (3 treatment + 3 control, same code, same deck, days-stable source) gave `SAME_ORDER=yes` on 7/7 ordinals in all 5 comparisons. So on the gate deck the brief names, a same-code A-vs-A control **is** valid and should be run as a control, and A-vs-B differences on RAISE10 are attributable. The 2026-09-04 scrambling evidence is from the **Gold** deck. The draft generalised the Gold caveat to all decks and would have thrown away the strongest available control.

**C9 — The `extra_member_edits` hook already exists and the draft missed it.**
P11. It is not needed for the chosen slot (the z-order write is a separate, later rewrite than the geometry write, so there is no member collision), but it is the documented W2 affordance and its docstring should be updated rather than left claiming a use we did not take.

**C10 — `ownedDrawables` is not "unmeasured".**
SKILL.md:548 says it is unmeasured whether the *lighter* (`drawablesZOrder`-only) write opens cleanly. The both-arrays write is measured (P16, live pass). The draft inverted the risk framing. Keep both; do not spend the live window on the lighter variant.

**C11 — Slide eligibility: "non-refused pass-1 write" is necessary but the draft gave no mechanism.**
`run_offline_write` returns `refused` (P12); the value is available as `offline_write_info` at `remap_keynote.py:1462` and still in scope at `:1608`.

---

## Contract

**What the GUI raise produces today (the behaviour W2 must reproduce byte-for-byte in effect):**

For each slide `s`, in this order:

1. **Stat raises** — the set `T_stat(s)` of `group`-kind drawables that `obedStatJob` successfully resolved on `s`, moved to the front of the slide's stack, **ordered ascending by their pre-raise `group` kindIndex**. Targets end above every non-target; their relative order among themselves is preserved (P4).
2. **Badge raises** — the rows `B(s)` from `plan_out["badgeRaises"]`, moved to the front **in row order**, so the last row is frontmost and row 1 (the plate) is the bottom of the badge block (P6). Because badges run after stat raises in the same session, **the badge block ends above the stat block**.
3. Partial-slide behaviour is already tolerated: stat raises abandon the rest of a slide on `raiseUnknown` (`keynote.py:1017-1019`); badges are all-or-nothing per slide (`keynote.py:1270-1276`).

**Offline equivalent, per eligible slide `s`, applied to the post-pass-2 saved deck:**

```
new_order = [id for id in z if id not in R] + sorted(T_stat, key=z.index) + [id for id in B_ids]
```
where `z` = the slide's current `drawablesZOrder`, `R` = `T_stat ∪ B_ids`, and `B_ids` is in planner row order. Write `new_order` to **both** `drawablesZOrder` and `ownedDrawables` (identical lists — C10).

Note this is strictly *stronger* than the GUI: it is atomic, order-exact, and immune to the `raiseDead`/`raiseUnknown`/`raiseVacuous` classes entirely. It also happens to repair Keynote's own save-time scrambling **for the target ids**; it does **not** fix scrambling among non-targets, and W2 must not claim to (D7).

**Id resolution.** Targets are resolved against **the saved deck on disk after pass 1's offline geometry write** (i.e. immediately after `run_offline_write` returns, `remap_keynote.py:1462`), using `derive_kind_index(slide, objects)` (P9) and `bridge_kind_index(kind, wall_ki, hide_specs)` (P10) — exactly `_resolve_positional`'s pair, reused, not reimplemented. Index bases: planner badge `index` is **1-based wall**; planner stat `groupIndex` is **1-based, already hide-bridged** by `adjust_child_resize_indexes`; `derive_kind_index` is **0-based post-hide**. Every off-by-one here is a silent mis-raise; the conversion belongs in one function with a table-driven unit test.

**Eligibility (tranche 1).** A slide `s` is eligible iff **all** of:
- `s ∈ offline_slides` (so `s ∉ reuse_slides`, `s ∉ donors` — P12; reuse ids are minted by `applyReuse` paste and are not addressable at plan time, and `adjust_child_resize_indexes` voids their `groupIndex` to 0);
- `s ∉ offline_write_info["refused"]`;
- every `T_stat(s)` and `B(s)` target resolves to exactly one archive id, **and** the resolved stat ids equal what the plan's `groupIndex` predicts with no ambiguity (C3): refuse the slide if the slide has any stat job whose `(slide, childSig)` count > 1, i.e. any job that would take the `sigFallback`/`sigTwin` branch. Those slides stay on GUI in tranche 1.

Reuse slides therefore keep their GUI raises, and Accessibility stays required for any run that contains them (C6).

---

## Pipeline order

**Chosen: (ii) — patch after pass 2, and move the export out of pass 2.**

```
… → run_offline_write (pass 1, offline geometry)          remap_keynote.py:1462
  → resolve raise targets to archive ids on the saved deck  [NEW: eligibility only]
  → restore_card_stroke_widths                              :1467
  → _run_stat_finalize(..., export_dir=None if zorder_on)   :1531   ← font sizing, dedup; raises SUPPRESSED on eligible slides
  → run_offline_zorder(dest, …)                             [NEW, before :1608]
  → restore_source_builds                                   :1608   ← still LAST
  → (return) remap_and_inspect exports via its EXISTING fallback     :1720-1724
```

Why this is provable:

- **Font sizing keeps a coherent kindIndex snapshot.** Every stat job is `(slide, childSig, gi)`-addressed and runs before any reorder, so the plan-of-record line "must run after pass 2's font sizing (**or** recompute stat indices)" is satisfied by the first branch, at zero cost. No index recomputation anywhere.
- **The export problem is solved with code that already exists and is already tested.** P14: setting `export_dir=None` on the pass-2 call makes `child_resize_result["exported"]` False, and `remap_and_inspect`'s existing `if export_dir and not info.get("exported")` branch runs `export_slide_images` *after* `remap_keynote` returns — i.e. after the z-order patch. No new export code, no new AppleScript. P15: that exporter `close`s `saving no`, so it cannot re-scramble or re-save over the patch. Cost: **one extra Keynote open + export**, which is a deliberate, knob-gated partial revert of R0.4's export fold; `tests/test_export_fold.py` must gain a case asserting the fold is retained when `OBED_ZORDER_WRITE=off` and released when `on`.
- **`restore_source_builds` still runs last**, satisfying the standing constraint stated twice (`w-zorder-patch` and `w1-build-order-nondeterminism`: "must keep running LAST, after any future W2 z-order write"). No data dependency: it addresses `builds`/`buildChunks`/`transition` by archive id on **reuse slides only**, which are excluded from W2 eligibility — the two writes are disjoint in both field and slide set.

**Rejected (i): patch between pass 1 and pass 2, re-addressing pass-2 stat jobs via the bridged kindIndex.**
`bridge_kind_index` bridges *deleteHides*, not a reorder — it is a subtraction over deleted same-kind items (`iwa_write.py:159-167`) and has no representation for a permutation. Re-addressing would require a genuinely new bridge computing post-permutation kindIndex for every stat job, and then pass 2's `obedResolveGroup` would *still* re-resolve by signature and could disagree (P5). Worse, pass 2 ends in `close theDoc saving yes` (P2) and Keynote is known to permute `drawablesZOrder` on save — so the offline order would be written, then handed back to the exact mechanism the item exists to defeat. Rejected on both correctness and purpose.

**Rejected (ii-b): patch after pass 2 and add a brand-new re-export AppleScript pass.**
Strictly dominated by the chosen variant, which reuses `remap_and_inspect`'s existing, tested fallback. Rejected as redundant code.

**Rejected (iii): move the font sizing offline too.**
Out of scope. Stat font sizing writes character-level `size` on leaves through `_stat_leaf_font_writes` (`keynote.py:940-950`); SKILL.md's offline-write rules cover geometry, stroke widths, and builds — text style writes are explicitly not in the proven set, and `w-offline-write-stabilise` records that text `naturalSize` staleness is the class that already produced a severe regression. Rejected; would swallow the whole live window.

---

## Design

New module `src/obed_edom/iwa_zorder.py` (keeps `iwa_write.py` from growing a third concern; imports its private mechanics):

```python
def raise_to_front(order: list[str], targets: list[str]) -> list[str]:
    """Remove `targets` from `order` and append them, in `targets` order, at the front
    (= END of drawablesZOrder). Pure. Ids not in `order` raise ValueError."""

def resolve_raise_targets(
    slide: dict, objects: dict[str, dict],
    stat_jobs: list[dict],          # plan `statJobs` rows for this slide (1-based, hide-bridged gi)
    badge_rows: list[dict],         # plan `badgeRaises` rows for this slide (1-based WALL index)
    hide_specs: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    """-> (stat_ids ascending by z-position, badge_ids in row order, unresolved tokens)."""

def plan_slide_order(
    slide: dict, objects: dict[str, dict], stat_ids: list[str], badge_ids: list[str]
) -> list[str]:
    """The Contract formula. stat block then badge block, both at the front."""

def patch_deck_zorder(deck: Path, orders_by_slide: dict[int, list[str]]) -> dict[int, PatchResult]:
    """ONE zip rewrite. Per-slide refusal (member left byte-identical) on: slide member !=
    drawables' member; id set/length mismatch vs current drawablesZOrder; ownedDrawables
    not a permutation of drawablesZOrder; member shared with another patched slide.
    Writes drawablesZOrder AND ownedDrawables identically. Reuses iwa_write._patch_member /
    _rewrite_members / PatchResult, and inherits their value_clean (obj_diffs <= len(edits),
    header_diffs == 0) and OfflineWriteCorrupted semantics."""
```

`iwa_write.read_slide_zorder(deck, slide_number)` — promotion of `probe_zorder_patch.read_zorder` verbatim; `scripts/probe_zorder_patch.py` imports it and keeps `permute_front`/`permute_front_within` **as probe-only rotations** with a docstring line saying they are NOT the production primitive (C5).

New orchestration in `src/obed_edom/offline_write.py`:

```python
def zorder_eligible_slides(dest, mode, offline_slides, refused, stat_jobs, badge_rows, transform_dicts, say) -> dict[int, dict]
    # one deck decode, right after run_offline_write; returns {slide: {"stat":[ids],"badge":[ids]}}
def run_offline_zorder(dest, mode, targets_by_slide, say) -> dict[str, Any] | None
    # re-reads the POST-pass-2 order, rebuilds each slide's order by id, patches, read-back verifies
```

**Env knob.** `OBED_ZORDER_WRITE` = `off` (**default, tranche 1**) | `on` | `verify`, mirroring `offline_write_mode`'s shape (`remap_keynote.py:85-96`), including `probe_iwa_extra` forcing `off` without `keynote_parser`. Additionally forced `off` when `offline_write_mode()` is `off` (no eligible slides by construction). `verify` = `on` + a second deck decode asserting the read-back.

**Read-back verify** (always, not just `verify`): after the patch, re-read each patched slide and assert (a) the id multiset is unchanged, (b) `ownedDrawables == drawablesZOrder`, (c) the target ids occupy the final `|T|` slots in the intended order. Per the plan's "compares reordered kinds AS A SET", the *kind-level* assertion is set-equality per kind; the id-level assertion above is strictly stronger and is what we actually check. A failed read-back raises (the deck is already written; a silent pass is the worse outcome).

**Counters** (in the result dict and on a new `Stat zorder detail:` line, parallel to `_say_stat_finalize_detail` at `remap_keynote.py:878-895`):
`zorderSlides`, `zorderStatRaised`, `zorderBadgeRaised`, `zorderNoop` (target already frontmost — the offline analogue of `raiseVacuous`), `zorderUnresolved(s=,k=,i=)`, `zorderRefused(s=,reason=)`, `zorderGui` (slides that fell back), `zorderLost(s=,id=)` (an id resolved pre-pass-2 that vanished post-pass-2 — must be 0 on non-reuse slides; WARN loudly).
No token may contain the literal `" exported="` (SKILL.md:309-320 — both parsers cut there).

**Suppression / mutual exclusion.** A slide's raises run **exactly once**: offline or GUI, never both, never neither. Mechanism: `zorder_eligible_slides` runs *before* `_run_stat_finalize`, and its keys are passed in as a new `suppress_raises: set[int]` argument to `_run_stat_finalize`/`_build_stat_finalize_script`, which (a) skips `my obedRaiseSlide(<slide>)` emission at `keynote.py:1541-1542` and (b) skips the `obedBadgeSlide` emission at `:1544-1549` for those slides. Font sizing, dedup, and `raiseTargets` accumulation are untouched — `obedStatJob` may keep appending targets; if the slide is never passed to `obedRaiseSlide` they are simply never drained. **Do not** try to suppress inside `obedStatJob`; that couples the font path to W2.

**Fallback.** All-or-nothing per slide, matching `obedBadgeSlide`'s existing shape (P6): if any target on a slide fails to resolve, or the slide's member refuses, that slide is **not** added to `suppress_raises` and its full GUI raise runs unchanged. Because eligibility is computed before pass 2, there is no post-hoc unwind. The only residual hole is `zorderLost` (an id present pre-pass-2 and gone post-pass-2); on non-reuse slides nothing deletes objects, so this is a WARN + slide-level refuse, not a design case.

Eligibility (`zorder_eligible_slides`) does not stop at id resolution: on the post-pass-1 saved deck it also runs the exact validation `patch_deck_zorder` would run on each candidate slide's order — member resolution, `ownedDrawables` permutation, requested-order id-set permutation, and member collision across the candidate set (`validate_slide_order`/`_zorder_slide_edit`, shared with `patch_deck_zorder` so there is only one code path for "would this slide refuse"). A slide failing any of these checks is never added to `suppress_raises` in the first place — it stays on GUI, exactly like an unresolved id. This makes the post-pass-2 refusal path in `run_offline_zorder` a should-never-happen: every slide it is asked to patch has already passed the same checks once. If pass 2 nonetheless changes something eligibility could not see (an id in `targets_by_slide` refused or lost post-pass-2), `run_offline_zorder` finishes patching every other slide, emits the `Stat zorder detail:`/`zorderLost` tokens, and then raises `RuntimeError` naming the affected slide(s) — never a silent unraised slide, because their GUI raise was already suppressed and there is no post-hoc GUI fallback once pass 2 has run. `remap_keynote` applies the same rule one step earlier: if pass 2 (`_run_stat_finalize`) itself does not report `ok`, the deck may still be open in Keynote, so the offline z-order patch is skipped entirely and the same `RuntimeError` is raised for the suppressed slides rather than attempting a patch against a possibly-open document.

---

## Pieces (4, sonnet-sized, each independently mergeable, each with a Keynote-free gate)

**Piece 1 — pure primitives + the promoted reader.** *(A fresh sonnet can start here from this document alone.)*
- Add `src/obed_edom/iwa_zorder.py` with `raise_to_front`, `resolve_raise_targets`, `plan_slide_order` (pure; no zip, no deck write).
- Move `read_zorder` → `iwa_write.read_slide_zorder`; `scripts/probe_zorder_patch.py` imports it; add the C5 docstring warning to `permute_front_within`.
- Index-base conversion lives in `resolve_raise_targets` and nowhere else: stat `groupIndex` (1-based, hide-bridged) → 0-based, no further bridging; badge `index` (1-based **wall**) → `bridge_kind_index(kind, index-1, hide_specs)`.
- Tests (new `tests/test_iwa_zorder.py`, fixtures `_arch`/`_member`/`_shape_super` from `tests/test_iwa_write.py` as `tests/test_probe_zorder_patch.py:1-30` already does): `raise_to_front` with targets already frontmost (no-op), targets interleaved with non-targets, targets spanning the whole array, single target, empty targets, unknown id → `ValueError`; `resolve_raise_targets` with a group hide below and above the target (bridge on/off), a badge row of each kind, a slide with a shape/text dual (`derive_kind_index`'s `duplicateOf`, `iwa_kindindex.py:120-122`), an unresolvable row; `plan_slide_order` asserting badge block ends above stat block.
- Gate: `pytest tests/test_iwa_zorder.py tests/test_probe_zorder_patch.py`; no plan-shape change, so `scripts/golden_plan.py` must be **unchanged** — assert that.

**Piece 2 — `patch_deck_zorder` + read-back.**
- Implement the writer against `iwa_write`'s `_patch_member`/`_rewrite_members`/`PatchResult`; update `patch_deck_geometry`'s `extra_member_edits` docstring (C9) to point at this function.
- Tests: single-slide patch → order honoured on re-read, `value_clean` True; two slides in one rewrite; two slides sharing a member → later refuses; id set mismatch → refuse, deck byte-identical; `ownedDrawables` divergent from `drawablesZOrder` → refuse; read-back verify failure path raises; simulated rewrite exception leaves the deck untouched.
- Gate: Keynote-free pytest only.

**Piece 3 — wiring, knob, suppression.**
- `zorder_write_mode()` in `remap_keynote.py` next to `offline_write_mode`; `zorder_eligible_slides` + `run_offline_zorder` in `offline_write.py`; call sites at `remap_keynote.py` ~1465 (eligibility), ~1531 (`export_dir=None` when on; `suppress_raises=` new arg), ~1607 (patch, before `restore_source_builds`); counters + `Stat zorder detail:` line.
- Tests: `_build_stat_finalize_script` emits no `obedRaiseSlide`/`obedBadgeSlide` for suppressed slides and is otherwise character-identical (string assertion); mutual exclusion (every raise-bearing slide appears in exactly one of the two sets); `export_dir` threading — pass 2 gets `None` iff the knob is on; `tests/test_export_fold.py` gains the knob-on/knob-off fold cases; knob parse table (`""`→off, `on`, `verify`, `garbage`→off, forced off without the iwa extra, forced off when `OBED_OFFLINE_WRITE=off`).
- Gate: `scripts/golden_plan.py` re-run — the plan dict gains no key when the knob is off, so the SHA-256 must be **unchanged at default**; that is the piece's headline assertion.

**Piece 4 — A/B gate extension.**
- Extend `scripts/offline_write_ab.py`: arm A = `OBED_ZORDER_WRITE=off`, arm B = `on`, both with `OBED_OFFLINE_WRITE` at the run's mode. Add a per-slide z-order verdict reusing `zorder_compare.py`'s method (P17) in two forms: `SAME_ORDER` (full id-list equality — the A-vs-A control metric) and `FRONT_BLOCK_OK` (A vs B: the target ids occupy the final `|T|` slots in the same order in both arms). Surface the new counters in the run record and summary.
- Document C8 in the gate's docstring: on RAISE10 a same-code A-vs-A control **is** valid (P18) and must be run; on Gold it is not, and only same-run A-vs-B is meaningful there.
- Tests: pure comparison-logic tests on synthetic order lists, mirroring `tests/test_offline_write_ab_slides.py`'s style; Keynote-free.

---

## Gates

**Keynote-free (every piece):** the piece's own pytest, plus `scripts/golden_plan.py` unchanged-at-default (piece 3 onward), plus `scripts/probe_zorder_patch.py` (pure mode) still exits 0.

**One live window (the only one budgeted before the 2026-09-19/20 owner deadline):**
`scripts/offline_write_ab.py` on **RAISE10**, `--slides 47,82,113 --pass2-bar strict`, plus the **Gold** deck, under the standing protocol (SKILL.md:296-320): unlocked working copy, Accessibility granted, refuse any already-open Keynote document, serial, quit Keynote between arms, `--mode verify --no-validate` on the Full-style deck.

Bar, per slide, on both decks:
1. `FRONT_BLOCK_OK` = yes for every eligible slide.
2. A-vs-B preview pixel diff = 0 on every eligible slide *that A raised correctly* (`raiseDead`/`raiseUnknown` empty for that slide in A). Non-zero diff on a slide where A had a dead raise is a **B win**, to be recorded as such, not as a failure.
3. Arm B: `zorderRefused`/`zorderUnresolved`/`zorderLost` all 0 on eligible slides; `zorderGui` = the reuse/ineligible set and nothing else.
4. Arm B pass-2 log: no `raiseDead`/`raiseUnknown`/`frontErr` token for any suppressed slide (they must not even be attempted).
5. Arm A run twice on RAISE10 as the control: `SAME_ORDER=yes` on all target ordinals (reproducing P18). If this control fails, the deck has started scrambling and the A-vs-B verdict for that run is void.
6. `restore_source_builds` unchanged: reuse slides' `buildChunks` order identical between arms.

---

## Risks

- **R1 (highest) — index-base confusion.** Three bases in play (1-based wall badge, 1-based hide-bridged stat, 0-based post-hide `derive_kind_index`). A silent off-by-one raises the wrong object and looks like a successful patch. Mitigated by concentrating the conversion in `resolve_raise_targets` with table-driven tests and by refusing any slide with ambiguous stat signatures.
- **R2 — the second Keynote open.** The chosen slot re-opens the deck to export, costing one open + one export on a ~6.7 GB deck (the R0.4 fold measured export 6.56 → 4.38 s on a 9-slide deck; on RAISE10 expect minutes). This partially undoes R0.4's "one Keynote open instead of two" for knob-on runs only. Named cost, not a defect; it is the price of correct previews (C1).
- **R3 — badge frames are not used offline.** Badge rows carry the planned frame purely for the live fuzzy probe; offline we ignore them. If the planner's `index` is ever wrong in a way the fuzzy probe was silently correcting, W2 will raise the wrong object where the GUI raised the right one. `badgeProbeUnknown(s=8,k=shape)` fires on all six banked RAISE10 runs (`results.md`) — evidence that the badge probe is already blind on at least one slide, so this is a live hazard, not theoretical. Mitigation: the A/B pixel diff on badge slides is the detector; slide 8's known blind spot should be in the `--slides` selection if the owner will allow it.
- **R4 — W2 does not fix non-target scrambling.** The 2026-09-04 Gold symptom (banner text hidden, "Global Missions" clipped to "Glob") was Keynote scrambling `drawablesZOrder` among objects we never raise. W2 pins the raised set only. If the owner expects W2 to close that symptom, it will not — and the plan item's own D7 text says the two must not be conflated.
- **R5 — partial Accessibility removal.** Any run containing a reuse slide with raises keeps GUI raises and therefore Accessibility (C6). The run log must say which.
- **R6 — `ownedDrawables` semantics under a *partial* rewrite.** We overwrite both arrays wholesale with the same list, as the probe did. If a real wall slide ever has `ownedDrawables ≠ drawablesZOrder` as a *set* (e.g. an object owned but not in z-order), the wholesale write would drop it. Piece 2 refuses on exactly that condition rather than guessing — but it means some real slides may refuse in the live gate, and the refusal reason must be inspected, not waved through.

---

## Open questions for the owner (only these change the design)

1. **Is one extra Keynote open + preview export per knob-on run acceptable?** (R2.) If not, the only alternatives are rejected option (i) or shipping stale previews; the design would have to change materially, so this needs an answer before piece 3.
2. **Badge raises in tranche 1: confirm yes.** The plan assumes yes (C6) because deferring them forfeits the Accessibility win. If the owner wants them deferred, say so now — piece 1's `resolve_raise_targets` shrinks and the live gate's success criterion must be restated as "speed only, Accessibility retained".
3. **Are `47,82,113` the right RAISE10 slides for the one live window?** They must include at least one slide with ≥2 stat raises (to exercise the ascending-order rule, C4) and one badge slide; the banked evidence is for `8,40,55,56,106,109,110`, where s=55 carries the badge `raiseVacuous`/`-1719` history and s=8 the `badgeProbeUnknown` blind spot (R3). If `47,82,113` lack a multi-raise slide, the gate cannot distinguish C4 from a no-op.

### Critical Files for Implementation

- `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster/src/obed_edom/keynote.py` (raise contract `:959-1021`, `:1199-1283`, `:1321-1356`; pass-2 script assembly and the export/close tail `:1526-1572`)
- `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster/src/obed_edom/remap_keynote.py` (pipeline `:1462-1608`, env-knob pattern `:85-96`, export fallback `:1720-1724`)
- `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster/src/obed_edom/iwa_write.py` (`bridge_kind_index:159`, `_resolve_positional:486`, `patch_deck_geometry:786` incl. `extra_member_edits`, `_patch_member:672`, `_rewrite_members:739`)
- `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster/src/obed_edom/offline_write.py` (`_offline_write_slides:74`, `run_offline_write:638` and its `refused` payload)
- `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-skills-memory-review-b2c054/6dc86713-7d15-40f7-8429-796b9f0583a5/scratchpad/wt-roster/scripts/probe_zorder_patch.py` (member-rewrite mechanics to promote; `permute_front_within` is probe-only)