# Robustness advisory: source identity for Magic Move image grafts

2026-10-14. Read-only review of `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808`, the supplied investigation and merged Stage T plan, F2.key/F2-html, 18 fixture exports, and the older Alpha 3b9019 export. No git, apps, browser, OBS, Keynote, osascript, pytest, or suites were run. All deliberate output is in this directory. Offline Python and small Quartz renders only; the requested `nice -n 15` wrapper was used, but this sandbox reports `setpriority: Operation not permitted`, so reduced scheduling priority cannot be claimed. Measurements were bounded, serial, and short.

Citation prefixes below are repository-relative: `pt` = `src/obed_edom/preview_textures.py`, `hp` = `src/obed_edom/html_preview.py`, `ki` = `src/obed_edom/iwa_kindindex.py`, `ir` = `src/obed_edom/iwa_runs.py`, `oi` = `src/obed_edom/offline_inspect.py`, `ig` = `src/obed_edom/iwa_geometry.py`, `iw` = `src/obed_edom/iwa_write.py`. Counts are observations, not proof of universal exporter contracts.

## 1. Recommendation and principal findings

Implement a **narrow, positive source-identity verifier for D2**, initially for simple, top-level, unmasked PDF images. Keep movies objectID-only and keep the existing D4 page-to-page agreement route unchanged. The F2 Malaysia donor satisfies the proposed chain. A second map has an equally strong chain and donor but is not damaged in this raw export. Do not promote geometry, filename, order, source data id, or correlation alone into identity.

The coordinator's direction is sound, with six necessary refinements:

1. Replace arbitrary containment with the observed pixel-expanded frame, plus uniqueness in both directions. On F2 all 31 tight image/accessibility pairs obey `left=floor(x)-1`, `top=floor(y)-1`, `right=ceil(x+w)+1`, `bottom=ceil(y+h)+1`. This is much stronger than “within 4 px.” Keep the broader 4 px envelope for detecting competitors, not accepting approximate matches.
2. Prove every rewrite member's identity. `_same_object` and `_groups` (`pt:434,443`) currently merge non-text images across events by old texture, approximate rect and movie ownership; their text key is always None. Verifying only `group.first` would let a different image in another event inherit the repair.
3. Count MM **witnesses**, not just distinct donor texture strings. `_d2` (`pt:577`) collapses donors into a set of ids. Two different source objects/events can supply the same id. Require exactly one eligible source MM leaf and unique event-0 destination, with retained source event/path and accessibility index.
4. Do not reject source objects merely for IWA opacity 0. Both small F2 source maps have opacity 0 in their media styles. Their MM leaves carry actual textures and land on visible destination images. Geometry/content proof must be independent of visibility; preserve all visibility and opacity state.
5. Keep the 64×36 correlation backstop at 0.9, with a positive non-flat requirement for this new route. Native-size exact comparison is disproved by the correct donor. Add source aspect and supported-appearance guards; threshold escalation is not an identity substitute.
6. Do not promise general image or Alpha tag-box coverage. Only 13/47 F2 image-type base-leaf occurrences resolve through the strict top-level raw-geometry chain. The 3b9019 tag boxes have **no tight accessibility match**. Injection cannot repair the leaf-to-accessibility gap.

## 2. Measurement method and coverage

Evidence artifacts: `measure.py`, `corpus-measurements.json`, `f2-leaf-identities.json`, `detail.py`, `detail.txt`, `extra.py`, `extra.txt`, `pixels.py`, `pixel-measurements.json`. IWA JSON snapshots and the two extracted source PDFs are local diagnostic inputs, not proposed repository fixtures.

The corpus census reads event base trees through `pt._load/_event_leaves`. An “image-type leaf” below is `textureType == 5` with no direct `_movie_of` binding. **This includes shape textures, group composites and flattened movie copies; it is not a count of source ImageArchive objects.** This denominator deliberately exposes why type 5 cannot establish image identity. Events and repeated fixture copies are counted separately; these are not 19 independent exporter implementations.

For the broad census, a tight pair means the accessibility rectangle is inside the leaf, with each edge gap 0–4 px (1e-3 numerical slack). Mutual uniqueness requires one entry per leaf and one base leaf per entry in that event, considering all leaf kinds. IWA comparison uses all four unrounded coordinates within 1e-3 and exactly one top-level drawable record; success additionally requires `TSD.ImageArchive`. No filename filtering or nearest-neighbour selection is used. The proposed acceptance rule is stricter than this census: the exact floor/ceil expansion above and appearance guards.

