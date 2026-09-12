# VERDICT: APPROVE-WITH-NITS

Full suite: `1809 passed, 84 skipped` in 76s (`PYTHONPATH=src … -m pytest -q`).
`dashboard && npx tsc --noEmit`: clean (unchanged since r2).

All four Codex findings are fixed, and each is now covered by a test that would fail if the
fix were reverted. I verified the four requested behaviours by running them. One MED remains:
the message-only path that the same round added to SKILL.md is unreachable on a real file.

## Verification

| codex-r1 | status | evidence |
| --- | --- | --- |
| 1 replay compared only the post-severity outcome | FIXED | `diagnostics.py:139-199` now compares the SELECTED attempt (`source`, `inputLeft`, `inputRight`, `ignoreLeftTokens`, raw finding) and derives the published outcome separately through `_published_outcome` + `header.ruleSeverities`. `_selected_attempt` (`:87-96`) correctly mirrors the recorder's break-on-first-finding, falling back to the last attempt tried. An `off` rule now replays MATCH — `tests/test_diagnostics.py:151-182` builds the record from a real `select_text_sources` + `classify_text_diff` pass with `ruleSeverities={rule: "off"}` and `outcome: null`, and asserts exit 0. The `TYPED_COVERAGE` test at `:84` still flips, so a source-selection change is still caught. |
| 2 client-patchable `diagnosticsPath` | FIXED | `_trusted_diagnostics_path` (`app.py:668-680`) resolves the claim and requires equality with `(diff_work_dir(job_id) / "diagnostics.jsonl").resolve()` plus `is_file()`; both endpoints go through it. `tests/test_dashboard_api.py:686-700` patches a job result to a readable file outside the work dir and asserts 404 on GET and on reveal. |
| 3 writer could still drop records or raise from `close()` | FIXED | `_sanitize` (`:19-28`) nulls non-finite floats recursively and the record survives — verified: a `score=nan` record and the following record both land, `score` reads `null`, `writer.error` stays `None`. Serialisation failure now `return`s without disabling the stream (`:49-51`); only a write failure sets `_failed`. `close()` (`:59-63`) captures its exception into `self.error`. |
| 4 outline flags written after close | FIXED | `_run_diff_check` moved `_apply_outline` inside the `try` (`app.py:1040`) with the `finally: diag.close()` still covering every path including an exception from `compare_inspects`. `_apply_outline` records correspondence flags with `pairIndex=None` (`:1115-1116`) and corroboration flags with `pair.get("index")` (`:1136-1137`). `tests/test_diagnostics.py:316-382` drives a real outline discrepancy and asserts `cue.uncued_slide` at `pairIndex: null` and `outline.dsk_deviates` at `pairIndex: 0`. |

Everything approved in r1/r2 is still intact: `select_text_sources` remains byte-identical,
the header is still first, the inventory `Counter` test still passes, per-side `ocrUsed` was
added (`diff_keynotes.py:1500`), and the r2 findings 1 and 2 are both resolved
(`app.py:1046-1053`, discard-on-error; `diagnostics.py:49-51`, NaN no longer kills the stream).

