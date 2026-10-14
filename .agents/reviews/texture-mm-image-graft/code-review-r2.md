# Code review r2: texture MM image graft (Opus 5.5 high)

Target: uncommitted diff on `claude/texture-mm-image-graft` vs origin/main (5 files), after Sol's fold of r1 findings 1–9.
Plan: `.agents/plans/keynote_export_texture_identity.plan.md` rev 4.

**Verdict: APPROVE WITH FIXES.** 0 blocker, 0 major, 0 medium, 4 low (2 of them nits). All r1 findings 1–9 are folded correctly; no regression from the fold itself. One regression vs main (G1 refused/error rows) predates the fold and was missed in r1.

## What I ran (machine rule respected)

- `py_compile` on all 5 files: pass.
- Tiny pure-Python check (no pytest, no Quartz, no F2 decode) of `_SourceEvidence.identity` with hand-built `_Leaf`/`_Slide` and an injected `_objects` dict:
  - DEST alone → `_ImageIdentity('DEST', '44137')`.
  - DEST + OTHER `(152,102,96,16)` → `None`. OTHER expands to `(151,101,98,18)` (not `exact`), envelope gaps all 2 px (`_in_frame_envelope` True), so only `len(envelope) != 1` refuses.
- Not run: pytest, G1, F2 sanity. **The fold is untested.** Before the PR: full suites + 3.10 floor locally, and G1 F2 rows to re-establish the pins, once the machine is released.

## r1 closure (re-derived from the code, not the report)

| r1 | Status | Evidence |
|---|---|---|
| 1 MEDIUM envelope competitor row | Closed | `tests/test_preview_textures.py:284-288` uses `(152,102,96,16)`; offline check above confirms refusal now comes only from the envelope count (`pt:225`, `len(envelope) != 1`). Deleting `len(envelope) != 1` would now turn this row red. |
| 2 LOW digest after failed load | Closed | `pt:174` sets `_loaded = True` before any import/decode; `pt:1127` tests `evidence._loaded`. ImportError / UndecodableIWAMember / BadZipFile now reach the digest check; an unchanged digest still falls through to the refusal. |
| 3 LOW dead checks in `_verify_image_d2` | Closed | `pt:831-834`: `witness, _, _ = fix.landings[0]`; `if not to or to != fix.donor[1]`. The dropped `landed_to`/target-key checks are guaranteed by `_landings(own=True)` (genuine `contents.to` is required here) and the `_d2` key filter (`pt:745`). |
| 4 LOW `_doc` extraction | Closed | `pt:433-440` holds the one NSURL/`CGPDFDocumentCreateWithURL`/`_docs` block; `_page` and `page_count` both use it. `png` never had its own doc cache: it goes through `_page`, and its NSURL import is still needed for `CGImageDestinationCreateWithURL`. Cache keys and semantics are unchanged. |
| 5 LOW `_SourceEvidence` state | Closed (see R2-3 nit) | Two pieces of state: `_loaded` plus nullable `_objects`. `_load()` returns `self._objects is not None` once loaded. Identifier conversion at `pt:203-209` is clean. |
| 6 LOW parametrize column | Closed | `source` is now a per-row key in `expected`, popped at `:467`. The 9 untouched rows have no diff. The non-source path calls `_repair(tmp_path, slides, **{})`, identical to main. The pop order (source, raw_corr, stale, refused) is independent. |
| 7 LOW docstring | Closed | `scripts/texture_repair_check.py:6-8` covers the pins, the kwargs, the synthetic label, post-repair checks, and INCONCLUSIVE exit 3. |
| 8 LOW `run_g1` structure | Closed | `f2_checks` was extracted (`:229-280`). `inputHashes` is written once (`:317`), `injection` once (`:333`). `checks["ok"]` is evaluated before the key is inserted, so it does not include itself. A list value (`fullDetectorHits`) passes only when empty. |
| 9 LOW `winnerUnchanged` | Closed (see R2-2) | Slide 4 is looked up by `ordinal == 4` both before (`:338`) and after (`:249`). The check is now `winner_after == winner_before - repaired_leaves` (`:275`). `entry["leaves"]` uses `leaf.key`, the same string as `_Leaf.key`, so the set difference is well-typed. `winner_before` is taken after injection, so in the synthetic row the injected leaf is in the before set and is removed by the repair. The optional `leaves` in `exactRepairs` was not done (it was optional). |

## Regression check on the fold

- **`_doc()`**: `_page` keeps its own Quartz import for `CGPDFDocumentGetPage`/`GetBoxRect`. `page_count` returns `None` for a missing file, as before. No change in thumbnail or png behaviour.
- **`_SourceEvidence`**: `identity()` dereferences `self._objects` only after `_load()` is True, so it is never None at that point. `pdf()` checks `_member_counts[data_id] != 1` before the member lookup, which keeps the duplicate refusal. Exceptions outside the plan's refusal set (for example OSError when the deck vanishes) still propagate before the digest check. That matches plan §2 and is unchanged from r1.
- **Digest condition**: `evidence is not None and evidence._loaded and deck_digest(path) != source_digest`. It runs after `_plan`, before the `refused` raise, and before any write. It is skipped when the image route was never reached. Plan conformance is unchanged.
- **Tests**: rows (1)–(5) still pass for the right reasons as r1 reasoned. Row (2) now also pins I1.3(b). `_corr` returns exactly `1.0` on `np.array_equal`, so `"corr": 1.0` in row (1) is exact. `test_html_preview`'s stub requires both kwargs, and `apply_preview` passes both on both attempts.
- **Script**: the `f2_checks` extraction and `winnerUnchanged` are correct. One structural regression vs main exists in `run_g1`; it predates the fold and is R2-1.

