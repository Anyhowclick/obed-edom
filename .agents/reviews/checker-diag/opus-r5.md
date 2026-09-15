# VERDICT: APPROVE-WITH-NITS

Full suite: `1821 passed, 84 skipped` in 78s (`PYTHONPATH=src … -m pytest -q`).
`dashboard && npx tsc --noEmit`: clean.

All three codex-r3 findings are fixed, and the four r4 nits are applied (three as written, the
symlink-parents one deliberately declined with a note — the right call, see below). Nothing
remains above LOW. I traced the replay loop against the recorder line by line and drove both
the "fires on the first attempt" and "no finding on any attempt" cases through real
`compare_inspects` output.

## Verification — codex-r3

**1. Full attempt sequence (was MED).** `diagnostics.py:204-231` now mirrors
`compare_inspects` (`diff_keynotes.py:1439-1458`) exactly:

| recorder | replay | same? |
| --- | --- | --- |
| appends an entry for every attempt *tried*, before the break | `replay_attempts.append(entry)` before the break | yes |
| `carried = carried or dropped` per attempt | `replay_carried_acc = replay_carried_acc or carried` | yes |
| `break` on the first non-None finding | `break` on the first non-None finding | yes |
| strip skipped entirely when `point_titles` is empty (`compare()` at `:1414-1417`) | `if point_titles:` guard at `:208-210`, `carried = None` otherwise | yes |

`sequence_ok` (`:253-256`) compares length plus a per-entry `_attempt_key` covering source,
reason, both inputs, ignore tokens, that attempt's own `carried`, and `(rule, default)`;
`carried_ok` (`:257-258`) compares the accumulated pair-level value against the new
`carried` field on the record (`diff_keynotes.py:1523`). An earlier attempt's carry change is
therefore caught twice over. `test_replay_catches_a_carry_change_on_a_non_selected_attempt`
(`tests/test_diagnostics.py:361`) is the requested two-attempt regression.

Run against real output:
- identical slides, nothing fires — both attempts recorded
  (`typed/typed-covers-both/None`, `clean/filter-symmetric/None`), `replay` reconstructs both
  and returns MATCH. This is the case the early `break` could most easily have got wrong.
- `Your Faith` vs `Faith` — the typed attempt fires, exactly one attempt recorded, MATCH.

**2. Per-attempt `reason` (was LOW).** `select_text_sources` (`diff_keynotes.py:994-1015`)
returns 4-tuples carrying the admitting gate — `typed-covers-both`, `filter-symmetric`,
`filter-asymmetric` — and separately the skip cause (`typed-empty` /
`typed-below-coverage` / `None`). That is the plan's five constants split across the two
places they actually belong, which resolves my r4 objection properly rather than by dropping
the field: `reason` is now compared by replay through `_attempt_key`, and `typedSkip` carries
the near-miss signal the log was missing. `test_select_text_sources_typed_skip_causes`
(`:409`) is a parametrised table over the three causes.

**3. Symlinked canonical file (was LOW).** `_trusted_diagnostics_path` (`app.py:666-683`)
rejects a symlinked final component outright, then resolves only the PARENT and re-appends
the literal name, so the candidate can no longer be resolved onto the expected path.
`test_diagnostics_endpoints_404_when_the_canonical_file_is_a_symlink` (`test_dashboard_api.py:702`)
symlinks the real canonical path at a neighbouring file and asserts 404 on GET and reveal.
I re-ran it twice in separate sessions to check it is idempotent — it is, because
`tests/conftest.py:13-14` redirects `OBED_EDOM_OUTPUT_ROOT` to a fresh temp dir per session
and removes it in `pytest_sessionfinish`, so nothing lands in the user's real `output/`.

Declining the parents-symlink check is correct: on macOS `/var` is itself a symlink to
`/private/var`, so any "no symlinked ancestor" rule rejects every `tmp_path`, and the parent
is server-owned (`diff_work_dir`) anyway. The one-line note at `diagnostics.py:38-40` says so.

## Verification — opus-r4 nits

- #2 commit gate: `app.py:1057-1058` now calls `diag.commit()` unconditionally and lets
  `commit()`'s own `_failed` check decide, so a single dropped record no longer discards the
  file.
- #3: `app.py:1064-1067` logs "Some diagnostics records were dropped (…)" alongside the
  success line.
- #4: `app.py:1068-1073` now says "…the previous diagnostics file is unchanged".
- #5: declined with a note, as above.

## 1. LOW — `typedSkip` is the one field in the decision record replay never compares
`src/obed_edom/diagnostics.py:200` unpacks it as `_typed_skip` and drops it. Every other part
of the decision — the attempt sequence, each attempt's reason, the accumulated carry, the
published outcome — is now compared, which makes this the last gap. It is reachable: a change
that moves a pair from `typed-empty` to `typed-below-coverage` (an upstream render change that
starts producing a thin typed layer) leaves the attempt list byte-identical, so replay reports
MATCH while the recorded decision genuinely differs.
Fix: rename the variable and add one clause to `selected_ok` (`:260-264`):
```py
and replay_typed_skip == rec.get("typedSkip")
```
with a test that flips `TYPED_COVERAGE` on a pair whose typed side is non-empty but thin.

## 2. LOW — `SCHEMA` is still 1 although the record shape changed four times
`src/obed_edom/diagnostics.py:16`. Harmless today — nothing has shipped, so no staff file
exists at an older shape — but the comparisons read missing fields as `None`
(`rec.get("carried")`, `rec.get("typedSkip")`), which is exactly the silent-pass that
`load_records`' hard schema check was added to prevent. The moment the first real file leaves
a church laptop, any further field addition must bump `SCHEMA`.
Fix: no code change now; one line in the plan's schema note saying the bump is owed on the
next field change after the first staff file exists.

## 3. LOW — the plan's Format section no longer matches what is written
`.agents/plans/checker_diagnostics.plan.md` — only the `todos` statuses were updated. The
record shape it documents is now stale in four ways: the pair-level `carried` field, the
`typedSkip` field, per-side `ocrUsed` inside `left`/`right`, and the reason constants, which
are now split between `attempts[].reason` (three) and `typedSkip` (two). SKILL.md ends its
diagnostics section with "See `.agents/plans/checker_diagnostics.plan.md` for the format", so
this is the document a future reader is pointed at.
Fix: update the Format block in the plan to the shipped shape.

## Checked, no regression
- `select_text_sources` now returns a 2-tuple `(attempts, typed_skip)`; both production
  unpack sites (`diff_keynotes.py:1435`, `diagnostics.py:200`) and all nine test call sites
  take two values. No other caller exists in `src`, `tests`, or `dashboard/src`, and the
  selection logic itself is still byte-identical to the pre-refactor block.
- `_selected_attempt` and replay's `replay_attempts[-1]` fallback agree on which attempt is
  "selected" in the no-finding case.
- `replay`'s function-local import of `strip_carried_point_title` means the carry test's
  `monkeypatch.setattr(diff_keynotes, …)` is actually honoured — the test would not pass
  vacuously.
- Writer atomicity, symlink refusal on write, the commit/close/`__exit__` matrix, endpoint
  trust, and the flag inventory are all unchanged from r4, where I exercised each by hand.
