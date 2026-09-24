---
name: Pass-1 hides offline — delete hide targets in the IWA writer after the pass-1 save
overview: >-
  2026-09-23, first-pass plan (Opus, extra-high), from handover
  `.agents/handovers/pass1-hides-offline-2026-09-23.md` and `pass1_profile.plan.md` todo
  `h-hides-offline`. pass-1 `deleteHides` costs 82–118 s for 947 one-AppleEvent deletes
  (≈122 ms each). Keynote-side batching is DROPPED (owner). Lever: pass 1 skips the delete on
  eligible slides; right after the pass-1 save a new surgical writer deletes each hide's owned
  archive subtree and cleans every reference to it, restoring exactly the "source − hides" deck
  that every later stage assumes. Keynote-free census of the source deck (§Census) sized all
  references first: outside the hide subtrees, the only referrers are the slide's two drawable lists
  plus its header, 6 builds (slide 122), and `Index/Metadata.iwa` tables that are exact functions of
  member contents. Opt-in `OBED_OFFLINE_HIDES` (off | on | verify), default off until the live gate.
  Refused slides fall back per slide to an AppleScript delete session that runs before the first
  Keynote reopen. Expected saving ≈ 65–100 s per run, net of a 15–30 s offline stage.
todos:
  - id: s0-census
    content: >-
      Keynote-free reference census of the hide targets on the source deck plus Metadata
      invariants (§Census). Captured the plan with `scripts/golden_plan.py capture` (Keynote-free).
      The census scripts are scratch and are not committed.
      DONE 2026-09-23 (this plan).
    status: completed
  - id: a-checker
    content: >-
      Stream A. `scripts/deck_decode_diff.py` + `tests/test_deck_decode_diff.py`: the ID-insensitive,
      reference-aware per-slide decode diff, with null and positive controls of the checker itself.
      See §Oracles/O2.
    status: pending
  - id: b-writer
    content: >-
      Stream B. New `src/obed_edom/iwa_hides.py` (`patch_deck_hides`), an optional `drop=` on
      `iwa_write._rewrite_members`, and `tests/test_iwa_hides.py`. See §Writer.
    status: pending
  - id: c-js
    content: >-
      Stream C. `remap_keynote.js`: skip `deleteHides` on `plan.offlineHideSlides`, return
      `hidesDeferred`, fix the 0-applied abort; `tests/offline_hides.test.js`. See §JS.
    status: pending
  - id: d-wiring
    content: >-
      Stream D. Flag helper, pure eligibility, `run_offline_hides` orchestration + AppleScript
      fallback, insertion at py:1636/1637, Applied accounting, pre/post snapshots, wiring tests.
      See §Wiring.
    status: pending
  - id: e-offline-dryrun
    content: >-
      After A+B+D, Keynote-free: dry-run `patch_deck_hides` on a scratch COPY of the source deck. Hides
      still sit at their source kindIndex there, as on the pass-1 deck. Gate before any live run:
      0 refusals except the build slide, read-back and verify pass, stage ≤ 30 s at load < 10 (record
      `uptime`). Checker: source vs dry-run differs on exactly the eligible slides, and per slide only
      in the removed subtree pbtypes (§Census counts). Dropped `Data/` = the orphan set. Needs ≈ 21 GB
      free (copy + 2.1× rewrite guard, iwa_write.py:919). Delete the copy after recording.
    status: pending
  - id: f-live-gate
    content: >-
      OWNER-GATED (Keynote shared with AK / GL-replay: owner go or peer all-clear first). Two
      interleaved A/B pairs, pass/fail per §Gate. Record in
      `.agents/reviews/pass1-hides-offline-<date>/README.md`.
    status: pending
  - id: g-flip-docs
    content: >-
      After a GREEN gate and owner approval: default `OBED_OFFLINE_HIDES` to on (explicit off stays
      the kill switch). Update README remap section, `.agents/skills/obed-edom/SKILL.md` §Offline
      writes (new bullet: hide deletion + Metadata tables), and `pass1_profile.plan.md`
      `h-hides-offline`. Run the full suites.
    status: pending
  - id: followup-single-rewrite
    content: >-
      GATED FOLLOW-UP, not in this round. Fold the hide delete into `patch_deck_geometry`'s rewrite
      (one decode and one rewrite instead of two). Precondition: the bulk seed read must run on the
      undeleted deck, with rows re-keyed through `bridge_kind_index`, which changes a live-validated
      path (offline_write.py:122-133). Pursue only if the measured hide stage is ≥ 10 s AND
      `h-bulk-seed-read` has settled what the seed read looks like.
    status: pending
  - id: deferred-build-hides
    content: >-
      NOT PLANNED. Hides that carry a build (benchmark: slide 122, 6 text hides, ≈0.7 s) stay on the
      Keynote delete. Deleting them offline would also mean maintaining the `KN.SlideNodeArchive`
      caches `buildEventCount`/`hasBuilds`. On the source deck `buildEventCount` = non-automatic
      chunk count on only 94/170 nodes, so the formula is unknown. Revisit only if a deck puts
      material time there.
    status: closed-not-pursued
---

# Pass-1 hides offline

## Census (source deck, read-only, 2026-09-23)

Inputs: `Full_Report_Card_Wall.key` (6.77 GB); the plan was captured Keynote-free with `scripts/golden_plan.py capture`.
The benchmark range `1-129,135-143,145-155` has **947 hides on 131 slides**, matching the run census. By
kind: image 547, text 338, shape 45, group 11, line 6 (movie 0). 0 locked, 0 dual text/shape targets, and every
kind is one of the six. Each hide resolved positionally with `derive_kind_index` to a top-level
drawable. Its owned subtree (closure over header `objectReferences`, pruned to archives referenced
only from inside) has **6,948 archives**, all in the slide's own member: ShapeInfo 1,180,
Storage 1,180, StandinCaption 3,490, Image 554, Mask 533, Group 11.

References into those subtrees from outside the subtree, across the whole deck (bodies + headers):

| referrer | count | handling |
|---|---:|---|
| `KN.SlideArchive.drawablesZOrder` / `.ownedDrawables` (+ the slide header `objectReferences`) | 947 each | remove the ids |
| `KN.BuildArchive.drawable` (weak; slide 122 only, 6 builds, tail chunks 158–163, all `automatic`) | 6 | slide excluded → Keynote delete |
| `TSP.PackageMetadata.components[].objectUuidMapEntries` | 6,948 | drop entries |
| `…components[].dataReferences[].objectReferenceList` | 554 objects | recompute |
| masks / text-wrap / connection lines / comments / placeholders / `Index/Document.iwa` / ViewState | 0 | refuse the slide if ever seen (R5) |

Subtree → outside: only `Index/DocumentStylesheet.iwa` styles. These are shared and are never deleted.
Data: the hides reference 64 datas; **46 (49.8 MB) become unreferenced** after deletion.

