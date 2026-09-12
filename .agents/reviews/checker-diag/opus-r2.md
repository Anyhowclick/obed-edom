# VERDICT: APPROVE-WITH-NITS

Suite: `102 passed, 2 skipped` (test_diagnostics.py, test_diff_keynotes.py, test_dashboard_api.py).
`dashboard && npx tsc --noEmit`: clean.

All ten r1 findings are fixed, and I verified the three hard ones by running them, not by
reading. Two MED items remain, both introduced by the r1/#5 robustness fix; neither blocks
the behaviour the plan asks for.

## Verification of the r1 findings

| r1 | status | evidence |
| --- | --- | --- |
| 1 header ordering | FIXED | `count_flag` hoisted to `diff_keynotes.py:1147`, recorded at `:1232-1233` after `diag.header`. Re-ran my repro (same-type decks, 1 vs 2 slides): first line is now `kind: "header"`, `load_records` succeeds, and the `diff.count` finding record is still present. |
| 2 replay re-derives the branch | FIXED | `diagnostics.py:95-111` calls `select_text_sources` on the raw recorded strings, applies `strip_carried_point_title` with `header["pointTitles"]`, and recomputes `ignore_left_tokens=point_number_lines(text)`. `tests/test_diagnostics.py:63-91` builds a pair whose typed share (0.7) straddles the threshold and asserts `replay == 0` then `replay == 1` after `monkeypatch.setattr(diff_keynotes, "TYPED_COVERAGE", 0.99)` — it flips. A live `compare_inspects` file also replays 0. |
| 3 `text.point_carry` | FIXED | `record: bool = True` on `_add_flag` (`:1023`), `record=False` only at the `text_flag` site (`:1481`). `text.point_carry` now lands as a `finding` record. |
| 4 `validate_inspect` flags | FIXED | `diff_keynotes.py:1717-1718`, and asserted by the new inventory test (`bounds.straddles`). |
| 5 diagnostics can't abort the check | FIXED | `_write` self-disables (`diagnostics.py:31-40`) with `default=str, allow_nan=False`. I closed the file handle mid-run to simulate disk death: `compare_inspects` completed all 3 pairs, `writer.error == "I/O operation on closed file."`. I also forced a non-serialisable header value; `default=str` absorbed it. |
| 6 honest replay test | FIXED | the `classify_text_diff` stub test is gone, replaced by the `TYPED_COVERAGE` test above. |
| 7 inventory completeness | FIXED | `tests/test_diagnostics.py:142-193` — `Counter` over text outcomes + finding records vs `Counter(f.rule for f in result["flags"])`, on a fixture that produces `diff.count` and a deck-level `bounds.straddles`, with unequal slide counts. This is the test r1 asked for and it also covers finding 1. |
| 8 stale `diagnosticsPath` | FIXED | `app.py:1039` is now `str(diag_path) if diag is not None else None`. |
| 9 `open -R` on a non-mac host | FIXED | `app.py:307-310` wraps in `try/except OSError` → 500. |
| 10 style | FIXED | trailing-comma call style restored at every `_add_flag` site; `__version__`, `NEAR_DUPLICATE`, `ocr_unavailable`, `load_rules` moved to module top (no cycle — `obed_edom/__init__.py` is two lines); `TYPE_CHECKING` import of `DiagnosticsWriter` with string annotations. |

The step-2 refactor is unchanged from r1 and still byte-identical.

## 1. MED — a writer that dies mid-run is invisible to the operator and to the UI
`src/obed_edom/web/app.py:1032-1039`. `diag.error` is set by the writer but nobody reads it:
`_run_diff_check` still logs `"Wrote diagnostics for N pair(s)."` and still publishes
`diagnosticsPath`. Reproduced — after an IO death the file is 0 bytes, the dashboard shows
"Export diagnostics", the staff member downloads an empty file, and `diag-replay` on it
dies with `Empty diagnostics file`. Silent-and-wrong is worse than the crash r1 removed.
Fix:
```py
if diag is not None:
    if diag.error:
        job.log(f"Diagnostics were incomplete and have been discarded ({diag.error}).")
    else:
        job.log(f"Wrote diagnostics for {len(pairs)} pair(s).")
...
"diagnosticsPath": str(diag_path) if diag is not None and not diag.error else None,
```

## 2. MED — one bad float discards the rest of the run's diagnostics
`src/obed_edom/diagnostics.py:31-40`. `allow_nan=False` is right, but the resulting
`ValueError` sets `self._failed` permanently, so a single NaN in one `score` silently drops
every later record. Verified: `header` + `record(score=nan)` + `record(score=2)` produces a
one-line file with `error="Out of range float values are not JSON compliant"`. A NaN is a
per-record data problem, not a broken stream; an IO error is the opposite.
Fix: separate the two.
```py
except ValueError:
    return                       # unserialisable record, keep the stream
except Exception as exc:         # noqa: BLE001
    self._failed = True
    self.error = str(exc)
```
Then finding 1's discard only triggers on a genuinely broken file.

## 3. LOW — replay still compares rule only, never message
`src/obed_edom/diagnostics.py:123-124` compares `finding.rule` to `recorded_rule`. The plan
explicitly wants the planned `_phrase` presentation change to surface as a "message-only
mismatch" ("a good check that the tool distinguishes message changes from classification
changes"). Today it would replay as MATCH.
Fix: compare `(rule, message)`, and print `MISMATCH(message)` when the rules agree but the
messages differ; count it separately from classification mismatches so a message-only
change does not have to fail the exit code unless the caller wants it.

## 4. LOW — the pre-`left`/`right` replay fallback is unreachable
`src/obed_edom/diagnostics.py:112-122`. Within `SCHEMA = 1` every `text` record carries
`left`/`right`, and `load_records` hard-rejects any other schema, so this branch can never
run. It is the only place `attempts[].ignoreLeftTokens` is consumed, which makes the
recorded value look load-bearing when it is now purely descriptive.
Fix: drop the branch and let a malformed record raise, or keep it and say in one line why
(a hand-written fixture that omits the raw strings). Do not leave it unexplained.

## 5. LOW — per-side `ocrUsed` is still not recorded
`src/obed_edom/diff_keynotes.py:1503` records only the OR'd `pair["ocr"]`. When tuning a
false positive it matters whether the LEFT or the RIGHT string came from OCR.
Fix: add `"ocrUsed": a_render.ocr_used` to the `left` block and
`any(r.ocr_used for r in b_renders)` to the `right` block.

## Checked, no defect
- `_record_flag` is called from exactly two places outside `_add_flag` (`diff.count` at
  `:1233`, `inspect_flags` at `:1717`), both with `pairIndex=None`, and no flag is recorded
  twice — the new `Counter` test proves it on a fixture with both.
- `record=False` appears at exactly one call site, the text outcome, which is carried by the
  `text` record's `outcome` field instead.
- Top-level import moves introduce no cycle and no import-time cost beyond what
  `obed_edom.rendered` / `obed_edom.validate` already paid.
- `default=str` means no realistic value can raise `TypeError`, including the verbatim
  `load_rules()` blob (verified with a `set` inside it).
- Endpoints, filename, purge-with-workDir, overwrite-on-recheck and the dashboard change are
  unchanged from r1 and remain correct.
