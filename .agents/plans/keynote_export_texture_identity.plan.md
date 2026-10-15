# Rev 4 — folds Opus 5.5 high critique r3 (final round)

Status: FINAL for owner review, 2026-10-14. All nine r3 findings accepted; prior folds retained as corrected here. Offline rewrite only; no implementation, measurements, tests, suites, git, apps or owner acceptance. Supplied base: `origin/main 5b09b379 + docs`, Stage T merged #267, unverified.

Anchors: `pt` = `preview_textures.py`; `hp` = `html_preview.py`; `ir` = `iwa_runs.py`; `ki` = `iwa_kindindex.py`; `oi` = `offline_inspect.py`, under `src/obed_edom`. Evidence: adjacent `advisory.md`/measurements, `../critique-r2.md`, `../critique-r3.md`, and prior offline results; not rerun.

## 1. Problem and measured basis

F2-html, player `17c0c938`: slide-4 Malaysia `(588,827,176,205)` wrongly uses `DF3DB700…`, the local 5850×4368 Asia winner; R1+R6 flag it. Previous slide 3 MM `contents.to` provides the correct 176×205 donor, PDF page 15. Source 15355064 → data 44137 → destination 15348427. `_d2` finds it (`pt:577`); plain images lack verification (`pt:663–685`).

Other map: 15355057 → data 44140 → 15348425, destination `(939,807,357,235)`, donor page 14 `B37026D5…`. Correct in the real export; only G1's labelled synthetic variant damages it. Both source wrappers have opacity 0; leaf opacity is 1. Ignoring visibility/opacity is necessary.

Prior measurements: 31/31 mutually unique tight floor/ceil pairs; source/donor correlations 0.98472/0.99573, thumbnail std 49.5/49.1 and 43.9/43.5. Wrong-size alternatives score 0.908/0.944; pixels cannot replace geometry/size. `_corr` checks equality before flatness (`pt:352`). Accessibility matches 13/47 base occurrences, with both MM witnesses individually verified; it adds no independent geometry proof and is excluded.

R2: **18/57 eligible** non-movie type-5 base/MM leaves, including all four map endpoints. The 26 unique ImageArchive matches include eight masked-emblem 15347050 copies, excluded by I1.1. Each map has exactly one own-tree MM landing and one matching single-page source member; donor sizes agree. Malaysia's group has one member; general groups require every-member proof.

Stage T remains: D4 independent pixels, movies objectID-only, exactly one re-export after `TextureRepairRefused`; 3b9019 slide-9 D4 proof and slide-10 refusal. Its tag-box landings lack `contents.to`.

## 2. Implementation stream and source lifetime

One later **Codex GPT-5.6 Sol high** implementer; **Opus 5.5 high** integrated review. No agents now. One stream: `preview_textures.py`, `html_preview.py`, both existing test files, and two source-aware G1 EXPECT rows in `scripts/texture_repair_check.py`; no new module. Reserve/serialize `tests/test_preview_textures.py` with Stage B; preserve assertions and derive feed sizes/captures from served repaired JSON.

Add optional `source_path`/`source_digest` kwargs to `repair_textures`; `hp.apply_preview` passes both on both attempts (`hp:1088`). Add `_Slide.slide_id: str | None = None` via `.get("originalSlideId")`. Match by original slide id, never export index, including skipped slides. No-source callers retain existing behavior.

Lazily import `_load_deck_full` from `iwa_runs` at call time; reuse `_load_deck_full(strict=True)` (`ir:225`), `iwa_kindindex._geometry` on raw `drawablesZOrder` (any kind, once per id), `offline_inspect.data_member_index` (`oi:58`) and `_Renderer.thumb`. Write selected PDF bytes to generated filenames in `_plan`'s scratch, never extract ZIP paths. Count duplicate ZIP entries before the index collapses them; require one matching data member. No broader `SourceSlide`, generic context API or persisted decoded dictionaries.

> Load IWA once per attempt on first need; read members as needed; run the single digest check once, immediately after `_plan` returns (`pt:887`) and before the `refused` raise (`pt:888`), whenever evidence was read. Refuse the candidate only on `UndecodableIWAMember`, `zipfile.BadZipFile`, a missing or duplicate member, `ImportError` of the iwa extra, or unresolvable geometry. Other exceptions propagate.

Count the source pages and render with Quartz (`CGPDFDocumentGetNumberOfPages`, `_Renderer.thumb`), which return None instead of raising. Do not run pypdf on the source bytes. A slide id that is absent, or is not a `KN.SlideArchive`, refuses the candidate.

Require `deck_digest(path) == source_digest` (handed-off `manifest.sourceDigest`); mismatch raises `PreviewStale`, bypassing retry and using existing export cleanup. Recompute each attempt; no cross-attempt cache or extra before/after/commit checks. Existing prepare validation remains. Unsatisfied certificate predicates below supply no proof.

