# Plan critique r2: keynote_export_texture_identity rev 2 (Opus 5.5 high)

**Verdict: CHANGES REQUIRED.** 0 blockers, 1 major, 4 medium, 4 low.

The core rule holds on F2. I re-derived it independently, and it resolves every map endpoint exactly and uniquely, with no false acceptance. All 15 r1 findings are folded faithfully. The remaining changes are:

- **Major:** one OQ recommendation, which my predecessor introduced, would break other sessions' census tests.
- **Medium:** one helper that does not cover the "any kind" domain the rule names; one witness-counting gap; one test row that cannot be built; and G1/G3 plumbing the plan does not specify.

Scripts for these measurements are in `SCRATCH/r2/` (`i1.py`, `premise.py`, `wit.py`, `size.py`, `count.py`). I ran them offline with strict `_load_deck_full(F2.key)`. The F2 digest is still `9fc882c1…55e1`.

## Verification of focus 1: does I1 resolve F2 exactly?

Rule as written: floor/ceil+1 within 0.01, two-way 0–4 px envelope, own tree.

| Leaf | Tree | Object | Data | Drawables / own-tree leaves in envelope |
|---|---|---|---|---|
| s4 `0/baseLayer/layers/5/layers/0/layers/0` (588,827,176,205) | s4 ev0 base | 15348427 | 44137 | 1 / 1 |
| s4 `0/baseLayer/layers/3/layers/0/layers/0` (939,807,357,235) | s4 ev0 base | 15348425 | 44140 | 1 / 1 |
| s3 `1/effects/0/baseLayer/layers/11/layers/0` (938,846,21,24), MM, contents.to DF3DB700 = p15 | s3 ev1 MM tree | 15355064 | 44137 | 1 / 1 |
| s3 `1/effects/0/baseLayer/layers/10/layers/0` (972,844,39,27), MM, contents.to B37026D5 = p14 | s3 ev1 MM tree | 15355057 | 44140 | 1 / 1 |

Other checks:
- **Donor table sizes:** 176×205 and 357×235, equal to the leaves.
- **Source data:** `Data/pasted-image-44137.pdf` and `-44140.pdf` are each the only matching ZIP entry. Each is a single-page PDF and agrees with `TSP.PackageMetadata`.
- **Geometry:** all four objects have `angle 0`.
- **Witnesses:** `_landings(own=True)` gives exactly one MM leaf per destination, the same as `own=False`.

**Opacity-0 sources.** Both maps render a leaf in slide 3:
- They appear in the ev0 and ev1 base trees, and the MM witness is that object's own leaf in the ev1 MM tree.
- The opacity 0 sits on the parent wrapper layer. The leaf's own `initialState.opacity` is 1. The MM leaf animates `opacity`.

So "visibility and opacity ignored" is both correct and necessary.

**False-acceptance probe across F2.** 42 leaves have a floor/ceil candidate:
- All 42 are two-way unique, and none is a competitor-contested match.
- 26 of 57 type-5 non-movie base and MM leaves resolve to a unique ImageArchive. Only **18** pass the no-mask eligibility. The 8 differences are the masked emblem 15347050 and its copies.
- No non-type-5 leaf matches an ImageArchive frame.

**Is "a non-rendering competitor cannot be the leaf's content" sound?** Yes, but only on an unstated premise: the matched top-level image has its own leaf in that tree. F2 shows the premise is not universal. Slide 4 event 1 is flattened to one full-slide type-0 composite (`1/baseLayer/layers/0/layers/0`, 1920×1080), and none of the four slide-4 images has a leaf there. The current rule could only misattribute such a composite to an image whose floor/ceil frame equals the composite rect, for example an image at (1,1,1918,1078). For destinations, the MM landing, the equal data id and source-pixel agreement back this up. A one-line kind guard closes the gap (finding 8). Master/layout objects and group children that render produce leaves, which the own-tree count catches. Hidden leaves are present in base trees (for example 15346644 on s3 ev0), so they must count as competitors.

## Findings

### 1. Major · process/safety: OQ-5's `output/fixtures` location breaks other sessions' real-export censuses
I recommended this location in r1, and it was wrong.

