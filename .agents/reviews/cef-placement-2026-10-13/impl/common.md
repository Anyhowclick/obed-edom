NON-INTERACTIVE. Do not propose a plan or ask for approval: implement, test, then write ONE final report.

Repo worktree: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f, branch `claude/cef-obs-placement` at bd7f354c. Plan: `.agents/plans/keynote_live_cef_placement.plan.md`
rev 3.3 — read §0–§2, §4–§7 and ALL of §11 "Frozen contracts" (code exactly against them; if a contract is wrong or
unimplementable, implement the nearest faithful version and report the deviation with evidence — never silently redesign).
Parent: `.agents/plans/keynote_live_dissolve_crossfade.plan.md` rev 17. Step-0 evidence:
/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-step0-2026-10-13/README.md.
The coordinator already committed the §11.1/§11.2 type skeleton (`src/obed_edom/placement_probe.py`, the contract block in
`src/obed_edom/managed_obs.py`). Six implementers (W1–W6) work IN PARALLEL in this same worktree on disjoint files.

Rules:
- Edit ONLY your stream's files (listed below). Never touch another stream's files, `.agents/`, README or skill docs. Do not commit,
  stash, reset, checkout or rebase — the coordinator commits. Other streams' files may change under you; import their §11
  names, and where their bodies are still `NotImplementedError`, test your code with fakes built on the §11 types.
- Style: match surrounding code; Python ≥3.10 compatible; MINIMAL docstrings, NO inline comments unless absolutely necessary
  (tests may be verbose). Do not reinvent existing helpers. Fix player behaviour only via sha-pinned in-memory replacements;
  never edit a Keynote `main.js` on disk.
- Tests: maximum coverage with the FEWEST new test functions — parametrize, extend existing tests/fixtures; the plan's test
  list (§6) is a coverage checklist, not a count. Run ONLY your targeted test files:
  `cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest <your test files> -q -n 2 -p no:cacheprovider`.
  NO full suite, no `-n auto`, no run_gates, no OBS, no Chrome/headless browser, no Keynote — the coordinator runs those.
  Known external reds NOT yours (a new main-checkout fixture from another branch): `test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_across_real_exports`,
  `test_dissolve_real_patched_methods_on_node[*-census]` ×2, `test_handback_census_mirror_affects_only_p2_1_to_2_slots_2_and_4_across_real_exports`;
  leave them alone and report them separately.
- Dashboard tests (W5 only): `cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/dashboard && PATH=$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run test:ui` (and `npx tsc --noEmit` if available).
- Long commands in the foreground, bounded; no sleep/poll loops.
- Final report → write it to /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/20ff56a9-0814-410f-9628-290bebf3e027/scratchpad/impl/<STREAM>-report.md (that dir is writable): files changed, what each contract item maps to,
  deviations from §11 with evidence, test commands + exact pass/fail counts, open items for the coordinator. Your final chat
  reply: one paragraph + the report path.
