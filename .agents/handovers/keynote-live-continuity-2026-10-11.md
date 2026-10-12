# Handover: S2 V1–V6 done; instrument r21–r25 APPROVED; decision 14 done; final round next (2026-10-12)

Read this first. It supersedes every earlier keynote-live-continuity handover (all deleted); every live item from them
is copied below. Verify branches and PRs on GitHub before acting. Evidence paths are in the MAIN checkout
(`/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/`), which is git-ignored.

## Where everything is
| Thing | State |
|---|---|
| `main` | `1589d096` = #257 (raw Astra rounds of #256 removed) on #255 (resizer seed read) on #256 (bridge easing). |
| PR #256 | Merged 2026-10-10. **Owner confirmed in real OBS 2026-10-11: the 3→4 rubber band is gone.** Post-merge chore done (#257). |
| `claude/s2-detach-fix` | `8bdaf582` (+ docs), pushed. Gate worktrees `gate-v-277c720b` (Stage 1) and `gate-v-9d4fbef5` (Stage 3) in `.claude/worktrees/` — trash after the final round. Instrument folds r12–r16 on top of the contract pass. Worktree `obs-mac-camera-swap-fbc63b`. Contains everything below. |
| gl-clock | Core `a9e1e66a` merged (Astra gl-clock r1 REQUEST CHANGES → fold `5e9c9faf` → **r2 APPROVE**). Live GL-1/2/3 done 2026-10-11 (below). |
| Contract pass | MERGED (`1c02c447` → `de6df228`). Plan `.agents/plans/keynote_live_continuity_contract.plan.md` (owner GO; Q1 N1–N3 yes, Q2 admit rare legal shapes, Q3 smoke yes). Astra r12 → r16 folded; **r17 APPROVE** (section below). |
| Gate worktrees | All trashed. Their live host logs were recovered to `s2-dev/live-logs/<wt>/` (`gate-glclock-c7d2d649`, `gate-preglclock-8ee7077d`, `gate-contract-de6df228`). |
| Dissolve cross-fade plan | Separate session (owner-started), branch `claude/keynote-live-dissolve-crossfade-plan`, worktree `brave-goodall-bd9851`. Plan only. |
| Stale branches | `claude/continuity-generalisation-s2`, `s2-instr-fold3`, `s2-main-final`, the fold4/fold5/gl-clock agent branches: all contained in S2, deleted 2026-10-11 (with their stale handovers). |
| `confident-elion-b41768` | Not ours. Leave it. |

## Done 2026-10-11 (S2 history, in order)
1. Merged fold3 (`effdae21`), s2-main-final (`513b40b6`) and `origin/main` → `4a389a72`. Suites: 3.12 10099 / 0 failed;
   3.10 floor 4499; test:ui 320; maps 542+2.
2. Astra r10 (`s2-dev/instrument-review/astra-r10.md`): 5 false passes → fold4 (`aa7bab37`, `cd27b46d`; independent
   verification found 5 more, all fixed). OBS qualifier: unknown `score_armed` clause → M1 INVALID (`1316589d`); the g2-off
   known-bad check scored on M1's five enforced clauses (`8ee7077d`; fold3 had made it always unknown → M1 INVALID on every
   real take; rescored the two saved 2026-09-25 g2 takes: KB False again). Suites 10149 / 0.
