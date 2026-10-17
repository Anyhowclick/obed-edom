# C5, stream G: Sol high implementation brief (draft, 2026-10-17)

NON-INTERACTIVE. Do not propose a plan or ask for approval. Implement, test, write ONE final report, stop.

**Base: `claude/stage-b-arch` @ `9f7df247` or later** (the MM-FEED fix merged 2026-10-17). Runs in parallel with the C4 stream-F brief. The coordinator fills in `<BASE>`, `<WORKTREE>` and `<SCRATCH>`.

## Authority
- Plan: `.agents/plans/keynote_live_continuity_stage_b_instrument_restructure.plan.md` §7 (C5) and §9. The plan's line numbers refer to an older baseline. Re-anchor by symbol and function name.
- Skills: `.agents/skills/obed-edom/SKILL.md`, `.agents/skills/codebase-design`. No unrelated CLI extraction, no framework.

## Scope (exclusive files for this phase)
- **New:** `scripts/gate_checks.py`, `tests/test_gate_checks.py`.
- `scripts/run_gates.sh`, `tests/test_run_gates.py`.
- **Probe: only the table move.** In `scripts/live_continuity_probe.py`, delete the moved tables and replace them with imports from `gate_checks.py`. In `tests/test_live_continuity_probe.py`, migrate the assertions that pin those tables. Nothing else in either file: stream P integrates C4 after you.

