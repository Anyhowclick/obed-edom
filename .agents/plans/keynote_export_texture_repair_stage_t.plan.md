# Repair Keynote HTML-export texture mis-mapping at prepare time (Stage T)

Status: **DRAFT rev 2 (2026-10-13), planning only. Read-only investigation.**
- **Critique r1 (rev 2):** (M1) D1 used rect-only identity. Export text/image leaves carry no `objectID`, and OCR similarity ≥ 0.8 passes one-glyph differences, so an in-place swap could donate the wrong texture. D1 is now text-only and gated on the slot's accessibility text being equal in both events. (M2) D3's rect fallback is dropped: every movie slot carries its `objectID`. (M3) The flattened-frame oracle leaves V3 and becomes a G2 measure. Every page-vs-page correlation renders over 50% grey, and R6 gets a measured threshold. Evidence was added for (b)–(e) in §1.4–1.5: no-contents MM landings change text, Stage B sizes, fixtures. 3b9019 is now refused at slides 9 and 10.

Read against `claude/s2-followups-dsk-deck-902af1` @ `1138e220` and `claude/stage-c-orchestration` @ `ac847ba1` (PR #264). It implements the owner's decision of 2026-10-13: fix Keynote's texture-id mis-mapping in the cached export copy when the deck is prepared, and never touch the `.key`. Scratch evidence is in `SCRATCH/textures/`:
- `detect2.py`: detector rules R1, R2, R3 and R4.
- `plan_repair.py`: dry-run donor search.
- `textslots.py`: maps text slots to their accessibility text.
- `graft/`: a dry-run PDF graft with renders.
- `pages/`: rendered PDF pages.

Citation prefixes: `hp` = `src/obed_edom/html_preview.py`, `lc` = `src/obed_edom/live_continuity.py`, `rt` = `src/obed_edom/live_runtime.py`, `gl` = `src/obed_edom/live_gl_replay_js.py`, `host` = `src/obed_edom/live_host.py`, `probe` = `src/obed_edom/html_alpha_probe.py`, `pm` = Stage C `src/obed_edom/preview_movies.py`. `main.js@N` = a byte offset in player 17c0c938.

## 1. Evidence (offline, measured)

### 1.1 How the player resolves a texture: per slide, never global
- **Lookup is scoped to one slide.** Each slide has its own cache, `textureManager.slideCache[slideIndex].textureAssets` (`main.js@2330356`). Every renderer reads only that cache:
  - the GL path: `fB.setupTexture` → `this.textureAssets[id]` (`main.js@2263021`);
  - the CSS and smart-build paths: `slideCache[V].textureAssets` (`main.js@2307104`, `@2316419`).
- **The PDF is always the slide's own.** `requestPdfDocument` hard-codes `showUrl + uuid + "/assets/" + uuid + ".pdf"`, or `.pdfp` under `file:` (`main.js@2330356`).
- **Page = index + 1.** For every `type:"texture"` entry whose `url.native` ends in `.pdf`, the player renders page `index+1` of that PDF at `zC=1` into a canvas. That canvas becomes `textureAssets[id]`. Any other extension is loaded with `new Image` (`main.js@2332238`, `generateUrl @2333163`).
- **Consequences:**
  - A slide cannot reference another slide's page.
  - Two different textures that share an id in one slide's table collapse to one page: the asset table is a dict.
- **Slide JSON source.** Over http the player fetches `<uuid>.json` (`main.js@1954062`). `host:1144-1168` separately parses `<uuid>.jsonp` (`local_slide({"name","json"})`). Today the two payloads are identical on all 10 Alpha slides.
  - **Who reads what.** Live and preview serve the player over http (`host` `_AssetServer` on 127.0.0.1), so `.json` and `.pdf` are what plays. `.jsonp` and `.pdfp` are read only under `file:` (`main.js@1954062`, `@2330356`).
  - The host parses `.jsonp` only to count events (`host:1155`). `hp:490-492` and `lc:1847` read `.json`.
  - A repair still rewrites all four, so the export stays self-consistent.

### 1.2 The defect (Alpha_DSK `7e3c9301…`; ordinal → player index: 8→6, 9→7, 10→8)
Text leaves are `textureType 6`, images `5`, background `1`. Every PDF page's mediabox equals its table entry's size, so the table itself is consistent. What is wrong is the leaf → id reference.

**Slide 10, event 0 base tree:**
- "Children's Church" (787,745) 256×31 → `C6571B`. Its page is the 582×327 poster on p4, which shows WA0125.
- "Sunday Service" (189,745) 224×36 → `F89B74`. Its page is the poster on p2, which shows WA0121.
- The posters themselves map correctly: A0064856=WA0121→`F89B74`, DF992E47=WA0125→`C6571B`. Pixel correlation against each movie's first frame is 1.0 vs 0.1.
- No 256×31 or 224×36 page exists in slide 10's PDF.
- Slide 9's Magic Move (MM) records the correct destination textures for these labels:
  - `1A75DB` 256×31 = "Children's Church" (slide 9 p19);
  - `A0B577` 224×36 = "Sunday Service" (slide 9 p20).
  - Both were OCR-verified. In slide 10's own table those two ids are the 391×330 graphic and the 259×58 tag box.
- Keynote's own flattened frame of slide 10 is page 15 (`AF8F0F`, 1920×1080), the outgoing texture of its dissolve. It shows all three labels correctly. This is an oracle already inside the export.

**Slide 9:**
- "Sunday Service" 223×36 → `8194C7`, whose page is the 13×404 divider (p3). Three leaves are affected: ev0 base, ev1 base, and the ev1 MM slot. Slide 8's MM records `8194C7` as 223×36 "Sunday Service" (slide 8 p13, OCR-verified).
- **New poster finding.** WA0125 (A94D1E57) uses `309718` in four places: the ev0 slot, its movie-start leaf, the ev1 slot, and the 9→10 MM slot. On slide 9, `309718`'s page is WA0121's image (correlation 1.00 vs 0.12). WA0125's real poster is in the same slide: `CF6BC1` (p8, its renderMovie poster leaf, correlation 1.0). Slide 8's MM records `309718` (slide 8 p12) as WA0125's image. With continuity off, this is the crossfade "from the wrong poster".

**Slide 8:** "Sunday Service" (ev0) → `B95077`, whose page is the 824×463 WA0125 poster. The correct `67C064` (224×36) is in the same slide, used by the same rect in ev1.

### 1.3 Why ids collide (hypothesis; the detector and repair do not depend on it)
- **Ids are identity keys.** They are 32-hex and mostly stable across slides for the same texture:
  - the background `9B0DBEF0` appears on every slide;
  - label ids repeat across adjacent slides: `52233E`, `5B7DEA`, `67C064`;
  - an MM's `contents.to` id equals the destination leaf's id in every consistent case: residual 0.0 px, 22 pairs measured.
- **They are not pixel hashes:**
  - the video placeholder `C01CA56A` appears at four sizes;
  - an MD5 of the page's XObject or contents never matches the id.
- **The pattern.** Within one slide, two different textures receive the same id, and the dict keeps one page (the "winner"). The stolen id is usually the correct id of another object on that slide or the neighbouring slide.
- **Common shape of every hit:**
  - the slide has a movie;
  - the slide is an MM destination;
  - the victim is an MM-matched object from the previous slide (labels, tag boxes, posters);
  - it happens mostly in event 0, the movie-start build event.
- **Nondeterminism.** An earlier export of a near-identical deck (`3b9019f0`, 10 slides) has different victims: the slide 9 tag box (288×78 → `309718`), the slide 10 tag box (287×77 → `C6571B`), and only one slide 10 label. The two D2 exports also differ (`html-unmodified` vs `.across-first-build`). It cannot be prevented upstream, so it has to be detected per export.

### 1.4 Detector, run on every available export
Rules:
- **R1 (JSON).** A leaf's w×h differs from its table entry's w×h by more than 1.5 px. Exempt: renderMovie video/`textureType None` frame leaves whose aspect matches (scaled movie frames, benign).
- **R1b (JSON).** An MM leaf's `contents.to` table size differs from its end rect. The end rect is computed as in `__obedHandbackTextures` (`rt:34-54`): scale about the anchor, then translate.
- **R2/R4 (pixels).** A poster leaf attributed to movie M has a page that correlates < 0.5 with M's own renderMovie poster page and ≥ 0.9 with another movie's poster. Pages are rendered at 64×36 via Quartz.
- **R6 (pixels).** An MM `contents.to` page and the destination leaf's page at exactly the landing rect (≤ 0.01 px, unique leaf) correlate < 0.5.
  - **Rendering:** every page-vs-page correlation (R4, R6, V3) renders both pages at 64×36 over **50% grey**. Text pages are transparent: over black, dark text is flat, and over white, white text is flat. Measured on the slide 10 labels: 0.98 over black and 0.0 over white.
  - **Flat guard:** if either render has a std below 2 levels, the check gives no verdict.
  - **Measured:** true hits −0.17…0.12; consistent `contents.to` landings ≥ 0.9.
  - **Only `contents.to`, never a no-contents slot.** 10 MM-matched text objects in D1/D2/D2-across/D3/D6 land with *different text* and no `contents` animation. For example "D1 S3" lands on "D1 S4" (correlation 0.85–0.87). So the slot's own texture is not the destination's appearance.
- **R3** (same id, different sizes across an MM) is diagnostic only: it does not by itself break playback.

| Export | Hits (R1 / R4 / R6) | Verdict |
|---|---|---|
| Alpha `7e3c` | R1: slide 8 label; slide 9 label ×3 leaves; slide 10 labels ×2. R4: slide 9 WA0125 poster. R6: slide 9 label and poster, slide 10 labels | all true |
| Alpha `3b9019` | R1: slide 9 tag box, slide 10 tag box, slide 10 "Sunday Service". R6: the label | all true |
| D2 (gate fixture) | R1: S2 and S5 movie poster slot plus movie-start leaf → a black 1920×1080 background page (rendered and verified) | **true positives**, hidden on air while the video covers them |
| D2 `.across-first-build` | R1: S5 only | true |
| Minimal (59cb, fixture copies), Positive Control, P2 binary/loop/loop-grey/recovery/gl-replay, D1, D2-across, D3–D6 | 0 | — |
| p2-soak-loop | JSON 0; pixels not runnable (the fixture has `.pdfp` only) | — |

- R1b found 0 hits across 81 MM `contents.to` checks. This validates the end-rect formula used by the donor rule.
- **R5 (optional diagnostic): OCR of every text page vs the event-0 accessibility text.** It flags exactly the 4 bad pages, plus one fuzzy-match false positive: the verse number "1" read as `"`. That rules R5 out as a refusal rule.
- **Identity in the export.** `objectID` exists only on movie layers and effects: slot wrappers, `apple:movie-start` and `renderMovie`. Text and image leaves have none (7e3c slides 8–10 dumped). Slot indices also shift between events: slide 8's label is ev0 slot 3 and ev1 slot 7. So the owner's objectID-only rule can bind posters (D3), while any other identity must be rect plus a model-level check.
- **Fixtures (question e).** Repair runs only inside `apply_preview`, and gate fixtures never pass through it. They are never rewritten, and D2 stays the detector's real-world positive control. Plan shas cannot move, because no Python reads texture ids: `lc` only validates them as non-empty, and `host`, `rt` and `hp` do not read them. A live-prepared D2 *is* repaired, but its defect sits under the video and in the destination table, so GL replay (source-slide uploads) is unaffected.

### 1.5 What the repair touches downstream (checked)
- **Continuity derivation.** `derive_plan` (`lc:1816-1857`) reads events, the asset table and movie URLs:
  - Texture strings are only validated as non-empty (`lc:209,356`).
  - `slotSizes`/`slotRects` come from leaf `initialState` (`lc:560-645`).
  - `_bridge_slot_chain` (`lc:1545-1577`) uses slot geometry.
  - So the plan is byte-identical if only leaf texture strings change and table entries are added.
- **Player digest.** `SUPPORTED_PLAYERS` (`rt:11-22`) hashes `main.js` only, which is untouched.
- **The handback mix is fixed as a side effect.** It matches destination event-0 leaves by rect and uses their texture ids (`rt:34-54`), so today it can cross-fade into a mis-mapped texture.
- **GL replay behaviour changes.** Poster detection matches *canvas* uploads whose size equals `slotSizes[movieSlot]` (`gl:273-283`), and the opacity proof checks upload sizes (`gl:789-796`). Uploads on repaired slides change; for example, slide 9 draw 8 goes from 13×404 to 223×36. So GL-replay and Stage B binding gates must be re-run on repaired exports.
- **Stage B.** B rev 3 binds "never by texture id", by draw index plus regular-upload ordinals and sizes, so it stays correct only if it computes `feed` from the **served (repaired) JSON**.
  - Repair re-points textures and adds table entries. It adds no leaves or `contents`, so draw and upload counts and ordinals are unchanged.
  - Sizes do change. On 9→10, WA0125's `from` goes from 715×402 to 714×402, and the label draw goes from 13×404 to 223×36.
  - B's Alpha expectations (its §4 stream D row: sizes "equal the experiment's") must therefore be re-captured from a repaired export.
  - B's §8 residual "does not depend on the repair" is true of the mechanism only.
- **Precedent.** P2 probes rewrote export PDFs with pypdf and played them in Chrome: `probe:3319-3398` (`rewrite_pdfp_from_pdf`, `strip_export_pdf_bg_fills`), used by `scripts/p2_recovery_html_*.py`.
- **Dry-run graft** (scratch copy of slide 10's PDF plus slide 9 pp19–20, pypdf `clone_from` + `add_page`):
  - 0.02 s, +10 KB;
  - original page content streams identical;
  - new pages render pixel-identical to the donors (max diff 0, Quartz);
  - OCR reads "Children's Church" and "Sunday Service".

## 2. Repair options

| Option | Verdict |
|---|---|
| (a) Re-point the leaf to the correct page | **Yes.** Same slide when the right page exists there (slide 8, the slide 9 poster, D2). Otherwise *graft* the donor page into the recipient slide's PDF, because the player cannot load another slide's page (§1.1). |
| (b) Re-render text from the IWA or from the slide PDF | No as a source: font, kerning and effects fidelity is unprovable, and the PDF has no such page. Usable only as a text-identity check, and the export's accessibility text already provides that. |
| (c) Rewrite ids to be unique per slide | Not enough on its own: the loser's page is gone. It becomes part of (a): grafted entries get fresh ids. |
| (d) Fail the prepare and name the slide | The fallback when no verified donor exists (today only 3b9019's two tag boxes, slides 9 and 10). |
| PNG instead of graft | Rejected. `new Image` uploads are `srcType 'other'`, not canvas, which bypasses GL-replay poster matching (`gl:273-283`) and the pdf.js path. |
| Re-export retry | Rejected as the default: nondeterminism is unproven and it doubles prepare time (see OQ-T1). |

### 2.1 Recommended design: `preview_textures.repair_textures` (new module, shaped like `pm`)
1. **Detect.** Run R1 and R1b (JSON), then R4 on slides with at least 2 distinct movie assets and R6 on MM destinations (Quartz 64×36). An unknown player digest means repair is skipped and recorded, since live refuses that player anyway.
2. **Find a donor for each bad leaf.** Leaves are grouped by (slide, rect, size), so the ev0, ev1 and MM copies share one fix. The first rule that verifies wins:
   - **D1, same slide, text leaves only** (`textureType 6`).
     - The donor is the same type, at the same rect (≤ 0.01 px), size ≤ 0.5 px, and table-consistent.
     - The accessibility text of the bad leaf's event at that rect (unique entry, IoU ≥ 0.5) must **equal** the donor event's text after NFKC normalisation. Then re-point the id.
     - Covers slide 8 → `67C064` ("Sunday Service" in both ev0 and ev1).
     - Why: rect is the only identity a text leaf has. An in-place swap ("Point 1" → "Point 2") would otherwise donate, and V3's OCR cannot catch it (difflib "point 1"/"point 2" scores 0.86).
     - A non-poster image never uses D1: it has no model-level check. 3b9019's slide 9 tag box (D1 candidate `CE49CEF4`, which is in fact correct) therefore refuses, see OQ-T4.
   - **D3, poster:** the leaf is attributed to movie M by `objectID` only, through its slot wrapper (`/baseLayer/layers/k/layers/0.objectID`, present on every movie slot in the corpus). M's own renderMovie poster id must be within 1.5 px → re-point. Covers slide 9 → `CF6BC1`, D2 → `E606C252`/`B07083CF`.
   - **D2, MM landing:** the previous slide's MM leaf has a `contents.to` T, never a no-contents slot texture (§1.4 R6). T's end rect equals the leaf rect (≤ 0.01) and exactly one destination ev0 leaf sits there. T's table size matches, and T's source leaf is not itself a detector hit → graft page `index(T)+1` from the previous slide's PDF. Covers slide 9 ← slide 8 p13; slide 10 ← slide 9 p19 and p20.
   - Otherwise **refuse:** `PreviewError("Cannot repair Keynote's HTML export: slide 10 (287×77 image | 'Sunday Service' label | movie X): its texture is mis-mapped and no verified replacement exists")`. One message lists every unrepairable object. The ordinal comes from `manifest.slides`.
3. **Verify the donor (fail closed).** Refuse unless all three pass:
   - **V1 structure:** sizes match, the donor is table-consistent, the donor page's mediabox equals its table size.
   - **V3 content:**
     - text: OCR of the donor must not *confidently contradict* the slot's event-0 accessibility text (IoU ≥ 0.5; NFKC and quote normalisation; similarity ≥ 0.8);
     - text, limitation: this is a backstop against garbage, not an identity check, because "D1 S3" vs "D1 S4" scores 0.80. Identity comes from D1's accessibility equality and from D2's `contents.to`;
     - poster: correlation with M's renderMovie poster ≥ 0.9 (rendered over grey);
     - the flattened-frame oracle is **not** a V3 check, only a G2 measure. It is the slide's *final* build state composited over other layers: objects that build out, move or are overlapped would refuse a correct donor.
   - **V4 postcondition, checked after writing:**
     - the detector finds 0 hits on the repaired export;
     - a texture-blind fingerprint is byte-identical: slide JSON with every texture string blanked and texture table entries dropped;
     - grafted pages render pixel-equal to their donors;
     - `.json` equals the `.jsonp` payload;
     - `.pdfp` decodes to the `.pdf` bytes.
4. **Write**, per slide, temp file then `os.replace`:
   - **Graft:** `PdfWriter(clone_from=…)` + `add_page`. The new entry uses the same `url.native` as its siblings, `index = old page count + k`, the donor's width and height, and a fresh id `sha256(recipient:donor_uuid:donor_id)[:32].upper()`, checked unique within the table.
   - **Re-point** only the bad leaves, plus their own `contents.from` when it equals the old id. Never rename a table key: the winner, e.g. the divider, keeps its id.
   - **Rewrite** `.json`, `.jsonp` (`ensure_ascii`), `.pdf`, `.pdfp`. Move `rewrite_pdfp_from_pdf` from `probe` to a shared helper.
   - Any exception propagates to `apply_preview`'s existing `rmtree` of the export (post-C `hp:1056-1059`), so a partial repair never persists.
5. **Record.** Always write `manifest.textureRepair = {version, playerDigest, repaired:[{ordinal, uuid, leaves:[event/path], rule: D1|D2|D3, from, to, donor:{uuid,id,page}|null, verify:{ocr|corr}}], pdfs:[{path, sourceSha256, sha256}]}`. An empty `repaired` list is still written, because the record's presence proves the check ran.
6. **Hooks, stacked on C:**
   - In `apply_preview`, after `manifest_from_export`, call `repair_textures` *before* `convert_movies`: it is fast and can refuse, so it fails before a slow encode.
   - In `load_cached`, return `None` unless `manifest.textureRepair.version == TEXTURE_REPAIR_VERSION` and JSON R1/R1b find nothing. This mirrors C's `unconverted` gate. The current Alpha cache will therefore re-export once.

## 3. Tests (minimal)
1. `tests/test_preview_textures.py`, synthetic JSON:
   - an R1 hit;
   - a renderMovie scaled frame that is not a hit;
   - D1/D2/D3 donor selection, including MM end-rect landing;
   - D1 refuses an in-place text swap (accessibility texts differ) and any image;
   - D3 ignores a rect-matching movie without the `objectID`;
   - refusal text names the ordinal and the object;
   - a fresh id never collides.
2. Fixture-backed tests, skipped when the fixture is absent (`fixture_paths`):
   - the detector finds 0 hits on Minimal, P2, D1, D3–D6;
   - D2 is repaired via D3;
   - Alpha (new fixture, OQ-T5) round trip on a temp copy satisfies V4, and the derived plan signature is equal before and after (`lc:671`).
3. `tests/test_html_preview.py`:
   - `load_cached` misses without a `textureRepair` record and hits with the current version;
   - `apply_preview` calls repair before conversion and deletes the export on refusal.

## 4. Gates
- **G1 offline.** The detector and repair over all exports reproduce the §1.4 table:
  - Alpha 7e3c: 6 leaves plus 1 poster group repaired (D1×1, D2×3 sites/2 grafts on slide 10 + 1 graft on slide 9, D3×1);
  - D2: repaired via D3;
  - 3b9019: refused, with one message naming both tag boxes (slide 9: an image, so no D1; slide 10: no donor), or OQ-T4;
  - 0 hits elsewhere.
- **G2 headless**, when the machine is free (pattern in `SCRATCH/goto10.py`), with `continuity=off`:
  - settled slide 10: each label crop vs the `AF8F0F` oracle crop, correlation ≥ 0.9 (fails before repair);
  - slides 8 and 9: OCR of the label crops equals the expected text;
  - a mid-frame of the 9→10 MM: WA0125's slot correlates with WA0125;
  - this is the first proof that pdf.js renders grafted pages: the dry run used Quartz, and the P2 precedent rewrote a single document only.
- **G3.** Plan-sha and S3 corpus unchanged. Re-run GL replay and Stage B feed-binding gates on the repaired Alpha.
- **G4 owner eye.** Slides 8, 9 and 10 on air: Chrome and the managed OBS Keyer.

## 5. Work streams (Opus MEDIUM, one PR stacked on `claude/stage-c-orchestration`)
- **T1:** `src/obed_edom/preview_textures.py` plus its tests. Detector, donor planner, writer, record. Quartz rendering and Vision OCR reuse `ocr.py`. Render to a temp dir outside the export, because `ocr.py` writes `.ocr.json` sidecars next to the PNG. Declare `pyobjc-framework-Quartz`: today it is only a transitive dependency of Vision.
- **T2:** the `hp` hooks plus the `test_html_preview` additions (about 10 lines next to C's).
- **T3:** the G1/G2 script (`scripts/texture_repair_check.py`), README and SKILL lines, and capturing the Alpha fixture.

**Order:** C (#264) → T, then S3 in parallel. T must land **before B**: B's bindings, Alpha qualification and owner eye all assume correct textures. The poster mis-map does not matter while the GL feed runs, but it does with continuity off or under poster hold.

## 6. Owner questions (recommendation first)
1. **OQ-T1: no verified donor.** Rec: (a) fail the prepare and name the slide and object, consistent with OQ-C1. Alternatives: (b) prepare with a warning; (c) re-export once, then refuse.
2. **OQ-T2: scope.** Rec: repair text **and** posters (R4/R6) with the same machinery.
3. **OQ-T3: text verification.** Rec: refuse only when OCR *contradicts* the slot's text. Requiring a positive OCR match risks false refusals on CJK or stylized fonts.
4. **OQ-T4: D4**, the previous slide's same-size texture for MM-matched objects with no contents change. This would fix 3b9019's tag boxes. Rec: defer.
   - Text is never eligible: no-contents text landings change text (D1 S3 → S4, §1.4).
   - Images are eligible later only with independent pixel agreement. One source is the destination-slide D1 candidate. 3b9019's slide 9 `CE49CEF4` matches slide 8's landing at 1.00, and the slide 10 tag box has slide 9's `CE49CEF4` landing at residual 0.000.
5. **OQ-T5: fixture.** Rec: yes, add `output/fixtures/alpha-dsk-textures` (7e3c JSON, PDF and pdfp, no movies, about 40 MB) to `FIXTURE_NAMES`.
6. **OQ-T6: order.** Rec: C → T (stacked) → B, with S3 in parallel. Old caches re-export once rather than being repaired in place.
