# CEF/OBS placement calibration — handover (2026-10-13, end of day)

Branch `claude/cef-obs-placement` (local, **not pushed**, no PR), head `ae1c0f63`; worktree `.claude/worktrees/angry-mestorf-abe88f`.
Plan: `.agents/plans/keynote_live_cef_placement.plan.md` rev 3.3 (§8 owner decisions O1–O5, §11 frozen contracts, §12 status).
Raw review rounds, briefs and implementer reports: `.agents/reviews/cef-placement-2026-10-13/` (keep until merge).
Evidence: `output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-13/` (main checkout): results
(run JSON, records, logs) for live1–live3, plus 2A's full raw output in `live3/raw-out/` (1.8 GB; keep until review closes,
then strip to results). The scratchpad copies are session-local.

## Done

- Feasibility (off-program sources do not render; hidden Studio Mode preview chosen), step 0
  (`cef-placement-step0-2026-10-13/README.md`), plan + 3 Opus critique rounds, frozen contracts.
- W1–W6 implemented (Codex GPT-5.6 Sol high), Opus 5.5 high code review r1–r3 folded (all severities), r4 + r4b on the
  post-review live fixes: 0 major/blocker. Docs (README, skill, follow-ups handover) updated in `975138aa`.
- Tests on `3eae0fde`/`ae1c0f63`: all touched files 1224 passed, 1 skipped; `test_managed_obs.py` 157 passed on `ae1c0f63`.
  Full suites on `4c5771b6` (before the live fixes): 3.12 and 3.10 floor 10892 passed, 36 skipped, 1 xfailed; dashboard
  tsc clean, test:ui 329/329. **Full suites have NOT been re-run since `aac7a026`, `3eae0fde`, `ae1c0f63`.**
- Live qualification (`managed_obs_qualify.py --arm placement --takes 1`, decision `q0b-2026-10-11/runs/decision_record_q0b1.json`):

| Run | Code | 25 fps | 30 fps |
|---|---|---|---|
| live1 21:16 | `60122973` | FAIL: 36 valid/frac; 5 controls failed (harness bugs + 2 product bugs) | interrupted at launch (owner priority for Line-Draw) |
| live2 22:16 | `3eae0fde` | FAIL: 37 valid/frac; only off-canvas controls failed (product bug) | same |
| live3 (2A) 23:17 | `ae1c0f63` | FAIL: 38 valid/frac; every control PASS; run checks OK | **INVALID (Mac slept)** — 38 valid/frac, no failing run check; ended 07:59 |

Product bugs found live and fixed: off-canvas activation race (`3eae0fde`), unstable Program baseline read as disturbance
after Show (`3eae0fde`), off-canvas built while Studio Mode duplicated the program scene (`ae1c0f63`), rejection cause not
logged (`3eae0fde`). Harness bugs fixed in `aac7a026` (W6 diagnosis: `.agents/reviews/cef-placement-2026-10-13/impl/W6-live1.md-report.md`).

## Open items (resume in this order)

1. **Analyse pass 2A** (owner: next day). Symptom: `CEF-placement` FAIL at 25 fps although all controls pass and 38
   sessions are `valid/frac/granted`. Remaining failing checks: `CEF placement tone observation` ("null timing while paused"),
   DX scorer arms INCONCLUSIVE (`cut-on`, `cut-off`, every `m-snap-cef*`, `m-tone-cef`, `m-tone-raw-cef`, `wrongrule-cef`,
   `perfect-shift`, `m-snap-cef-dsk`) and the `cut`/`frozen_frame`/`frozen_region`/`tone`/`holder_pixels`/`reference`/`mask`/
   `geometry` aggregates. Expected: classify each as inherited (parent handover: reference capture "null timing while paused"
   for all `m-snap*`/`m-tone`, cut — INCONCLUSIVE since the dissolve merge) vs new; for inherited, decide with the owner
   whether `CEF-placement` should score them as REPORTED for this PR or the parent follow-up must fix the producer first.
   Evidence: `live3/out/runs/placement-20261013-231739.json` (+ the 30 fps JSON) and per-session `record.json` under
   `live3/out/shots/`. Note: `dissolve_probe.score_arm(...)` needs the full harness context; use
   `managed_obs_qualify.py --score <out>` and the per-arm `CEF-placement` check values. Suggested owner: W6 (offline).
2. **Pass 2B** (owner moved to the next day): one more `--takes 1` invocation into 2A's output dir (now
   `cef-placement-live-2026-10-13/live3/raw-out`) on the same code, then `--score` that dir. 2A's 30 fps take is INVALID (the
   Mac slept overnight despite `caffeinate`), so run 2B while someone is at the Mac, or check `pmset` sleep settings first;
   a third pass may be needed for two valid 30 fps launches — the classifier/isolation gates need two fresh launches per backend. Send "need window"
   first (~45 min, OBS throughout); peers: Line-Draw, S2 follow-ups (Stage B), deck-staleness; skip field-test prep.
3. **Full suites** (3.12 + 3.10 floor + dashboard) on the final head, then the owner check (Keyer output with a real
   DeckLink: Recalibrate, freeze on a movie slide; the configured-device `decklink_preview_output` response is untested — the
   precheck only knows the no-device 600 response), then the PR.
4. Below-bar review notes kept for the record (r4): unstable-baseline `ok=None` is returned before visibility events are
   checked (cheap fix: check visibility first); a Program video frozen from `arm` to `finish` reads inconclusive; settle-loop
   timeout counts as isolation failure (fails closed).
5. Parent items unchanged: r13 #3 (Chrome stale grant) open with the O4 CEF residual; W5 tone map; scaled stages; Q6 bridge.

## Gotchas learned today

- OBS hides a browser source unless it is showing; an off-program source returns an empty or **stale** frame. Studio Mode
  preview shows it without touching program; off-canvas works only with Studio Mode off (scene duplication puts the program
  on a copy).
- `GetSourceScreenshot` trails the page by ~200 ms; paint challenges ≥ 300 ms before capture.
- CEF switches the Program cadence (50 → 30 Hz) shortly after Show with visible media.
- A one-take run is ~23 min per rate; to yield between rates, split invocations (`--takes 1` per pass) — SIGINT the
  **python** pid (not the zsh wrapper); its finally quits OBS cleanly. SIGSTOP/SIGCONT on codex process trees pauses
  implementers for a peer's window.
