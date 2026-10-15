# Plan critique r3 (final round): keynote_export_texture_identity rev 3 (Opus 5.5 high)

**Verdict: CHANGES REQUIRED, one wording fold.** 0 blockers, 1 major, 0 medium, 8 low.

Finding 1 is the only must-fix. It is a self-contained wording change to G2, so the coordinator can fold it without another critique round. Fold the lows at the planner's discretion. With finding 1 folded, the plan is READY for one Codex Sol implementer.

## Fold check: r1 (15) and r2 (9)
- All 24 findings are present with their fix wording. No regressions.
- r2-2 is complete: `derive_kind_index` is gone from the reuse list, which now says `_geometry` on raw `drawablesZOrder`.
- Anchors re-checked against the current tree. All are within ±5 lines: `pt:352,577,663–685,706–711`, writer `748–818`, `ir:225`, `oi:58`, `hp:1088`, `tests/test_preview_textures.py:362,373–381,386`, `tests/test_html_preview.py:433,446`.

## Spot checks this round (offline; scripts in `SCRATCH/r3/`)
- **Source digest:** `shasum F2.key` = `9fc882c1…55e1`, which matches the pin, although the deck's mtime is today 18:25.
- **No missing geometry:** across all 9 F2 slides, no `drawablesZOrder` entry has missing or non-finite `_geometry`. Slides 3 and 4 contain only ImageArchive and ShapeInfoArchive entries, so I1.3(b)'s new "missing geometry refuses" clause cannot refuse F2.
- **Data field:** all four map objects carry both `data` (44137 / 44140) and `thumbnailData` (44138 / 44141).
- **F2-html detector run (read-only):** player `17c0c938`. Hits are R1 + R6 on slide 4 `0/baseLayer/layers/5/layers/0/layers/0`, forming one group with one member. So the G1 baseline row's D2×1 is the full expectation.
- **Main `output/.html-preview`:** holds only empty `9fc882c1…-p3-r1` and `cf0f6cb4…-p3-r1` folders today, so there is no census perturbation yet.
- **Alpha_DSK.key digest:** `bf1c093f…`. That matches neither existing cache nor any corpus digest (7e3c / 3b9019).

## Implementability: the touch list Sol needs, all buildable as written
- **`pt` data model:** `_Slide` (L84) gains `slide_id: str | None = None`, set in `_load` (L201–212) via `.get("originalSlideId")`. `_Fix` (L140) gains the witness landings.
- **`pt` call chain:** `repair_textures` (L870) takes the kwargs and builds a per-call lazy source context. It threads that context through `_plan` (L686) into `_verify` (L663). The new image branch replaces `return False` at L683 and runs only when a context is present and the group has no movie.
- **`pt` pixel check:** I4 calls a std ≥ 2 pre-check, then `_corr` (L348), because `_corr` returns 1.0 on equality before its flat guard.
- **`hp`:** the call at L1088 passes `source_path=path, source_digest=digest`.
- **`tests/test_preview_textures.py`:** add `originalSlideId` to `_export` (L135), kwargs to `_repair` (L147), the rows, and the L362 key set.
- **`tests/test_html_preview.py`:** the `_repair` stub signature (L482) must accept and assert both kwargs. As it stands it would raise a TypeError on the new call.
- **`scripts/texture_repair_check.py`:** F2 rows in `g1_exports`/`EXPECT`, plus an INCONCLUSIVE path in `run_g1` (see finding 7).
- **Test rows (1)–(4):** each is constructible with the existing builders.
  - Row (1): `_d2_slides` with `kind=5` on both slots and the MM leaf, `"TO": (100, 20, "L")`, an L-filled `Data/x-<id>.pdf` in a tmp zip, and a monkeypatched `iwa_runs._load_deck_full`.
  - Row (2): an extra ShapeInfo drawable inside the envelope.
  - Row (3): a different `data.identifier`.
  - Row (4): S2 event 1 gets a second, consistent leaf with a different texture inside the envelope. It neither joins the group nor hits.
  - This works only if `pt` imports `_load_deck_full` lazily from the module at call time, which matches the house pattern.

## Certificate (I1–I4), refusal and record
I found no correctness hole. In particular:
- Ambiguous `_landings` matches that are dropped before I2's count can only arise from two event-0 targets within 0.01. Those are two own-tree leaves in the envelope, so I1.3(a) refuses them.
- I4 independently ties the donor page to the source data. A mis-mapped `contents.to` therefore cannot pass.
- The witness drawable must also pass I1.1, so a masked or movie witness refuses.
- `PreviewStale` escapes the inner `except TextureRepairRefused` (`hp:1092`), and the outer `except` deletes `html`.
- Version 1 is safe because `load_cached` (`hp:923–927`) re-checks only R1/R1b, which a correct graft satisfies.

## Findings

