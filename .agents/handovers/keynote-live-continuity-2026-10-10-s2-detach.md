# Handover: S2 detach experiment, gate speed-up follow-ons, resizer (2026-10-10, ~01:00)

Read this first; then the S2 handover `keynote-live-continuity-2026-09-25-s2.md` ("Rebase r2" section on the rebase
branch) and the detach plan `.agents/plans/keynote_live_continuity_detach_r8.plan.md` (§5 = tonight's results).
Verify every branch/PR on GitHub before acting; nothing below was merged except #247.

## Branches (all local unless marked)
| Branch | Head | Where | State |
|---|---|---|---|
| `main` | `0f0a70aa` | origin | #247 merged: gate round 35 -> ~7¼ min at GATE_JOBS=3 |
| `claude/continuity-generalisation-s2` | `4e6df7b5` | **origin** | S2 as of 2026-10-09 (rebased on dda62e86 + continuity-test prune). No PR. |
| `claude/continuity-generalisation-s2-rebase` | `dcbb6363` | worktree `agent-aaa115e00ecabe6d7` | S2 rebased onto `0f0a70aa` (#247) + owner-approved P2 re-registrations + plan §4 option (a) + detach plan. No upstream on purpose. **Moving S2 to it = force-push: owner's go.** |
| `claude/s2-detach-experiment` | this commit | worktree `obs-mac-camera-swap-fbc63b` | Detach driver (`scripts/detach_experiment.py`, Level 1+2, a1/a2 core-fix arms), plan + results, this handover. Based on the OLD S2 head 4e6df7b5 — rebase onto the S2 rebase branch before reuse. |
| `claude/detach-main-p2` | `97332ef6` | worktree `agent-a5c9ad38200733a70` | Driver ported to main for the P2 relevance check. Evidence only. |
| `claude/splice-aspect-stale` | `004aef83` | worktree `agent-ad1565c2abe558572` | Resizer stale-aspect fix (owner: stale-only) + Codex r1 fold (cache marker `spliceAspectRefreshed`). |
| `claude/gold-oracle-tests` | `d4276cb2` | same worktree | Stacked: Map deck retired -> tests on `Gold_Wall_Input.key`; 14 always-skipping tests now run. |

## Results tonight
- **Detach experiment (owner asked for the full plan):** controls valid; A/B early-stop V8 6/19 vs V7 0/18, V5 0/18
  (p 0.012); 1920 V8 3/10. Level 2 trace: every blink is **H3 -> H1** (re-home into the outgoing poster layer, player
  removes that layer ~1 ms later, `stash` returns on `__obedRemounting`). Fix A/B: V8 8/23, **a1 0/23 (p 0.0019)**,
  a2 4/23 (sham, as predicted). **a1 shrinks the gap 7.8 ms -> 0.7 ms but does not close it** (~4% residual expected).
  Main P2 (GL auto): 1→2 hand-back eligible 10/10, 0 blinks — race not reached on main; no escalation.
- **Full suites (tonight, machine quiet):** S2 rebase 9105 passed; with the banked cache 9108 + 1 failure
  `test_two_tier_splice_makes_write_affecting_gate_green_full_deck` = the resizer bug (fixed on splice-aspect-stale,
  not yet on main) — expected, not an S2 regression. Resizer+Gold 8972 / 8988 passed. `test:ui` 305 on both.

## Open decisions for the owner
1. **Detach fix:** (rec) refine a1 into a same-delivery re-home (gap 0; verify gapMs = 0 / sameDelivery with the
   driver's `--core-fix` arm), then land in the core — vs land a1 as measured (0.7 ms residual gap).
2. **Resizer fallback:** when a pre-fix offline cache cannot be re-read because the offline read fails, it is served
   with every aspect nulled (no snapping), mirroring `stale_mixed`. Alternative: a full Keynote re-read. Agent's choice
   kept pending the owner.
3. **S2 force-push** to `dcbb6363` (or a later head).

## Next steps, in order
1. Fold Codex r2 on the resizer + Gold stack (`.agents/reviews/splice-aspect/codex-r2.md`, r1 alongside):
   **MAJOR** — a media count mismatch sends the slide through `_merge_legacy_slides`, which restores pre-splice
   image/movie aspects by an untrusted `kindIndex` and still stamps `spliceAspectRefreshed=True` (remap_keynote.py ~318,
   ~495) -> null those aspects (or restore only where correspondence is proven) + a count-mismatch regression. MINORs:
   fallback slides need an explicit `aspect=None` so fresh caches are not rejected (inspect.py ~825); Gold oracle helper
   must accept only `reader == "jxa"` (test_iwa_geometry.py ~599); vacuous fallback-geometry loop
   (test_offline_inspect.py ~1614); duplicated `boom_two_tier` stub. Codex confirmed the aspect-nulling fallback is
   conservative and the Gold assertions are not weaker than Map's. Then push both branches and open the resizer PR with
   the Gold PR stacked on it (owner merges).
2. Owner decision 1 -> implement the detach fix as a core variant, measure (≥ 30 events, interleaved, gap = 0), land it
   in the core (core sha re-pin; red-arm variant shas re-derive), on top of the S2 rebase.
3. The owed S2 gates on the rebased head: full `run_gates.sh` (now 38 runs incl. 22 deck red arms — GATE_JOBS=3 was
   qualified only for the 16-run mix; deck arms have never run concurrently, re-qualify serial vs 3-wide), decks at
   1600×1000 and 2560×1440, Pass G on D1–D6, then review and the Q2–Q7 re-qualification (plan §3.4).
4. Housekeeping: trash the agent worktrees once their branches are pushed/merged (check git-ignored `output/` first).

## Open bugs (owner-raised or found)
- **One-frame detach (S2):** symptom — one rAF with no `<video>` at the destination's movie start after an MM (D-deck
  pin carries, arm C/attach, 2560 and 1920). Expected — the carried decoder stays painted. Cause — H3→H1 above.
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