| Export | Player | Slides / events | Accessibility entries | Entries with exactly one tight base leaf | Image-type leaves / mutually unique entry | Exact top-level IWA image chain |
|---|---|---:|---:|---:|---:|---:|
| F2-html | 17c0c938 | 9 / 16 | 94 | 31 | 47 / 31 | 13 / 47 (27.7%) |
| Alpha fixture, html-unmodified | 17c0c938 | 10 / 19 | 42 | 7 | 35 / 7 | Revision-matched source absent |
| gl-decks/Minimal Alpha_DSK | e9b2fad4 | 9 / 20 | 29 | 8 | 52 / 8 | Revision-matched source not established |
| minimal-alpha-dsk-17c0c938 | 17c0c938 | 9 / 20 | 29 | 8 | 52 / 8 | Same limitation |
| gl-decks/Positive Control | e9b2fad4 | 4 / 8 | 4 | 3 | 8 / 3 | Revision-matched source not established |
| p2-binary, p2-loop, p2-loop-grey, recovery, recovery/gl-replay (each raw) | e9b2fad4 | each 4 / 10 | each 8 | each 5 | each 27 / 5 | Source absent from fixtures |
| p2-soak-loop raw | e9b2fad4 | 9 / 20 | 29 | 8 | 52 / 8 | Source absent; PDFP-only limitation remains |
| D1 | e9b2fad4 | 4 / 8 | 12 | 3 | 3 / 3 | Source absent |
| D2 raw; D2 across-first-build; D2-across | e9b2fad4 | each 5 / 10 | each 15 | each 3 | each 3 / 3 | Source absent |
| D3 | e9b2fad4 | 4 / 8 | 14 | 5 | 7 / 5 | Source absent |
| D4 | e9b2fad4 | 3 / 7 | 13 | 5 | 3 / 3 | Source absent |
| D5 | e9b2fad4 | 3 / 6 | 11 | 4 | 8 / 4 | Source absent |
| D6 | e9b2fad4 | 5 / 10 | 16 | 5 | 6 / 5 | Source absent |
| **19-export total** | both | **104 / 222** | **378** | **121** | **417 / 119 (28.5%)** | No defensible pooled source percentage |

Of 378 accessibility entries, 243 have no tight leaf, 121 have one, and 14 have multiple. Of 417 image-type leaves, 286 have no tight entry, 119 have one mutually unique entry, and 12 have multiple. Unbounded containment gives multiple enclosing leaves for 186/378 entries (49.2%); F2 alone has 49/94. Backgrounds and the huge off-canvas Asia map make this an actual ambiguity, not a hypothetical one.

F2 event-0 coverage is 8/25 image-type leaves (32%). Across all F2 events, accessibility-to-any-top-level-IWA-drawable matching succeeds uniquely for 19/94 entries; 75 do not match. Across its nine source slides there are 22 top-level images: only 8 have a raw-geometry event-0 accessibility match, versus 18 with the existing composed-geometry helper. That improvement is diagnostic only: `ig:377–405` explicitly has masked/rotated/approximate paths, so composed geometry is not automatically an identity certificate. The investigation's “every top-level image matches exactly” overstates raw geometry: F2 slide 3's masked emblem is 85.171036×85.16276 in raw IWA but its accessibility target is 85.162757×85.162757. The event-0 report-card PNG has a leaf but no corresponding accessibility entry; it appears in event 1.

Source limitations were checked rather than filled in by assumption. The current local Alpha_DSK.key hashes to `bf1c093f…`, whereas the fixture's manifest names `7e3c9301…`; the old cache is `3b9019f0…`. Diagnostic matching against current Alpha, using manifest slide ids, gives 6/42 and 6/38 accessibility-to-IWA matches and **zero** complete image chains. These are not regression success rates for the exported revisions. Local Minimal and Positive Control comparisons similarly give zero image chains, with unproven source/export revision pairing. Fixtures contain HTML, not their source `.key` files. F2 has no source-digest manifest tying this raw export to the current file either; its specific map chains are independently observed, while the future live prepare must establish the source revision. Current F2 digest: `9fc882c130dffd2d600d816d98f97ea01a2f3a1e38ae9ef4127254c6296a55e1`.

JSON-only detector results reproduce the expected distribution: F2 1 R1; Alpha fixture 6; D2 4; D2 across-first-build 2; all other census exports 0. Full F2 detection adds one R6 on the same Malaysia leaf. No corpus-wide pixel suite or repair was run.