3. Astra r11 (`astra-r11.md`): 5 more false passes → fold5 (`2fb41d89`..`ad35364e`): 162-site inventory (73 flagged) and
   3 verification rounds (10 / 4 / 8 found, all fixed; round 3's fix NOT re-verified). Real-artifact rescore: 2280 verdicts,
   0 changes. Owner then chose the **producer-contract pass** (below) instead of more folds.
4. gl-clock core v6 (plan `.agents/plans/keynote_live_continuity_glclock.plan.md`): core `7b1e04ba` (`CONTINUITY_VERSION` 6),
   red `no-gl-clock`, D1 carry-cover arms (green/red/null) with the `via` clock rule in `check_cc`, docs, `bridge-clock` in
   the frozen F5 note kinds. Interplay fix `5fa7d48b`: carry-cover sets aside `bridge-clock` notes before fold5's
   note checks (else every live carry-cover run would read inconclusive). Suites at `5fa7d48b`: 3.12 10280 / 0.
5. Fixture strip fix `715cb3f1` (dissolve item, below).

## Live gl-clock validation (2026-10-11, gate worktree at `c7d2d649`, evidence `s2-dev/glclock-v6/`)
- **GL-1 D1 carry-cover, 12/12 as predicted:** green 5/5 pass, both bridges strip 0 px, `gl`, lag 5.8–7.7 ms (b2to3 scored
  live for the first time — the note-scoping fix works; held-path lag ≈ pooled, so Q1 is not triggered); `no-gl-clock` 5/5
  fail, b1to2 strip 6–8 px, `fallback` lag 50.6–64.6 ms (1 px margin, Q2 not triggered); null 2/2 fail (72/72 frames);
  largest screencast skew jump 4.3 ms (no clock step).
- **GL-2 P2:** carry-cover green pass (`gl`, lag 5.0 ms), `linear-bridge` fail (57 px), null fail. P2 adversarial
  fast ×2 and `--gl-replay auto`: success True; freeze bracket pass, marker→trigger 69.1 / 67.2 / 79.5 ms, trigger frame
  10, deadline 13/13/12; slide-3 restart 0.131 / 0.129 / 0.106 s. Plan correction: the P2 harness snapshots kept events
  after the 2→3 restart, before 3→4, so no `bridge-clock` note can appear there (the keep-kind is inert); P2's lag is read
  from the carry-cover arm instead.
- **GL-3 full `run_gates` round:** `failed=6 pending=0` (plan predicted 2). All six CARRY-COVER lines as predicted (P2 and
  D1 green/red/null), host gates at 3 viewports pass, Pass G pass on all 7 decks, paint control 3/3, every P2 arm MATCH.
  FAILED: the two expected unregistered no-pin-hold reds (`HOST red D5`, `PASSG-RED D1`) plus four **V4 moved sets**:
  D1 `strip pin@6` and D4 `strip pin@5` (paint adds a `:carry` red — a duplicate painter for 58–62 frames during the
  pin-stripped move — to the registered `duplicate:slideN`), D5 `fifo-reuse` (registered `stray:slide3`, observed
  `b1to2:carry` + `duplicate:slide3`), D3 `strip pin@2` (inconclusive: b0to1 paint unreadable).
- **A/B attribution** (`glclock-v6/V4AB/`, old = `8ee7077d`, core `6c7a482e`): D1 `pin@6` and D4 `pin@5` reproduce the same
  mismatch on the old core → not gl-clock/fold5. (Run under load ~20 from the contract implementer's suite; the new
  core's D1 read inconclusive there — a load artifact.) Quiet second batch: D5 `fifo-reuse` old = new (same moved set);
  new D1 `pin@6` = GL-3's fail (the load-run inconclusive was load); **D3 `pin@2` passes on both cores** (GL-3's
  inconclusive was 3-wide round load — a watch item, not a moved set). **Three V4 moved sets** (D1 `pin@6`, D4 `pin@5`,
  D5 `fifo-reuse`) go to V4 re-registration (measured reason + evidence + owner sign-off).

## Contract pass (merged 2026-10-11)
- `scripts/live_evidence_contract.py`: exact producer shapes per evidence kind, validated once at 8 ingestion points
  (`score_verdicts`, `rescore_artifact`, `score_force_wrap_run`, `score_carry_cover`, hand-back/forced/live-ring,
  visible/census, managed `arm_gates` + `score_mmo`, P2 `_score_freeze_control` → `nullControlSound`); a violation makes the
  arm INCONCLUSIVE (INVALID for force-wrap and managed runs). N1–N3 fixed. SKILL.md: a change to any `*_JS` producer or note
  payload updates the contract in the same commit.
- Suites at `de6df228`: 3.12 full **10396 passed / 0 failed**; 3.10 floor (contract branch) 6397 passed. Regression
  oracle OLD `0ccd6c88` vs NEW: **0 changes across 1482 retained records** (13 families); acceptance scan 0 rejections
  incl. GL-3's 33,096 schema-2 rows (the first scan found one missed producer generation — an old managed `handedBack`
  shape — now admitted). Q3 smoke (`s2-dev/contract-smoke-de6df228/`): P2 host 1920 and D1 carry-cover both pass, 0
  contract errors. Oracle/acceptance/spy scripts copied to `s2-dev/contract-impl/`; suite logs `s2-dev/suites-de6df228/`.
- **Review criterion (owner, 2026-10-11)** — every Astra finding is one of: (1) CLOSED BY CONTRACT (names the clause;
  non-blocking); (2) CONTRACT SLACK (the contract admits a producer-impossible input; blocks only if it yields a false pass;
  fix = tighten the table); (3) FALSE PASS (producer-legal evidence scores pass/True/matching red; blocks; needs a repro
  with producer citations); (4) FALSE REJECTION (blocks only if a retained verdict would change; else MINOR).