**Do NOT touch:**
- `mm_feed_instrument.py`, `live_evidence_contract.py`, or their tests (stream F, running in parallel);
- `live_run_validity.py` (import it, don't edit it);
- the OBS qualifier;
- `.agents/`.

## Deliverables
1. **`gate_checks.py` owns all plan pins and expectation tables.** That covers:
   - the P2, deck, Alpha, D7 and D7s plan SHAs;
   - the red and strip sets;
   - `MM_FEED_GATE_EXPECTATIONS`;
   - `MM_FEED_READ_EXPECTATIONS` (including the D7/D7s values re-registered by the MM-FEED fix);
   - `MM_FEED_STRIP_EXPECTATIONS`;
   - the paint floors;
   - the feed/REPORT rows;
   - `D7_COUNTER_MDAT_SHA256`, the strip2 media-identity pin. `run_gates.sh` staging AST-reads it next to the D7/D7s plan pins.

   Move the values **byte-for-byte**, with no edits; the plan-sha tests' pinned literals stay independent. The probe imports these from `gate_checks`. `gate_checks` imports `live_run_validity` but never the probe. Where `run_gates.sh` currently AST-reads the probe for pins, it AST-reads `gate_checks.py` instead.
2. **`judge(record, gate_kind, arm, host_kind, *, rc) -> GateResult`.**
   - It returns `MATCH | RECORDED | MISMATCH | INVALID | REPORT`, ordered printed lines, and the existing exit/status mappings.
   - Derive the deck from `groundTruth.planSha256`, never from a filename or label.
   - The registry key is `(plan SHA | registered deck class, arm, host kind)`. Keep GL mode in the arm identity, so the `(plan, arm, gl)` red sets cannot collide.
   - Join on exact spec IDs. A duplicate, missing or extra ID fails; a malformed or missing inventory can't MATCH.
   - Precedence everywhere: a known validity failure, then execution/integrity errors or unproven validity, and only then expected-pass/red matching. An INVALID expected red is never MATCH, and RECORDED stays discovery-only.
3. **Port the seven judgement heredocs into `judge`, in this order:**
   - `check_mm_feed`
   - `expect`
   - `check_host_red`
   - `check_passg`
   - `check_passg_red`
   - `check_paint_control`
   - `check_cc`

   The shell keeps:
   - queueing, the nonce, process groups, `.rc` files, load handling and staging;
   - main-venv vs gate-worktree-src behaviour;
   - these five bodies in place: `summ`, the H.264 prewarm, D7/D7s staging, Alpha repair, `paint_report`.
4. **The host feed table from plan §7, encoded as the plan's "Proposed owner decision" column:**
   - feed-off `noRiderAboveCanvas` and `artworkAbove` required True on both hosts once evidence closes;
   - feed-on `holdFrame` an explicit evidenced N/A;
   - `entryColdStart` REPORT.

   Leave `departureExposure` rows **unregistered**. Stream P registers them after C4.

   **Flag in the report** any row where encoding the proposal changes today's verdict. The coordinator takes those to the owner; don't decide them.
5. **Alpha control scope and re-registration** (MM-FEED round `adfeb552`, `mmfeed-fix-gate-record.md`; evidence `output/evidence/stage-b-2026-10-13/mmfeed-fix/round-adfeb552/`).
   - **Scope controls to their target.** `--feed-tamper ordinal|after-feed --feed-tamper-scene 10` tampers only the carry at atScene 10 (Alpha b5to6). Apply the control expectation to that carry only; every other carry must meet the plain feed-on expectation.
   - **Exempt not-applicable rows.** `mm-opacity-off` expects `labelsOverFeed` False only where a label over the feed applies. A row whose verdict is `notApplicable` (Alpha b5to6, expected 0 labels) is exempt, and is never silently counted as a pass.
   - **Name the target explicitly.** In `judge`, both rules key on exact spec IDs and atScene from the plan, never on substrings. If the target carry is missing, the result is MISMATCH.
   - **Re-register the Alpha first-crossfade read expectation** from the stored `adfeb552` from-only record. Use the same procedure the owner approved for D7: fresh per-progress values, with the old value, the new value and a justification for each. At 0.75 the GL patch matches the unfed to-unit's poster (dVideo 149.6 against dPoster 4.7), so the read is red. Re-check 0.5 the same way. Don't fit values to a desired outcome.
   - **One more mismatch to report, not fix.** The ordinal arm's targeted carry also scores `holdFrame` None (reads missing under standDown). That is stream F's instrument item. Report it as a remaining mismatch.
6. **`tests/test_run_gates.py` gates fixture:**
   - symlink `gate_checks.py` and `live_run_validity.py` into the fake gate worktree;
   - move the D7 pins out of `PROBE_STUB`;
   - keep the sha-mismatch case's independent literal.

## Tests (minimal: max coverage, fewest new tests)
- Move the existing heredoc stub cases into `test_gate_checks.py` judge tests, and keep the orchestration assertions in `test_run_gates.py`.
- Replace the probe shell-text and adversarial-regex policy tests only once outcome coverage exists for them.
- Reds:
  - an invalid expected red;
  - absent hold/retirement/departure evidence;
  - a wrong paint floor;
  - a duplicate ID, and an ID that collides by substring;
  - a non-matching rc.
- Null: complete, valid inventories that match the frozen rows.
- Every new red must be shown failing against a mutant.

## Acceptance
- **Printed lines and exit codes are byte-stable** against the pre-change shell for every existing stub case. Any intended semantic change is listed explicitly, with an updated snapshot.
- The discovery/full/dev distinctions are preserved, including dev success **10**.
- Nothing uses recursive walks or substring matching for IDs.

## Commands
- `.venv/bin/python -m pytest tests/test_gate_checks.py tests/test_run_gates.py tests/test_live_continuity_probe.py -q -p no:randomly -n 2`
- If the sandbox blocks pytest, say so: the coordinator runs the tests outside the sandbox.
- No full suites, gates or live runs, and nothing under main `output/`. Scratch goes in `<SCRATCH>`.

## Report (`<SCRATCH>/c5-g-report.md`)
Cover:
- files changed;
- each table moved (old location → new location, values unchanged);
- the judge API;
- the heredoc → judge mapping;
- the byte-stability evidence per stub case;
- the semantic changes;
- the tests with their mutants;
- the tallies;
- the owner-flag rows;
- what P must do next: register `departureExposure` and resume, and the remaining probe wrappers.

Commit on the given branch, with a message ending in the attribution line the coordinator supplies. Don't push.