## 3. Certificate: all rules must pass

### I1. Direct identity at both endpoints

Leaf frame equals floor/ceil+1 of exactly one top-level drawable's raw geometry within 0.01; it is an eligible ImageArchive, with no competing drawable or leaf within I1.3's 0–4 px envelope. No accessibility requirement.

**I1.1 — eligibility.**

> Every destination member leaf and the witness leaf has `textureType 5` and is not `isVideoLayer`.

Object must be `TSD.ImageArchive` with no `mask`. Preserve movie-owner ambiguity protections; a missing wrapper id creates no new movie route. Ignore visibility/opacity. Defer optional `geometry.angle == 0` and appearance tightening: no style-inheritance, stroke, shadow, reflection, adjustment or flip-bit interpretation. Appearance can lower pixel agreement and fail closed. No canvas, affine, ancestor, sublayer or contentsRect checks.

**I1.2 — frame.** Finite raw `(x,y,w,h)`, positive dimensions: `L=floor(x)-1`, `T=floor(y)-1`, `R=ceil(x+w)+1`, `B=ceil(y+h)+1`. Leaf equals `(L,T,R-L,B-T)` within 0.01 logical px, without off-canvas clipping. No nearest-frame selection, rounding, filename/order inference or accessibility link.

**I1.3 — two-way uniqueness.** Domain (a): leaves in the candidate's own tree within the envelope, counting identical duplicates; domain (b):

> (b) every `drawablesZOrder` entry of the slide, any `_pbtype`, with geometry from `iwa_kindindex._geometry`, counted once per id. An entry with missing or non-finite geometry refuses the candidate.

> Hidden and opacity-0 leaves count as competitors. 'Tree' is the leaf path's prefix through its last `baseLayer`.

For selected drawable, count own-tree leaves; for selected leaf, count top-level drawables. Each count must be one. Each outward leaf edge is 0–4 px from the raw drawable edge, with 1e-3 slack. Check competitors before image eligibility; groups/other kinds can disqualify. Different base/effect trees are not simultaneous competitors. Identity is scoped to source revision/original slide.

Do not traverse master/layout objects, placeholders or group descendants; their separately rendered leaves count in (a). The render premise is that the matched image has its own leaf in this tree, not that all images always do. F2 slide 4 event 1 is a flattened type-0 composite: I1.1 excludes it; MM landing, equal data and pixels support destination identity. Non-rendering competitors' absence alone proves no content identity.

### I2. Unique MM witness, equal data and size

> Count every previous-slide MM leaf that `_landings(own=True)` lands on any group member, before `_d2`'s filters. Exactly one is required, and it must carry a genuine `contents.to` and pass `_d2`'s existing filters.

`_d2` attaches to the `_Fix` the unfiltered `_landings(previous, slide, own=True)` triples whose target is a group member. The image branch counts those, and checks the single survivor's `_end_rect(leaf)[0]` is non-empty.

Include no-contents, wrong-size, bad-texture and untrusted landings across all previous-slide events. Preserve unique event-0 landing within 0.01, **leaving text D2's set semantics unchanged**. Equal donor ids cannot collapse multiple witnesses into proof.

data id = `ImageArchive.data.identifier` (never `thumbnailData`). Resolve witness/destination independently through I1; nonempty data ids must match in the verified revision and resolve to one member. File-changing MM refuses. Preserve R1b/`_trusted_landing`; no witness selection by pixels. Donor table dimensions equal destination dimensions within 0.01. Keep V1 mediabox/page-index checks and `_end_rect`; no independent MM-transform, source-aspect or PDF box-origin/rotation restriction.

### I3. Every group member

Every member resolves through I1 to the target's same IWA object, in its own tree; otherwise refuse the whole group. Unresolved members inherit no proof. No partitioning or Stage T grouping change.

### I4. Independent source pixels

Require a single-page source PDF; render it and donor using `_Renderer.thumb`'s 64×36 grey profile. Both thumbnails finite with std ≥2 **before** equality/correlation; finite unrounded corr ≥0.9, recorded raw. No source/display size/aspect or native-size source/donor equality requirement. Unsupported raster/failed decoding supplies no proof. Keep V1/V4; pixels override no identity/witness/group/size failure. Existing D4 thresholds/flat handling remain.

## 4. Writes, record, cache and refusal

Use existing graft writer (`pt:754–813`): append donor page, fresh recipient-local id, repoint certified textures/matching `contents.from`, regenerate JSON/JSONP/PDF/PDFP. Preserve winner, geometry, timing, opacity, `contents.to`, player code and `SUPPORTED_PLAYERS`. Plan all fixes before writes; unresolved hits use existing aggregate refusal/cleanup. Exactly one `TextureRepairRefused` re-export; stale source is not retried.