**Evidence**
- `tests/test_live_runtime.py:160` sets `MAIN_OUTPUT = main_checkout()/"output"`. `_corpus_headers(MAIN_OUTPUT)` (`:1391–1392`) rglobs every `assets/header.json` under all of `output/`, excluding only `alpha-dsk-textures`.
- Its consumers assert exact sets:
  - `test_mm_opacity_census_mirror_changes_only_expected_slots_across_real_exports`: `stock_changed == {(P2_1_TO_2_FINGERPRINT, 4)}`;
  - the handback census `..._across_real_exports` in `tests/test_live_runtime_handback.py`: `affected == {...}`.
- `OUTPUT_FIXTURES.rglob("index.html")` (`test_live_runtime.py:634`) adds every page under `output/fixtures` to the shadow-DOM pin.
- `scripts/dissolve_probe.py:70` and `tests/test_dissolve_probe.py:888` glob `output/fixtures/**/main.js`.
- `tests/fixtures/` is committed and scanned too (`FIXTURE_ROOT` rglobs). F2 has Magic Moves, so any F2 export slice with a `header.json` under `output/` would perturb these censuses for every worktree.

**Fix wording.** Replace OQ-5's recommendation with:
> "Rec: keep the evidence where it already lives, `~/Desktop/Convert wall to 16x9 CGs/F2.key` and `F2-html/` (owner's folder, read-only). Record sha256 of F2.key (`9fc882c1…`) and of each F2-html file G1 reads (header.json, main.js, slide 3/4 json/jsonp/pdf/pdfp) in the gate record. The G1 F2 rows pin those hashes; absence or mismatch is INCONCLUSIVE (exit 3), never PASS. Never copy any F2 export, slice or repaired copy under the main checkout's or any worktree's `output/`, or under `tests/fixtures/`. Temp and G3 copies go in the session scratchpad."

Add to G2:
> "A successful F2 prepare leaves a cache under main `output/.html-preview/9fc882c1…-p3-r1/html`, which the same censuses glob. Run the full suites before G2, or Trash that cache after G2 is recorded, and report it either way."

### 2. Medium · correctness: `derive_kind_index` is not "drawablesZOrder records of any kind"
**Evidence**
- `ki:110–115` skips every `_pbtype` outside Image, Movie, Group and ShapeInfo (module docstring: "Tables/charts are omitted"). Tables, charts, connection lines, drawings and similar objects never become competitors.
- `ki:117–128` emits two records with one id for dual text/shape boxes.
- F2 has no dropped kinds, so F2 is unaffected. The gap is in the general rule.

**Fix wording** (I1.3(b) and §2 reuse list):
> "(b) every `drawablesZOrder` entry of the slide, any `_pbtype`, with geometry from `iwa_kindindex._geometry`, counted once per id. An entry with missing or non-finite geometry refuses the candidate."

Drop `derive_kind_index` from the reuse list.

### 3. Medium · correctness: count witnesses before `_d2`'s filters, including no-contents landings
**Evidence**
- `_d2` (`pt:587–595`) drops landings that fail `_fits`, bad textures or `_trusted_landing` before collapsing to a set.
- "Require one eligible MM witness" can therefore be read as "one witness survives filtering". On that reading, a second MM leaf landing on the same destination is ignored when it has a wrong-sized, bad or absent `contents.to`. Two objects morphing into one destination is ambiguity.
- On F2, `_landings(own=True)` already gives exactly one landing per map, so the stricter count costs nothing (measured).

**Fix wording** (I2):
> "Count every previous-slide MM leaf that `_landings(own=True)` lands on any group member, before `_d2`'s filters. Exactly one is required, and it must carry a genuine `contents.to` and pass `_d2`'s existing filters."

### 4. Medium · tests: row (4) "a group member resolving to another object" cannot be built
**Evidence**
- Group members share slide, old texture and rect within `GROUP_TOL` 0.5 (`pt:434`). Floor/ceil frames are integers within 0.01. Candidate drawables are slide-level.
- So members either match the same drawable set, or a member with a non-integer rect matches nothing. No member can resolve to a *different* object.
- The test that I3 needs is an unresolved member.

**Fix wording:**
> "(4) the destination's event-1 copy (same group) has an envelope competitor leaf in its own tree, so the whole group is refused. This covers I1.3(a) and I3."