Invariants that hold exactly on every one of the 176 components / 155 slides (the writer pre-checks
them, refusing on a violation, and re-asserts them on read-back):
- I1: `KN.SlideArchive` header `objectReferences` set == the set of body identifier refs.
- I2: `ownedDrawables` == `drawablesZOrder` (same list, same order).
- I3: component `dataReferences` == aggregate of the member archives' header `dataReferences`, as (data, object, count).
- I4: component non-weak `externalReferences` == the member archives' cross-member header refs (an entry
  without `objectIdentifier` = the component root); weak entries are untouched.
- I5: `objectUuidMapEntries` ids ⊆ member archive ids.
- I6: no `datas` entry is unreferenced. Measured 0/1179 in the wall deck, 0/1284 in `Full_Report_Card_CG.key`,
  0/364 in `Gold_Wall_Input.key`: Keynote never saves an unreferenced data.
Header `objectReferences` are copied through verbatim by keynote_parser; only `length` is fixed up
(`keynote_parser/codec.py:372-380`). So the writer must edit them itself.

Pass-2 re-check (independent scratch scripts, wall deck, read-only):
- I3 and I4 recomputed from scratch: 176/176 components exact. I4 needs the component-root rule
  (an entry without `objectIdentifier` targets the component's root, id == `componentIdentifier`).
- I2 holds on all 155 slides. Slide headers have exactly one `messageInfo` and no duplicate refs.
- Weak `externalReferences`: Slide/TemplateSlide → DocumentStylesheet root (170), ViewState → Document (1).
  None of them target a slide member.
- UUID-valued references (`{lower, upper}`) outside Metadata that match a mapped uuid:
  `KN.BuildChunkArchive.buildId` (build UUIDs) and `KN.SlideNodeArchive.templateSlideId` only.
  None point at a drawable.
- `datas`: 1,179 entries against 1,176 `Data/` members. The 3 without a member carry
  `documentResourceLocator`, and all 3 are the `TSP.DataMetadataMap` entries (R6). 8 members have
  non-ASCII names stored with ZIP flag bit 11 clear, so `"Data/" + fileName` misses them. They
  resolve only through the CP437 round trip (`offline_inspect.data_member_index`, offline_inspect.py:58).
- `featureInfos` sit on 23 Slide components, all `TSDMovieInfoPlaysAcrossSlides`.
- Precedent: Metadata component edits already ship in the add direction (`dsk_pill.py:427-457`
  uuid/data/external refs; `mint_media_style`). The new parts are removal, `datas` edits, and ZIP
  member removal. Orphaned archives are tolerated by Keynote (SKILL.md §Offline writes: orphan
  Build/BuildChunk archives are harmless).

## Answers to the handover's five questions

**Q1: insertion point.** In `remap_keynote.remap_keynote`, immediately after
`_require_pass1_saved_closed(jxa)` (py:1636) and before `_debug_snapshot_pass1` (py:1637). That is
before `run_offline_write` (py:1640), whose first action on offline slides is the Keynote bulk seed
read (`_patch_offline_slides` → `inspect.bulk_geometry`, offline_write.py:389). Rows there are keyed
"row index == saved kindIndex" (offline_write.py:122-133). The later Keynote openers are the
geometry fallback session (offline_write.py:1107) and stat-finalize (py:1747). Stat-finalize uses
`groupIndex` values already shifted for deleted group hides (`adjust_child_resize_indexes`,
map_remap.py:3156, called py:1445). Two further conditions hold. (a) The applied/missed line (py:1623)
moves below the new stage. (b) The pass-1 zero-applied abort (py:1613, js:836) counts deferred hides
(§JS, §Wiring).

**Q2: order vs `run_offline_write`.** It runs strictly before, with its own rewrite, so each stage
decodes once and rewrites once. One combined rewrite is impossible without changing the bulk read:
that read sits between the pass-1 save and `patch_deck_geometry` (offline_write.py:389 → :412) and
must see the deleted deck (Q1). Folding the two is `followup-single-rewrite`. No per-slide whole-deck
decode: `patch_deck_hides` makes exactly one whole-deck decode (a local loader over
`IWAFile.from_buffer` that also keeps per-archive headers; `_load_deck_full` drops them,
iwa_runs.py:224-263). Per-slide planning is pure over that model, as in `_slide_edits`. Each touched
member is decoded once more by `_decode_apply_reencode_diff` (iwa_write.py:779), all through one
`ZipFile` handle. Then comes one `_rewrite_members`, and one read-back pass over the touched members
only. A counting test enforces this (§Tests B7), mirroring
`test_readback_loads_deck_once_for_many_slides` (tests/test_iwa_zorder_write.py:236). Measured
while the machine was under load (load average 33): `_load_deck` 5.5–7.7 s, and
decode+encode+reparse of the 131 members plus Metadata 12.5 s. Expect a 15–30 s stage.

**Q3: every reference to a deleted object.** See §Census and §Writer.
- Builds: excluded before pass 1, and refused after it (R5). Offline build deletion is `deferred-build-hides`.
- Groups: a hide is never a group child. Hides are made only from top-level payload items
  (`_hide_item_transform`, map_remap.py:2244, :2496-2516). Kind indices enumerate `drawablesZOrder` only
  (iwa_kindindex.py:98-130), and JXA `getItem` reads slide-level collections (js:87-99). A hidden
  group's children go with its subtree. R4 refuses a target that is not in `drawablesZOrder`.
- Masks: owned by their image (strong `mask`, weak `parent`) and deleted with it. A mask that any
  other image also references is refused (R5; precedent `dsk_pill._mask_exclusively_owned`, dsk_pill.py:365).
- Text-wrap: a value property of the drawable itself. Nothing references it.
- `dataReferences`: vanish with the archive headers. I3 is recomputed, and data that becomes
  unreferenced is purged (datas entry + `Data/` member) to keep I6.
- Also cleaned: the slide header refs (I1), uuid entries, and `externalReferences` (I4).
- Checked and absent, with R5 refusing if they ever appear: connection lines, comments,
  placeholders (title/body/number are slide fields outside `drawablesZOrder`), `Index/Document.iwa`
  (SlideNode fields change only with builds, which are excluded), and ViewState.
- Styles are shared and untouched; any Keynote-side style GC is an O3 expected difference.
- Delete archives rather than only unlinking them. Orphan drawables would still be counted by
  whole-deck scans: `card_styles` counts every image/movie in `objects` (iwa_write.py:1154), which feeds
  `restore_card_stroke_widths` (py:906-948). So later stages would diverge from the Keynote path.
  Unlinking alone would be openable (orphan archives are harmless, SKILL.md §Offline writes), so this
  is about matching the Keynote path, not about Keynote safety.

**Q4: what stays on the Keynote delete.** Hide kinds are always the six JXA kinds (js:38-46,
iwa_kindindex.py:13). Tables, charts and audio are never payload items, so they can never be hides.
The writer still refuses any other pbtype. What stays on Keynote:
- Before pass 1, from the wall payload: slides where any hide is the target of a build
  (`wall.slides[].builds`, attached py:1169-1171). The benchmark has 1 such slide and 6 hides.
- After pass 1: any slide refused by R1–R8. It gets the per-slide AppleScript delete fallback (§Wiring),
  which runs before the first Keynote reopen.

The full-JXA slide (slide 1, 2 hides) is **eligible**. Its JXA geometry runs before `deleteHides`
(js:733-746), so hides are present during geometry writes, as today. Nothing addresses slide 1
positionally between the pass-1 save and stat-finalize. Excluding it would add a special case and no
safety.

**Q5: the opacity-0 fallback.** It has no offline equivalent; refuse the slide instead. An offline
opacity-0 would leave the object in `drawablesZOrder`, which breaks "source − hides". Specifically,
`expected_base_counts` (iwa_write.py:226) would refuse the slide in `patch_deck_geometry`, and its
AppleScript fallback bridges indices assuming deletion (`bridge_kind_index`, iwa_write.py:168). A
refused slide goes to the AppleScript fallback session. That session keeps today's semantics: delete,
then opacity 0 on error (js:547-558), counted as missed with a reason. Pre-existing hazard, not
introduced here and not fixed here: an opacity-0 survivor (in today's JS path too) makes that slide's
later geometry fallback use shifted indices.

## Writer: `iwa_hides.patch_deck_hides` (Stream B)

`patch_deck_hides(deck, hides_by_slide, *, source_counts_by_slide, items_by_slide, verify=False,
force_refuse=frozenset()) -> HidesResult`. `hides_by_slide` holds the role=hide specs with WALL
kindIndex. The deck still contains them, so no bridge is needed. `items_by_slide` is the wall payload
items for identity checks. The result has, per slide, `deleted`, `refused`, `reason` and
`removed_ids`, plus `dropped_data` and `members`.

Per slide, pure, over the single decode. Any failure refuses that slide only, and its member stays byte-identical.
- R1: slide resolves; slide archive and every drawable live in one member (as `_slide_edits`,
  iwa_write.py:627-630); no other slide shares that member.
- R2: I1–I4 hold on the unedited slide/component before the edit (the R8 recompute reproduces the stored
  tables); the component resolves by locator (`_resolve_member_components`, iwa_write.py:1628).
- R3: `reconcile_counts(derived, source_counts)` is clean on the undeleted slide (iwa_kindindex.py:174).
- R4: each hide resolves at `(kind, kindIndex)` to an id in `drawablesZOrder` with pbtype in
  {`TSWP.ShapeInfoArchive`, `TSD.ImageArchive`, `TSD.MovieArchive`, `TSD.GroupArchive`}. No two specs may
  resolve to the same id. A target with two memberships (a text/shape dual,
  `derive_kind_index`, iwa_kindindex.py:98) refuses: deleting it would remove two kind slots
  against one hide spec. The per-kind identity sequence must equal the payload's over every
  derived record. Payload text items past the derived count are allowed only if they are tail
  placeholders (`map_remap.is_placeholder_text`, at most `TEXT_PLACEHOLDER_SLACK`; JXA appends them
  last, iwa_kindindex.py:21). Identity is normalised text for text/shape, data file name for
  image/movie (`offline_inspect._data_identifier` :74 + `_build_data_index` :44, built once per
  deck), and the child-text signature for groups. Lines are count-only.
- R5: build the subtree S(d) as in §Census. Every archive in S must live in the slide's member.
  The reference scan is over a **strict** decode (`UndecodableIWAMember`, iwa_runs.py:247; a
  skipped member could hide a referrer). It walks every object of every archive, not `objs[0]` as
  `_load_deck` keeps. Every body or header reference to an id in S must come from S itself, the
  slide archive's `drawablesZOrder`/`ownedDrawables` fields (any other slide-archive field refuses)
  or header, or `TSP.PackageMetadata`. Also refuse on:
  - another component's `externalReferences` naming an id in S;
  - a `{lower, upper}` uuid anywhere outside Metadata that equals a uuid entry of S (0 today, §Census).

  Anything else refuses, for example `KN.BuildArchive.drawable`, a connection line, a shared mask,
  ViewState, or `Index/Document.iwa`.
- R6: an orphaned data that appears in `TSP.DataMetadataMap` (Metadata.iwa; 3 entries today)
  refuses. So does an orphaned data with no `Data/` member, or whose member is not unique in
  `data_member_index`. A movie hide on a component that carries `featureInfos` also refuses
  (`TSDMovieInfoPlaysAcrossSlides` would go stale; 0 movie hides today).
- R7: edit the slide member. Remove the hide ids from both lists and the header refs (exactly
  `len(hides)` from each), and drop the archives in ∪S. `_decode_apply_reencode_diff` then
  `_archive_diff` must give removed == ∪S, added == ∅, changed == {slide id} (the gate of
  `patch_slide_builds`, iwa_write.py:2105-2113).
- R8: edit Metadata once for all accepted slides.
  - Drop the uuid entries of ∪S.
  - Edit I3/I4 **by subtraction**, keeping Keynote's order: remove the removed objects' (data, object)
    pairs, drop a data entry left empty, and drop a non-weak external entry no longer referenced.
  - Then assert that each touched component equals a from-scratch recompute (as a multiset). The
    same recompute must already equal the stored table on the unedited component (R2 pre-check), or
    the slide refuses.
  - A data is orphaned only when no component references it after the edit. That is a check over
    all 176 components, not just the touched ones; templates and the Document thumbnails
    (`Data/st-*`) count as references.
  - Drop orphaned `datas` entries.

  Changed archives must be {PackageMetadata} only.

Then one `_rewrite_members(deck, edits, drop=orphan_data_members)`. `drop` takes **raw**
`namelist()` names from `offline_inspect.data_member_index` (never `"Data/" + fileName`; 8 names
differ today). It refuses a name that is missing or also edited. Every other member streams through
verbatim, including the `_preserve_raw_name` handling (iwa_write.py:880). `OfflineWriteCorrupted`
propagates, as in `_patch_offline_slides` (offline_write.py:421-428).

Read-back, always on, is one batched pass over the touched members plus Metadata. It never calls
`read_slide_zorder` (one `_load_deck` per call). A mismatch raises `RuntimeError`, because the deck
is written. The precedent is `patch_deck_zorder`, which raises `ValueError` (iwa_zorder.py:378-388).
Checks:
- lists == expected;
- I1–I6 hold for the touched components;
- no touched-member archive references a removed id;
- dropped members are absent;
- `derived_kind_counts` == `expected_base_counts(source_counts, hides)`. This is the exact contract
  the geometry patch checks next (iwa_write.py:634-639).

`verify=True` adds one whole-deck decode. It asserts no reference to any removed id anywhere, and
I3–I6 on all 176 components.

## JS (Stream C)

In `applyNonReuseSlide` (js:707-752), a 9th optional parameter `offlineHideSlides` (array or null).
When it contains `n`, skip `deleteHides` (js:746) and add the slide's hide count to `hidesDeferred`.
Everything else stays byte-for-byte the same, including the `hides` stage key. `run` reads
`plan.offlineHideSlides`, accumulates `hidesDeferred`, and returns it in both JSON results
(js:841, :894). The abort becomes `appliedFirst === 0 && hidesDeferred === 0` (js:836).
`readMapGeom` (js:858) is untouched. On eligible map slides it now reads before the deletion, so the
diagnostic "Map object after apply" line (py:1689) can change there. It is not part of the null control.

## Wiring (Stream D)

- `offline_hides_mode(explicit=None, *, offline_mode, say) -> "off"|"on"|"verify"` in `remap_keynote.py`,
  shaped like `offline_maskcrop_enabled` (py:192-212). Env `OBED_OFFLINE_HIDES`, default off. An unknown
  value becomes off with a `say`. Forced off when `offline_mode == "off"`: it needs the `iwa` extra and
  the offline-write kill switch covers it.
- `offline_write.offline_hide_slides(transform_dicts, wall, wanted) -> set[int]`, pure: slides with ≥ 1
  hide, ∩ wanted, minus slides where a payload build targets a hide `(kind, kindIndex)`. Computed at
  py:1540, passed as `plan["offlineHideSlides"]` only when the mode is not off. `plan_out` is unchanged,
  so `tests/test_golden_plan.py` stays green (its pins force offline write off, scripts/golden_plan.py:48-56).
- py:1613: abort when `jxa.applied + jxa.hidesDeferred == 0`, tolerating a dict without
  `hidesDeferred` (the test stubs return bare dicts, tests/test_offline_write.py:2099-2103).
- New `offline_write.run_offline_hides(dest, mode, hide_slides, transform_dicts, wall, say)`, called at
  py:1636/1637. It is a no-op (no decode) when `hide_slides` is empty or the mode is off. Its steps:
  - Snapshot pre-delete to `<OBED_DEBUG_PASS1_SNAPSHOT stem>.pre-hides.key` when that env is set.
  - `patch_deck_hides`, then one `say` line: slides, deleted, refused with reasons, dropped data,
    seconds. The census line stays untouched.
  - Refused slides → one AppleScript session built with `build_fallback_scripts`
    (offline_write.py:258) and run by `_run_fallback_scripts` (:320), with its own dump suffix and
    marker. Per slide, it deletes in `deleteHides` order (slide desc, kind asc, kindIndex desc,
    js:522-529), with AppleScript index = kindIndex + 1 (py:45), and falls back to opacity 0 on error.
  - A failing session raises `RuntimeError`: those slides would otherwise carry undeleted hides into
    every positional stage.
  - `_run_fallback_scripts` gains a `suffix` keyword (default `.offline-fallback`), so the dumps do
    not collide with the geometry fallback's.
- **Failure semantics.** The stage must never continue with hides silently left in place. A leftover
  hide makes `expected_base_counts` refuse the slide, and then `bridge_kind_index`, the bulk seed
  read and stat-finalize address the wrong objects on the live deck. So:
  - Any exception before `_rewrite_members` starts writing leaves the deck untouched. That covers the
    import, a strict-decode failure, `OfflineWriteRefused` (including the 2.1× disk guard), and any
    bug. Say a WARNING, then send **every** eligible slide through the AppleScript delete session
    (today's cost).
    - This is unlike `_patch_offline_slides`, whose `return {}` (offline_write.py:407-432) must not
      be copied here.
  - `OfflineWriteCorrupted` propagates with the recovery line and no fallback (offline_write.py:421-428).
  - A read-back or verify mismatch after the write raises `RuntimeError`, with no fallback: the
    deck's state is unknown.
  - A failing fallback session raises (above).
  - `OBED_DEBUG_HIDES_REFUSE=<slides>` (diagnostic only) is passed as `force_refuse`, so the live gate
    can exercise the fallback path.
- Then the existing `_debug_snapshot_pass1` (post-delete, so its meaning stays "the deck later stages see").
- `Applied {applied}, missed {missed}.` moves below the stage. `applied` = jxa.applied + offline deleted +
  fallback deleted, and `missed` adds fallback failures, so the benchmark still prints `Applied 3822 …
  missed 0`. `result["applied"]` (py:1808) takes the same value.

## Oracles

- **O1: null control, every live run.** These lines must be identical to runs 1–8:
  `Applied 3822 … missed 0`, the census line, the fallback-reason line, `Stat zorder detail`,
  `Builds follow source: …`, and every `Card-border stroke:` line. The last one catches any
  whole-deck-scan divergence.
- **O2: checker (Stream A).** `scripts/deck_decode_diff.py A.key B.key [--allow REGEX…] [--json OUT]`.
  - It decodes each deck once. Per slide (by `slide_order`), it compares the multiset of archives in
    that slide's member, canonicalised with `identifier`, `randomNumberSeed`, `saveToken` and uuids
    dropped. Each body reference **and each header `objectReferences` entry** is replaced by the
    target's content label (pbtype + ref-free body hash). Header `dataReferences` become (digest)
    multisets. Header refs are exactly what R7 edits, so dropping them (as the handover's comparator
    did) would hide a stale-header bug. One refinement round makes it reference-aware; a dangling ref
    gets the label `<dangling>`.
  - Non-slide members: the same multiset per member.
  - Metadata, per component (by locator):
    - the uuid-entry count, plus `featureInfos`;
    - `dataReferences` as a multiset of (data digest, object label, count);
    - `externalReferences` as a multiset of (target locator prefix, target label, isWeak);
    - component `saveToken` ignored.
  - `datas` as a multiset of (preferredFileName, digest); ZIP names CP437-normalised, with the
    `-<id>` suffix stripped.
  - Exit 0 iff every difference matches `--allow`.
  - Checker controls: unit tests (§Tests A); live null = A-run vs A-run snapshot → 0 slides; live
    positive = B pre-hides snapshot vs A snapshot → differing slides == exactly the eligible set.
- **O3: main deck oracle.** B post-delete snapshot vs A snapshot → **0 differing slides**. Non-slide
  differences must be ⊆ (members differing in the O2 null) ∪ this deliberate list:
  - thumbnails `Data/st-*` of hide slides, plus `preview*.jpg`. B's pass-1 render still showed the
    hides, as with the offline geometry patch today;
  - `DocumentStylesheet.iwa` styles used only by deleted objects, if Keynote GCs them. Record which,
    and do not fix them in this round;
  - `Metadata.iwa` `lastObjectIdentifier`/`revision`/`saveToken`.
  - The `Data/` set and `datas` must be EQUAL. If Keynote kept the 46 orphans, stop and re-plan R8.
  - Final decks: B vs A. Slide diffs must be ⊆ the final-vs-final null (A pair-1 vs A pair-2 final
    decks). A silent Keynote repair shows up here, not as a prompt.
  - Component `saveToken`s and `thumbnailsAreDirty`/`thumbnails` on hide slides are expected
    differences. Thumbnail staleness is the same class as today's offline geometry patch.
- **O4: live A/B.**
  - A = detached `origin/main` worktree sharing this worktree's `.cache`; B = branch with
    `OBED_OFFLINE_HIDES`. Order: pair 1 A,B (B in `verify`), pair 2 B,A (B in `on`, the timing pair).
  - Command per handover (`--slides 1-129,135-143,145-155 --no-export`, one shared `--out`), with
    `OBED_DEBUG_PASS1_SNAPSHOT` set. Record `uptime` before each run.
  - Plus one short subset run each of A and B, B with `OBED_DEBUG_HIDES_REFUSE=<one eligible slide>`:
    the fallback session deletes that slide's hides. The O1 lines of B equal A's subset run (not the
    benchmark's), and O3 holds on the subset.
  - Disk: the deck (6.8 GB) + the 2.1× rewrite guard + two B snapshots (pre-hides, post) ≈ 35 GB free.
  - Record Keynote cold/warm. Trash the decks once the diffs are recorded.

## Gate

PASS iff all of the following hold:
- O1 holds in all runs.
- The O2 null is 0 slides and the O2 positive is exactly the eligible set.
- O3 has 0 slide diffs, non-slide diffs ⊆ the list, and the final-deck compare ⊆ its null.
- Read-back and verify pass, with 0 refusals on the benchmark.
- Keynote opens the patched deck with no repair prompt (the bulk read and stat-finalize complete).
- The JS `hides` stage is ≤ 2 s, and the offline stage is ≤ 30 s.
- `runJxa` falls by ≥ 60 s, and the whole run by ≥ 45 s, in both pairs. The whole-run bar catches
  the second 6.8 GB rewrite that the stage adds.
- Magic Move is unchanged (owner condition for Q1). The hide set itself does not change: the planner
  already deletes the off-canvas and coincident MM leftovers (`map_remap.py:2494-2500`), and this round
  moves only the mechanism. O3's 0 slide diffs covers every survivor and each slide's transition archive.
  Survivors' `identifier`s are untouched by the writer, so an identity-keyed match cannot shift. Plus an
  owner playback spot-check of two or three MM transitions into and out of hide-heavy slides on the B final
  deck, because preview images cannot prove animation.

Expected: hides 82–118 s → ≈0.7 s (slide 122), offline stage 15–30 s, net ≈ 65–100 s of ≈ 545–560 s.
FAIL on any slide diff, a dangling ref, or a repair prompt: keep the default off and record why.

## Tests

- **A** `tests/test_deck_decode_diff.py`, on synthetic decks (the `IWAFile` builder pattern from
  tests/test_iwa_write.py:260-330):
  - null: a deck vs itself → 0;
  - consistent identifier renumbering → 0;
  - a `randomNumberSeed` change → 0;
  - one field mutated on slide 2 → exactly slide 2 reported;
  - two build refs swapped between drawables → reported, and not reported with refs off;
  - a dangling ref → reported;
  - a dropped `Data/` member and a `datas` entry → reported, and silenced by `--allow`;
  - CLI exit codes.
- **B** `tests/test_iwa_hides.py`, on synthetic decks:
  - B1: a shape hide deletes the drawable, its Storage and its standins; updates lists and header;
    drops uuid entries; recomputes I3/I4.
  - B2: an image+mask hide removes both; a hide's data shared with a survivor is kept; orphan data
    purges the datas entry and the `Data/` member.
  - B3: a group hide removes the children.
  - B4: every untouched member is byte-identical, other slides included.
  - B5: each refusal R1–R8 leaves the deck byte-identical and the other slides patched (build ref,
    shared mask, connection-line ref, dual target, non-top-level target, identity mismatch, reconcile
    mismatch, I1/I2/I3/I4 pre-violation, DataMetadataMap orphan, shared member).
  - B6: an injected post-write corruption makes the read-back raise.
  - B7: exactly one whole-deck decode for N slides with `verify=False`. Count `IWAFile.from_buffer`
    per member name: 1 per untouched member, ≤ 4 per touched member (load, apply, reparse,
    read-back). `read_slide_zorder` / `_load_deck` are never called per slide.
  - B8: `_rewrite_members(drop=)` refuses a missing or edited name.
  - B9: `OfflineWriteCorrupted` propagates.
  - B10: integration: `patch_deck_geometry` on the result with the same specs does not refuse (reconcile clean).
  - B11: data. An orphan whose member name is non-ASCII with bit 11 clear is dropped by its raw name.
    Data shared with another slide, or with a TemplateSlide, is kept. An orphan with no member, or one
    in `DataMetadataMap`, refuses.
  - B12: reference proof. Each of these refuses:
    - a uuid reference to a hide outside Metadata;
    - another component's `externalReferences` into S;
    - a non-list slide field referencing a hide;
    - a text/shape dual target;
    - an archive in S living in another member;
    - an undecodable member (strict).
    - Positive case: tail placeholder text items in the payload do not refuse.
  - B13: Metadata edit order. The surviving entries keep their original order, and the post-edit
    tables equal the from-scratch recompute. A pre-state that the recompute cannot reproduce refuses.
  - B14: a movie hide on a component with `featureInfos` refuses.
- **C** `tests/offline_hides.test.js`:
  - a listed slide skips deletes and counts `hidesDeferred`;
  - an unlisted slide keeps the order `["delete:s2","delete:s1","delete:t0"]`;
  - deferred-only hides do not abort;
  - `tests/attrs_roundtrips.test.js:348-380` and `tests/pass1_stages.test.js` are unchanged and green.
- **D** `tests/test_offline_hides_wiring.py`:
  - the mode helper (default off, on/verify, unknown → off, forced off with offline write off or the
    extra missing);
  - eligibility (the build exclusion, wanted, empty);
  - the plan field present iff not off;
  - a call-order recorder: `run_offline_hides` after `_require_pass1_saved_closed`, before
    `_debug_snapshot_pass1`, `run_offline_write` and any Keynote opener (pattern: tests/test_zorder_wiring.py);
  - Applied accounting and the abort;
  - the fallback body order and index;
  - a fallback failure raises;
  - a pre-write exception, and a disk-guard `OfflineWriteRefused`, route every eligible slide to the
    AppleScript delete session;
  - a read-back mismatch and `OfflineWriteCorrupted` propagate, with no fallback session;
  - no decode happens when there are no eligible slides;
  - snapshot naming.
- Must stay green: test_iwa_write, test_iwa_zorder_write, test_offline_write, test_zorder_wiring,
  test_remap_keynote, test_golden_plan, test_iwa_builds, test_write_gate, and all `node tests/*.test.js`.
- Full suites, per the owner rule (first `uv sync --all-extras --all-groups` and `npm ci`):
  `uv run pytest tests/ -n auto --dist loadfile`, `node tests/*.test.js`, and in `dashboard/`
  `npm run test:ui` and `npm run test:maps`.

## Streams (disjoint files, parallel)

| stream | files | depends on |
|---|---|---|
| A checker | `scripts/deck_decode_diff.py`, `tests/test_deck_decode_diff.py` | — |
| B writer | `src/obed_edom/iwa_hides.py`, `src/obed_edom/iwa_write.py` (`_rewrite_members(drop=)` only), `tests/test_iwa_hides.py` | — |
| C JS | `src/obed_edom/remap_keynote.js`, `tests/offline_hides.test.js` | — |
| D wiring | `src/obed_edom/remap_keynote.py`, `src/obed_edom/offline_write.py`, `tests/test_offline_hides_wiring.py` | B's signature and C's field names as fixed above (stub B in tests) |
| E record/docs | gate record README, SKILL.md, README.md, the plans | the live gate |

Integration order: A, B and C land first, then D, then `e-offline-dryrun`, then Codex review, then the owner-gated `f-live-gate`.

Review artifacts: raw reviewer rounds (Codex/Opus) stay out of git, in the session scratchpad or git-ignored
`output/pass1-hides-offline-review/`, while the loop runs, so later rounds can classify findings and check that
earlier fixes closed. Each round adds one line to §Review log. At merge the raw rounds are deleted. The gate record
(`f-live-gate` README) and the measurement write-ups stay.

## Must not change

- The `_require_pass1_saved_closed` contract; bundle-id addressing; never quitting Keynote; working on copies.
- `deleteHides` order on non-eligible slides.
- The census line and the `OBED_WRITE_TIMING` output.
- `expected_base_counts` and `bridge_kind_index` semantics (the writer produces what they assume).
- Byte-identity of untouched members. The only removals are orphaned `Data/` members.
- The `OBED_OFFLINE_WRITE=off` kill switch.

## Owner decisions (2026-09-23)

1. Orphaned `Data/` removal: APPROVED, on the condition that Magic Move transitions are not broken (§Gate MM line).
   The 46 files are image/movie payloads referenced only by deleted hides. A payload shared with any
   survivor or template slide is kept (B2/B11).
2. After a GREEN gate, `OBED_OFFLINE_HIDES` defaults to ON (`g-flip-docs`), with explicit off kept as the kill switch.
3. Implementers: Opus, Effort MEDIUM. The live gate waits on Keynote use by the other sessions.
4. Whole-deck pre-write refusal (`OfflineWriteRefused`) ABORTS the run (owner, after the Astra H advisory, reversing an
   earlier lean towards the fallback). A save can reorder same-kind groups (`iwa_zorder.py:84`, Gold slide 19), so
   deleting by kindIndex without identity proof can remove a survivor. The abort raises `OfflineHidesAborted(reason)`.
   The CLI prints the reason and says to rerun with `OBED_OFFLINE_HIDES=off`. On the dashboard, the Resize tab shows the
   reason and switches offline hides off for the operator's next run. A per-slide refusal still falls back only when
   `order_proven`.

5. Twin slides whose disambiguation would rest on approximate (`needs_keynote`) geometry are excluded BEFORE deferral and
   stay on the Keynote delete, like builds and duals (owner agreed, 2026-09-23, after the round-4 FRC dry run refused slide 20).
   `iwa_hides.pre_deferral_twin_risk` must be a superset of the saved-deck refusal; the post-save check stays as the backstop.
   The payload carries no `needs_keynote`, so the first proxy excluded 17 FRC slides (≈190 hides, ≈23 s). Owner chose (b):
   the offline reader records the flag on payload items. The predicate uses it when present and falls back to the proxy
   for JXA or cached payloads.
   After S4 the owner chose (i): eligibility evaluates the flag at each item's PLANNED transform (scale), so a
   source-clean twin that pass 1's scaling would make approximate (e.g. an off-axis mask crossing `_MASK_TRUST_PX`) is
   excluded before deferral. There is no generic `group-residual` error bound, and excluding every twin was rejected on
   cost. The saved-deck check stays as the backstop.

6. Dashboard recovery after a fallback timeout (`needs_fresh_output`) is SIMPLIFIED (owner, 2026-09-24, after S8: 5 rounds of
   lifecycle races, all edge cases). A process-wide, in-memory lock is set by the worker when the abort happens. While it is set,
   every resize Apply is refused, and the worker also re-checks it before touching any destination. The notice says: close
   <file> in Keynote, then restart the dashboard. Restarting clears the lock. This replaces the per-job/per-path confirmation,
   the abort generations and the closure checkbox. The "offline hides off for the next run" setting stays.

## Owner questions (resolved above)

1. **ZIP member removal.** Keynote never saves an unreferenced data (I6, 3/3 decks). Mirroring that
   drops the benchmark's 46 orphaned `Data/` members (49.8 MB) and their `datas` entries. That is the
   first offline writer to remove ZIP members, and is otherwise byte-preserving. Approve? If not,
   R8 keeps them, which gives a state Keynote never produces and whose tolerance is unproven, and O3
   lists them as expected.
   - The stat-finalize save probably garbage-collects them anyway (I6), but that is unverified.
     The final-deck compare in O3 would show it either way.
   - Keeping them removes `drop=` and the raw-name mapping (B11) from this round.
2. **Default flip after a GREEN gate** (`g-flip-docs`): flip to on, as for text/maskcrop, or keep it opt-in for a while?

## Not verified (pass 2)

- The census counts (947/131, the 6,948-archive subtree, 64 → 46 orphan datas, 49.8 MB) were not
  re-derived. Doing so needs the captured plan, and the census scripts were scratch. Dry-run `e`
  re-measures them.
- Whether any of the 46 orphans has a non-ASCII member name (8 such names exist deck-wide).
- Whether the benchmark has payload tail placeholders on hide slides. The R4 refinement makes that
  moot, and `e` measures refusals.
- Keynote's acceptance of Metadata **removal** edits, `datas` removal and ZIP member removal. Only
  the add direction has precedent. The live gate is the only oracle.

## Critique (pass 2)

Every file:line citation was checked. All hold except the ones fixed below. Insertion point
py:1636/1637 is confirmed: py:1602-1636 only prints and checks `jxa`, and nothing reads the deck.
Two whole-deck decodes are confirmed (hides stage, then `patch_deck_geometry`). The stream files are
disjoint.

- **BLOCKER. Failure semantics were unspecified.** If the stage failed before writing and copied
  `_patch_offline_slides`' swallow-and-return-{} pattern, undeleted hides would flow into
  `expected_base_counts` refusals. From there, `bridge_kind_index`-bridged AppleScript bodies and
  shifted stat-finalize indices would write the wrong live objects.
  - Fix: a pre-write failure routes every eligible slide to the AppleScript delete session.
    Corrupted, read-back and fallback failures raise (§Wiring). Tests added (§Tests D).
- **MAJOR. Data-member naming.** 8 `Data/` names are CP437 mojibake in `namelist()`, so
  `"Data/" + fileName` misses them. `drop=` would refuse and fail the stage.
  - Fix: use `offline_inspect.data_member_index` raw names; B11.
- **MAJOR. The R5 reference proof had holes.** `_load_deck` is non-strict (it skips undecodable
  members) and keeps only `objs[0]`. The scan also ignored uuid-valued refs, other components'
  `externalReferences`, and non-list slide fields.
  - Fix: a strict decode that walks every object, plus the added refusals. The uuid and weak-ref
    scans were measured at 0 today; B12.
- **MAJOR. R4 would false-refuse** slides whose payload has JXA tail placeholders, and did not name
  the dual-target refusal. Fix: a placeholder-tolerant identity check and an explicit dual refusal.
- **MAJOR. The O2/O3 oracle was blind to the writer's own edits.** It dropped header refs, and
  compared Metadata tables by count only. The final-deck compare was also "report" rather than
  gated.
  - Fix: header refs, dataReferences, externalReferences and featureInfos are compared in
    content-label space, and the final-deck compare is ⊆ its A-vs-A null in the gate.
- **MINOR.**
  - The R8 edit now works by subtraction and preserves order, with a recompute self-check that is
    confirmed exact on 176/176.
  - The orphan test now covers all components.
  - Movie-with-`featureInfos` refusal.
  - B7 now allows 4 decodes per touched member.
  - A whole-run time bar and a disk budget.
  - The subset-run O1 baseline is now an A subset run.
  - Citation fixes: the disk guard is at :919, `card_styles` at :1154, and the zorder read-back
    raises `ValueError`.
  - "Metadata acceptance unknown" is narrowed: the add direction has precedent (`dsk_pill`,
    `mint_media_style`).
  - Unlink-vs-delete is re-justified on whole-deck-scan parity, not on Keynote safety.
- No repo-root `AGENTS.md` exists in this worktree, so the house rules came from `SKILL.md` and
  memory.

## Review log

- P1 (2026-09-23, Opus xhigh planner): first-pass plan. Keynote-free census of the source deck; five handover questions answered.
- P2 (2026-09-23, Opus xhigh critic): 1 BLOCKER (failure semantics), 4 MAJOR (Data/ mojibake names, reference-scan holes, R4 false refusals, oracle blind to writer edits), all folded in (§Critique (pass 2)).
- E (2026-09-23, offline dry run on FRC copy): PASS. 941 hides on 130 slides, 0 refusals (slide 122 excluded), 46 `Data/` (49.8 MB) dropped, 27.0 s at load ~7, differing slides = eligible set. Checker quirk: survivors' parent refs (`.super`, `SlideNodeArchive.slide`) show as diffs when their slide changes.
- C1 (2026-09-23, Codex GPT-5.6 Sol): BLOCK. 3 BLOCKER (fallback on an identity-refused slide uses source kindIndex; swapped equal-signature twins; opacity-0 fallback continues), 7 MAJOR (untouched-component data liveness, same-component ambiguous ids, header-less child refs, stat-based failure phase, slide re-encode not checked exactly/MM transition, checker blind to nested fieldInfos refs and to same-count uuid swaps). One is a new class (#8), the rest are edge cases of known ones.
- C1 fix round (2026-09-23): all 10 C1 findings fixed, none refuted (#2 by saved-geometry twin disambiguation, 0/130 FRC slides refused; #6 adapted: weak parent/stylesheet refs are never in headers). FRC dry run re-passed (941/130, 26 s). Suites green: 6334 passed.
- A1 (2026-09-23, Codex GPT-6 Astra H, advisory on decision 4): abort instead. 2 BLOCKER (save reorders groups; a global refusal discards per-slide unproven results), 4 MAJOR on the fallback session (dual-membership targets, unconfirmed close, not stopping at the first failure, document bound by name prefix), 1 MINOR (`mapReadback` is diagnostic only). The owner switched decision 4 to abort.
- A2 (2026-09-23, Codex GPT-6 Astra H, round 2 on 2c46a2cc): BLOCK. 15/17 earlier findings CLOSED; C1 #2 and #6 NOT CLOSED. New: 1 BLOCKER (group identity by child text vs ambiguity by richer saved signature: same-text/different-media twins swap undetected, reproduced in memory), 4 MAJOR (cross-member owned child without header ref; versioned Metadata refs unscanned; fallback doc path needs `as alias` + canonicalisation + cleanup on bind failure; dashboard hides recovery detail on fallback timeout), 1 MINOR (dismiss clears the retry-off; Apply ignores the proposal's saved override).
- A3 (2026-09-23, Astra H, round 3 on d6906cc7): BLOCK, narrowing. A2 #1 #3 #4 #6 CLOSED; C1 #2 / #6 and A2 #2 / #5 NOT CLOSED. The 4 findings are all edge cases of known classes, no new class: 1 BLOCKER (twin geometry disambiguation trusts `needs_keynote` approximate geometry: rotated-group swap, reproduced), 3 MAJOR (ownership checked on `objects[0]` only; case-insensitive AppleScript path `is` can close an unrelated doc; recovery requirement lost across a fresh Propose).
- A3 fix round + 5/5b (2026-09-23): all A3 findings fixed. The strict approximate-geometry rule refused FRC slide 20 post-save, so decision 5 excludes twin-risk slides before deferral. The first proxy cost 17 slides; 5b's `needsKeynote` on payload items brings that to slide 20 only. FRC dry run: 129 slides, 929 hides, 0 refused, 27.8 s at load ~4, planSha256 unchanged. Superset gap measured: off-axis masked images gain the flag at ≥2× upscale (0 at the benchmark's planned scale). If that happens the saved-deck check aborts the run; it never deletes the wrong object. Suites: 6389 passed.
- S4 (2026-09-23, Codex GPT-5.6 Sol H, round 4 on 5904e890 + design review of decision 5): no BLOCKER. Part 1: the exclusion is fail-safe (a missed case aborts, it never deletes a survivor), but it is not a complete predictor: the planned transform can push masked twins over `_MASK_TRUST_PX`. No general `group-residual` bound is justified. Recommends transform-aware eligibility, or excluding all twins. Part 2: 3 MAJOR, edge cases of known classes (strong-ownership fields beyond children/storage/mask, e.g. `fakeShapeForEmptyGroup`; closure requirement lost when jobs are deleted; Metadata not checked for exactness and the checker is blind to unprojected PackageMetadata fields). A3's 4 findings closed or closed-as-written except the ownership class.
- S4 fix round + 5c (2026-09-23): all 3 S4 majors fixed. The planned-size mask check covers only rotated-masked and group-residual-via-masked-child (the composer's scaling model is an assumption). FRC dry run: 129 slides, 929 hides, 0 refused, 24.4 s at load ~5; excluded slides 20 (twin) and 122 (builds); planSha256 unchanged. Suites: 6412 passed, test:ui 247.
- S5 (2026-09-23, Sol H, round 5 on dcb324ac): BLOCK, narrowing. S4 #3 and #4 CLOSED; S4 Part 1 and #2 NOT CLOSED. 2 MAJOR, edge cases of known classes: the mask scale uses rounded payload w/h, so a 99.51 px, 0.865° mask on a full-JXA slide crosses `_MASK_TRUST_PX` unpredicted; nested strong refs under text storage (attachments, footnotes, comment/highlight, pencil storage and tables) are unclassified. Reason-level size claim confirmed: only rotated-masked and group-residual via a masked child are scale-dependent. No other defects found.
- S5 fix round (2026-09-23): #1: any pre-hide masked size write pre-excludes the twin class, and `planned` covers only slides not in `suppressGeometry` (only slide 1 on FRC); #2: exhaustive reference classification, with unclassified refs refused. FRC dry run: 129 slides, 929 hides, 0 refused; excluded 20, 122; 37.6 s at load ~35 (not comparable). Suites: 6423 passed.
- S6 (2026-09-23, Sol H, round 6 on b936168d): BLOCK, 3 MAJOR, edge cases of known classes. S5 #1 (transform-aware eligibility) CLOSED: no approximate-geometry counterexample remains. Metadata exactness CLOSED. Open: (1) subtree closure follows every same-member header ref, so weak style targets and header-only comment/pencil refs can be pulled in, and unresolved forbidden refs skip classification; (2) a running resize job can be deleted before its fallback timeout records `needsFreshOutput`; (3) the dashboard's closure confirmation is keyed by job ID only and never consumed, so a stale confirmation survives a second timeout. Fix round 7 (2026-09-23): all 3 fixed and committed, suites 6455 passed / test:ui 248. NOT yet reviewed, and NOT dry-run on FRC: the new header-only-ref refusal is unmeasured on real decks.
- 2026-09-24: merged origin/main (#217, no overlap) as a5060ddf; suites 6848 passed. FRC dry run on round 7: 129 slides, 929 hides, 0 refused (the header-only rule never fired), excluded 20 and 122, planSha256 unchanged; 32.5 s at load ~45 (not comparable).
- S7 (2026-09-24, Sol H, round 7 on a5060ddf): BLOCK, 4 MAJOR + 1 MINOR, all edge cases of known classes. S6 #1 and #2 CLOSED; the census found 0 unattributed header refs in 31,364 FRC and 14,313 Gold archives. Open: (1) closure confirmation is an unbound boolean (export-dir switch, a queued job behind a new timeout, concurrent Apply); (2) subtree/reference refusals after a proven identity lose `order_proven`; (3) twin eligibility ignores planned x/y, so an exact move of a survivor onto the hide rect on a pre-hide-geometry slide aborts post-save; (4) the checker silently keeps the first archive for a duplicate id; (5, MINOR) signature-restating private docstrings.
- S7 fix round (2026-09-24): all 4 majors and the minor fixed. Timed FRC dry run on a5060ddf: 28.4 s at load ~7 (the ≤ 30 s gate passes), 129 slides, 929 hides, 0 refused; unchanged after the fixes (the re-run was at load ~40). Suites: 6860 passed, test:ui 249.
- S8 (2026-09-24, Sol H, round 8 on 3500a3b3): BLOCK, 6 MAJOR, edge cases of known classes. S7 #3 (twin eligibility is now a superset), #4 and #5 CLOSED. Open: dashboard closure lifecycle x4 (ns generation exceeds JS safe integers; re-apply to a clean destination drops an unconfirmed marker; a concurrent Apply mutates a queued job before its 409; markers store a non-canonical path); writer x2 (duplicate ids / second PackageMetadata only recorded, not refused; "slide archive shared with another slide number" wrongly `order_proven=True`). The dashboard lifecycle has drawn a major in 5 consecutive rounds.
- S8 fix round (2026-09-24): writer #5 and #6 fixed; dashboard #1–#4 made moot by decision 6 (in-memory restart lock, −481 lines). Suites: 6857 passed, test:ui 246.
- S9 (2026-09-24, Sol H, round 9 on 5f1f36a0): BLOCK, 4 MAJOR. S8 #1, #2 and #4 CLOSED as moot by decision 6; S8 #5 and the decision-6 lock CLOSED. Open: (1) shared-slide detection counts only targeted aliases, so a one-target/two-alias archive is patched; (2) a rejected concurrent Apply still mutates a queued job's destination (general, not recovery-specific); (4) the checker recognises PackageMetadata only as objects[0]. (3) "deletion guard regressed" is REFUTED by design: decision 6 removed the closure-based deletion refusal. The in-memory lock protects the deck regardless of job records, and Apply's 409 carries the restart message.
- S9 fix round (2026-09-24): #1, #2 and #4 fixed (#3 refuted by decision 6). Suites: 6863 passed; test:ui 246 (one unidentified failure at load ~35, not reproduced in 4 reruns). FRC has no shared slide archives. Owner: round 10 reviews use Opus first.
- O10 (2026-09-24, Opus HIGH, round 10 on 042bc6b4, owner: Opus first): PASS with minor fixes, no BLOCKER or MAJOR. S9 #1, #2, #4 CLOSED; #3 refuted by design. 8 MINOR: HidesWriteFailed not routed to OfflineHidesAborted on the dashboard (MAJOR once default-on); CLI prints a traceback instead of `detail`; unreachable `except Exception` branch plus its stub-only test; the `Applied` line moved even when hides are off; the notice shows CLI-only advice; gate process (run B's subset in verify mode and patch its `.pre-hides.key` offline before a full pair); `_rewrite_members` phase typing changes 11 callers with no pinning test; positional tuples and long private docstrings. Fix round 11 (2026-09-24): all MINORs fixed; suites 6864 passed, test:ui 246. #6 is folded into `f-live-gate`: before pair 1, run the B subset in `verify` mode with `OBED_DEBUG_PASS1_SNAPSHOT` and patch its `.pre-hides.key` offline. It is the first measurement on a Keynote-saved post-pass-1 deck.
