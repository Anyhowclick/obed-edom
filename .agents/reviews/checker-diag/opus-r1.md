# VERDICT: REVISE

Suite: `101 passed, 2 skipped` (test_diagnostics.py, test_diff_keynotes.py, test_dashboard_api.py).
`dashboard && npx tsc --noEmit`: clean.

The step-2 refactor is byte-identical — I traced it and found no semantic change (finding 0).
The problems are in the record/replay contract and in robustness.

## 0. (no defect) `select_text_sources` is a faithful refactor — HIGH confidence

`src/obed_edom/diff_keynotes.py:982-994` vs the removed block. Verified:
`both_typed` gate, `_covers_slide` on both sides, `_filter_symmetric` → `a_clean or a_text`
fallback, attempt order. The loop at `:1408-1430` preserves `carried = carried or dropped`
across attempts, `compare_text = text` on every attempt, and break-on-first-non-None so the
clean/full attempt is skipped exactly when the typed attempt fired. `ignore_left_tokens=
point_number_lines(text)` is still computed inside `compare()` on the POST-strip text
(`:1385-1400`) and the record mirrors it (`sorted(point_number_lines(text))`, `:1419`).
Only behaviour delta: `a_clean`/`b_clean` are now always computed instead of lazily — pure
strings, no side effects.

## 1. HIGH — the header is not the first line whenever `diff.count` fires
`src/obed_edom/diff_keynotes.py:1136-1149` (finding record) precedes `:1196-1231` (header).
Reproduced: two same-type decks with different slide counts produce a file whose first line
is `{"kind": "finding", "rule": "diff.count", ...}`, and `load_records` then raises
`Diagnostics file missing header` — the whole file, and `diag-replay`, is dead for exactly
the jobs staff most want to report. No test covers unequal slide counts.
Fix: leave `flags.append(count_flag)` where it is and move only the `diag.record("finding",
... "diff.count" ...)` call to immediately after the `diag.header(...)` block at `:1231`
(guard it on the flag being set), or hoist the header write above the count block by
computing `point_titles` earlier.

## 2. HIGH — `replay` does not re-run the branch selection, so it cannot detect the change it exists to detect
`src/obed_edom/diagnostics.py:80-89` iterates the RECORDED `attempts` and calls
`classify_text_diff` on the recorded post-strip strings. Consequences:
`select_text_sources`, `_covers_slide`, `_filter_symmetric`, `TYPED_COVERAGE`,
`FILTER_TOLERANCE` and `strip_carried_point_title` are all outside the replay loop. Move
`TYPED_COVERAGE` from 0.6 to 0.9 and `diag-replay` still reports 100% MATCH. The plan's
stated reason for step 2 existing ("replay then covers the whole decision, not its tail")
is unmet, and the header advertises those thresholds as if replay honoured them.
The record already carries everything needed. Fix: in `replay`, when `rec["left"]` is
present, do
`attempts = select_text_sources(l["text"], l["typed"], l["outsidePhotos"], r["text"], r["typed"], r["outsidePhotos"])`,
then per attempt `text, _ = strip_carried_point_title(a_src, b_src, header["pointTitles"])`
when `pointTitles` is non-empty, and classify with
`ignore_left_tokens=point_number_lines(text)`. Fall back to the recorded `attempts` only
when the record has no `left`/`right` block.

## 3. MED — `text.point_carry` is recorded nowhere
`src/obed_edom/diff_keynotes.py:1002` excludes every rule starting with `text.` from the
`finding` records, but only the pair text OUTCOME is captured in the text record's
`outcome` field (`:1487-1489`). `text.point_carry` (`:1435-1444`) therefore appears in
`flags` and in the UI but in no diagnostics record — the file is not the complete inventory
the plan promises, and a point-carry false positive cannot be reported at all.
Fix: replace the rule-prefix test with an explicit opt-out at the single call site that
needs it — add `record: bool = True` to `_add_flag` and pass `record=False` only for the
`text_flag` call at `:1458`.

## 4. MED — deck-level `validate_inspect` flags are never recorded
`src/obed_edom/diff_keynotes.py:1659-1685`: `flags.extend(inspect_flags)` bypasses
`_add_flag` entirely, so every `bounds.*` / `bible.*` / `outline.*` flag from
`validate_inspect` is missing from the file. Plan step 4 asked for this loop explicitly.
Fix: after `flags.extend(inspect_flags)` add
`if diag is not None: for f in inspect_flags: diag.record("finding", rule=f.rule, ..., pairIndex=None)`
— factor the repeated kwargs block (it now appears three times) into a module-level
`_record_flag(diag, flag, pair_index)`.

