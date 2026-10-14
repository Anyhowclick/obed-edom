# Code review r1: texture MM image graft (Opus 5.5 high)

Target: uncommitted diff on `claude/texture-mm-image-graft` against origin/main, which touches 5 files. Plan: `.agents/plans/keynote_export_texture_identity.plan.md` rev 4.

**Verdict: APPROVE WITH FIXES.** 0 blocker, 0 major, 1 medium, 8 low, plus 1 informational note.

## What I ran

- `py_compile` passed on all 5 files.
- Offline imports passed: `UndecodableIWAMember`, `_load_deck_full` and `data_member_index`.
- Offline boundary math on `_expanded_frame` and `_in_frame_envelope` behaved as the plan specifies.
  - `(152,102,96,16)` against leaf `(150,100,100,20)` falls inside the envelope but is not an exact match.
  - `(145.99,…)` falls outside the envelope.
- `data_member_index(['Data/map-44137.pdf','Data/x-44137.png'])` collapses both names into one id. `_member_counts` counts 2 for that id, so the code refuses.

**F2 sanity: not re-run.** OBS was live at about 93% CPU, Backblaze was running, and the load average was about 15. A full strict decode of the 562 MB F2.key IWA is not cheap under the machine rule. Instead I checked the implementer's log (`impl/sol.log`):
- Line 17607 (F2): D2 page 15, corr 0.9847192302, objects 15355064→15348427, data 44137.
- Line 17610 (synthetic): adds page 14 `B37026D5`, corr 0.9957348363, objects 15355057→15348425, data 44140.
- Pins (lines 4601–4602): tree `25495ad1…` over 38 files and source `9fc882c1…`.
- The implementer's run says `shasum F2.key` matches the pin even though F2.key's mtime is 18:25 today.

These figures match advisory r2: 0.984719 / 0.995735. G1 must still re-establish the pins after the machine is released.

## Plan conformance (all pass)

- **§2 source lifetime**
  - Lazy `_load_deck_full(strict=True)` runs once per attempt (`pt:174-193`).
  - Duplicate entries are counted per raw name before the index collapses them (`pt:188-189`).
  - Generated scratch filenames are used (`pt:261`).
  - Quartz handles `page_count` and `thumb`; there is no pypdf on the source bytes.
  - An absent slide id, or one that is not a `KN.SlideArchive`, refuses (`pt:198-201`).
  - Refusal triggers are exactly ImportError, UndecodableIWAMember, BadZipFile, a missing or duplicate member, and missing or non-finite geometry. Everything else propagates. The extra `KeyError` in `pdf()` is the "missing member" case.
- **Digest check placement:** after `_plan` returns, before the `refused` raise, before any writes, only when evidence was read (`pt:1126-1129`). `PreviewStale` is not caught by `apply_preview`'s retry, so retry is bypassed and the existing export cleanup runs.
- **I1**
  - floor/ceil±1 frame within 0.01, no clipping.
  - Domain (b) covers every `drawablesZOrder` entry, any `_pbtype`, once per id. Missing or non-finite geometry refuses.
  - Domain (a) is the own-tree leaf count; `_leaf_tree` = event + path prefix through the last `baseLayer`, which is correct for both base trees and nested effect trees.
  - Edge slack is 0–4 px with 1e-3.
  - Competitors are checked before eligibility.
  - Eligibility requires type 5, not `isVideoLayer`, `TSD.ImageArchive`, and no `mask`.
  - Opacity and visibility are never read.
  - `exact ⊂ envelope` always holds (the floor gap is in [1,2)), so the `exact[0] == envelope[0]` comparison is sound.
- **I2**
  - Unfiltered `_landings(own=True)` triples on group members are attached before `_d2`'s filters, including no-contents landings.
  - Exactly one is required, it must have a genuine `contents.to`, and it must equal the donor.
  - Text-D2 donor set semantics are unchanged.
  - `ImageArchive.data.identifier` is used, never the thumbnail.
  - Donor dimensions must be within 0.01 of every member.
- **I3:** every member resolves independently to the same object id; one unresolved member refuses the group.
- **I4:** single page; both thumbnails finite and with std ≥ 2 before `_corr`; raw corr ≥ 0.9, recorded unrounded.
- **`_verify` fallthrough:**
  - The new route comes after the V1 fits/mediabox check and after the text and movie branches.
  - It is gated on `rule == "D2"` and evidence being present.
  - The D1/D3/D4/text/movie routes and thresholds are byte-identical. A D2 failure still falls through to D4.
- **Record:** exactly the 4 fields. `TEXTURE_REPAIR_VERSION = 1`. `hp.apply_preview` passes both kwargs on both attempts.
- **No false-acceptance path found.**
  - An ambiguous MM landing (two event-0 targets) is not counted by `_landings`. But any such duplicate also produces a second own-tree leaf in the envelope of the destination drawable, so I1.3(a) refuses.
  - A movie poster that falls through to the image route (owner unresolved) refuses on `_pbtype != TSD.ImageArchive`.

