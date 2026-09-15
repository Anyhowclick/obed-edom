# VERDICT: APPROVE-WITH-NITS

Full suite: `1816 passed, 84 skipped` in 76s (`PYTHONPATH=src … -m pytest -q`).
`dashboard && npx tsc --noEmit`: clean.

All four codex-r2 findings are fixed, and all six opus-r3 findings are fixed as well. I drove
every writer exit path by hand rather than trusting the tests. Two nits remain; neither is a
correctness risk and one is the `reason` field failing to carry the signal it was added for.

## Verification — codex-r2

| # | status | evidence |
| --- | --- | --- |
| 1 client-patchable write path | FIXED | `app.py:1026` writes to `diff_work_dir(job.id) / "diagnostics.jsonl"` with a comment saying why; `_trusted_diagnostics_path` (`app.py:668-680`) now expects `output_root() / ".diff" / job_id / "diagnostics.jsonl"`, which is `diff_work_dir`'s definition (`inspect.py:1073-1076`) minus its mkdir side effect — read and write paths agree, and the read side no longer creates directories (this also closes opus-r3 #5). `DiagnosticsWriter.__init__` (`diagnostics.py:37-40`) refuses a symlinked target or temp path. Covered by `test_run_diff_check_ignores_a_patched_external_work_dir` and `test_diagnostics_writer_refuses_to_write_through_a_symlink`. |
| 2 truncate-before-success | FIXED | Records go to `path + ".tmp"`; `commit()` (`:66-86`) closes, checks `_failed`, then `os.replace`. `_run_diff_check` commits only after `compare_inspects` AND `_apply_outline` return (`app.py:1052-1053`), with `finally: if not diag_committed: diag.close()` (`:1054-1056`). |
| 3 `carried` discarded in replay | FIXED | `diagnostics.py:203-214` keeps the strip's `carried` in `replay_selected` and `:236` compares it against the recorded attempt. `test_replay_catches_a_point_title_carry_change` covers it. |
| 4 missing `reason` | PARTIAL — see finding 1 | `select_text_sources` returns 4-tuples (`diff_keynotes.py:994-1007`) and the recorder writes `reason` per attempt (`:1438`). Both call sites unpack 4-tuples (`diff_keynotes.py:1431`, `diagnostics.py:201`); no other caller exists, and `tests/test_diff_keynotes.py:1358` was updated. But the value carries no information — below. |

## Verification — writer exit paths (run, not read)

Against a pre-existing `diagnostics.jsonl` containing `gen: OLD`, checking the directory
listing after each:

- `close()` without commit → old file intact, no `.tmp` left.
- `commit()` → file replaced with the new content, no `.tmp`.
- `commit()` twice → returns True, idempotent; `close()` after a commit is a no-op and does
  not delete the published file.
- write failure mid-run (handle closed under it) → `commit()` returns False, `error` set, old
  file intact, `.tmp` removed.
- `with` + exception → aborts, old file intact, no `.tmp`.
- `with` + clean exit → commits (`__exit__` at `:104-108` commits on `exc_type is None`,
  aborts otherwise), which is what every `with DiagnosticsWriter(...)` in the tests relies on.
- symlinked target → `OSError` from the constructor, caught by `_run_diff_check`'s
  `except OSError` and degraded to `diag = None`.

In `_run_diff_check` the `finally` covers a raise from `compare_inspects` and from
`_apply_outline` identically: `diag_committed` is still False, so `close()` discards. There is
no path that leaves a stray `.tmp` short of process death, and `_purge_artifacts` takes the
whole work dir anyway.

## Verification — opus-r3 findings

All six fixed. `_raw_key` (`diagnostics.py:222-224`) compares `(rule, default)` so a
presentational change now surfaces as message-only — verified end to end by monkeypatching
`text_diff._phrase` over a file written by a real `compare_inspects`:
`MISMATCH(message)`, exit 0, and exit 1 under `--strict`. The message-only test now drives
that same monkeypatch instead of forging an impossible record. `_published_outcome` delegates
to `validate.rule_severity(..., rules=...)` (`validate.py:44`), `record_flag` is public, and
the SKILL.md paragraph now describes the source re-derivation, the `off`-rule `--rule`
semantics, and the atomic replace.

