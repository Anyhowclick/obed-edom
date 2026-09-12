# Review — 9b486a8 "hide title/body placeholders instead of deleting them" (+ out-r9b)

Verdict: **APPROVE-WITH-NITS**. The live result on GW 17 is clean — measured, not assumed — but
the fix is *unobservable*: nothing in run.out says whether the hide branch ever fired, and I
could not determine it from the saved deck either (see F1). Land it, but add the marker before
the fix is treated as proven.

## Measurements (offline, read-only)

Output deck slide 3 (= GW 17, slideId 17275487, `KN.SlideArchive`):

| | source `Sermon_PK (GW).key` | output `out-r9b/Sermon_PK_DSK.key` |
|---|---|---|
| ownedDrawables | 17510826, 17275485, 17275486, **17277671**, **17277682**, **17289361**, 17290708, 17290717, 17290734 | **17277671, 17277682, 17289361** (drawablesZOrder identical) |
| titlePlaceholder | 17275509 (`kKindTitlePlaceholder`, **not** in ownedDrawables) | 17275509, same id, geometry re-based to the black layout (753.25,412,413.5×45) |
| bodyPlaceholder | 17275542 (not in ownedDrawables) | 17275542 |

Delete set (derived kindIndex): `shape:1`/`text:3` = **17290708** (the same object — a dual),
`text:4` = 17290717, `text:5` = 17290734, plus images `image:0/1/2`.

## 1. Which survived hidden? — **none**

`17290708 / 17290717 / 17290734` are **absent from the output deck's object table entirely**
(not merely out of ownedDrawables). The surviving `text:0..2` are the *left* (kept) copies:
17277671 "John 17", 17277682 "21 That all of them…", 17289361 "May they also be in Us…".
The title/body placeholders that *do* survive share `ownedStorage` 17275514, whose
`storage_runs` is `[]` in **both** decks — they are the layout's empty placeholders, were never
showing, and hold **no mirrored duplicate text**. So: no hidden box retains mirrored content,
and there is no invisible-but-present duplicate on slide 3.

Corollary worth stating plainly: on this run the hide branch left **no trace**, so the evidence
is equally consistent with "the guard fired and Keynote purged the drawable" and "the guard
never fired at all". That is F1.

## Findings

**F1 (should-fix). The guard emits no marker — the fix cannot be verified from evidence.**
`src/obed_edom/dsk_assemble.py:1116-1127`. The delete path logs nothing on the hide branch, and
the saved deck cannot distinguish hide-then-purge from plain delete. r9 refused and r9b did not,
which is suggestive, not probative. Fix: add
`log ("HIDDEN" & tab & "<number>" & tab & "<addr>" & tab & "title"|"body")` in each branch and
parse it into `warnings`/a result field next to `DELETEFAIL`, so the run states which object
tripped it. One line each; it makes the whole change auditable.

**F2 (should-fix, latent, pre-existing but now masked). The dual address is an index landmine.**
The emitted order for GW 17 (verified by generating the script) is
`shape 2` → `text item 6` → `text item 5` → `text item 4`, and `shape 2` and `text item 4` are
the *same* object 17290708. Pre-delete addressing is safe only while each earlier statement
removes at most the item it names, descending within a kind. If the `shape 2` statement
*removes* 17290708, the text collection shrinks to 5 and `text item 6` errors (-1728) → slide
refusal; since r9b did not error, the object must still have been a member when `text item 6`
was evaluated, i.e. the hide retained collection membership. Either way the invariant is
unverified and load-bearing. Fix: dedupe duals in `_delete_order`
(`src/obed_edom/dsk_plan.py:38`) so one underlying object yields one address, and keep the guard
for the genuine title/body case.

**F3 (nit, real). `is` on object specifiers is not an identity test.**
`dsk_assemble.py:1119-1122`. AppleScript `is` between two application references dispatches a
comparison to Keynote; Keynote usually compares its own objects by identity, but the contract is
not documented and a specifier-level comparison (`text item 4 of slide 3` vs
`default title item of slide 3`) is the classic false-negative case. A false negative silently
degrades to `delete theObj` = the r9 refusal (loud, acceptable); a false *positive* would hide
the wrong box (silent). Safer idiom: compare `id of theObj` with `id of (default title item …)`
inside a `try`. `missing value` itself is handled correctly — `theObj is missing value` is false
for a real object, so a slide with no title item falls through to `delete`, which is right.
Note the guard is *not* wrapped in `try` in the assembly path, so if `default title item` ever
raises (rather than returning `missing value`) a previously-working delete becomes a slide-level
refusal. Cheap insurance: wrap the identity probe.

