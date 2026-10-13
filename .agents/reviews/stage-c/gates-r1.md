# Stage C gate record, round 1 (2026-10-13)

Plan: `.agents/plans/keynote_live_continuity_stage_c.plan.md` rev 2 (approved). Branch `claude/stage-c-orchestration`.

## Review (Codex GPT-6 Astra, effort high)
| Round | Scope | Result |
|---|---|---|
| r1 | `9d71ded2..27eb7b1b` | 1 MAJOR (new class): the overlap check read an unmeasured instance's unscaled bounds, so a bridge could overlay a scaled movie drawn above it. Folded in `3c4a189c` (R11-refuse the carry), with a case added to the existing parametrised test. |
| r2 | the fold, plus the whole diff | No blocker or major findings. Loop closed. |

## Gates
| G | Run | Result |
|---|---|---|
| G1 | `pytest tests/ -n auto --dist worksteal` on 3.12 and the 3.10 floor; `npm run test:ui`; `npm run test:maps` | 3.12 and 3.10: 10488 passed, 1 failed, 36 skipped, 1 xfailed. The one failure (`test_live_host.py`) asserted the old deck-wide mask refusal; it was rewritten in scoped form, and the file now passes 316/316 on 3.10. UI: 44 files, 321 tests passed. Maps: 542 passed, perf 2 passed. Oracle tests (allowlist, plan-sha, D decks, `PINNED_CORE_SHA256`) are unedited. |
| G2 | `convert_movies` on a scratch copy of Minimal Alpha_DSK (`59cb220d…`) | PASS. 10 HEVC/ProRes copies, 3 encodes (6, 2 and 2 copies, hardlinked, `st_nlink` 6/2/2), wall time 30.5 s. `unconverted` returns `[]` after the run. `derive_plan` `as_dict()` and refusals are equal before and after (2 `overlap`). |
| G3 | The same on Alpha_DSK (`7e3c9301…`, all H.264) | PASS: no-op, `converted: []`, plan equal (4 `overlap`). |
| G4 | Headless `LiveOutputHost` advancing through every build of the converted Minimal copy; then a live API qualify and start of Alpha_DSK with a real headless host | PASS. 13 steps, 0 failures. Every `<video>` has no error, `readyState` 4, and `currentTime` advancing, including the converted HEVC and ProRes clips. API: qualification `continuity.mode = unsupported` with the allowlist reason, `qualified: true`, start 200 `ready`, no 409, no codec warnings. Note: load was 31 at the start of G4a, from a peer's suite tail. |
| G5 | Owner prepares the new Alpha_DSK in the dashboard | Pending (owner). |

Scripts and logs are in the orchestrator session's scratchpad (`gates/g2g3.py`, `g4_smoke.py`, `g4_api.py`); not retained.
