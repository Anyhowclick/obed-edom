# S3 (delete the allowlist) gate record, round 1 (2026-10-13)

Plan: `.agents/plans/keynote_live_continuity_generalisation.plan.md` §S3, OQ-8; Stage C §3.1 (R11). Branch
`claude/s3-allowlist-delete`. Code under gate: `264acdd4`. No JS byte changed: core sha `a9e1e66a…48be0` at start and end
of the gate round, as in S2.

## Implementation and review
| Step | Who | Result |
|---|---|---|
| WS-D (allowlist removal, `planSha256`, test flips, `managed_obs_qualify` pinned-P2 guard, `loop_fixture`) | Opus MEDIUM started it; the auto-mode classifier stopped it; owner confirmed the scope; Codex GPT-5.6 Sol high finished it | `cbb1aaff` |
| WS-N (negative corpus) | Opus MEDIUM | `tests/test_live_continuity_corpus.py`: 14 cases; a control that stubs `_overlap_refusal`/`_bridge_timing_refusal` reds 3 |
| WS-P (README, SKILL, runbook, plan status) | Opus MEDIUM | `cbb1aaff` |
| r1 | Opus 5.5 high on the Codex parts; Codex GPT-6 Astra high on the Opus parts (reviewer class ≠ implementer class) | Opus: APPROVE, 5 lows. Astra: 2 lows (one duplicates Opus's). All folded in `264acdd4` |
| r2 | Codex GPT-6 Astra high, fold + whole diff, all severities | No findings at any severity. APPROVE. Loop closed. |

## Gates
| Gate | Run | Result |
|---|---|---|
| Plan identity | Runtime plan + refusals of P2, p2-loop, D1, D2, D2-across, D3–D6, GL replay off and on (18), derived on `eb1fb6d2` vs this branch | Byte-identical, 18/18. Pinned sha values unedited. |
| Suites | `pytest tests/ -n auto --dist worksteal` on 3.12 and the 3.10 floor at `264acdd4`; `npm run test:ui` | 3.12: 10721 passed, 4 failed, 87 skipped, 1 xfailed. 3.10: same tallies. UI: 44 files, 321/321. The 4 failures are the census tests that sweep main-checkout `output/` (`test_mm_opacity_census…`, `test_dissolve_real_patched_methods_on_node[*-census]` ×2, `test_handback_census…`). Stage T's new fixture `output/fixtures/alpha-dsk-textures` causes them: with only that directory filtered out, 10/10 pass. Fixed on the Stage T branch. **Known; not S3.** |
| Probe (`run_gates.sh --tier full`, `GATE_JOBS=3`, pinned detached worktree at `264acdd4`) | P2 + D1–D6 host gates, red arms, Pass G, paint and carry-cover | `DONE failed=4 pending=0` (the 2560×1440 gate counts twice: exit and status). Host 1600×1000 and 1920×1080 pass; Pass G ×7 and its red arm, every P2 arm, the paint controls, the carry-cover controls and 28 of 30 host red arms match. The reds: HOST 2560×1440 `inconclusive` (arm A/C b0to1 paint 242 unpainted) and D1 `--strip bridge@4` / `--strip pin@6`, each with an extra b0to1 carry paint red (3–6 unpainted frames). Load at launch 3.79. |
| Probe A/B retake | The 3 reddened gates, serial, interleaved `eb1fb6d2` vs `264acdd4`, 2 rounds with the order reversed | 12/12 pass. Main and S3 verdicts and red sets identical every take (D1 red sets exactly as registered). The round's reds were load on the first boundary's paint read, not the code. Plans and core bytes are identical, as above. |
| Real deck, headless | Alpha_DSK export `7e3c9301…` (frozen copy), `derive_runtime` both GL flags, then `LiveOutputHost` continuity `auto` vs `off`: goTo every slide, then advance through every build | Derives `qualified`, `planSha256` `c2dd5107…`, runtime: bridge@6, restart@8, 4 × `retire refused`. Named refusals: 4 × `overlap` (6→8 wa0125, 8→9 wa0125, 9→10 wa0121 + wa0125). Plays: every visible `<video>` has `readyState` 4, no error and an advancing clock on every slide, the same in `auto` and `off`; slide 11's two clips play in turn. A 1 s settle after each advance read mid-transition (no videos); 3 s settle used. |

Scripts and logs are in the orchestrator session's scratchpad (`plan_identity.py`, `ab_retake.zsh`, `alpha_dryrun.py`,
`gates-r1/`, `ab-r1/`); not retained.

## Follow-ups
- Owner: B's oracle is now the plan-sha tests plus the corpus; B re-points the corpus `overlap` case only if it moves
  off P2's click-driven 1→2 (the test asserts `automaticPlay is False`).
- The runbook still says HEVC under OBS makes continuity `unsupported` (a Stage C staleness; prepare converts to H.264).
- Codex launches need an owner permission rule in auto mode (`codex exec`), else the classifier denies them.