**F4 (nit). Staged-index accounting: the implementer's claim holds for the emitted script, but
not for the offline consumers.** Addresses are pre-delete kindIndex and descending, so a removal
never invalidates a later, lower address, and a hide that removes nothing is equally safe —
agreed. But `_staged_retained_ids` / `_staged_kind_ranks` (`dsk_assemble.py:2059`) and their
consumers (`_verify_builds` 2125, stroke restore, crop z-order) compute staged `(kind, index)`
on the assumption the item is **gone from the staged deck**. If a hide ever leaves the drawable
in `ownedDrawables`, every later staged index on that slide shifts by one and stroke/z-order
silently mis-target. Measured here: no shift — the output's ownedDrawables is exactly the three
keepers, and stroke touched only 17443837/17502747 on slide 48 as intended. Mitigating: a build
surviving on a retained-but-hidden item would surface as a **surplus**, which `_verify_builds`
refuses (only clip movie-start is tolerated), so that particular failure is loud. Fix: with F1's
marker in hand, assert the staged census for any slide where the guard fired.

**F5 (info, not a defect). `_verify_builds` is unaffected, and slide 17's tolerated_missing is
correct.** Source slide 17275487 carries two builds: 17290791 on kept 17289361 and 17290790 on
the deleted mirror 17290734 — identical `('text', 'May they also be in Us…')` identity. Output
keeps exactly one. The `tolerated_missing` entry is properly attributed to a planned deletion,
not to a hidden item. No build landed on a hidden object.

**F6 (info). Text stack / rect writes / OVERFLOW keys are all upstream of the change.**
Geometry writes precede deletes per slide (`test_script_deletes_after_geometry_per_slide`), and
`fit` only ever contains kept items — a hidden item is never in `fit`, so no rect is written or
fitted to it, and `_text_overflow_lines` (1246) is emitted during the geometry phase, before any
delete or hide. OVERFLOW keys use source kindIndex, which here coincides with the output staged
index because every deleted item had a higher index (`text:2` on 17 = 17289361, output
`text:2`). No interaction.

**F7 (nit, style). Cross-module import of a private helper.** `dsk_movie_export.py:63` imports
`_delete_or_hide_placeholder_lines` from `dsk_assemble`, out of the file's grouped import order
(it lands after `dsk_live`) and pulling the heavy assembly module into the export path for seven
lines of string. No cycle today (`dsk_assemble` mentions `dsk_movie_export` only in a docstring
at 1422), but the natural home is `remap_keynote`, beside `_AS_KIND_NAMES`, which both modules
already import. Relatedly, `dsk_movie_export.py:312`'s `*(f"  {ln}" for ln in …)` re-indents by
string surgery; give the helper an `indent: str = "        "` parameter instead.

**F8 (nit). Tests assert substrings, not structure.**
`tests/test_dsk_assemble.py` `test_script_mirror_dedupe_delete_hides_placeholder_instead_of_failing`
bypasses the planner via `dataclasses.replace` and only counts emitted lines (4 and 4); it does
not pin the *addresses* or their order, which is exactly what F2 is about. Its name promises a
mirror-dedupe test it does not perform — rename to `…_script_shape…` or assert the emitted
address sequence (`shape 2`, `text item 6/5/4`). Nothing tests the `missing value` fall-through.

**F9 (nit, out of scope).** `src/obed_edom/maps_keynote.py:1068-1101` still issues
`delete every text item` / `delete every shape`, which is exposed to the identical -10003
refusal. Different pipeline; flagging for the backlog only.

## OVERFLOW lines — real, not merely predicted

Band 704..1054. All three boxes are `kFrameAlignTop` with stored height 0 (autosize), so they
grow **downward** from the written `y`; the logged live height is the authority.

| log line | object (output) | written y | live h | bottom | vs band bottom 1054 |
|---|---|---|---|---|---|
| slide 13 `text:1` 249.0 | 17259615 | 812.0 | 249 | 1061 | **over by 7** |
| slide 17 `text:2` 142.0 | 17289361 | 973.0 | 142 | 1115 | **over by 61** |
| slide 28 `text:1` 340.0 | 17338432 | 800.0 | 340 | 1140 | **over by 86** |

So these are genuine band-bottom breaches in the saved deck, not just a box exceeding its own
predicted rect. Slide 17's is structural: `text:2` is placed at y=973 with only 81pt of band
left, so no plausible fitted height clears it — the stack placement, not the shrink, is what
needs revisiting. Slide 13's 7pt is within a hair of the 2pt logging threshold and is cosmetic.