## 3. F2 chain and pixel evidence

| Link | Malaysia | Third map |
|---|---|---|
| Source slide / object | 3 / 15355064 | 3 / 15355057 |
| Source accessibility / raw IWA frame | (939.6598, 847.30927, 17.811296, 20.810328) | (973.7362, 845.82404, 36.208515, 23.780859) |
| MM source event / path | 1 / effects/0/baseLayer/layers/11/layers/0 | 1 / effects/0/baseLayer/layers/10/layers/0 |
| Source data id | 44137 | 44140 |
| Destination slide / object | 4 / 15348427 | 4 / 15348425 |
| Destination accessibility / raw IWA frame | (589.8989, 828.8279, 172.87213, 201.98) | (940.1916, 808.13135, 354.18378, 232.61914) |
| Destination texture rectangle | (588, 827, 176, 205) | (939, 807, 357, 235) |
| Previous-slide contents.to / PDF page | DF3DB700… / 15 | B37026D5… / 14 |
| Data member | Data/pasted-image-44137.pdf | Data/pasted-image-44140.pdf |
| Correct donor/source correlation | **0.984719** | **0.995735** |
| Wrong Asia page/source correlation | 0.319103 | −0.236116 |
| Other small page/source correlation | 0.908112 (44×50) | 0.943669 (88×59) |
| Native destination-size correlation | 0.895731 | 0.944984 |
| Native-size exact equality | false | false |

Rendering used the existing `_Renderer.thumb` and `_corr` (`pt:302,348`), over 50% grey. Native-size comparison changed only thumbnail dimensions to 176×205 and 357×235; mean absolute differences were 5.912 and 2.504 grey levels. It did not attempt image registration or border removal. This disproves a naive native-size exact comparator, not every possible registered appearance comparator. The true donor's padding and rasterization differ from the raw source. Larger rendering or threshold tightening cannot be justified from two positive PDF examples.

The wrong-size high scorers are excluded by D2's landing/size checks, not the correlation threshold. Likewise, global “best matching page” search would remove a necessary structural constraint. Require positive non-flat source and donor thumbnails before calling `_corr`: it currently returns 1.0 for byte-equal arrays **before** its low-variance guard (`pt:352–355`), so two blank pages would otherwise count as evidence. Scope this change to the new source verifier to avoid silently changing Stage T's existing D4 behavior.

Keep V1 exact donor page mediabox vs table dimensions (0.01 px) and table vs destination size (existing 1.5 px); for this new route additionally require donor size to equal the quantized landing size within 0.01. Validate finite positive dimensions, integral nonnegative page index, page existence, zero/understood page rotation and page-box origin. `_mediabox_ok` currently lacks a negative-index guard (`pt:640`). The source PDF natural aspect should agree with the **unexpanded IWA image** aspect, not with the padded texture box; recommend relative error ≤1e-3 for the initial simple-image route. Both small F2 maps satisfy this. Raw source dimensions need not equal display dimensions.

## 4. Failure modes, by identity link