## Instrument review r12 → r17: APPROVED (2026-10-11 night, `baa07e36`..`510de8bb`)
Owner GO "Sweep + exact match" (2026-10-11 ~22:40), then "I trust ur decisions" for the night. Reviews on GPT-6 Astra
(high); rounds + prompts + logs in `s2-dev/instrument-review/astra-r{12..17}*`; oracle outputs, suite logs, the live smoke,
implementer briefs (`common.md`, `sweep.md`) and their scratch scripts in `s2-dev/fold-r12-r16/`.
| Round | Verdict | Folded in |
|---|---|---|
| r12 (at `de6df228`) | 4 blocking | `baa07e36`: managed `movie_painters` identity/rect-first (M5 + sibling g2 M2); hand-back foreign src False; contract handoff release needs `ok=True`+elId; stream-wide elId→probeId; failsafe unreadable containers → INVALID (M5 + run); reference V contract-validated; rescore reports contract rejection |
| r13 | 4 blocking (incl. a regression from our M2 fold) | `ae4e05ff` + **L2 closing sweep**: substring asset matching RETIRED (`names_asset` gone); one shared `obed_edom.live_continuity.canonical_asset_name`; rule B everywhere (paint, P2 `_movie_key`, managed precheck, adversarial 2→3 restart `unnamedRows`) |
| r14 | 3 blocking | `7e185bd2`: rect identity before src (hand-back, arming census `foreignId`); paint `substitute` for a decoder of the asset painting another; P2 `_movie_key` sources-only vs `_note_movie_key` logical keys; bound-decoder src before presented-time aggregation (1→2, 3→4, restart); contract R4 (empty-key fromDom needs its stamp) |
| r15 | 2 blocking | `9dc88785`: `match_painting_videos` judges the claimed instance's asset (visible slide + census); retire's handed-back exemption needs the retired asset |
| r16 | 2 blocking | `510de8bb`: managed precheck judges the handed-back element's src; **`CARRY_COVER_SAMPLER_JS` reads now carry `src`** (additive; contract: new read generation, no mixing, legacy without src stays legal and pixel-only) |
| **r17** | **APPROVE** (1 MINOR) | — |
| r18 (follow-up) | **APPROVE** | `14f49c8c`: r16 #3 — geometry-tied instances go to the one whose asset the painter names (IoU first, exact) |
Rules now in force (owner): (A) exact canonical asset matching in every scorer; (B) identity first (probe id / elId /
carried / pooled / facade / armed rect), then src: exact → the movie; foreign on an identity-resolved element →
False/FAIL; empty/unreadable → unreadable; unresolved exact-asset elements still count. Exception (coordinator, Astra
accepted): in multi-row decoder TRACKS a row naming another asset is INCONCLUSIVE, not False (element reuse).
Verification at `510de8bb` (`14f49c8c` is one scorer line + 2 test cases: targeted `-k` subsets only — the next session's first full suite covers it): full 3.12 **10455 passed / 0 failed** (`9dc88785`: 10446); 3.10 floor touched files 4651
(`9dc88785`) + 2040 (`510de8bb`) passed; regression oracle vs `de6df228` **0 changes / 1503 records** at every fold;
acceptance scan 0 rejections / 3,879 records; live D1 carry-cover (from this worktree, load ~4.5): green pass, null fail
(72/72 both bridges), an instrumented green run showed every `vids`/`pre` read carrying `src`
`counter-a.mov-0.0000-60.0000.mov` (`fold-r12-r16/smoke-510de8bb/`, spy `scripts/srcspy.py`).
Known: retained `loop-gates/l5/runs/soak-20260925-121732.json` (recorded PASS) re-scores FAIL already at `9dc88785` and
before — no `reads.postHandback`; predates the hand-off requirement (Codex r4 #5); not caused by these folds.

## Live validation V1–V6 (2026-10-12) — evidence `s2-dev/instr-v-277c720b/stage1/` (discovery) and `s2-dev/instr-v-9d4fbef5/stage3/` (final head)
Owner-approved shortened schedule (target ~2.5 h): Stage 1 discovery at `277c720b` → Stage 2 freeze → Stage 3 final head.
The deck sweep ran ONCE, serially, in Stage 1 and counts at the final head because the freeze diff touched only registration
tables, `run_force_wrap` and `run_gates` DECK_ARMS (verified by diff); the `GATE_JOBS=1` round was replaced by a serial
re-run of the timing-sensitive arms (P2 host ×3, Pass G ×7). Drivers/helpers: `s2-dev/fold-r12-r16/`-style scratch copies
in the session scratchpad (`vrun/`: stage1/1b/3 drivers with an escalating load guard, summ/blind/pc/wraps/inconc/v6,
prepinhold, v3b, wrappix).
| Step | Result |
|---|---|
| V0 | 3.10 + 3.11 green (14f49c8c) |
| V1 | D1 full host 1920: pass; A sampler ok, pp every row, 0 seq gaps, 16.7 ms, 0/0/0/0, gaps ≤ 33.3/58.45; attach True, owner 0 (B0 effective). "without B0" run dropped (owner). P2 harness never injects `#body{opacity:0}` (answered from code). |
| V2 | all 13 positive controls exact seq sets (N 0/1/6/30 early+late, half, element-visibility, display depth 2, 1600). |
| V3 | reds = GL-3 exactly: D5 b0to1+b1to2 (108/223), D2 b2to3 (108), D3 b0to1 (107), D4 none, D1 Pass G G1-3-4 carry (229) + `G1-3-4:destination` (slide-4 rect dead after arrival). Blind rescore (paint off): D2 b2to3 / D5 b0to1 green (old scorer blind; paint catches). Pre-pin-hold core (`fbba575e^`): D5 same set; D1 Pass G carry only (no destination red — the destination red is the current core minus pin hold). |
| V3b | landed core: counter advances in the pin rect (D1 1-3-4, D5 pin@2); `no-pin-hold`: frozen. As predicted. |
| V4 | D1 pin@6, D4 pin@5, D5 fifo-reuse reproduce GL-3's moved sets; reason measured (paint instrument's new coverage; blind rescore reads D1/D4 added carries green; same on pre-fold core). D3 pin@2 passes. Re-registered (owner "go with ur rec"). |
| V5 | all 18 deck runs + P2 full pass on the real core (2 coverage inconclusives re-ran serially → pass). INCONCLUSIVE A 2/67, attach 0/25. |
| V6 | cadence 16.7 ms everywhere; read cost mean ≤ 0.18 ms, max 1.6 ms/frame; P2 slide-3 restart 0.099/0.097 s (Phase D 0.093/0.095; limit 0.35). |
| Registrations | `9d4fbef5` (Astra r19 APPROVE): D2/D3/D5 no-pin-hold (floor 60), D1 Pass G (carry + destination, floor 60), V4 sets; run_gates DECK_ARMS + D2/D3 no-pin-hold. |
| Stage 3 C1 | `run_gates --tier full` 3-wide at `9d4fbef5`: `failed=1 pending=0` — only PASSG D5 inconclusive (66.7 ms coverage gap); every registered red, moved set, paint control, carry-cover arm matched. Serial subset: Pass G ×7 all pass (incl. D5); P2 host 2560/1600 pass, 1920 coverage-inconclusive (arm B red window). |

**Findings fixed today (root-caused):**
1. `run_force_wrap` never called `show_output()` (B0 missed it): every force-wrap take sampled under the launch host's black
   cover → paint unreadable on 3→4. Fixed `9d4fbef5`.
2. **Force-wrap 1→2 was blind** and P2's legacy `continue1to2` windowed the NEXT press: the 1→2 take rests at `#2` with the
   sampler's `scene` still 1, so nothing crossed `onset1to2`=2; since the 2026-10-10 not-observed→None folds every unheld 1→2
   carry read `invalid` (kb-1to2 could never fail; September's fail was vacuous). Fixed `b7e0d760`: `press_scene_1to2` shared by
   `score_boundaries` and force-wrap; no wrap + unheld carry → fail; `rescore_artifact` compares pre-convention stored
   `continue1to2` by verdict+reason (`--rescore` exits 1 on ok False). Oracle: no stored verdict value changes; kb-1to2 → fail.
   Audit: every D-deck pin window contains its move, margin thin (84–100 ms before the press; a ≥ ~1.9 s pin move or a resting
   destination would miss it) — follow-up guard.
3. **66.7 ms coverage inconclusives = Chrome's 30 Hz throttle** with ≥ 2 visible playing videos (viz "2 or more videos"
   frame-interval matcher; 18/18 gaps 66.6–66.8 ms, all ≥ 2 videos; 0 at steady 60 Hz; not load; predates the instrument). The
   scorers judged gaps against the window median (16.7). Fixed `b7e0d760`: local period = slower of the medians of the 8 deltas
   either side (gap rule unchanged). 965 retained windows: 11 fail→pass, 0 pass→fail. The r3 carry-cover null INCONCLUSIVE was a
   genuine screencast hole at steady 60 Hz (stays). Product note (owner: low priority): with ≥ 2 movies playing the page
   animates at 30 fps; 30 fps clips lose nothing; optionally confirm in OBS (CEF 127 offscreen) at Q6.
4. **Decision 14 (loop-wrap `seeking`)**: with the cover fixed, 3→4 force-wrap takes show ONE `seeking` frame on the carried
   decoder exactly at the recorded wrap (takes 375/1700 fail; it appears only when the wrap lands within ~17 ms of schedule).
   Owner: pixel-check it; if painted → narrow excuse (carried decoder, seeking only, ±1 frame of the recorded wrap, Astra), if
   blank → real flicker → core. First pixel run (8 attempts) inconclusive: the screencast changed timing so no seeking frame
   occurred; driver v2 (`vrun/wrappix.py`: narrow screencast window, 5 offsets, `--no-screencast` rate comparison) ready.
Suites: `9d4fbef5` 3.12 10466 / 3.10 floor (probe+run_gates) 1905; `b7e0d760` 3.12 **10485 passed / 0 failed**.

## Next steps, in order
1. **gl-clock:** DONE (Astra r2 APPROVE; live GL-1/2/3 above). Its Astra rounds: `s2-dev/glclock-review/astra-r{1,2}.md`.
1b. **START HERE (next session).** State 2026-10-12 ~15:00: instrument review loop r21–r25 DONE, **Astra r25 APPROVE at
   `8bdaf582`**; decision 14 DONE. Commits on top of `d2c619f5`: `ee481a90` (r21 P1: carry-cover gaps = elapsed rAF intervals
   from raw tick times, boundary intervals prorated), `5858dd0d` (owner "Tighten": paint + carry-cover no-interior gaps share
   `paint_instrument.local_period`), `bd9ac414` (r22: sampler ticks must span the carry-cover mid-move window, else
   inconclusive), `d411aef9` (r23: an unobserved gap is judged at the FASTEST delta within 8 either side, never slower than the
   fallback unless both sides are complete + steady; + the decision-14 excuse), `8bdaf582` (r24: the excuse waives ONLY decode
   readiness). Astra r24's closing-sweep inventory: every coverage-allowance path closed as a class.
   - **Decision 14 (owner rule applied):** `wrappix.py` v2 caught the carried decoder `seeking` at the 3→4 wrap in two live
     takes (offset 1700); both show the clip's last frame (counter 1380) fully painted on the seeking frame, then frame 0
     (`s2-dev/instr-v-9d4fbef5/decision14/`); `--no-screencast` rate 5/10 takes vs 2/8 with the screencast. Excuse: on a
     classified wrap sample (`wrapTimes`) whose sampler read has the carried decoder `loop: true`, a `seeking` pre-paint read is
     re-judged with readiness satisfied (all other paint rules apply) → `seekExcused`. Stage 3 green takes 3to4_375/1700 now pass.
   - Suites: 3.12 full at `8bdaf582` **10499 passed / 0 failed** (`OBED_EDOM_CACHE_DIR` set: 11 skips; without it 28); 3.10
     floor (probe + paint + run_gates files) 2070 passed at `d2c619f5` — re-run the floor at the final head. Oracle vs
     `9d4fbef5` (pre-local-cadence): 19 changes = 13 force-wrap (b7e0d760's approved 1→2 fix), stage3 V2b 3to4_375/1700
     fail→pass (decision 14), GL3 host-redD3 strip pin@2 (inconclusive both), **V5 D3-1920 attach pass→inconclusive** (66.6 ms
     switch-point gap next to a short 60 Hz run — the "Tighten" cost). Paint rescore of 1031 retained windows: 0 fail→pass,
     3 pass→fail (those GL3 + D3 windows). The oracle diff's "crash" line is a false alarm (it matches `"__error__": null`).
   - Open, non-blocking (tracked): r21 P3 MINOR — the exact old-convention rescore rejects
     `contract-smoke-de6df228/host-p2-1920.json` arm A (renamed coverage diagnostic; no verdict/`ok` change); r23 P3 contract
     slack — paint drops the interval crossing a requested window edge; r24/r25 contract slack — the wrap excuse trusts
     `unwrap_clock`'s classified wrap (no recorder alignment, a manual seek landing on a wrap sample is not excluded).
   - Tools/evidence (scratchpad is wiped on reboot): `output/evidence/s2-dev/instr-v-9d4fbef5/tools/{r21..r25,fc2,
     oracle-vs-9d4fbef5-d411aef9,suite-*.log}`; oracle scripts in `tools/oracle` + `tools/r22/run_oracle.sh` (fix scratch paths).
   - **Final round, 2026-10-12 afternoon** (evidence `s2-dev/instr-v-8bdaf582/final/`, gate worktree `gate-v-8bdaf582`):
     C1 `run_gates --tier full` 3-wide `failed=5`, ALL registered reds inconclusive on one 66.6 ms Chrome-throttle-onset gap
     (red evidence present) — the r23 "fastest nearby delta" rule. **Owner: "fix what my eyes can catch"** → `ecf1b553`
     reverts paint `local_period` to the slower side's median (partial sides count; window median fallback). Offline
     rescore at `ecf1b553`: C1 36/36 host/red/paint-control pass; V5 19/19 pass; serial P2 host ×3 + Pass G ×7 pass (live);
     V2b: kb-1to2 + kb-3to4 FAIL, all green takes pass, 1to2_375/1125 invalid on wrap timing (retake; same as Stage 3).
     **Q7 PASSED (owner, 2026-10-12 ~17:00):** Q7a external attach in OBS 32.2.2 on D1 + D4; Q7b dashboard Keyer (managed
     OBS, viewed via chrome://inspect screencast) on D1–D5. D4 S1→S2: the non-carried movie fades out on frame 0 = the
     export's baked opening frame (dissolve patch F3), owner confirmed not S2. Follow-ups: Show OBS cannot surface the
     tray-minimised managed OBS ("no available windows"); start the output session visible + green/red Show/Hide button
     (owner; separate session/PR off main).
   **Next:** (iii) final round at `8bdaf582` (or later head): fresh gate worktree; `run_gates --tier full` 3-wide (must be
   `failed=0`; switch-point coverage inconclusives are now expected more often — re-run serially, never relax), V2b force-wrap
   takes (kb-1to2 must FAIL, kb-3to4 fail, green takes pass), serial P2 host ×3 + Pass G ×7, then Phases D3, D4, D5 L1 hosts
   (3-wide OK). **V5 deck sweep must RE-RUN** (the freeze diff now touches scorer logic). Then Q6/Q7 with the owner, full suites
   + 3.10 floor, Astra on the final diff, gate record. Trash `gate-v-277c720b` / `gate-v-9d4fbef5` after the final round (move
   their `output/.html-preview/live-logs/` to `s2-dev/live-logs/` first).
2. **Instrument review loop:** DONE — Astra r17 APPROVE at `510de8bb` (section above). Folds 3–5's guards stay; a
   simplification pass after S2 may remove the ones the contract made redundant (owner's option). **Start next session at
   step 4 (V1–V6; V0 done).** The carry-cover producer changed (additive `src`): GL-3's six CARRY-COVER lines in the next
   `run_gates` round are its full live check (only a D1 green/null smoke ran tonight).
3. **Live GL-1/2/3 — DONE 2026-10-11** (results above; kept here as the re-run recipe). Coordinator-only, serial, load < 3 at start, ≤ 3 Chromes, peers told "go idle"
   first, never during the owner's OBS session. From a clean gate worktree `G` at the merged head; evidence to
   `output/evidence/s2-dev/glclock-v6/`.
   - **GL-1, D1 carry-cover:** 5× green and `--core-variant no-gl-clock` interleaved, then 2× `--carry-cover-null`:
     `PYTHONPATH=$G/src $PY -u scripts/live_continuity_probe.py --fixture $FX --original-index $FX/index.html --viewport 1920x1080 --carry-cover [--core-variant no-gl-clock | --carry-cover-null] --artifact $OUT/GL1/<arm>-<i>.json`
     with `FX=<main>/output/fixtures/qual-decks/D1/html-unmodified`. Read per bridge: verdict, `maxStripPx`, strips,
     `clock`; and the largest jump in `pts−domTs` between frames (over 17 ms → `log show --predicate 'process == "timed"'`
     around `timeOrigin + t`, a wall-clock step). Predicted: green 5/5 pass (b1to2 strip ≤ 1, `gl`, lag 5–9 ms; b2to3
     scored — first live proof of the note-scoping fix — strip ≤ 1, `gl`, lag < 50); red 5/5 fail (b1to2 6–9 px,
     `fallback`, lag ≥ 50); null 2/2 fail on both bridges.
   - **GL-2, P2:** carry-cover green / `linear-bridge` / null once each → pass / fail / fail, green `gl`. Then
     `p2_recovery_html_adversarial.py --reuse-export --disposable --wait-profile fast` ×2 and once with `--gl-replay auto`:
     the same success line as the last S2 round; freeze bracket passes with marker→trigger ≈ L+Δ … L+Δ+16.7 ms (L = 61.0,
     Δ = the run's own `bridge-clock` `lagMs`, ≈ 68–85 ms); slide-3 restart 0.106–0.222 s; a kept `bridge-clock` note
     showing `gl`.
   - **GL-3, only if GL-1 and GL-2 met their predictions:** `GATE_JOBS=3 scripts/run_gates.sh $G $OUT/GL3 --tier full` →
     `failed=2 pending=0`, exit 1; the two FAILED lines are exactly the unregistered `HOST red D5 --core-variant
     no-pin-hold` and `PASSG-RED D1 --core-variant no-pin-hold`; six CARRY-COVER lines as predicted above; wall time ≈ the
     last S2 round + 30 s.
   - **Back to the owner if:** a green strip over 1 px or any green `fallback` (D1 or P2); a D1 red reading pass; a green
     trailing strip of ~10–15 px (Keynote losing its first frame's delta); any playback break (player build or page errors,
     a missing Magic Move, an error mentioning `requestAnimFrame` → revert); a P2 freeze-bracket INCONCLUSIVE or any P2/host
     verdict differing from the last S2 round; a null arm passing; any GL-3 FAILED line beyond the two above. A null
     INCONCLUSIVE under round load is the known watch item (re-run at `GATE_JOBS=1`, never widen the gap). A run with a
     `timed` step is reported, re-run once, both reported; neither ever turns a FAILED into a pass.
   - **Pre-approved conditional changes (owner 2026-10-11):** Q1 — if a green bridge reports `fallback` with a held-path
     lag ≥ 50 ms, the 50 ms wait starts at the departure's latest setup mark (`markTransition` refreshes `departure.at`;
     wait = `max(started, departure.at)`; 2 lines + 1 assertion). Q2 — if the D1 `no-gl-clock` red ever reads pass (1 px
     margin), the D1 red becomes `linear-bridge`; thresholds are never tuned.
4. Then the instrument's live validation V0–V6, red registrations, the full S2 re-run, Q6, Q7 with the owner, and the S2
   gate record `.agents/reviews/continuity-generalisation/gates-r1.md`:
   - V0: **DONE 2026-10-12 at `14f49c8c`** — streams A–D targeted tests (15 files: paint, probe, detach, managed, run_gates,
     core js, core variants, contract, p2_adversarial ×5, html_alpha_probe, live_continuity) 3.11.3 4562 passed and 3.10.10
     4562 passed, 0 failed (`fold-r12-r16/suites/v0-31{0,1}-14f49c8c.log`; 3.11 venv built in the session scratchpad).
   - V1 smoke: D1 attach arm without, then with, B0 `show()`; D1 host 1920 `--skip-arms B,C,V,Voff,attach`; a full P2 host
     run; check whether any P2 harness reading `footprintOwnerDecoderId` (`p2_recovery_html_adversarial.py:893`) runs hidden in
     alpha mode. V2 positive controls (exact seq sets); V2b L2 force-wrap with paint on (measure
     `seeking`/`readyState` at wraps, decision 14); V3 reds + V3b pin pixel spot check; V4 moved sets (strip arms
     `D1/D2 strip:pin@6`, `D3 strip:pin@2/@4`, `D4 strip:pin@5`, `D5 strip:pin@2/@4`; post-hoc `D4 wrong-instance`/`fifo-reuse`,
     `D5 fifo-reuse`/`stash-any`; re-register only with a measured reason and owner sign-off); V5 null sweep; V6 overhead.
   - Red registrations (conditional owner sign-off, 2026-10-10): register only on exact match — D5 host
     `--core-variant no-pin-hold`: exactly the A carries at b0to1 and b1to2, longest unpainted run ≥ 60 frames (~108
     expected); D1 Pass G: exactly leg `G1-3-4` at b2to3 red, legs (2,1,2) and (1,2,3) green, ≥ 60 frames. Any difference
     goes back to the owner with evidence.
   - Full S2 re-run: Phases A (decks × 3 viewports), B/D1 (`run_gates` 3-wide incl. Pass G, carry-cover, paint arms) plus one
     `GATE_JOBS=1` round (identical verdicts and exact seq sets; red counts ±3 frames; restart margins within the 2026-10-09
     baseline), D2, D3 (P2 main vs S2 interleaved), D4 (G2 seam), D5 (loop); then Q6 (managed OBS 25/30, KBs, soak 4 min;
     pre-approved), then Q7 with the owner (Q7a external attach D1/D4; Q7b dashboard Keyer on D1–D5).
   - Final: full suites, Astra on the final diff, the gate record. The gate commit keeps in `QUALIFIED_PLAN_SHA256` only
     the S2 shas of P2 off/on, p2-loop off/on and the decks that passed Q3+Q7, and removes the others before the PR is
     offered. The owner opens and merges. S3 (delete the allowlist) stays the owner's call.
   - After S2 merges: delete the main checkout's `output/<name>` → `output/fixtures/<name>` compat symlinks once no branch
     reads the old paths.
5. **After the S2 gate record:** rebuild the 8 stripped P2 fixture variants with the strip fix and re-pin their digests
   (owner, 2026-10-11).

## Open items (owner-raised or found; symptom / expected / evidence)
1. **Q7 #1 pins dark during the move** — FIXED on S2 (pin hold `fbba575e`); per-frame proof = the instrument's V-runs, owed.
   Evidence `s2-dev/pingap/`; `pingap/run.sh` names a trashed worktree — re-point `W=` first.
2. **Q7 #2 bridge rubber band** — FIXED on main (#256), owner-confirmed in OBS 2026-10-11. The faster D decks' ~6.8 ms
   GL-clock start offset is fixed by gl-clock v6 (live GL-1 owed). Not started: hide the carried movie's GL quad via
   `patch_player`.
3. **53 px D1 outlier (green-2)** — EXPLAINED: a macOS wall-clock step (`timed` `settimeofday`, −89 ms, 20:17:16) mid-bridge.
   Keynote's animation runs on `Date`, the old core on `performance.now()`. Live-show hazard on today's core (main too); the
   GL clock removes it by construction: origin and progress both on Keynote's `Date`; the fallback deadline on
   `performance.now()`.
4. **P2 2→3 Dissolve on a transparent page** — LOCALISED (`s2-dev/dissolve-alpha-2026-10-11/`). Owner checked the Keynote
   app: normal cross-fade. Two causes, neither OBS nor our host/patches:
   - grey/white squares = our fixture strip dropped `/Cs1 cs` (pdf.js DeviceGray, grey = 255×R). Code fixed `715cb3f1`;
     the 8 stripped fixtures are rebuilt after S2 (until then P2 shows grey squares).
   - slide 3 pops in = Keynote's HTML export draws `apple:dissolve` as CSS opacity on the OUTGOING layer only (incoming
     fixed at 1); opaque backgrounds hide it, transparent pages don't. Hits real DSK decks (clip slides forced to dissolve).
     Cross-fade patch being planned in the owner-started session on branch `claude/keynote-live-dissolve-crossfade-plan`
     (plan only: an in-memory sha-pinned player patch fading the incoming layer 0→1, exact compositing, CEF 127 support).
   - Tooling: our CDP JPEG screencast squares alpha on transparent pages (opacity²); judge fades from PNG-with-alpha or OBS.
5. **End of show** (deferred by owner): D1–D3 hold the carried movie at end of show; D5 ends empty. Resume options: a scene
   count in the schema-2 plan, or read `__obedLive`.
6. **Dashboard gating** (owner: keep): a continuity-refused deck can't start even with continuity off until the allowlist
   widens and is removed. The fresh `Minimal Alpha_DSK` export (player `17c0c938`) is blocked on main (ambiguous ownership 7→8).
7. **Instrument follow-ups (tracked, not blocking):** Astra r10/r11 MINOR false fails (`_recompute_slide_verdict` with an
   unknown stray verdict; `score_vgl_armed_slide` missing armed slide; `score_paint_control` absent record). Fold5 calls left
   for the owner: dropping a null/'ambiguous' footprint owner (2026-09-23 decision); `unplanned_wraps` with no readable
   duration; keyed-note tie vs foreign stamp in `score_retire`; binding the execute log to its call; the paint-control JS
   `placementEvents` gap; substring asset matching; untimed carry-cover frames. Fold5 changed (owner FYI): a preserve-refused
   note without `via` / a retire-boundary note without `elIds` left the known-bad red list (now INCONCLUSIVE); unattributed or
   conflicting refusal notes are None (was False, Astra S2 r2 #3's test); the pre-flip census needs a non-null probe id.
7b. **Instrument follow-ups from r12–r17 (non-blocking, Astra-classified):** r15 #3 MINOR (4) — a
   legitimately overlapping second movie at the carried/instance rect now reads hand-back/arming False (needs explicit
   unrelated-instance provenance before the rect fallback; ignoring foreign src would reopen r14 #1); r17 MINOR (4) — a looping handed-back element hidden behind the GL layer is omitted by `PAINTING_VIDEOS_JS`, so
   the managed precheck reads INVALID (fix: capture src in the identity-specific `HANDED_BACK_JS` read — a producer +
   contract change); (2) the adversarial census `mineByKey` substring branches are in-page JS producers
   (`CARRY_CENSUS_JS` and the GL carry census, adversarial ~:236/378; over-count, fail closed) — exact-match them with a
   contract update + live re-check; legacy carry-cover records without `src` stay pixel-only (criterion 2, accepted);
   P2 pool entries with no key and no stamp fail closed (pre-existing); managed rect matching assumes the stage is 1:1
   with the 1920×1080 browser source (true on retained runs; removing it = `STAGE_MAP_JS` in `Session.read`).
8. **Watch items:** the carry-cover null control can read inconclusive under round load (never widen the gap; re-run at
   `GATE_JOBS=1`). Carry-cover thresholds/masks are P2-calibrated and now also run on D1 unchanged. The strip rule rounds
   left/top up but right/bottom down (1 px inconsistency; fix separately, never to pass a deck).

## Owner decisions (still governing)
- 2026-10-11 night: r13 fold = "Sweep + exact match" (exact canonical asset matching in every scorer; identity first,
  then src — rules A/B in the r12→r17 section); then delegated the night's calls to the coordinator ("I trust ur decisions").
- 2026-10-11: dissolve — fixture strip code now, fixtures rebuilt after S2; cross-fade patch planned in a separate session.
  gl-clock plan GO as written; Q3 = hold at the source, then today's clock after 50 ms; Q1 (wait from the latest setup mark)
  and Q2 (D1 red → `linear-bridge`) pre-approved, applied only on their live triggers. Instrument audit closes with the
  producer-contract pass (plan GO: N1–N3 included, rare legal shapes admitted, smoke run; reviews use the four-class
  criterion in the contract section). OBS qualifier: unknown armed clause → INVALID; g2-off KB on the five enforced clauses.
  `score_stage_fit` stays an integrity FAIL. Planning agents run at HIGH (not EXTRA HIGH). Agent scratch goes in the
  session scratchpad, never under `output/`.
- 2026-10-10: gl-clock into S2 core v6, hardened; red registrations conditionally signed off (exact match only); audit scope C.
- `CONTINUITY_VERSION` stays 6 for every S2 core change. Detach fix a1. R9 = movie not fully opaque (R2 reports first).
  R10 = bridge timing (S2 narrow reader, bridges only, checked last). A runtime carry refusal lasts until the next go-to.
- Pass G: no-consumption = settled position + exact auto-run kinds; runs inside `run_gates` (full tier). Advance legs treat
  end of show as an exit; any end of show in a leg makes it inconclusive, never red.
- Pin hold accepted (a pinned movie paints above authored content during its move). Main fix = "fix properly", including
  the new player on a byte-level argument. Main freeze bracket: option A (never relax `firedVia=='moved'`, marker identity,
  the 1 px detector).
- Instrument plan (all 14 recommendations): (1) opacity ≥ 0.99; (2) D2 restart 1-frame blank report-only; (3) red
  registration = id sets + 60-frame floor; (4) CLI `--pass G --core-variant` and `--paint-control`; (5) every expected-True
  carry gets a Pass G leg; (6) V3b pin pixel spot check now, a pin carry-cover gate after the D1 lag fix; (7) the
  pre-pin-hold red once, outside `run_gates`; (8) census incl. `endOfShow` report-only, triaged before the full re-run;
  (9) consolidating the duplicate opacity logic deferred until after the S2 gates; (10) Stream D in parallel, landed before
  V2–V5; (11) D2/D3 `no-pin-hold` arms added to `run_gates` only after V3; (12) B0 `show()` its own commit;
  (13) `outsideStagePx` report-only; (14) no loop-wrap `seeking` excuse until V2b. Minimal test additions.
- Reviews on GPT-6 Astra (high) while the owner's resets last
  (`codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only -o out.md "$(cat p.md)" < /dev/null`).

## Machine / coordination
- One heavy job at a time machine-wide. `run_gates` refuses above load 4; timed runs start below 3. macOS `mediaanalysisd`,
  `spindump` and the Claude app push baseline load up; agents' `-n auto` runs push it far higher.
- Peer sessions: "Resizer optimizations" finished its round (#255 merged). The dissolve-plan session may run headless Chrome;
  message it "go idle" before timed windows.
- OBS: the owner launches it (`/Applications/OBS.app/Contents/MacOS/OBS --remote-debugging-port=9222`); never drive it
  without the owner's go. OBS 32.2.2 = CEF/Chromium 127. Presenter into OBS from the main checkout:
  `OBED_LIVE_ATTACH=http://127.0.0.1:9222 OBED_LIVE_ATTACH_MATCH='about:blank#program' PYTHONPATH=$PWD/src .venv/bin/python -u scripts/live_fixture_session.py --export output/fixtures/p2-recovery/html-adversarial/html-player --index output/fixtures/p2-recovery/html-adversarial/html-unmodified/index.html`.
- Suites: `uv run` inside the worktree (`OBED_EDOM_CACHE_DIR=/Users/anyhowclick/Desktop/work/obed-edom/.cache`); 3.10 floor
  with the main checkout's `.venv` and `PYTHONPATH=<wt>/src:<wt>/scripts` (no xdist). Logs: `s2-dev/suites-4a389a72/`.
- Agent worktrees start at `main`: briefs say `git checkout -B <branch> <sha>`; agents can't use `env …` (plain assignments).
  A fresh worktree needs `uv sync --frozen --all-extras --all-groups` and the `output/{fixtures,evidence,bank}` links, or
  ~80 tests skip. The probe tests load the probe by file path (PYTHONPATH alone doesn't swap it).
- Hook: this session and its subagents cannot Edit/Write in another session's worktree; agent isolation worktrees are fine.
- Tools: `s2-dev/tools-2026-10-10/` (old drivers hard-code trashed worktrees; re-pin `W=`/`GM=` before re-running);
  `s2-dev/dissolve-alpha-2026-10-11/scripts/dissolve_ab.py` (one-Chrome transparent A/B driver).
