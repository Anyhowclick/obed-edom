# C4 slice, stream F: Sol high implementation brief (draft, 2026-10-17)

NON-INTERACTIVE. Do not propose a plan or ask for approval. Implement, test, write ONE final report, stop.

**Base: `claude/stage-b-arch` @ `9f7df247` or later** (the MM-FEED fix merged 2026-10-17). The coordinator fills in `<BASE>`, `<WORKTREE>` and `<SCRATCH>` at launch.

## Authority
- Plan: `.agents/plans/keynote_live_continuity_stage_b_instrument_restructure.plan.md` §6 (C4 slice) and §9 (streams, co-landed contracts). The plan's line numbers refer to an older baseline. Re-anchor every reference by symbol.
- Owner decisions that still govern:
  - report-wide producer-error rejection (a malformed producer report nulls ALL feed entries; a malformed normalized record nulls only its own entry);
  - `entryColdStart` is REPORT-only;
  - repeated-visit aggregate verdicts stay INCONCLUSIVE this round;
  - only the fully evidenced one-frame resume drop becomes REPORT.
- Skills: `.agents/skills/obed-edom/SKILL.md`, `.agents/skills/codebase-design`. Ordinary typed records and pure functions. No adapter framework, no speculative generality.

## Scope: stream F only (exclusive files)
- `scripts/mm_feed_instrument.py` (INSTRUMENT_JS producer and Python scorers)
- `scripts/live_evidence_contract.py` (F authors every contract patch)
- `tests/test_mm_feed_instrument.py`, `tests/test_live_evidence_contract.py`, `tests/test_live_mm_feed_js.py`

**Do NOT touch:**
- `scripts/live_continuity_probe.py` or its tests (stream P; the integration of `underArtwork.departureExposure` and `underArtwork.resume` comes after you);
- `run_gates.sh`, `gate_checks.py` or `test_run_gates.py` (stream G, running in parallel with you);
- any pin or expectation table;
- `binary_counter_movie.py`, the OBS decoder;
- `.agents/`.

## Deliverables
1. **Producer report version 3.**
   - Bump `kind: mm-feed` to `version: 3`, in both the report and `window.__obedMmFeedProbe`.
   - Make normalization and the contract version-aware for 1, 2 and 3. Hand-back handling that is gated on version 2 today must also apply to version 3.
   - Keep the empty/unbound null-`atScene` context exemption **for version 2 only**. In version 3, unplanned contexts are counted diagnostically (a count field) and emit NO frame records.
   - Reject populated unattributed frames, and keep legacy replay of versions 1 and 2 byte-identical.
2. **Per-visit reset.**
   - Reset `artworkDone`, the DOM/hand-back buffers, ring ownership and attribution per visit, independently of how long the decoder observation lives.
   - Keep the existing `visit` attribution and the lightweight lifecycle tracking.
   - A context that becomes planned without complete required evidence stays unreadable.
3. **Departure evidence + `score_departure_exposure(record) -> dict`.** It covers attributed ride start through first GL draw:
   - no visible rider above the authored labels;
   - no source-poster exposure caused by hiding the decoder early.

   Record the endpoints, the decoder/visit/context identity, the ordering and the interval coverage. Missing evidence gives `None`; observed exposure gives `False`. Use the `_verdict` shape. Raw and normalized fields plus their contract go in the same change.
4. **`score_resume(record) -> dict`, split out of `score_poster_hold`.**
   - `score_poster_hold` keeps its required checks: pause, stationary clock, no seek/restart, and readable resume continuity.
   - `score_resume` reports `exactHeldPlusOne` / the drop size. An exactly-one-frame drop that is fully evidenced is REPORT (`True` with a `report` reason).
   - Missing resume evidence, inconsistent clocks, non-advance, or a drop of 2 or more frames is never REPORT.