| Case | Evidence / failure | Required behavior |
|---|---|---|
| Leaf → accessibility | Containment ambiguities measured above; text IoU helper `pt:489` was designed for labels, not image identity. | Exact quantized frame and mutual uniqueness in the relevant render tree; reject all near-frame competing entries/leaves. Never pick smallest containing box or highest IoU. |
| Grouped/nested images | `ki:98` enumerates top-level drawables; child coordinates may be parent-local, absent, or composed through masks/transforms. F2 has 20 GroupArchive records, but this audit does not claim complete descendant coverage. | Initial route excludes grouped/composite targets. Do not search all deck objects for a coincident local frame. Traverse source ancestry enough to establish top-level ownership and detect unresolved competitors; reject if uniqueness depends on guessing a group transform. |
| Rotated/flipped images | `_walk` (`pt:150`) sums position/anchor offsets without general affine composition; `_end_rect` (`pt:234`) only applies scale and translation. F2 itself contains a rotated hidden type-5 line. | Check leaf and ancestor transforms, source geometry and flip/mask fields. Reject rotation, reflection, shear, unsupported ancestor scale/clip, contentsRect crop, or unsupported animation. Do not retrofit a general affine engine in this fix. |
| Masks/crops | F2 masked emblem fails the exact raw-geometry link; composed frames can restore geometry but do not restore full-image appearance. Same data can produce many crops. | Exclude masked/cropped images and source appearance effects for the new route. Equal data id does not prove equal rendered content. Future support requires a verified destination appearance descriptor/renderer. |
| Image fill in a shape | `textureType 5` includes `TSWP.ShapeInfoArchive` output; data may live in style/fill, with stroke, path and clipping. F2's tag-like rounded rectangle is such a shape. | Require an actual ImageArchive at both ends. Do not follow arbitrary style data to “make it an image.” |
| Duplicate same-file objects | Same data id proves asset identity, not object identity or crop. Real Minimal slide 8 event 1 has two identical `Untitled.mov` entries and two leaves at (31,717,1191,341); also slide 9. | Preserve entry multiplicity, including identical text/rect entries. Require unique geometry on both sides and unique source object, not distinct-name or distinct-id sets. Movie duplicates remain in the existing objectID-only machinery. |
| Same frame across slides | Unchanged geometry can contain a new file or new styling. | Resolve each slide independently by manifest originalSlideId, then require equal data id and valid destination appearance. No ordinal-only join, rect-only join, filename join or digest-across-decks join. |
| MM changes source file | A legitimate contents transition may replace file A with B. | Refuse this new route if data ids differ, even if pixels correlate. Supporting this is separate scope; contents.to alone does not expose destination asset identity. |
| Builds / moved objects | F2 report-card accessibility is absent at event 0 and present at event 1. Later trees flatten wrappers and shift indices. Accessibility can describe a different build state. | Use each leaf's own event and current geometry; no event-0 substitution. If an MM witness cannot be matched in its event, refuse. Missing information is not permission to borrow another event's identity. |
| Multiple events / multiple MM witnesses | Current group/set construction can hide a second source or an in-place swap. | Validate every group member, retain event/path, require one witness to the event-0 destination. Split independently proven objects; refuse unresolved hit members. Do not fan out a successful proof to unresolved copies. |
| Hidden / opacity 0 | 75/417 census image-type base leaves have hidden=true. Leaf opacity 0 count is zero, but F2's two source images have IWA style opacity 0; opacity may live on wrappers. | Do not discard invisible competitors. Preserve visibility/opacity. Permit property-only opacity/hidden state when complete identity and non-flat destination-donor content still pass; reject unverifiable appearance baked into a texture. No source-style opacity-equality requirement. |
| Partly off-canvas | F2 Asia destination is (−2022,−1125,5850,4368), with an exact IWA/accessibility chain. | Use the full logical frame, including negative coordinates; no clipping to 1920×1080, screenshots or visible-intersection identity. Reject clipped texture representations the simple rule cannot explain. |
| Scaled stage | Browser CSS scaling is separate from logical export coordinates. `_walk` is not a general stage transform solver. | Compare source canvas and export header coordinates, and use unscaled logical JSON. Reject an unexplained export/source scale; never fit a transform from a few matches. |
| PDF vs PNG/TIFF/JPEG | F2 repair donors and source assets are PDFs. A PNG ImageArchive resolves geometrically in event 1, but raster correlation was not calibrated here. Raster metadata/EXIF, alpha and color management differ. | Initial extension accepts single-page, ordinary-box PDFs only. Preserve existing D4 behavior for other formats. Later raster support should use one bounded grey-composite pipeline with explicit orientation/color semantics and positive/negative examples, never reinterpret PNG as PDF or use thumbnailData as original data. |
| Both players | Both digests occur in this census; `live_runtime.py:9–22` documents the two PDF.js-option differences. Geometric ambiguity exists under both. No source-backed positive image graft was proved on e9b2fad4. | Keep the existing supported-digest gate. Qualify the new source route on both; do not infer full object identity equivalence from the small main.js delta. |
| Source revision / parser loss | `source_slides` loads IWA then discards its objects (`hp:478`); `_load_deck` is non-strict, while `_load_deck_full(strict=True)` exists (`ir:225`). Local Alpha is demonstrably a different revision. | Build a strict source context tied to expected sourceDigest and manifest slide ids. Missing IWA members, duplicate asset mapping, missing assets, ambiguous geometry or source changes are no proof. Do not fetch online or invoke Keynote to fill gaps. |

## 5. Metadata hooks and injection

