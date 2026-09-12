# Codex review brief — Sermon Checker diagnostics log

You are the final-gate reviewer. Read-only. Review the UNCOMMITTED working tree of this
repo (`git status --short -- src tests dashboard/src .agents`, `git diff -- src tests
dashboard/src .agents`, plus untracked `src/obed_edom/diagnostics.py` and
`tests/test_diagnostics.py`). Ignore `dashboard/dist`.

Spec: `.agents/plans/checker_diagnostics.plan.md` steps 1–8 (step 9 deliberately not
built). Owner decisions: slide text may be logged; one `diagnostics.jsonl` per job,
overwritten on re-check; always on; dashboard "Export diagnostics" download named
`sermon-diagnostics-<date>-<jobId>.jsonl` plus "Show in Finder" via
`POST /api/jobs/{id}/diagnostics/reveal` (`open -R`). Prior reviews, all findings applied since: `opus-r1.md`, `opus-r2.md`, your own
`codex-r1.md` (4 findings: replay compares the selected attempt and the severity-mapped
outcome separately; endpoints require the canonical work-dir path; writer sanitises
non-finite floats and guards close(); outline flags recorded with the writer open), and
`opus-r3.md` (message-only mismatch path made reachable, `rule_severity(rules=)` reuse,
public `record_flag`, no mkdir in path validation). Your `codex-r2.md` (4 findings: writer path from the canonical job dir, symlink refused;
atomic temp-file publish; replay compares `carried`; per-attempt `reason`) has also been
applied, then re-reviewed by opus (`opus-r4.md`). Your `codex-r3.md` (replay compares the full attempt sequence with accumulated
`carried`; per-attempt `reason` = admitting gate; canonical-path check resolves the parent
and rejects a symlinked final component) has been applied and opus re-reviewed
(`opus-r5.md`). Your `codex-r4.md` (purge the canonical `.diff/<job.id>` dir on delete regardless of the
patchable `workDir`; a real two-attempt carry regression test) has been applied and opus
re-reviewed (`opus-r6.md`, `opus-r7.md` APPROVE; the r6 purge-symlink regression is fixed by routing the canonical dir through the existing containment guard). Your `codex-r5.md` (diagnostics path built without mkdir via a shared `_diagnostics_path` helper; writer open remains the only guarded creation point) is applied. This is round 6 for you: confirm every earlier finding is
fixed and hunt regressions from the fixes. Be concrete; do not re-raise findings already
fixed.

Focus, in order:
1. `select_text_sources` in `src/obed_edom/diff_keynotes.py` must be a byte-identical
   refactor of the old typed→clean/full two-attempt block (see `git diff`).
2. Replay (`diagnostics.replay`) must re-derive the whole decision from the raw recorded
   strings and header (`pointTitles`, thresholds) and honestly detect classifier or
   threshold changes.
3. The check pass must never fail or noticeably slow because of diagnostics; JSON
   serialisation edge cases; overwrite and purge semantics; endpoint path safety.
4. Tests test behaviour, not the implementation.
5. House style: minimal comments, small diff, matches surrounding code.

Run tests EXACTLY as: `PYTHONPATH=src /Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python -m pytest -q tests/test_diagnostics.py tests/test_diff_keynotes.py tests/test_dashboard_api.py`
(plain pytest imports another checkout via an editable-install .pth).

Output: VERDICT line first (APPROVE / APPROVE-WITH-NITS / REVISE), then numbered findings
with severity (HIGH/MED/LOW), file:line, problem, concrete fix.