## 1. MED — `reason` duplicates `source` and still omits why the typed attempt was skipped
`src/obed_edom/diff_keynotes.py:1000-1006`. The three constants map one-to-one onto `source`:
`typed`→`typed-covers-both`, `clean`→`clean-symmetric`, `full`→`clean-asymmetric-full`. A
recorded pair's reason is therefore fully derivable from a field already present, and replay
correctly does not bother comparing it (`diagnostics.py:230-237`). The plan's list was
`typed-covers-both`, `typed-below-coverage`, `typed-empty`, `filter-symmetric`,
`filter-asymmetric` — the two that carry real signal are exactly the missing ones: when the
typed attempt is skipped, the log does not say whether it was skipped because a side had no
typed text at all or because it missed `TYPED_COVERAGE`. That distinction is the near-miss
the plan wanted visible, and it is the tuning question the whole file exists to answer.
(The `shares` floats make it derivable by hand, which is not the same as recorded.)
Fix: return the skip cause alongside the attempts —
```py
def select_text_sources(...) -> tuple[list[tuple[str, str, str, str]], str | None]:
    ...
    if not both_typed:
        typed_skip = "typed-empty"
    elif not (_covers_slide(a_typed, a_text) and _covers_slide(b_typed, b_text)):
        typed_skip = "typed-below-coverage"
    else:
        typed_skip = None
```
record it on the text record next to `shares` as `typedSkip`, and rename the fallback reasons
to the plan's `filter-symmetric` / `filter-asymmetric`. If instead you keep `reason` as is,
delete it — a field that restates `source` is noise in a file that is already a few MB.
Whichever way, if `reason` ever becomes informative it must join the `selected_ok` comparison
at `diagnostics.py:230-237`.

## 2. LOW — one unserialisable record now discards the entire file
`src/obed_edom/web/app.py:1052`: `if diag is not None and diag.error is None: diag.commit()`.
But `_write` (`diagnostics.py:55-59`) deliberately sets `self.error` WITHOUT `_failed` for a
`json.dumps` failure, precisely so the stream survives one bad record — that was the r3 fix
Codex asked for. The commit gate now makes that same single bad record fatal to the whole
file, reversing the policy one layer up. The two rules should not disagree.
Fix: drop the precondition and let `commit()` decide — it already returns False when
`_failed` (`:75-77`) and leaves the previous file in place:
```py
if diag is not None:
    diag_committed = diag.commit()
```
A dropped record then still publishes (and `diag.error` is still worth logging as a warning
rather than as "discarded").

## 3. LOW — the failure log line goes silent when a record was merely dropped
`src/obed_edom/web/app.py:1058-1062`. With finding 2 applied, a run with `diag.error` set but
a successful commit would log "Wrote diagnostics for N pair(s)." and say nothing about the
dropped record. Add an `elif diag.error:` after the committed branch —
`job.log(f"Diagnostics are missing a record ({diag.error}).")` — so the operator knows the
file is not complete before they send it.

## 4. LOW — a failed re-check leaves an unreachable old file
On a commit failure, `diagnosticsPath` is set to `None` (`app.py:1067`) while the previous
`diagnostics.jsonl` stays on disk. That is the right call — serving last week's file as if it
were this check's would be worse — but the operator is told only that diagnostics were
"discarded", which is untrue of the file that is still there.
Fix: one word in the log line — "…discarded; the previous diagnostics file is unchanged".

## 5. LOW — the symlink guard checks only the final component
`src/obed_edom/diagnostics.py:37-38` tests `path.is_symlink()` / `tmp_path.is_symlink()`, not
the parents. Moot while the path comes from `diff_work_dir` (server-owned, under
`output_root()`), but the guard reads as more general than it is.
Fix: either say so in the docstring, or `self.path.parent.resolve()` and require it to be
under `output_root()`.

## Checked, no regression
- `select_text_sources`'s selection logic is untouched by the 4-tuple change — same gates,
  same order, same `a_clean or a_text` fallback; the reason string is appended only.
- Both unpack sites take 4 values; `tests/test_diff_keynotes.py:1358-1400` and the three
  `_record`-style helpers in `tests/test_diagnostics.py` were all updated, and no other caller
  of `select_text_sources` exists in `src`, `tests`, or `dashboard/src`.
- `_discard_tmp` swallows its own `OSError`, so an undeletable temp file cannot mask the real
  error; the leftover is purged with the work dir.
- The download endpoint keeps serving the previous complete file for the whole duration of a
  re-check, which is the behaviour codex-r2 #2 asked for.