## Findings

### 1. MEDIUM, edge case (test): row (2) never exercises the envelope competitor check

- **Where:** `tests/test_preview_textures.py:283-287`, row `D2-image-refuses-envelope-drawable-competitor`.
- **Problem:** `OTHER` has geometry identical to `DEST` (151,101,98,18). It therefore matches `exact` too, and the refusal fires at `len(exact) != 1` (`pt:225`). The I1.3(b) envelope-only competitor, the 0–4 px boundary the row is named for, is never exercised. Deleting `len(envelope) != 1` from `pt:225` would leave every row green.
- **Fix:** give `OTHER` the geometry `{"position": {"x": 152, "y": 102}, "size": {"width": 96, "height": 16}}`. That expands to (151,101,98,18), which is not the leaf, so `exact` stays `[DEST]`. All four gaps are 2 px, so `envelope == [DEST, OTHER]` and only the envelope count refuses. I verified both predicates offline.

### 2. LOW, edge case: a failed evidence load skips the digest check

- **Where:** `src/obed_edom/preview_textures.py:193` and `:1127`.
- **Problem:** `evidence_read` is set only after a successful load. A deck that is mid-save during repair (BadZipFile, or a member that won't decode) becomes a refusal plus one re-export instead of `PreviewStale`. That is wrong classification only, not a false acceptance.
- **Fix:** run the digest check whenever a load was attempted. Either set the flag at the top of `_load()` (after `self._loaded = True`), or test `evidence._loaded`, and drop the third boolean (see finding 5). An unchanged digest still falls through to the refusal.

### 3. LOW, new: dead and redundant checks in `_verify_image_d2`

- **Where:** `src/obed_edom/preview_textures.py:832` and `:836`.
- **Problem:**
  - `not end` is always False, because `_end_rect` always returns a 4-tuple.
  - `landed_to != to` cannot be true for a landing that has `contents.to`.
  - `target.key not in {…group keys}` is already guaranteed by the filter in `_d2` (`pt:744`).
- **Fix:** reduce line 832 to `if not to or to != fix.donor[1]:`, delete lines 836-837, and unpack the triple as `witness, _, _ = fix.landings[0]`.

### 4. LOW, new: `page_count` duplicates `_page`'s document cache

- **Where:** `src/obed_edom/preview_textures.py:474-482`.
- **Problem:** `_Renderer.page_count` copies the NSURL/`CGPDFDocumentCreateWithURL`/`_docs` block from `_page` verbatim.
- **Fix:** extract `def _doc(self, pdf) -> Any` that both `_page` and `page_count` use. Cache behaviour is unchanged: one dict keyed by Path, and scratch names are unique per attempt.

### 5. LOW, new: `_SourceEvidence` carries redundant state and one clunky line

- **Where:** `src/obed_edom/preview_textures.py:162-193`, `:207`.
- **Problem:** there are three booleans (`_loaded`, `_available`, `evidence_read`) where one tri-state is enough. Line 207 calls `ref.get("identifier")` twice.
- **Fix:**
  - Keep `_loaded` (attempted) plus `_objects: dict | None` (None meaning unavailable).
  - Make `evidence_read` the attempted flag (folding in finding 2).
  - Rewrite line 207 as `ident = ref.get("identifier"); if ident is None: return None; ident = str(ident)`, or equivalent.

### 6. LOW, new (style): new `source_case` column touches nine unchanged rows

- **Where:** `tests/test_preview_textures.py:374-463`.
- **Problem:** the new `source_case` parametrize column adds `None,` to 9 untouched rows. Local style carries per-row knobs inside `expected` and pops them; `raw_corr`, `refused` and the new `stale` already work this way.
- **Fix:** put `"source": "ok" | "drawable-competitor" | "different-data" | "wrong-digest"` in the new rows' `expected` dicts, read it with `source_case = expected.pop("source", None)`, and drop the column. The existing rows' diff then disappears.

### 7. LOW, new: script docstring doesn't describe the new g1 behaviour

- **Where:** `scripts/texture_repair_check.py:4-5`.
- **Problem:** the g1 paragraph still says only "every known export … compared with the expected outcome table".
- **Fix:** add one sentence covering three things:
  - the two pinned F2 rows, with source and tree sha256, the source kwargs, and `F2/synthetic-357` labelled "synthetic defect, real chain/donor";
  - the post-repair checks;
  - that a missing or mismatched pin, or `PreviewStale`, is INCONCLUSIVE (exit 3).

### 8. LOW, new (style): `run_g1` has grown into a deeply nested block with duplicate row writes

- **Where:** `scripts/texture_repair_check.py:226-412`.
- **Problem:** `run_g1` is now about 185 lines and 7 levels deep. It writes the same row fields more than once:
  - `inputHashes` is set at `:249`, set again in the mismatch branch at `:262`, and re-copied from itself at `:360`;
  - `injection` is re-copied at `:361`.
- **Fix:**
  - Move the F2 post-repair block (`:300-351`) into `def f2_checks(copy, slides, record, second, blind_before, winner_before, plan_before) -> dict`.
  - Compute `checks["ok"] = all(v if isinstance(v, bool) else not v for v in checks.values())`, or an explicit tuple.
  - Delete the redundant `inputHashes=`/`injection=` re-assignments.

### 9. LOW, edge case: `winnerUnchanged` cannot catch a wrongly repointed winner leaf

- **Where:** `scripts/texture_repair_check.py:277-279`, `:336`.
- **Problem:**
  - The check compares slide 4's `DF3DB700` table entry, which no writer ever mutates, so it cannot fail.
  - `exactRepairs` compares only `(ordinal, rule, page, id)`, not `leaves`.
  - `loaded_before[3]`/`loaded_after[3]` hard-codes a player index, while `inject_f2_357` looks the slide up by `originalOrdinal == 4`.
- **Fix:**
  - Look slide 4 up by ordinal in both places.
  - Make `winnerUnchanged` assert that the slide-4 leaves still on `F2_WINNER` after repair are exactly the before set minus the repaired `leaves`. This means the Asia background leaf keeps the winner.
  - Optionally add `entry["leaves"]` to the `exactRepairs` tuple.

### 10. INFORMATIONAL (no action unless the owner wants it): two gaps in coverage

- No row covers the I2 witness count: a second, no-contents MM landing on a group member must refuse. Neither does anything pin "digest check before the refused raise"; row (5) only pins "before writes".
- Both are outside the plan's approved five rows. Under the minimal-tests rule I am not asking for them. Bring them to the owner only if they want the I2 multi-witness rule pinned.

## Tests: do rows (1)–(5) pass for the right reason? (reasoned, not run)

- **(1) ok**
  - The S2 BIG leaves in event 0 and event 1 form one group (R1 on both, R6 on event 0).
  - `_d2` returns donor TO with exactly one own-landing (the S1 MM leaf; the S1 base HELLO leaf is not MM).
  - V1 passes. The image route resolves:
    - DEST: expanded (150,100,100,20) equals the leaf, and it is alone in each event's own tree;
    - SRC: the MM effect tree `(1,'effects',0,'baseLayer')`;
    - both data ids are 44137.
  - The zip member `Data/map-44137.pdf` is counted once. It is a single 100×20 "L" page, pixel-identical to the TO page, so std ≈ 63 ≥ 2 and corr = 1.0.
  - The shared D2 assertions (`D2_ID`, index 1, two pages) hold, and the postcondition R6 sees corr 1.
  - **Passes.**
- **(2) drawable-competitor:** refuses, but for the exact-duplicate reason (finding 1).
- **(3) different-data:** the only change from (1) is DEST's data id, which refuses at `source.data_id != destination.data_id`. D4 has no donors, so it cannot mask the result. **Correct boundary.**
- **(4) group-competitor:** OTHER (kind 6, fits, not a hit) sits at the identical rect only in event 1's base tree. The event-0 member passes and the event-1 member gets a competitor count of 2, so the whole group refuses. This covers I1.3(a) and I3. **Correct.**
- **(5) wrong-digest:** evidence is read and the plan succeeds. `deck_digest` (sha256 of the zip) differs from `"0"*64`, so `PreviewStale` is raised before writes and the snapshot is unchanged. **Correct.**
- **`test_html_preview` stub:** `source_path == deck` holds because `apply_preview` uses `Path(str(proposal['path']))` unresolved. `source_digest == DIGEST` holds on both attempts. Other `apply_preview` tests use the unsupported fake player, so they skip before evidence. **Passes.**

## Script G1 conformance (§6)

- **Matches the plan:**
  - Pinned source and tree sha256.
  - Missing file, hash mismatch, or `PreviewStale` gives INCONCLUSIVE, and the run exits 3 unless something failed.
  - The synthetic row is labelled and records its field and before/after hashes.
  - Slides come from `source_slides(F2.key)` zipped onto `slideList`, with the count and no-skip asserted.
  - All work happens in system temp via `TemporaryDirectory`, and nothing is written under `output/` or `tests/fixtures/`. The only other write is `deck_digest`'s usual sidecar under `<repo>/.cache`.
  - Existing EXPECT rows are unchanged, and the `copy_minimal` refactor copies the same file set.
- **Findings:** 7, 8 and 9 apply here.
