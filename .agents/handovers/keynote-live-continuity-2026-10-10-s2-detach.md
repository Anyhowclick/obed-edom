# Handover: S2 detach experiment, gate speed-up follow-ons, resizer (2026-10-10, ~01:00)

Read this first; then the S2 handover `keynote-live-continuity-2026-09-25-s2.md` ("Rebase r2" section, on
`claude/continuity-generalisation-s2`) and the detach plan `.agents/plans/keynote_live_continuity_detach_r8.plan.md`
(§5 = tonight's results).
Verify every branch/PR on GitHub before acting; nothing below was merged except #247.

## Branches (all local unless marked)
| Branch | Head | Where | State |
|---|---|---|---|
| `main` | `1379b2df` | origin | #247 (gate round 35 -> ~7¼ min at GATE_JOBS=3), then #248/#249 (resizer splice aspect, Gold oracles). S2 is still on `0f0a70aa`. |
| `claude/continuity-generalisation-s2` | `dcbb6363` | **origin** | S2 rebased onto `0f0a70aa` (#247) + owner-approved P2 re-registrations + plan §4 option (a) + detach plan (force-pushed; = the former `-s2-rebase`). No PR. |
| `claude/s2-detach-fix` | this commit | **origin**, worktree `obs-mac-camera-swap-fbc63b` | S2 + detach driver (`scripts/detach_experiment.py`, Level 1+2, a1/a2 core-fix arms, removal-phase readout) + plan results + this handover. |
| `claude/detach-main-p2` | `97332ef6` | **origin** only (worktree trashed) | Driver ported to main for the P2 relevance check. Evidence only; kept because plan §5 cites it. |

Deleted: `claude/continuity-generalisation-s2-rebase`, `claude/s2-detach-experiment`, `attach-viewport-session`.

## Results tonight
- **Detach experiment (owner asked for the full plan):** controls valid; A/B early-stop V8 6/19 vs V7 0/18, V5 0/18
  (p 0.012); 1920 V8 3/10. Level 2 trace: every blink is **H3 -> H1** (re-home into the outgoing poster layer, player
  removes that layer ~1 ms later, `stash` returns on `__obedRemounting`). Fix A/B: V8 8/23, **a1 0/23 (p 0.0019)**,
  a2 4/23 (sham, as predicted). **a1 closes the gap** (rescore by removal phase, plan §5): the teardown removal is
  re-homed in the core's own delivery (sameDelivery 23/23); the 0.5–1.3 ms left is the carry-time removal of the held
  decoder, swapped back by the facade observer in the same microtask checkpoint (23/23, 0 pre-paint rows) — no task
  boundary, no residual rate.
  Main P2 (GL auto): 1→2 hand-back eligible 10/10, 0 blinks — race not reached on main; no escalation.
- **Full suites (tonight, machine quiet):** S2 rebase 9105 passed; with the banked cache 9108 + 1 failure
  `test_two_tier_splice_makes_write_affecting_gate_green_full_deck` = the resizer bug (fixed by #248, merged) — expected, not an S2 regression. Resizer+Gold 8972 / 8988 passed. `test:ui` 305 on both.

## Owner decisions (2026-10-10, resolved)
1. **Detach fix = a1** as measured; `CONTINUITY_VERSION` stays 6.
2. **Resizer fallback:** keep the aspect-nulled old cache when a pre-fix offline cache cannot be re-read.
3. **S2 force-pushed** to `dcbb6363`.

## Next steps, in order
1. Detach fix: a fresh ≥ 30-event interleaved V8 vs V8+a1 session with the new instrument (positive control first),
   then land a1 in the core (core sha re-pin; red-arm variant shas re-derive) on S2.
2. The owed S2 gates on the rebased head: full `run_gates.sh` (now 38 runs incl. 22 deck red arms — GATE_JOBS=3 was
   qualified only for the 16-run mix; deck arms have never run concurrently, re-qualify serial vs 3-wide), decks at
   1600×1000 and 2560×1440, Pass G on D1–D6, then review and the Q2–Q7 re-qualification (plan §3.4).
3. Housekeeping: trash the agent worktrees once their branches are pushed/merged (check git-ignored `output/` first).

## Open bugs (owner-raised or found)
- **One-frame detach (S2):** symptom — one rAF with no `<video>` at the destination's movie start after an MM (D-deck
  pin carries, arm C/attach, 2560 and 1920). Expected — the carried decoder stays painted. Cause — H3→H1 above. Fix — a1
  (decided; not yet in the core).
  Evidence: main checkout `output/evidence/s2-dev/detach-{controls,s1,ab,1920,l2,l2-smoke,fix-ctl,fix}/`.
- **Flaky test:** `tests/test_watercolour.py::test_cancel_after_png_encoding_still_discards_the_item` failed once under
  `-n auto` load (cancelled vs done); untouched code, passes alone 5/5.
- **`managed_obs.py` `free_port()`** pre-picks OBS ports by bind-and-close (same race #247 removed for Chrome).
- **Instrument note:** `elementsFromPoint`-based "top at pin" never sees the decoder (`pointer-events:none`); use `videoAt`.

## Machine / facts
- Keynote 15.4 JXA payloads banked for Full_Report_Card_Wall + Gold_Wall_Input in the MAIN checkout `.cache`
  (worktrees: `OBED_EDOM_CACHE_DIR=/Users/anyhowclick/Desktop/work/obed-edom/.cache`). Map_Extracted_Wall_1st.key retired.
- Never start a gate round within minutes of a suite run (load guard refuses above 1-min load 4). >3 Chromes not qualified.
- Keynote is still open (idle) from the re-banks; the owner said it was free.