## 5. MED — diagnostics can abort a staff check run
`src/obed_edom/web/app.py:1005-1009` guards only `OSError` on OPEN. Every subsequent
`diag.record(...)` runs inside `compare_inspects` unguarded, and
`src/obed_edom/diagnostics.py:29-31` will raise `TypeError` on any non-JSON value or
`OSError` on a full disk, killing the check. `ruleSeverities=load_rules().get("rules")`
(`diff_keynotes.py:1229`) is a verbatim parsed-config blob — the one field here whose type
is not under this code's control.
Fix: make the writer self-disabling —
```py
def _write(self, obj):
    if self._failed: return
    try:
        self._fh.write(json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False) + "\n")
    except Exception:
        self._failed = True
```
`allow_nan=False` also closes the `NaN`-is-not-JSON hole (a NaN today would be written as a
bare `NaN` token that non-Python readers reject).

## 6. MED — the replay test does not prove replay works
`tests/test_diagnostics.py:59-68` monkeypatches `classify_text_diff` itself to
`lambda *a, **k: None`. That stubs out the entry point, so the test passes against ANY
replay implementation that calls it once — including one that ignores the recorded inputs.
The plan asked for a THRESHOLD monkeypatch precisely because that is the honest signal.
Fix: `monkeypatch.setattr(text_diff, "LINE_MATCH", 0.0)` (or another real constant) and
assert the mismatch. Add a second case for finding 2: record a pair whose typed share sits
just above `TYPED_COVERAGE`, monkeypatch `diff_keynotes.TYPED_COVERAGE` to 0.99, and assert
`replay` returns 1 — that test fails today.

## 7. MED — the inventory-completeness assertion is too weak to catch 3 or 4
`tests/test_diagnostics.py:113-115` compares SETS of text rules only. The plan's assertion
was "every flag in `flags` appears exactly once across the `text`/`finding` records", which
would have caught both `text.point_carry` and the `inspect_flags` gap.
Fix: build `Counter` over `[r["outcome"]["rule"] for text records with outcome] +
[r["rule"] for finding records]` and assert it equals `Counter(f.rule for f in flags)` on a
fixture that produces at least one non-text and one deck-level flag. Also add the
unequal-slide-count case from finding 1.

## 8. LOW — a failed writer leaves the PREVIOUS run's diagnosticsPath in the result
`src/obed_edom/web/app.py:1038`: `str(diag_path) if diag is not None else result.get("diagnosticsPath")`.
On a re-check where the open failed, the result keeps the stale path; the file still exists
in the work dir, so the UI serves the PREVIOUS check's diagnostics as if they were current.
Fix: `"diagnosticsPath": str(diag_path) if diag is not None else None`.

## 9. LOW — `open -R` on a non-macOS host returns 500
`src/obed_edom/web/app.py:308`: `check=False` suppresses a non-zero exit, not a missing
binary; `FileNotFoundError` propagates as a 500. argv form is a list with no shell and the
path is server-derived (not user input), so there is no injection or traversal issue — the
endpoints take no path component at all and correctly 404 on a missing/absent file.
Fix: `try: subprocess.run([...], check=False) except OSError: raise HTTPException(500, "Could not reveal the file")`.

## 10. LOW — style: closing-paren reflow and per-pair record noise
The `_add_flag` call sites were reflowed from the file's trailing-comma style to
`), diag=diag, pair_index=pair_i)` (e.g. `diff_keynotes.py:1301, 1314, 1341, 1368, 1444`),
which does not match the surrounding code and makes the diff harder to read than it needs
to be. Keep `),\n  diag=diag,\n  pair_index=pair_i,\n)`.
Also `from obed_edom.validate import load_rules` at `:1199` is a function-local import
although `obed_edom.validate` is already imported at module top (`:36`) — move it up;
`NEAR_DUPLICATE`/`ocr_unavailable` likewise (`obed_edom.rendered` is imported at `:21`).
`diag: object | None` gives up all typing on a parameter with exactly one real type —
`if TYPE_CHECKING: from obed_edom.diagnostics import DiagnosticsWriter` costs one line.

## Not defects
- Overwrite-on-re-check (`"w"`), purge-with-the-job (`diagnosticsPath` lives under
  `workDir`, covered by `jobs.py:287-289`), 404 paths, the download filename, and the
  dashboard change (one anchor + one button, `diagnosticsUrl` mirroring `evidenceUrl`) are
  all correct and minimal.
- Per-pair "no finding" records are present unconditionally at `diff_keynotes.py:1459-1490`.
- `split_labels` is never passed by `compare_inspects` and defaults to `True` in both the
  live path and replay, so its absence from the record is harmless. Per-side `ocr_used`
  flags are the one genuinely missing tuning input (only the OR'd `pair["ocr"]` is kept) —
  cheap to add as `left.ocrUsed` / `right.ocrUsed`.