## Findings

### R2-1. LOW, regression vs main (introduced in the r1 implementation, missed by r1): G1 refused/error rows lose `hitsAfter`, `slidesFrom` and `log`

- **Where**: `scripts/texture_repair_check.py:329-409`.
- **Problem**: on main, `after = json_hits(copy, slides)` ran after the try/except inside the `TemporaryDirectory`, and every row got `slidesFrom`/`hitsAfter`/`log`. Now the whole `with` sits inside the `try`. On `PreviewError` or `Exception`, `after` stays `None` from `:292`, the temp copy is already gone, and the row has no `slidesFrom`/`log`.
  - `preview/3b9019` (the expected-refusal row) now prints `hits after -` and records `hitsAfter: null`. The evidence that a refusal left the hits in place, which is what "writes nothing" looks like in the artifact, is lost.
  - The gate verdict is unaffected, because `matches()` ignores `hits_after` for `refused`.
- **Fix**: restore main's shape inside the temp dir. Keep `slides` prep, the hash checks and `inject_f2_357` where they are. Inside `with tempfile.TemporaryDirectory(...)`:
  - wrap only the `repair_textures` calls, `outcome_of` and `f2_checks` in `try`;
  - in `except PreviewStale` set the inconclusive outcome;
  - in `except PreviewError` / `except Exception` set `record, outcome = None, {...}` as on main;
  - after the except, compute `after = preview_textures.json_hits(copy, slides)` unconditionally;
  - then do one `row.update(slidesFrom=source, hitsBefore=before, hitsAfter=after, outcome=outcome, record=record, log=log, checks=checks)` for every non-stale outcome.
  - Keep an outer `except PreviewError` only for `f2_manifest_slides`/`inject_f2_357` failures.

### R2-2. LOW, edge case (missed in r1): `exactRepairs` derives its expectation from the output it checks

- **Where**: `scripts/texture_repair_check.py:246-248`, `:275`.
- **Problem**: `exact` gains `(4,"D2",14,F2_OTHER_MAP)` whenever *any* repaired entry has donor `F2_OTHER_MAP`, regardless of row.
  - The combined row verdict is still correct, because EXPECT's `{"D2": 1}`/`{"D2": 2}` catches a wrong count.
  - But the check named "exactRepairs" is self-referential, so its own `true` in the artifact proves less than it says.
  - Separately, `winnerUnchanged` passes vacuously if `winner_after` is empty. The plan's "Asia background keeps the winner" is then implied only by the group-rect separation in `_groups`, not asserted.
- **Fix**:
  - Add a `synthetic: bool` parameter to `f2_checks`, passing `label == "F2/synthetic-357"` from `run_g1:371`.
  - Build `exact = [(4, "D2", 15, F2_WINNER)] + ([(4, "D2", 14, F2_OTHER_MAP)] if synthetic else [])`.
  - Change `:275` to `"winnerUnchanged": bool(winner_after) and winner_after == winner_before - repaired_leaves`.

### R2-3. LOW (nit), new: `_objects` starts as `{}` although `None` is its "unavailable" value

- **Where**: `src/obed_edom/preview_textures.py:166`.
- **Problem**: the declared tri-state is `None` = unavailable and dict = loaded. The pre-load value `{}` is a third, unexercised state that reads like "loaded, empty".
- **Fix**: `self._objects: dict[str, dict] | None = None`. Behaviour is identical, because every reader goes through `_load()`, which checks `_loaded` first.

### R2-4. LOW (nit), new: `row["injection"]` is written on every G1 row

- **Where**: `scripts/texture_repair_check.py:333`.
- **Problem**: every non-F2 row now carries `"injection": null`. On main those rows had no such key, and only the synthetic row needs it.
- **Fix**: `if injection is not None: row["injection"] = injection`. Or set it inside the `inject_f2_357` conditional.

## Not findings (checked)

- g2 (`:718`) does not pass source kwargs. The Alpha 7e3c repairs are not image-D2, which is in plan scope and unchanged.
- `f2_manifest_slides`/`inject_f2_357` raising `PreviewError` becomes a `refused` FAIL rather than INCONCLUSIVE. Both inputs are hash-pinned before this point, so only a code change can trigger it, and FAIL is the right signal for that.
- `_SourceEvidence` access to `evidence._loaded` from module scope in the same module is the r1-offered option.

## Gate note

The fold ran without tests under the machine rule. Before the PR, when the machine is free:
- run the full local suites, including the 3.10 floor;
- run G1, which re-establishes both F2 pins (source `9fc882c1…` and tree `25495ad1…`) and checks rows F2 / F2/synthetic-357 against the D2 page 15 / page 14 expectations.
