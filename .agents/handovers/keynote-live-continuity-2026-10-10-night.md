# Handover: main PR #256 MERGED (owner to check); S2 instrument integrated, in review (2026-10-10, ~23:15)

Read this first. It supersedes `keynote-live-continuity-2026-10-10-evening.md` and `…-q7-findings.md`; every live item from
both is carried below. Verify branches and PRs on GitHub before acting. Evidence paths are in the MAIN checkout
(`/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/`), which is git-ignored.

## Where everything is
| Thing | State |
|---|---|
| `main` | `27ef72ce` = merge of **PR #256** (owner merged it optimistically at 15:12 UTC; **owner will check it next session**). Before that, `f4a44ca0` (#254). |
| **PR [#256](https://github.com/Anyhowclick/obed-edom/pull/256)** `claude/main-bridge-easing` → `main` | **MERGED** (`27ef72ce`; head `5888be29`). Contains the eased bridge overlay, player `17c0c938`, the carry-cover gate, bridge-timing qualification, fix A (freeze-trigger bounds follow the bridge curve), the `SUPPORTED_PLAYERS` SKILL fix, the gate record and the six raw Astra rounds. Local branch and worktree removed after the merge (the commits are in `main`). |
| `claude/s2-detach-fix` | Code head `e38ded06`; branch head = the handover commits on top. **Pushed.** Worktree `obs-mac-camera-swap-fbc63b` (this session). Suite-green. Contains streams A–D, the D1 note-scoping fix, the `gl-clock-bridge` probe variant, Astra folds r1–r8 and the schema-2 port of fix A v1. **Lacks** fold3 and the final main fix — see the two rows below. |
| `s2-instr-fold3` @ `effdae21` | **Pushed** (backup), no worktree. Astra r9's 4 MAJORs plus an audit of every older scorer (restart / armed / hand-back / retire / refusal / forced / force-wrap / recorder / `page_errors_in`), with several more false passes closed. A 60-case parametrized test: 51 injected cases fail on the old code, 9 controls pass on both. Targeted 2085 passed. **Not merged.** |
| `s2-main-final` @ `513b40b6` | **Pushed** (backup), no worktree. The FINAL main fix (`5888be29`, = #256) merged into S2 (on `e38ded06`). No conflicts, no schema-1 reads left (the bridge is read only through `_bridge_side_rect`). The 6 touched files pass on 3.10 (1299, L 61.0 / 4.8 ms). **Not merged.** |
| Owner's fresh `Minimal Alpha_DSK` export (player `17c0c938`) | **Moved** to the main checkout's `output/fixtures/minimal-alpha-dsk-17c0c938/html` (1.5 GB, with a README and the dashboard `.sessions` json). `gate-main-dd61e7c0` is trashed. The old drivers (`main_gates*.sh`, `main_r3_followups.sh`) still name the old path. |
| Cleanup done 2026-10-10 ~23:40 | All agent, gate, scratch and `main-bridge-easing` worktrees trashed. Their live logs moved to `output/evidence/{s2-dev,main-bridge-easing}/live-logs/<wt>/`. Merged local branches deleted (`s2-instr-*`, `s2-fixa-port`, `s2-cc-notes`, `s2-glclock`, `claude/main-bridge-easing{,-2}`, `worktree-agent-*`). Old session scratchpads trashed; cited bits kept in evidence: `main-bridge-easing/baseline-2026-10-09-main-linear/`, `s2-dev/rubber-prototype/`, `s2-dev/triage-2026-10-10/scripts/`. `~/.Trash` holds ~50 GB until the owner empties it. Still local + origin: `claude/continuity-generalisation-s2` (old S2 head `dcbb6363`, superseded); deleting it is the owner's call. |
| `confident-elion-b41768`, `resizer-optimizations-7cae67` | Not ours. Leave them. |

## Main PR #256 — merged; what's done, what's left
- **Done:** final round at `dcd5b9e4`: `run_gates` full tier 3-wide `failed=0 pending=0` (18 runs, 452 s). Carry-cover green pass / linear red fail / null fail. Freeze bracket passes on the eased core (L 61.0 ms, trigger frame 10, deadline 13). Slide-3 restart fast/gl/slow 0.168 / 0.119 / 0.150 s, against the 2026-10-09 range 0.106–0.222. Max rAF gap 34.3 / 33.3 ms. Live `pollTimes` checks 4/4. Host adapter on/off on player `17c0c938` (an r3-era run before the final round, `r3/fresh-adapter-1920-{on,off}.json`): pins match (`330ef72c` on, `4f9fbffd` off), presenter ready, continuity declined (ambiguous `untitled.mov` 7→8).
- **Suites:** 9156 passed / 0 failed / 11 local skips. 3.10 floor 2734 passed (touched files). test:ui 320; maps 542+2.
- **Review:** GPT-6 Astra (high). Branch r1 (3 MAJOR) → r2 APPROVE. Fix A r1–r3 folded → **r4 APPROVE**.
- **Record:** `.agents/reviews/main-bridge-easing/gate-record.md` (on the branch). Evidence: `main-bridge-easing/{r3,r3-rerun,freeze-ab,triage-r3,final-dcd5b9e4}/`.
- **Left:** the owner checks the merge next session, including the real-OBS re-look (no rubber band on 3→4). **Post-merge chore left (next session, a small docs PR on main):** delete the six raw Astra rounds in `.agents/reviews/main-bridge-easing/` (review lifecycle; the gate record stays). The worktree chores are done (logs moved; `gate-main-dcd5b9e4` and the `-2` scratch worktree trashed).

## S2 — state
- **Instrument stream** (plan `.agents/plans/keynote_live_continuity_instrument.plan.md`; owner LGTM, all 14 decisions; minimal tests):
  - Stream A: `scripts/paint_instrument.py` — painted(pv), pre-paint sampler pieces, scoring, positive control, census, self-check.
  - Stream B: probe — sampler v2, B0 `show()` in host/red/attach arms, per-frame paint in `score_continuity`, Pass G advance legs, Pass G red arm, paint-control CLI.
  - Stream C: `run_gates.sh` arms and checks + SKILL. Red registrations D5 host and D1 Pass G `no-pin-hold` are **PENDING owner sign-off**; nothing is registered before V3 measures it.
  - Stream D: core `6c7a482e` — a declined teardown cancels pending remount retries (the D5 stale-timer revival). `CONTINUITY_VERSION` 6.
- **Astra rounds on S2** (`s2-dev/instrument-review/astra-r{1..9}.md`): every finding was the class "incomplete or unreadable evidence counted as a verdict". r1–r8 folded (schemas `PV_FIELDS`, `PP_FIELDS`, `CONTROL_*`, `PAINT_SCORE_FIELDS`, `SAMPLE_*`; raw evidence validated before conversion; unknowns never overwritten in any aggregator). **r9 REQUEST CHANGES:** the schema-2 port is correct (L 61.040 / 4.779 ms). 4 MAJORs remain in OLDER scorers that predate S2:
  1. a null-scene row vanishes from `score_restart_strict` prior presence — **false pass**;
  2. force-wrap: unavailable `coreEvents` read as "never opened" — **false pass**; other unknowns read as fail;
  3. armed / hand-back / forced scoring turn error objects into False;
  4. `score_retire` returns False before its readability checks.
  Being fixed in `s2-instr-fold3`, with an audit table of all older scorers.
- **Suites at `e38ded06`:** 10040 passed / 0 failed / 11 local skips. 3.10 floor 4019 passed / 1 skipped. test:ui 320; maps 542+2.
- **Experiments tonight** (`s2-dev/experiments-2026-10-10-evening.log`):
  - **gl-clock D1:** `gl-clock-bridge` variant strip 0 px / exposure 0 in 5/5, against the default core's 8 / 53 / 7 / 9 / 7 px. Keynote's GL clock origin removes the ~6.8 ms start-offset lag (`cc-D1-glclock/`). The 53 px default-core outlier (green-2) is unexplained.
  - **D5 end of show:** old core 268 / 248 ms gap then revival; Stream D core never revives (`pingap-d5end/`). Confirms the stale-timer mechanism and the fix.

## S2 — next steps, in order
1. **Merge the final main fix into S2.** S2 merged `claude/main-bridge-easing` only up to `104364ee`. It needs everything in `104364ee..5888be29`: `abefdb2d`, `34cc9bf3` (SKILL `SUPPORTED_PLAYERS`), `18bbc221` (`pollTimes`, recorded-callback deadline), `dcd5b9e4`, `f2d90063` and `5888be29` (gate record), re-ported to schema 2 (`src.rect`/`dst.rect`, `_bridge_side_rect`). Committed as `s2-main-final` `513b40b6`; its touched files are green (1299 on 3.10). After merging it together with fold3, run the FULL suites. **Lesson:** after every main merge into S2, run the touched suites before building on it. Main is runtime plan schema 1, S2 schema 2; the last clean-looking merge broke 50 tests.
2. Merge `origin/s2-instr-fold3` (`effdae21`) and `origin/s2-main-final` (`513b40b6`) — both are on `e38ded06` and touch different areas; resolve if `p2_verdict` overlaps. Also merge `origin/main` (`27ef72ce`, = #256; content already in `513b40b6`). Run full suites (pytest 3.12 full, 3.10 floor on touched files, test:ui, test:maps). Then Astra r10 on everything since `e38ded06`. Continue until APPROVE.
3. **Live validation (V0–V6, plan §7).** All live work is coordinator-only, serial, load < 3 at start, ≤3 Chromes.
   - V0: streams A–D targeted tests green on 3.10 and 3.11.
   - V1 smoke: the D1 attach arm without, then with, B0 `show()` first (the plan predicts every attach carry reds without it). Then D1 host 1920 `--skip-arms B,C,V,Voff,attach`, then a full P2 host run. Also check whether any P2 harness reading `footprintOwnerDecoderId` (`p2_recovery_html_adversarial.py:893`) runs hidden in alpha mode (plan §8).
   - V2 positive controls (exact seq sets).
   - V2b: L2 force-wrap takes with paint on; measure `seeking`/`readyState` at wraps (no excuse until measured — decision 14).
   - V3 reds, plus the V3b pin pixel spot check (decision 6).
   - V4 moved sets: strip arms `D1/D2 strip:pin@6`, `D3 strip:pin@2/@4`, `D4 strip:pin@5`, `D5 strip:pin@2/@4`; post-hoc `D4 wrong-instance`/`fifo-reuse`, `D5 fifo-reuse`/`stash-any`. Re-register only with a measured reason, evidence and the owner's sign-off.
   - V5 null sweep; V6 overhead.
   - Then register the pending reds with the owner's sign-off.
4. **Full S2 re-run** on the final head: Phases A (decks × 3 viewports), B/D1 (`run_gates` 3-wide incl. Pass G, carry-cover, paint arms) **plus one `GATE_JOBS=1` round** (identical verdicts and exact seq sets; red counts ±3 frames; restart margins within the 2026-10-09 baseline), D2, D3 (P2 main vs S2 interleaved), D4 (G2 seam), D5 (loop). Then Q6 (managed OBS 25/30, KBs, soak 4 min; owner pre-approved), then Q7 with the owner (Q7a external attach D1/D4; Q7b dashboard Keyer on D1–D5).
5. Full suites, Astra on the final diff, S2 gate record `.agents/reviews/continuity-generalisation/gates-r1.md`. The gate commit keeps in `QUALIFIED_PLAN_SHA256` only the S2 shas of P2 off/on, p2-loop off/on and the decks that passed Q3+Q7, and removes the others before the PR is offered (plan §3.4). Owner opens and merges. S3 (delete the allowlist) stays the owner's call. After S2 merges, delete the main checkout's `output/<name>` → `output/fixtures/<name>` compat symlinks once no branch reads the old paths (plan §3.7).

## Open items (owner-raised or found; symptom / expected / evidence)
1. **Q7 #1 pins dark during the move** — Symptom: a pinned movie shows Keynote's frame-0 poster for the whole Magic Move (~1.8 s, 108 frames), then reappears ~1.8 s ahead (D1 `g 3` + advance in OBS; D2/D3/D5 sequential pins too). Expected: the carried decoder paints throughout. FIXED on S2 (pin hold `fbba575e`); the per-frame proof is the instrument's V-runs, still owed. Evidence `s2-dev/pingap/` (`SUMMARY.txt`). `pingap/run.sh` sets `W=` to the trashed `gate-s2-ff21695e`; re-point it before re-running.
2. **Q7 #2 bridge rubber band** — Symptom: during every bridge a second, frozen copy diverges from the carried movie (OBS and headless). Expected: one copy. Cause: the overlay moved linearly while Keynote draws the GL poster EaseInEaseOut. FIXED on main (#256: easing + carry-cover); **owner real-OBS re-look still owed** (originals: `s2-dev/q7a-goto1/screencast-mainP2/sheet-3to4.png`, `s2-dev/rubber/`). Later hardening, not started: hide the carried movie's GL quad via `patch_player`. S2 D1 still shows a ~6.8 ms GL-clock start offset (5–9 px strips): the overlay starts before Keynote's GL clock origin. `gl-clock-bridge` proves the fix (5/5 clean). **Moving it into the product core is a separate owner go — pending.** Analysis `s2-dev/triage-2026-10-10/carry-cover-D1-lag-fit.md`.
3. **Q7 #3 new player refused** — FIXED (#256).
4. **OPEN — P2 2→3 Dissolve on a transparent page** looks wrong in OBS (**owner comparing in Keynote on 2026-10-11**). Symptom: slide 3 is at full strength from the first frame, and slide 2's squares go grey/white then fade to black. Expected: a normal cross-fade. Owner to compare with Keynote itself (`~/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key`, do not save). Not investigated. Evidence `s2-dev/q7a-goto1/screencast-diss/sheet-2to3.png`. The P2 fixture's posters are the original clip, so judge hand-overs on the D decks or a real deck.
5. **End of show (deferred by owner):** D1–D3 hold the carried movie at end of show; D5 ends empty (consistently, after `cf9a9c13`). Resume options: a scene count in the schema-2 plan, or read `__obedLive`.
6. **Dashboard gating (owner: keep):** a continuity-refused deck can't start, even with continuity off, until the allowlist widens and is removed. The owner's fresh `Minimal Alpha_DSK` is blocked on main (ambiguous ownership 7→8).
7. **Scope question for the owner:** Astra r9 moved into older (pre-S2) probe scorers. Fold3 is closing them in one audit pass. If the owner prefers, cap S2 at the instrument's scope and track the older-scorer audit separately.
8. **Watch items:** the carry-cover null control can read inconclusive under round load (r3: one 67 ms hole; 3/3 quiet reruns fail correctly). Carry-cover thresholds and masks are P2-calibrated (`run_gates` runs carry-cover on P2 only). The strip rule rounds left/top up but right/bottom down (a 1 px inconsistency; fix separately, never to pass a deck). The 53 px default-core outlier on D1.

## Decisions — owner answered 2026-10-10 ~23:20 (details kept for reference)
**Answers:** (1) gl-clock into S2 core v6 — **GO, as recommended** (hardened: never throw, fallback to today's clock within ~50 ms, today's behaviour as a red variant, carry-cover D1 arms in `run_gates`, 53 px outlier read first, before the S2 full re-run). (2) Red registrations — **conditional sign-off GIVEN**: register the V3-measured sets only if they exactly match the predictions below; any difference goes back to the owner with evidence. (3) Scope — **option C, as recommended**. (4) Dissolve alpha — **the owner will compare in Keynote personally (2026-10-11)**; don't run the headless localisation unless the owner asks. (5) The two fold3 semantics calls are **still open** (recommendations below).

1. **gl-clock fix into the product core.**
   - Problem: the core starts its bridge animation ~5.5–8 ms (mean 6.8) before Keynote's GL animation of the same movie, so the poster peeks out behind the moving `<video>`'s trailing edge. The strip grows with speed: 5–9 px on D1 against a 5 px allowance. P2 (slower) passes, so main is fine today; S2's D decks fail.
   - Fix proven by the probe-only variant `gl-clock-bridge`: detect Keynote's own animation clock start by hooking `window.requestAnimFrame` as `main.js` assigns it, and time the overlay from there. D1 5/5 clean (0 px) against the default core's 8 / 53 / 7 / 9 / 7 px.
   - Risks to harden first: a missed hook would make `window.requestAnimFrame()` throw, which breaks playback; never seeing Keynote's start leaves the overlay at the source; an unrelated loop could set the origin; a mid-move key change could snap back.
   - **Rec: yes, in S2 core v6**, hardened:
     - never throw (fall back to native rAF);
     - fall back to today's clock if no Keynote start is seen within ~50 ms, so the worst case is exactly today;
     - today's behaviour becomes a red control variant;
     - carry-cover joins `run_gates` on D1 (green/red/null; P2-only today);
     - a read-only look at the 53 px outlier first.
     Before the S2 full re-run. Main untouched unless a faster deck needs to qualify there.
2. **Pending red registrations.**
   - D5 host red: `--core-variant no-pin-hold` expects exactly the A carries at b0to1 and b1to2, longest unpainted run ≥ 60 frames (~108 expected).
   - D1 Pass G red: exactly leg `G1-3-4` at b2to3 red, legs (2,1,2) and (1,2,3) green, ≥ 60 frames.
   - The registration tables are empty, so both arms read *unregistered* and FAIL the round. The S2 re-run can't be green until they're registered.
   - **Rec: conditional sign-off.** Register the V3-measured sets only if they exactly match these predictions; otherwise bring the evidence back to the owner.
3. **Scope: older-scorer audit.**
   - Astra r9 found the class in pre-S2 probe scorers (also on main). False passes: the null-scene restart and force-wrap with missing `coreEvents`. False fails: armed / hand-back / forced / retire.
   - Options: A = full audit in S2 until APPROVE; B = cap S2, fixing only the false passes; **C (rec)** = land fold3's audit, then Astra r10, then stop when only false fails or edge cases remain (tracked as a follow-up). Any new false pass still blocks.
   - Main gets the fixes when S2 merges, or via a small port PR if wanted sooner.
4. **Dissolve alpha (open item 4).**
   - Symptom/expected and evidence as in Open items.
   - Causes to separate: (1) Keynote's own dissolve on a transparent page (straight vs premultiplied alpha), i.e. stock behaviour; (2) our alpha/keyer mode or player patch; (3) OBS capture.
   - Owner step: compare in Keynote (`Minimal Alpha_DSK.key`, don't save).
   - **Rec: headless localisation first, no owner needed** (~1 h, 1 Chrome): raw export vs our patched/alpha mode on a transparent page; sample the squares' pixels across the dissolve; check the WebGL `premultipliedAlpha` setting and the dissolve's blend in `main.js`. Independent of S2. Queue after the S2 V-runs unless keyed dissolves matter for an upcoming service.

5. **Two semantics calls from the fold3 audit** (not changed; defaults keep today's behaviour):
   - `score_stage_fit`: no valid stage-map samples, or any untrustworthy row, gives `verdict: False`, which feeds error/fail in `overall_status`/`generated_status`. It's an arm-integrity precondition. **Rec: keep it as fail/error** — a broken stage map means the arm itself is invalid; that's not an observed behaviour red, and the run fails loudly either way.
   - `scripts/managed_obs_qualify.py:968` reads `score_armed` clauses through `bool(ok)`, so an unknown clause shows as FAIL, not INVALID. **Rec: make unknown INVALID there** (a one-line tri-state fix plus a test), to match the owner rule. The managed-OBS qualifier then can't report a clause failure it never observed.

## Owner decisions (still governing)
- 2026-10-10 night: gl-clock product fix GO for S2 core v6 (hardened); red registrations conditionally signed off (exact match to predictions only); older-scorer audit scope = hybrid C (any false pass blocks; false-fail/edge leftovers tracked separately); the owner checks the merged #256 next session.
- `CONTINUITY_VERSION` stays 6 for every S2 core change. Detach fix a1. R9 = movie not fully opaque (R2 reports first). R10 = bridge timing (S2 narrow reader, bridges only, checked last). A runtime carry refusal lasts until the next go-to.
- Pass G: no-consumption = settled position + exact auto-run kinds; it runs inside `run_gates` (full tier). Advance legs treat end of show as an exit; any end of show in a leg makes it inconclusive, never red.
- Pin hold accepted (a pinned movie paints above authored content during its move). Main fix = "fix properly", including the new player on a byte-level argument.
- Main freeze bracket: option A (bounds from the bridge's curve and geometry; never relax `firedVia=='moved'`, marker identity, the 1 px detector).
- Instrument plan: all 14 recommendations — opacity ≥ 0.99 (1); D2 restart 1-frame blank report-only (2); red registration = id sets + 60-frame floor (3); CLI `--pass G --core-variant` and `--paint-control` (4); every expected-True carry gets a Pass G leg (5); V3b pin pixel spot check now, a pin carry-cover gate after the D1 lag fix (6); pre-pin-hold red once, outside `run_gates` (7); census incl. `endOfShow` report-only, triaged before the full re-run (8); consolidating the duplicate opacity logic deferred until after the S2 gates (9); Stream D in parallel, landed before V2–V5 (10); D2/D3 `no-pin-hold` arms added to `run_gates` only after V3 (11); B0 `show()` its own commit (12); `outsideStagePx` report-only (13); no loop-wrap `seeking` excuse until V2b (14). **Test additions minimal** (max coverage, fewest tests).
- Delegation: Opus plans; Opus MEDIUM implements in disjoint streams; GPT-6 Astra (high) reviews while the owner's resets last (`codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only …`; revert to `gpt-5.6-sol` after).
- DeckLink field test postponed to next week. Q6 managed OBS pre-approved; Q7 needs the owner.

## Machine / coordination
- One heavy job at a time machine-wide. `run_gates` refuses above load 4; timed runs start below 3–4. macOS `mediaanalysisd` and the Claude app keep baseline load near 3–5.
- **Peer session "Resizer optimizations"** (`resizer-optimizations-7cae67`) yields compute. Protocol: message it before timed windows ("go idle") and when free ("free now"); its suites and census are fine during our non-timed work. Last state: "free now" sent at 21:23.
- **OBS:** for Q7 the owner launches OBS with `--remote-debugging-port=9222`; never drive it without the owner's go. OBS page tools (`obs_sampler.py`, `obs_screencast.py`) are read-only; quitting `scripts/live_fixture_session.py` (`q`) resets OBS's page and drops the sampler.
- Run a worktree's suites with `uv run` inside that worktree (`OBED_EDOM_CACHE_DIR=/Users/anyhowclick/Desktop/work/obed-edom/.cache`); the main checkout's `.venv` imports the main checkout's code (use it with `PYTHONPATH=<wt>/src:<wt>/scripts` for the 3.10 floor; it has no pytest-xdist). A fresh worktree needs the `output/*` and Sermon Outlines links (memory `worktree-env-setup`), or ~80 tests skip.
- **Hook:** this session (and its subagents) cannot Edit/Write files in another session's worktree. Agent isolation worktrees are fine.
- Agent worktrees start at the main checkout's HEAD (`main`), so briefs must say `git checkout -B <branch> <sha>`. Agents can't use `env …` in commands; use plain assignments.
- Tools: `s2-dev/tools-2026-10-10/` — `main_final.sh` (final main validation), `s2_experiments.sh` (gl-clock + D5), `main_r3_followups.sh` (host adapter + freeze A/B), `dump_corpus_s2.py` (corpus invariance), OBS samplers. Moved live logs: `s2-dev/live-logs/<wt>/` and `main-bridge-easing/live-logs/<wt>/`. Evidence JSON `logPath` values still name the old worktree paths. Past drivers (`phaseA.sh`, `passG.sh`, `phaseD*.sh`, `main_gates{,2}.sh`, `pingap/run.sh`) hard-code trashed gate worktrees; re-pin `W=`/`GM=` before re-running.