Also add these notes to §5:
- Row (1) must reuse S1/S2/`TO`/100×20, or the shared D2 assertions (`D2_ID`, dims, page count; `tests/test_preview_textures.py:373–381`) must be parametrised.
- The source PDF and donor need the existing `"L"` fill. Blank pages are flat, so the new std ≥2 guard would refuse them.
- New rows add `originalSlideId` to `_export`'s slides and pass the source kwargs through `_repair`.
- Cite `tests/test_offline_write.py:1359` as the decoded-dict precedent. `conftest.py:79` wraps the real loader.

### 5. Medium · gates: G1 and G3 plumbing is unspecified and fails as written
**Evidence**
- F2-html has no manifest, so `export_slides` falls back to `slides_from_header` (`scripts/texture_repair_check.py:97–106`). Those slides have no `originalSlideId`, so the new route cannot run.
- The synthetic variant needs its own row and mutation.
- `run_g1` repairs inside a `TemporaryDirectory` with `copy_minimal`, which copies no `index.html` or player bundle (`:123–133,176`). So no "G1-repaired copy" survives for G3, and the minimal copy could not be played anyway.

**Fix wording** (G1):
> "Two EXPECT rows sharing one source key: `F2` (D2×1) and `F2/synthetic-357` (D2×2). The script applies the documented JSON+JSONP mutation to its temp copy. Slides come from `html_preview.source_slides(F2.key)` zipped onto `header.slideList` (F2 has no skipped slides; assert the counts). Pass `source_path` and a `source_digest` pinned to `9fc882c1…`. A mismatch is INCONCLUSIVE."

Fix wording (G3):
> "Make a full copy of F2-html (and of the synthetic variant) in the session scratchpad, outside every `output/`. Repair it with the same call, record its hashes, and serve exactly that copy."

### 6. Low · correctness: pin where the single digest check runs, and narrow the refusals
**Evidence:** evidence is lazy and per candidate, with members read as data ids resolve. A check "after reading IWA" could therefore run before a later member read.

**Fix wording:**
> "Load IWA once per attempt on first need; read members as needed; run the single digest check once after `_plan` returns and before any write, whenever evidence was read. Refuse the candidate only on `UndecodableIWAMember`, `zipfile.BadZipFile`, a missing or duplicate member, `ImportError` of the iwa extra, or unresolvable geometry. Other exceptions propagate."

Also: read `originalSlideId` with `.get`. When it is absent (header-fallback callers, existing tests), the new route refuses.

### 7. Low · fact: "only accepts cases v1 refused" is not exact
**Evidence:** `_plan` tries D2 before D4 (`pt:706–711`). An image group with both a contents.to landing and a D4 candidate flips from D4 to D2. No current corpus case has both: the 3b9019 tag boxes have no contents.to, and fixture rows have no source. A v1 D4 cache is still a verified repair, so the no-bump decision stands.

**Fix wording** (§4 and OQ-6):
> "The new route turns v1 refusals into repairs and can pre-empt D4 where both exist (none in the corpus). v1 caches remain verified repairs; no bump."

### 8. Low · correctness: make the leaf-kind guard explicit and state the render premise
**Evidence**
- I1.1 says "Preserve existing non-video/type-5 … protections", but D2 has no type-5 check today.
- See the premise note in the verification section above (the flattened type-0 composite on slide 4 event 1).

**Fix wording** (I1.1):
> "Every destination member leaf and the witness leaf has `textureType 5` and is not `isVideoLayer`."

Fix wording (I1.3):
> "Hidden and opacity-0 leaves count as competitors. 'Tree' is the leaf path's prefix through its last `baseLayer`."

### 9. Low · fact
- §1 "resolves 26/57 … type-5 base and MM leaves" counts masked images. With I1.1's no-mask eligibility the figure is **18/57**; the 8 differences are the masked emblem 15347050's copies. All four map endpoints are among the 18.
- §5 row (1) "opacity-0 source": the code never reads opacity, so the row documents the fact rather than exercising a branch. Keep it, labelled as documentary.

## r1 fold check
All 15 r1 findings are present, and the quoted wording matches. The new issues come from two r1 items: finding 8's reuse of `derive_kind_index` (here 2) and finding 11's alternative for row (4) (here 4). Finding 10's G3 copy needs persistence (here 5). OQ-5's location was r1's error (here 1).
