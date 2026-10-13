NON-INTERACTIVE. Do not propose a plan or ask for approval; produce the review directly.

Implementation review of the Obed-Edom dissolve cross-fade QUALIFICATION INSTRUMENT changes made after the rev 17 implementation APPROVE (`.agents/reviews/dissolve-crossfade/impl-rev17-astra-r1.md`). Round 3 (last round that reports mediums). Diff under review: `git diff 2b77681a 32f36c35 -- scripts tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py tests/test_detach_experiment.py tests/test_live_runtime.py` (14c2d873 in between is a merge of origin/main; its other test files are out of scope) (scripts/dissolve_probe.py, scripts/managed_obs_qualify.py, scripts/detach_experiment.py and their tests; no src/ change). Commit messages: `git log --oneline --no-merges 2b77681a..32f36c35`. Plan: `.agents/plans/keynote_live_dissolve_crossfade.plan.md` rev 17 (§9 DX-1 headless gate, §9.2 DX-2 managed OBS/CEF); state: `.agents/handovers/keynote-live-dissolve-crossfade-2026-10-12.md` (READ FIRST sections).

What changed (verify against the bytes, do not trust this list):
- 52c37581 serve P2's .mp4 as exported; fe3bbfad raw-page driver waits on the hash; 5e3d1d47 F3-critical DX-1 instrument (rVFC presentationTime reference, pending-rAF curve samples, capture to the hand-off, destination movies excluded only after it); 5259d120 / 958d0be0 rebase repairs (census, detach_experiment slice).
- 99b7271a DX-2 CEF harness: await key input; G2 state None allowed under gl_replay off; rAF-gap rule for ALL profiles (a gap > 50 ms allowed only before any animation starts and only if the first post-gap record shows every animation pending at initial values); straight (un-premultiplied) OBS source shots.
- 7e11eaa1 texture classes (out/in/overlap) drop the 1 px ring around any partial-alpha pixel of A or B (CEF 127 draws an inside AA corner at α 223 where the export texture has 255; that pixel failed cut-on and the pre-transition complement); CEF profile mid-frame minimum 5 (DX-1 keeps 6); cef-skip-dsk class minimum 1000 px (1168 measured).
- 2a5d7f2d paused reference: rVFC armed before the seek, 'presented' only when seeked AND the presented frame is the target.
- cbca19fa OBS shots un-premultiplied after the burst (identity-tracked), not inside the timed capture.
- 9c283f78 folds round 1 (`impl-instrument-astra-r1.md`, MEDIUM: pending rAF records bypassed curve validation): leaf check first, an all-pending record is skipped only when `pending()` confirms initial values and effective opacities, otherwise an integrity problem. Verify the fold closes the class, then review the whole diff again.
- 32f36c35 folds round 2 (`impl-instrument-astra-r2.md`, MEDIUM edge case: a pending record after timed samples was skipped): `if both or not pending(r)`. Verify it closes the class.

Live results at the pre-fold commits (feed; you cannot run them; DX-1/DX-2 will be re-run live after this review loop): DX-1 F3 round at 2a5d7f2d: all F3 gates PASS, 16/16 arms MATCH (on AC power; a battery/Low Power Mode run was retired for 4-5 mid frames). Null control: the new scorer re-scored the 958d0be0 runs all PASS/MATCH. DX-2 at cbca19fa: calibration n 0.58 (tau 4, complement 3, no_dip 251), model/complement/no_dip/curve/monotone/handoff/cut/scope/cvc PASS, 10/10 MATCH; known-bad controls off / noblend / cut-off still behave as controls. Full suites 3.12 + 3.10: 10829 passed / 36 skipped / 1 xfailed.

Owner review rules (binding):
- Scope: F3 (the movie freeze and its host grant) and the gates that qualify it. The question is ONLY: can any of these instrument changes make a DX-1 or DX-2 gate PASS (or a control MATCH) when the product is wrong — a false pass / weakened control — or break a gate's ability to detect what it was built to detect?
- Report blocker, major and MEDIUM findings, each with a concrete scenario (inputs/state -> wrong verdict) and the exact smallest fix. Do not report minor/style/nits. No scope creep (no new arms, no redesign).
- If there is no medium-or-above finding, say so.

Machine is shared with timed runs: do NOT run pytest or start browsers. Small python/node checks are fine.

Output: findings (severity, file:line, scenario, exact fix), classify each (new class / closed class / edge case); one-line verdict: APPROVE or CHANGES REQUIRED.
