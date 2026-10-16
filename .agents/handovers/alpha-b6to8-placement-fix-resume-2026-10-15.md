# Resume here: Alpha placement fix (paused for the night, 2026-10-15)

Owner: "find an appropriate state to prep handover and pause for the night".

**State.** Branch `claude/friendly-stonebraker-16d950`, worktree `.claude/worktrees/session-cleanup-review-6b8808`, clean
after this commit.
- Fix commit `48d8182e`: core sha `838eeedf…`, pins updated, new unit row.
- Gate record: `.agents/reviews/stage-b/alpha-placement/gate-record-2026-10-15.md`.
- Reviews: Opus r1 READY and r2 READY.
- Headless A/B, red controls, P2 GL-replay, and D2/D5 are all done and green as specified.
- No PR, by agreement: the Stage B Restructure session (`local_c489bec1…`) merges this branch into `claude/stage-b-arch`
  after its C6 lands. It handles the `scripts/detach_experiment.py` overlap with its uncommitted C6 hunks; ours touches
  only line 76.

**Next, in order:** (steps 1–3 done 2026-10-16; the tallies are in the gate record)
1. Ask the linked sessions for a "need window".
2. Run the full suites: `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` on 3.12, then on the
   3.10 floor venv (see `.agents/skills/obed-edom/SKILL.md`). Send "done" afterwards.
   - Expect the pins to hold (`838eeedf` everywhere).
   - The known #278 load flake may show; re-run before attributing a failure.
3. Add the suite tallies to the gate record and commit. Report to the Restructure session: commits, A/B tables, review
   rounds (r1/r2 READY).
4. Optional: the r2 low on the doc line's double parenthetical (moves the sha again; only together with another re-pin).

5. **DONE 2026-10-16 (findings in the gate record): noRider headless A/B** (owner go, relayed by the Restructure session 2026-10-15: "do the dedicated
   headless A/B before Q7 attempt 4"). Diagnosis only: no product edits without a further owner go. Not started, because
   the owner paused this session for the night.
   - **Question:** why `noRiderAboveCanvas` reads False on Alpha b5to6, Alpha b7to8-wa0121 and D7 b0to1 a/b, with
     body#body rides during the scene-9/13 transitions. Is it a departure-fix regression, an instrument artefact
     (pre-move capture), or an interaction with the placement fix?
   - **Arms:** cores `4c917be4` (03a35b28), `302c218d` and `838eeedf`, each with pre-move capture on and off; D7 and Alpha,
     feed on (feed off only if the cores separate).
   - **Method:** time the #body ride against the GL draws and labels with the DOM recorder, and give the root cause with
     core path:line.
   - **Deliverable:** results to `output/evidence/stage-b-2026-10-13/norider-ab/`, plus a findings section appended to
     the gate record or a short handover.
   - **Lead:** the `departure-early-hide` control read noRider True on D7 b0to1, while the departure-fixed cores read
     False. Suspect `deferDepartureHide` / `departureInterimPlace` / `finishDepartureHides`
     (`live_continuity_js.py:846-875`, `:1336-1376`, `:1383-1420`).

**Do not touch** spec step 5 in the placement fix itself: the body#body rides during the scene-9/13 transitions and `noRiderAboveCanvas` False on
b5to6/b7to8-wa0121. That is an owner decision the Restructure session is asking about.

**Scratch** (session scratchpad, not kept): `ab2/run.sh` (arm runner; `CORE_FILE` arm A), `run_dbg.py` + `dbg.js`. Copies
are in `output/evidence/stage-b-2026-10-13/alpha-placement/fix-ab/repro/`. Arm A core text = `git show
16f6c9fa:src/obed_edom/live_continuity_js.py` → `PRESERVE_CORE_JS`.