The 378 census accessibility entries contain only `text` and `targetRectangle`. None of the 417 unbound type-5 base leaves has `objectID`; their keys are `animations`, `layers`, `texturedRectangle`, `initialState`, `texture`. In 24 events with at least two uniquely frame-matched entries, 10 have an inversion between accessibility-array order and base-leaf order. F2 slide 3 event 0 maps accessibility indices 1,2,3,4,5,6 to base-leaf indices 10,1,9,6,7,8. Z-order/array position is therefore not an identity hook.

IWA object ids, parent refs, slide drawablesZOrder, data references, and package UUID maps (`oi:204`) are valuable **inside the source graph**. No corresponding non-movie leaf id was found in these exports. Texture ids cannot fill the gap: their mis-mapping is the bug. `title`/`caption` references and accessibility filenames are not proven leaf keys. Do not reverse-engineer texture hashes from package UUIDs without evidence.

The proposed `TSD.DrawableArchive.accessibility_description` token could improve only accessibility → IWA, if Keynote exports it. It cannot attach an id to a leaf, recover an omitted accessibility entry, split a rasterized group, or disambiguate coincident leaf rectangles. Export propagation, build-event persistence, field JSON spelling and persistence through Keynote save/export remain unverified. `iw:782,907` provides re-encode/diff/atomic-package primitives, not an existing accessibility-token public API. Injection would add a new mutation and scratch-export lifecycle, and could change slide text identity (`hp:289–318`) or visible accessibility behavior. Defer it. A future isolated experiment must preserve existing descriptions, tag only the scratch copy, inspect both JSON event streams and source stability, and prove a leaf-binding benefit before production use.

## 6. D1/D4 reuse and Alpha counterexample

The older 3b9019 cache was read directly using the path in `scripts/texture_repair_check.py:47–64`. Its slide 9 image hit is (942,635,288,78); slide 10 is (773,715,287,77). Both have **zero tight accessibility entries**. Both have previous-slide MM witnesses with **no contents.to**, landing the source texture `CE49CEF4…`. Thus neither qualifies for the new D2 chain. Slide 10 also changes the texture extent by one pixel, reinforcing why copying a same-file page is not automatically a valid graft.

The merged Stage T gate record's final update (`.agents/reviews/stage-t/gates-r1.md:37`) is authoritative: D4 already repairs slide 9; slide 10 still refuses for lack of a same-slide candidate. Do not repeat the obsolete “both tag boxes refuse” baseline from the original plan body.

A future D1-for-images could use same-slide IWA object identity **plus equal appearance** independently resolved in both events, with source pixels as backstop. A future D4 extension could use independently resolved same-asset landing identity and destination appearance. Neither needs to be included to fix F2, and neither establishes the tag-box shape identity measured here. Keep text D1, poster D3, approved D4, and no-contents semantics unchanged. In particular, do not turn the owner's D4 approval into permission for arbitrary previous-page grafting.

## 7. Implementation implications and limits

Prefer a small source-evidence module and a narrow D2 verification branch over edits to the general IWA writer or geometry engine. The integration can pass the original source path and expected digest to repair, load a strict context lazily only when an image D2 candidate needs it, and retain source-member bytes/render results for the call. This duplicates the earlier source_slides parse only on the new path, which is simpler than widening SourceSlide and every manifest/cache API. Verify that the source digest still matches before and after acquiring evidence and again before committing a source-dependent repair; a source-change exception must not consume the texture-refusal re-export retry.

Do not alter all image grouping globally merely to add a verifier. Instead, give the new route an explicit per-member source-identity proof and refuse a proposed group if any member cannot share it. Existing text/poster/D4 behavior and tests remain regression controls. The review must check whether an unresolved competing group/master drawable could occupy the candidate frame; inability to exclude it must close the new route, not justify nearest-geometry fallback.

Record enough evidence to reproduce the decision: source digest; source/destination originalSlideId and IWA ids; common data id and member hash; each accepted leaf and accessibility index; MM witness path/event; donor PDF page; raw correlation, rendering profile and frame/appearance checks. Bump TEXTURE_REPAIR_VERSION from 1 to 2. Keep fail-before-write planning, existing postconditions, cache invalidation and exactly one re-export on TextureRepairRefused (`pt:870`; `hp:900,1043`).

This advisory proves a viable narrow donor certificate for F2, not a universal solution to texture mis-mapping. The implementation still needs focused tests and offline repair gates, then one live F2 prepare and Alpha regression when the timing-sensitive peer session has finished. Owner eye on slide 4 in the HTML player must include the move into it and settled maps. A fresh clean export is a valid live outcome but does not replace the deterministic damaged-raw-export gate.