D2-image records `verify = {"corr": <raw>, "object": <dest IWA id>, "sourceObject": <MM-source IWA id>, "data": <data id>}`. Keep outer D2 rule, donor provenance and `entry.leaves`; no nested proof version, duplicate digest, member hashes/list, frame/appearance/profile fields. Nothing consumes `repaired[].verify`. Keep **`TEXTURE_REPAIR_VERSION = 1`**:

> The new route turns v1 refusals into repairs and can pre-empt D4 where both exist (none in the corpus). v1 caches remain verified repairs; no bump.

`_plan` tries D2 before D4; refused exports are deleted, never cached.

## 5. Tests and later full validation

No new test file. Add rows to `test_repair_picks_the_rule_and_writes_a_consistent_export`:

> (1) D2-image success with opacity-0 source (documentary: opacity is never read), verify keys and graft;
> (2) envelope competitor → refused;
> (3) differing MM-source data id → refused;
> (4) the destination's event-1 copy (same group) has an envelope competitor leaf in its own tree, so the whole group is refused. This covers I1.3(a) and I3.
> (5) row (1)'s build with a wrong `source_digest` raises `PreviewStale`, and the snapshot is unchanged.

Row (1): reuse S1/S2/`TO`/100×20 for shared D2 assertions (`D2_ID`, dims, page count; `tests/test_preview_textures.py:373–381`). Source PDF and donor use existing `"L"` fill; blank pages fail std ≥2. New rows add `originalSlideId` to `_export`'s slides and pass the source kwargs through `_repair`.

Monkeypatch `iwa_runs._load_deck_full` with decoded dict plus ZIP containing one `Data/…pdf`; precedent: `tests/test_offline_write.py:1359`. `conftest.py:79` wraps the real loader. No manufactured IWA bytes. Reuse writer/no-write assertions; retain no-source refusal (`:386`), raw-correlation and `wrong-version` rows (`tests/test_html_preview.py:433,446`, already `version + 1`). Update verify-key assertion (`:362`). Extend `test_apply_repairs_textures_before_conversion_with_one_re_export`'s `_repair` stub to assert both kwargs on both attempts.

Targeted tests during folds; **FULL local suites before every code PR**, Python 3.12 and 3.10 floor, final integrated commit after peer releases machine. Follow final-tree commands including applicable maps/performance checks; `test:ui` if UI touched. Report interpreters/counts/failures. No CI; no runs now. Owner rule: `/Users/anyhowclick/.claude/projects/-Users-anyhowclick-Desktop-work-obed-edom/memory/feedback-run-full-suite-locally.md`.

## 6. Later gates

### G1. Offline repair and regression corpus

Schedule after machine release; register existing evidence per OQ-5. G1 temp copies may use system temp. They must be outside every `output/` and `tests/fixtures/`. `--out` goes in the session scratchpad. Add an INCONCLUSIVE outcome so that a missing F2 file or a hash/digest mismatch (including a `PreviewStale` from the pinned digest) makes `run_g1` exit 3.

> Two EXPECT rows sharing one source key: `F2` (D2×1) and `F2/synthetic-357` (D2×2). The script applies the documented JSON+JSONP mutation to its temp copy. Slides come from `html_preview.source_slides(F2.key)` zipped onto `header.slideList` (F2 has no skipped slides; assert the counts). Pass `source_path` and a `source_digest` pinned to `9fc882c1…`.

Preserve source originalSlideId/ordinal and exported UUID/player index, bypassing manifest-less header fallback. Full source pin from existing advisory: `9fc882c130dffd2d600d816d98f97ea01a2f3a1e38ae9ef4127254c6296a55e1`. Pin F2.key's sha256 and one sha256 over the sorted `(relative path, sha256)` list of the files `copy_minimal` copies from F2-html. Never automatically bless observed replacements.

Baseline: real Malaysia → slide 3 page 15; verify other map without damage. Synthetic: change slide-4 `(939,807,357,235)` leaf texture to winner `DF3DB700` using complete existing table ids; synchronize JSONP. Expect R1+R6, D2 → page 14 `B37026D5`, alongside Malaysia. Record exact injected field/input hashes; label **synthetic defect, real chain/donor**, never captured failure.

Assert empty post-repair R1/R1b/R4/R6, unchanged texture-blind JSON fingerprint/winner, JSON/JSONP and PDF/PDFP agreement, empty second pass.

Preserve Alpha D1×1/D2×3/D3×1; qual-decks D2 via D3 ×2; across-first-build D3 ×1; 3b9019 slide-9 D4/slide-10 refusal; clean controls and original ordinals, including Alpha's skipped slide. Fixture absence is unavailable evidence, not PASS. Both supported players retain Stage T outcomes, no new fixes/refusals. F2 proves the player-independent source positive on `17c0c938`; no old-player positive gate or player-specific route gating. Compare continuity plans; Stage B rechecks served repaired JSON bindings.