### 1. Major · gate safety: G2's cache clause covers F2 but not the Alpha_DSK prepare in the same gate
**Evidence**
- G2 runs "real Alpha_DSK prepare/player regression". The current Alpha_DSK.key digest is `bf1c093f…`, which has no cache today. A normal prepare served from main therefore writes `output/.html-preview/bf1c093f…-p3-r1/html`.
- `_corpus_headers(MAIN_OUTPUT)` (`tests/test_live_runtime.py:1391`) excludes only `alpha-dsk-textures`. Alpha's 7→8 Magic Move is exactly the stock-changed slot that the committed-fixture census lists, `(ALPHA_DSK_7_TO_8_FINGERPRINT, 6)` (`:1409`). The across-real-exports census requires `stock_changed == {(P2_1_TO_2_FINGERPRINT, 4)}` (`:1423`), so an Alpha cache under main `output/` breaks it.
- "Run the full suites before G2, or Trash…" is insufficient whenever suites run after G2: a review fold, or the final integrated commit in §5.
- `output_root()` is the serving checkout's `output/` (`paths.py:16`), not necessarily main's.

**Fix wording** (replace the G2 block quote):
> "Every successful G2 prepare leaves a cache under the serving checkout's `output/.html-preview/<digest>-p3-r1/html`: F2 `9fc882c1…` and Alpha_DSK `bf1c093f…` (re-read the digests at G2). When served from main, the real-export censuses glob these caches (`tests/test_live_runtime.py:1391`, the handback census). After G2 is recorded, and before any later suite run, Trash each cache G2 created, unless the owner chooses to keep one. Report which caches were created, kept or Trashed."

### 2. Low · digest placement: pin it before the refusal raise
**Evidence:** the plan says "after `_plan` returns and before any write". If the check is placed after `if refused:` (`pt:888`), a stale deck whose evidence led to a refusal triggers a full Keynote re-export before `PreviewStale`.

**Fix wording:**
> "…once, immediately after `_plan` returns (`pt:887`) and before the `refused` raise (`pt:888`), whenever evidence was read."

### 3. Low · refusal list vs "failed decoding supplies no proof"
**Evidence:** I4 says failed decoding supplies no proof, while §2 says other exceptions propagate. A pypdf page count on a malformed source PDF would raise `PdfReadError` and crash the prepare. A `KeyError` would do the same if `originalSlideId` is not a decoded `KN.SlideArchive`.

**Fix wording** (§2):
> "Count the source pages and render with Quartz (`CGPDFDocumentGetNumberOfPages`, `_Renderer.thumb`), which return None instead of raising. Do not run pypdf on the source bytes. A slide id that is absent, or is not a `KN.SlideArchive`, refuses the candidate."

### 4. Low · name the data field
**Evidence:** F2 images carry both `data` and `thumbnailData` with different ids.

**Fix wording** (I2):
> "data id = `ImageArchive.data.identifier` (never `thumbnailData`)."

### 5. Low · where the witnesses come from
**Evidence:** `_d2` iterates `_landings(previous, slide)` with own=False (`pt:589`), so the witnesses it carries would be post-filter, contents-only landings.

**Fix wording** (I2):
> "`_d2` attaches to the `_Fix` the unfiltered `_landings(previous, slide, own=True)` triples whose target is a group member. The image branch counts those, and checks the single survivor's `_end_rect(leaf)[0]` is non-empty."

### 6. Low · tests: the stale-digest branch has no row
**Evidence:** `PreviewStale` before writes is the only new control-flow exit with no test. The `hp` stub never runs `pt`.

**Fix wording** (§5, optional fifth row):
> "(5) row (1)'s build with a wrong `source_digest` raises `PreviewStale`, and the snapshot is unchanged."

The planner may decline this under the minimal-tests rule. If so, note that G1's pinned-digest path exercises it.

### 7. Low · G1 plumbing details
**Evidence**
- `run_g1` uses system `tempfile.TemporaryDirectory` (`:176`), not the session scratchpad.
- It returns only 0 or 1 (`:200–203`).
- The `--out` location is unstated.

**Fix wording:**
> "G1 temp copies may use system temp. They must be outside every `output/` and `tests/fixtures/`. `--out` goes in the session scratchpad. Add an INCONCLUSIVE outcome so that a missing F2 file or a hash/digest mismatch (including a `PreviewStale` from the pinned digest) makes `run_g1` exit 3."

### 8. Low · cut: one tree digest instead of per-file pins
**Evidence**
- `_load`/`_detect` read every slide, so G1 reads all 38 files that `copy_minimal` copies: header, `main.js`, and 9 slides × json/jsonp/pdf/pdfp.
- OQ-5's parenthetical lists only slides 3 and 4.

**Fix wording** (G1 and OQ-5):
> "Pin F2.key's sha256 and one sha256 over the sorted `(relative path, sha256)` list of the files `copy_minimal` copies from F2-html."

### 9. Low · cut duplicated checks
- **G1 "native-size graft/donor render equality":** the V4 postcondition already requires thumbnail equality (`pt:853–859`), and the graft copies the page object byte-for-byte. Delete it, or mark it optional.
- **G3 "compare Alpha transitions/labels/posters":** this duplicates G2's Alpha regression. Delete it from G3, and keep the owner's eye on F2.
