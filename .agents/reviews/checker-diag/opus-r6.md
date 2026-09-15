# VERDICT: REVISE

Full suite: `1823 passed, 84 skipped` in 78s (`PYTHONPATH=src … -m pytest -q`).
`dashboard && npx tsc --noEmit`: clean.

codex-r4 #1 is fixed in substance — the canonical dir is now purged — but the fix introduces a
destructive symlink-follow that the rest of `_purge_artifacts` explicitly defends against, and
it is the only purge candidate with no containment check. That is finding 1 and it blocks.
codex-r4 #2 and my r5 nits are fixed.

## 1. HIGH — purging the canonical dir follows a symlink and escapes `output_root`
`src/obed_edom/web/jobs.py:323-327`:
```py
canonical = (root / ".diff" / job.id).resolve()
if canonical.is_dir():
    shutil.rmtree(canonical, ignore_errors=True)
```
`.resolve()` follows a symlink at `.diff/<job.id>`, and unlike every other candidate this path
never goes through the `resolved.relative_to(root)` guard eleven lines above. Deleting a diff
job therefore deletes whatever that symlink points at, anywhere on disk.

Reproduced, with the existing guard as a control in the same run:
```
output/.diff/j9 -> <base>/Documents         (kind="diff",  canonical purge)
  victim dir still exists:   False
  victim file still exists:  False
result["workDir"] = <base>/Pictures         (the patchable path, existing loop)
  workDir escape refused (control):  True
```
So the code deliberately refuses this exact escape through the client-controlled field and
then performs it through the server-derived one. It is also the read-side hole codex-r3 #3
closed in `_trusted_diagnostics_path` (`app.py:669-675`, reject a symlinked component, resolve
only the parent), reopened on the destructive side.

Fix — reuse the guards already in the function rather than adding a second policy. Before the
loop:
```py
if job.kind == "diff":
    canonical = root / ".diff" / job.id
    if not canonical.is_symlink():
        candidates.append(canonical)
```
and delete the trailing block. The loop then applies `relative_to(root)`, the cache-root and
geocode-root exclusions, and the `seen` dedup to it, and `resolved.is_dir()` / `rmtree` do the
work. Add a test that a symlinked `.diff/<job.id>` pointing outside `output_root` survives the
delete.

## 2. LOW — the purge test covers only the happy path
`tests/test_sessions.py:161-179` asserts the canonical dir is purged despite a patched
`workDir`, which is the right regression for codex-r4 #1. It does not cover the two cases that
decide whether the new block is safe. I checked both by hand: a non-diff job with a same-named
`.diff/<id>` dir is correctly left alone (`job.kind == "diff"` gate works), `delete(purge=False)`
correctly keeps it, and no directory is created when none exists (no `mkdir`, as asked) — but
the symlink case fails, per finding 1.
Fix: add (a) the symlink-escape test from finding 1, and (b) a one-line assertion that a
`kind != "diff"` job's `.diff/<id>` dir is untouched, so the gate cannot be widened by accident.

## 3. LOW — the rebuilt carry test still mutates the record, not the code
`tests/test_diagnostics.py:361-440`. The rebuild is a real improvement and answers most of
codex-r4 #2: the two attempts now come from an actual `select_text_sources` call, the strip and
the classification from the real functions, and the asserted structure is genuine (typed
attempt strips "Your Faith" and finds nothing; the `clean` attempt carries nothing and fires),
with `replay == 0` first proving the record is faithful. But the change it then makes is
`attempt_records[0]["carried"] = "Someone Else's Point"` — it proves the comparison covers the
non-selected attempt's `carried`, not that a *behaviour* change is caught, which is the
property the tool exists for.
The nuance is real: monkeypatching `strip_carried_point_title` would also change that attempt's
`inputLeft`, so the mismatch would no longer isolate `carried`. Two honest options — keep the
corruption but say in the docstring that this test covers comparison coverage and that
`test_replay_catches_a_point_title_carry_change` (`:196`) is the behaviour-change counterpart;
or patch `strip_carried_point_title` to strip a *different* title (same text out, different
`carried`) so only the accumulator moves.

## 4. LOW — the `SCHEMA` bump note from opus-r5 #2 was not added
`.agents/plans/checker_diagnostics.plan.md`. The Format and Replay sections were updated
correctly — `typedSkip`, the pair-level `carried` with its accumulator semantics, per-side
`ocrUsed`, and the three-plus-two split of the reason constants are all documented, and the
per-attempt `carried` line now says it is "this attempt's own dropped title, not the
accumulator above". Still missing is the note that `SCHEMA` stays 1 only while no staff file
exists: `replay` reads absent fields as `None` (`rec.get("carried")`, `rec.get("typedSkip")`),
so a field added after the first real file would replay as a silent MATCH.
Fix: one line in the plan's schema paragraph.

## Verified fixed
- **codex-r4 #1 (substance)** — diagnostics in `.diff/<job.id>` no longer survive a delete
  after a patched `workDir`; confirmed by running the delete against a canonical dir holding
  `diagnostics.jsonl`. No `mkdir` side effect, and `purge=False` still keeps everything.
- **opus-r5 #1** — `typedSkip` is compared: `diagnostics.py:200` names it
  `replay_typed_skip` and `:263` adds it to `selected_ok`. Every field of the decision record
  is now compared.
- **opus-r5 #3** — the plan's Format/Replay sections match what is written.
- No risk to other job kinds: `job.kind` is set at `submit()` and is not patchable
  (`patch_job` at `app.py:230-242` writes only `result`), job ids are
  `str(uuid.uuid4())[:8]`, and only `_run_diff_check` / `_run_diff` use `diff_work_dir`, so no
  non-diff job stores artefacts under `.diff/<id>`.