### G2. Live F2 prepare and Alpha regression

After peer release/live availability, one normal F2 prepare with existing single retry; record source/player digests, repair/clean/refused outcome and result. Clean or different legitimate refusal does not replace G1. Run real Alpha_DSK prepare/player regression, preserving text/poster/D4 and Stage B bindings; no extra OBS pass.

> Every successful G2 prepare leaves a cache under the serving checkout's `output/.html-preview/<digest>-p3-r1/html`: F2 `9fc882c1…` and Alpha_DSK `bf1c093f…` (re-read the digests at G2). When served from main, the real-export censuses glob these caches (`tests/test_live_runtime.py:1391`, the handback census). After G2 is recorded, and before any later suite run, Trash each cache G2 created, unless the owner chooses to keep one. Report which caches were created, kept or Trashed.

### G3. Owner eye on persisted repairs

> Make a full copy of F2-html (and of the synthetic variant) in the session scratchpad, outside every `output/`. Repair it with the same call, record its hashes, and serve exactly that copy.

Persist both through review, outside `tests/fixtures/` too; include `index.html` and complete player bundle. G1's `TemporaryDirectory`/`copy_minimal` output cannot supply G3. Use G1's pinned inputs, slides, kwargs and mutation. Owner views actual baseline/synthetic repairs via existing host; record live outcome separately. Check move 3→4, settled slide 4, both maps' geography/position/scale/crop/opacity and Asia background. Record artifacts/owner result. Pending, not acceptance.

## 7. Owner questions with recommendations

**Owner decision 2026-10-14: OQ-1 to OQ-7 all as recommended; go to implement.**

- **OQ-1 — scope. Rec:** unmasked top-level PDF ImageArchive; opacity-0/off-canvas allowed. Defer raster/appearance/angle guards and flip interpretation. Owner eye assesses theoretical same-data/different-crop collision; style resolution risks refusing the 357×235 map (`TSDEmptyPattern` stroke, empty reflection).
- **OQ-2 — pixels. Rec:** 64×36 grey corr ≥0.9, both non-flat checks, exact frame/size. No aspect guard, higher threshold or raw-source/native-page equality without broader labelled evidence.
- **OQ-3 — injection. Rec:** no description tokens; defer scratch-export experiment until justified.
- **OQ-4 — widening. Rec:** preserve D4/slide-10 refusal; no image D1 or no-contents graft.
- **OQ-5 — evidence retention.**

> Rec: keep the evidence where it already lives, `~/Desktop/Convert wall to 16x9 CGs/F2.key` and `F2-html/` (owner's folder, read-only). Pin F2.key's sha256 and one sha256 over the sorted `(relative path, sha256)` list of the files `copy_minimal` copies from F2-html. Record both pins; absence or mismatch is INCONCLUSIVE (exit 3), never PASS. Never copy any F2 export, slice or repaired copy under the main checkout's or any worktree's `output/`, or under `tests/fixtures/`. G3 copies go in the session scratchpad; G1 may use system temp.

Real-export censuses recursively scan output headers, including `.html-preview`; fixture shadow-DOM/dissolve scans also apply. Handle G2's generated cache explicitly above.

- **OQ-6 — version. Rec:** keep version 1 for §4's reasons. Owner's uniformity alternative: bump with one-time re-exports.

- **OQ-7 — owner review. Rec:** use persisted full G1-equivalent repairs and labelled synthetic variant even if live export is clean; record live outcome separately.

## 8. Revision log — r3 dispositions

All 24 r1/r2 folds retained as corrected above; all nine r3 findings accepted, including both cuts. No refutations or new measurements.

| Finding | Severity | Disposition and location |
|---|---|---|
| 1 | Major | Folded, G2: serving-checkout F2/Alpha caches; cleanup before later suites, owner keep exception, report. |
| 2 | Low | Folded, §2: digest immediately after `_plan`, before refusal. |
| 3 | Low | Folded, §2: Quartz source pages/render; no pypdf; invalid slide id refuses. |
| 4 | Low | Folded, I2: `ImageArchive.data.identifier`, never thumbnail. |
| 5 | Low | Folded, I2: unfiltered own-tree triples on `_Fix`; nonempty survivor end rectangle. |
| 6 | Low | Folded, §5: wrong-digest `PreviewStale` row, unchanged snapshot. |
| 7 | Low | Folded, G1: system temp allowed; scratch `--out`; INCONCLUSIVE exit 3. |
| 8 | Low | Folded, G1/OQ-5: source pin plus one sorted-file tree digest; per-file pins cut. |
| 9 | Low | Folded, G1/G3: duplicate native-render equality and Alpha visual checks cut. |

Plan critique closed after r3 (0 blocker; the r3 major is a wording fix folded here); stop rule.