5. **Counter-deck refusal (MM-FEED diagnosis side finding).** Don't score a counter deck with Alpha distances. If a record's `counterLayout` is set and a read falls back to `kind: alpha` because the decoder reference has no counter, `score_feed_live` returns `None` with a named reason. That fallback must never give `False`.
6. **Errors and overflow stay feed-local**, never in C2's run-validity. Keep the owner's error scope exactly as it is today.
7. **Alpha hold: neighbourhood match (owner 2026-10-17).** Evidence: `mmfeed-fix-gate-record.md`, round `adfeb552`, the feed-off-2s/-5s/-12s and attach-once arms.
   - On near-static real footage, the held frame can't be told apart from its ring neighbours: hold margins are 0–5 against `ALPHA_HOLD_MARGIN` = 6, and neighbours sit at about 0. So `score_hold_frame` returns None today.
   - **Do not lower the margin.**
   - For `kind: alpha` reads, measure the frames that are indistinguishable from the target, meaning their alpha distance to the target frame is below the margin. Each must be measured on the same reads, never assumed.
   - Pass when the read matches the target or a measured-indistinguishable frame. Record `exactness: "neighbourhood"`, the neighbourhood (frame offsets) and the margins.
   - Return False when the read matches the poster or any *distinguishable* frame. Return None when the neighbourhood itself is unreadable.
   - Counter reads stay exact (`COUNTER_HOLD_MARGIN`, no neighbourhood).
   - Reds: hold on the poster, hold on a distinguishable frame. Null: a near-static hold within the measured neighbourhood. Offline replay: the `adfeb552` feed-off records go from None to True.
8. **Resume off-by-one (diagnose first).** Alpha b5to6 under feed-off-2s and after-feed: media time advanced one source frame more than `presentedFrames`. The base is `lastUploadedFrame` 66 against `pauseFrame` 65, on a constant-30-fps source.
   - Using the stored `adfeb552` records, decide per frame: is this a real one-frame skip at resume, or an off-by-one between the upload record and media time?
   - If it's a real skip and fully evidenced, `score_resume` makes it the owner-approved one-frame REPORT.
   - If it's an instrument off-by-one, fix the producer or normalization.
   - Report the frame table either way. Never REPORT an unexplained drop.
9. **no-pause control signal path.** With `--core-variant no-pause` and the feed off, the core feed seam emits neither a claim nor a departure, so the mode is `unavailable` and `posterHold` is None instead of the registered False.
   - Make the producer attribute the departure (or stand-down) independently of the pause, so the control reaches `score_poster_hold`.
   - The scorer then returns False because there is no pause.
   - Check against the stored `adfeb552` no-pause record.

10. **Ordinal targeted carry.** Alpha b5to6 under `--feed-tamper ordinal` scores `holdFrame` None (standDown; the held target or its first/middle/last reads are missing). Find out why the reads are missing, and fix it if it's the producer. The registered expectation is `holdFrame` False.

The `adfeb552` evidence is in `output/evidence/stage-b-2026-10-13/mmfeed-fix/round-adfeb552/`.

## Tests (minimal: max coverage, fewest new tests)
- Extend F's existing fake page with:
  - a second visit;
  - an unplanned context;
  - departure ordering (early hide → `False`; repaired → `True`; missing → `None`);
  - resume cases: one-frame drop → REPORT; two-frame drop → `False`; missing → `None`.
- Extend the existing contract tests for version 3 and the version-2-only exemption.
- Add the counter-deck Alpha-fallback refusal as one case in the existing feed-live test.
- Every new red must be shown failing against a mutant. Say which mutant in the report.
- Test against the REAL patched player and producer where the existing harness does. Don't build a test only on fakes, and don't assert only `is not None`.

## Commands
- `.venv/bin/python -m pytest tests/test_mm_feed_instrument.py tests/test_live_evidence_contract.py tests/test_live_mm_feed_js.py -q -p no:randomly -n 2`
- If the sandbox blocks pytest or a browser, say so in the report: the coordinator runs the tests outside the sandbox. Don't stub around it.
- No full suites, no gates, no headless Chrome beyond the existing test harness, and nothing under main `output/`. Scratch goes in `<SCRATCH>`.

## Acceptance (the report must show each)
- Offline Alpha producer replay: **0 contract errors** (don't assert pass); absent version-3 evidence stays unknown. Use the stored attempt-3 Alpha feed file named in plan §1.
- Reds: early hide, overlay ride, ambiguous attribution, malformed report, larger resume drop.
- Nulls: repaired departure, approved readable resume.
- Legacy versions 1 and 2 replay unchanged.
- The diff touches only F's files.

## Report (`<SCRATCH>/c4-f-report.md`)
Cover:
- files changed;
- new symbols;
- the contract diff summary;
- the test list, each with its mutant;
- the test tallies you ran, or "blocked by sandbox";
- anything you couldn't do, with the reason;
- open questions for P's integration: the exact field names P must publish and combine.

Commit on the branch you were given, with a message ending in the attribution line the coordinator supplies. Don't push.