## 1. MED — `--strict` and `MISMATCH(message)` are unreachable on a real diagnostics file
`src/obed_edom/diagnostics.py:181`. `selected_ok` compares `replay_raw == recorded_raw`, and
that dict includes `message`. In a file written by `compare_inspects` the outcome message IS
the raw finding message (`diff_keynotes.py:1471-1473` passes `finding.message` straight into
`make_flag`), so any presentational change moves both together: `selected_ok` goes False and
the run reports a hard MISMATCH before the message branch at `:196` can ever be reached.
Verified — with the plan's own `_phrase` bracket change monkeypatched in, a real file replays:
```
pair 1  text.word  MISMATCH  recorded=text.word  replayed=text.word
1 findings replayed, 1 mismatches, 0 message-only
```
A classification change and a rewording are indistinguishable, and the diagnostic line is
actively confusing (recorded and replayed rules are printed identical). The plan wanted the
opposite ("a good check that the tool distinguishes message changes from classification
changes"), and SKILL.md now documents `--strict` as the flag for exactly this case.
Fix: compare identity, not presentation, in `selected_ok`:
```py
def _raw_key(f: dict | None) -> tuple | None:
    return None if f is None else (f.get("rule"), f.get("default"))
...
and _raw_key(replay_raw) == _raw_key(recorded_raw)
```
The `(rule, severity)` equality check at `:192-193` still catches a real classification change;
the message difference then falls through to `MISMATCH(message)` and `--strict` starts meaning
something.

## 2. LOW — the message-only test cannot fail for the right reason
`tests/test_diagnostics.py:127-137` forges `outcome.message` to differ from
`attempts[].finding.message` — a state `compare_inspects` cannot produce. It exercises the
`:196` branch through an input no real file has, which is why finding 1 went unnoticed.
Fix: after fixing 1, build the record with `compare_inspects` (or the `_record` helper),
then `monkeypatch.setattr(text_diff, "_phrase", lambda *a, **k: "[" + orig(*a, **k) + "]")`
and assert `replay(path) == 0` with one message-only, `replay(path, strict=True) == 1`.

## 3. LOW — `_published_outcome` duplicates `validate.rule_severity`
`src/obed_edom/diagnostics.py:99-110` re-implements `validate.py:44-51` — the same
`off/none/false/silent` set, the same `info/warning/error/success` set, the same default
fallback. Two copies of a mapping that decides whether a finding is published will drift.
Fix: `def rule_severity(rule, default="warning", *, rules: dict | None = None)` in
`validate.py`, defaulting to `load_rules().get("rules")`, and have `_published_outcome` call
it with the header's pinned snapshot. One implementation, still pinned.

## 4. LOW — `app.py` imports a private name across modules
`src/obed_edom/web/app.py:29`: `from obed_edom.diff_keynotes import _record_flag`. The helper
now has a second module as a consumer, so the underscore is wrong.
Fix: rename to `record_flag` in `diff_keynotes.py` and update the three call sites there.

## 5. LOW — a path-validation helper creates a directory
`src/obed_edom/web/app.py:674` calls `diff_work_dir(job_id)`, which `mkdir(parents=True,
exist_ok=True)`s (`inspect.py:1073-1076`). Harmless in practice — the `if not raw: return
None` guard above means it only runs for a job that already has a work dir — but a function
whose whole job is to reject untrusted input should not have a filesystem side effect.
Fix: compute `output_root() / ".diff" / job_id / "diagnostics.jsonl"` directly in the helper.

## 6. LOW — `--rule` / `--pair` semantics changed silently
`src/obed_edom/diagnostics.py:141-145` now filters on the RAW recorded rule rather than the
published outcome — a necessary consequence of the `off`-rule fix, and the right call, since
`--rule text.unreadable` now matches the disabled findings you would want to inspect. But the
SKILL.md paragraph added this round still describes replay as re-running "`classify_text_diff`
over the recorded attempt inputs", which understates it (it re-derives the branch selection)
and says nothing about `off` rules or the filter change.
Fix: one sentence — replay re-derives `select_text_sources` + the carry strip + the classifier
from the recorded slide text, and `--rule` matches the classifier's rule even when the rule is
configured `off`.

## Checked, no regression
- `_sanitize` runs before `json.dumps` and covers float/dict/list/tuple recursively, so the
  restored default `allow_nan=True` cannot emit a bare `NaN`; anything exotic still goes
  through `default=str`.
- The `finally: diag.close()` in `_run_diff_check` covers an exception from `compare_inspects`
  and from `_apply_outline`; `pairs`/`flags` are only touched after the `try` completes, so no
  `UnboundLocalError` path exists.
- `_apply_outline`'s early `return []` (no outline file) leaves the writer untouched.
- Outline corroboration flags land in `pair["flags"]` only, and correspondence flags in the
  returned list only, so no flag is recorded twice.
- `_selected_attempt`'s fallback to `attempts[-1]` matches the recorder, which appends every
  attempt it tries and breaks on the first finding.
