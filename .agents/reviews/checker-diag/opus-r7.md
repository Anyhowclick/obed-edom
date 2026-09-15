# VERDICT: APPROVE

Full suite: `1825 passed, 84 skipped` in 77s (`PYTHONPATH=src … -m pytest -q`).
`dashboard && npx tsc --noEmit`: clean.

All four opus-r6 findings are fixed. I re-ran the r6 reproduction verbatim against the new
code and it is refused. No new findings; nothing outstanding from rounds 1–6.

## 1. r6 HIGH (symlink escape in the canonical purge) — FIXED, reproduction refused

`src/obed_edom/web/jobs.py:293-297` now appends the unresolved path as a candidate and lets
the existing guards do the work:
```py
if job.kind == "diff":
    canonical = self._output_root / ".diff" / job.id
    if not canonical.is_symlink():
        candidates.append(canonical)
```
The trailing `resolve()`-then-`rmtree` block is gone, so the canonical dir now passes through
`relative_to(root)`, the cache-root and geocode-root exclusions, and the `seen` dedup like
every other candidate. This is the minimal fix — one policy, not two.

Re-ran the r6 script against the new code, plus the variants:

| case | before (r6) | now |
| --- | --- | --- |
| `.diff/<id>` → `<base>/Documents` (outside `output_root`) | victim directory and file **deleted** | victim dir and file **survive** |
| `.diff/<id>` → `output/generated` (inside `output_root`) | would have been deleted | survives — `is_symlink()` rejects before any resolve, so the in-root variant is covered too |
| real `.diff/<id>` dir holding `diagnostics.jsonl`, `workDir` patched elsewhere | purged | still purged |
| `kind != "diff"` with a same-named `.diff/<id>` dir | untouched | untouched |
| `delete(purge=False)` | kept | kept |
| no canonical dir on disk | no mkdir | no mkdir |

Defence in depth holds even if the guard were bypassed: were `.diff` itself a symlink to
somewhere outside, the candidate's `resolve()` would land outside `root` and
`relative_to(root)` would skip it.

## 2. r6 #2 (purge tests) — FIXED
`tests/test_sessions.py` gains `test_delete_does_not_follow_canonical_diff_symlink` (asserts
both the victim dir and a file inside it survive, so a `rmtree` that emptied the target would
fail it) and `test_delete_leaves_non_diff_kind_canonical_dir_alone` (a `generate` job, so the
`kind == "diff"` gate cannot be widened by accident). Both go through `runner.submit` + `_wait`
rather than poking `_jobs`, matching the file's existing style.

## 3. r6 #3 (carry test mutated the record) — FIXED, and cleanly
`tests/test_diagnostics.py:432-444` now monkeypatches `strip_carried_point_title` with a
wrapper that delegates to the real function and rewrites only the returned title when it is
`"Your Faith"` — same stripped text, different `carried`. That isolates the accumulator
exactly as intended: the fallback attempt's inputs and classification are untouched, so the
MISMATCH can only come from the non-selected attempt's carry. `replay` imports the symbol
inside the function, so the patch is genuinely honoured (the test would fail vacuously
otherwise). Baseline `replay == 0` still runs first, proving the record is faithful before the
change.

## 4. r6 #4 (SCHEMA note) — FIXED
`.agents/plans/checker_diagnostics.plan.md:365-366` — the Risks section now records that
`SCHEMA` has stayed `1` and what that implies once a real staff file exists.

## Closing state

Across seven rounds every finding from opus-r1…r6 and codex-r1…r4 is resolved. Spot-checked
again in this pass and still correct:

- `select_text_sources` is byte-identical to the pre-refactor typed→clean/full block, now
  returning `(attempts, typed_skip)` with the admitting gate per attempt.
- `replay` mirrors the recorder's loop exactly — every attempt tried, accumulated `carried`,
  break on first finding — and compares the full attempt sequence, `typedSkip`, the
  accumulator, and the severity-mapped outcome, with message-only drift reported separately
  and gated behind `--strict`.
- The writer publishes atomically (temp + `os.replace`), never raises into the check pass,
  keeps records through a serialisation failure, and refuses a symlinked target.
- Download and reveal accept only the canonical server-owned path, rejecting a patched
  `diagnosticsPath` and a symlinked final component; delete now purges that same canonical
  directory without following a symlink out of `output_root`.
- The diagnostics file is a complete flag inventory (pair text outcomes, `_add_flag` findings,
  `diff.count`, `validate_inspect` deck flags, and both outline flag kinds), asserted by a
  `Counter` equality test against the returned flags.

Step 9 (opt-in image bundle) remains deliberately unbuilt, as the plan specifies.
