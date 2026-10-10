# Handover: S2 Phase D halted by Q7 (real OBS) findings; main fix in flight (2026-10-10, evening)

Read this first. The detach experiment's results are in `.agents/plans/keynote_live_continuity_detach_r8.plan.md` §5.
Verify every branch/PR on GitHub before acting.

## Branches and worktrees
| Branch / worktree | Head | Where | State |
|---|---|---|---|
| `main` | `dd61e7c0` | origin | #248–#252 merged today (resizer, Gold oracles, .agents cleanup, runbook, dashboard redesign). |
| `claude/s2-detach-fix` | `ff21695e` | origin; worktree `obs-mac-camera-swap-fbc63b` | S2 = S2 rebase + detach fix a1 + Codex r1 / Astra r2 folds (R9, runtime-refusal retire, exact asset names, nested R2, cut→web R7, instance-bound probe retire) + Pass G settled-position rule + Pass G in `run_gates.sh` + `main` merged in. Core v6 sha `6431ec0e…`. No PR (owner opens/merges). |
| `claude/main-bridge-easing` | `981d6df7` (+ uncommitted probe work by the gate implementer) | LOCAL only; worktree `main-bridge-easing` (from `dd61e7c0`) | Main fix, 3 streams: `8204b87a` bridge easing (core v5 `e9338aff`→`06789fbd`, variant `linear-bridge`); `981d6df7` current-Keynote player `17c0c938` supported (byte-level proof; `SUPPORTED_PLAYERS` pins on/off/rendering per player); **carry-cover gate stream still running** (`live_continuity_probe.py`, `run_gates.sh` + tests). |
| `claude/continuity-generalisation-s2` | `dcbb6363` | origin | Old S2 head; superseded by `claude/s2-detach-fix` (fast-forwardable). |
| gate worktrees `gate-s2-{0ff28399,32067445,702db627,867e415c,fd00b12c,ff21695e}`, `gate-main-{d45ae03a,dd61e7c0}` | pinned | local | Throwaway, clean. Evidence lives in the MAIN checkout `output/evidence/s2-dev/`; their own `output/.html-preview` holds only caches/live-logs (and `gate-main-dd61e7c0`'s holds the owner's freshly prepared `Minimal Alpha_DSK` copy, player `17c0c938`, `e17ff140…-p3-r1/html` — needed for the main fix's deck round). Trash after the next round (check output first). |
| `confident-elion-b41768` | `f4a44ca0` | local | NOT ours (another session) — leave it. |

## Owner decisions today (still governing)
- Detach fix = a1 (landed); `CONTINUITY_VERSION` stays 6 for every S2 core change.
- R9 = "movie not fully opaque" (per carry, Magic Move only; Dissolve/build-outs unaffected); R2 reports before R9.
- Runtime carry refusal lasts until the next go-to (`clear()` lifts it).
- Pass G no-consumption = settled position + exact host/JSON auto-run kinds; pixel half n/a without click builds. Pass G runs inside `run_gates.sh` (full tier).
- Reviews on GPT-6 Astra (high) while the owner's banked resets last (`codex exec -m gpt-6-astra -c model_reasoning_effort=high …`).
- Bridge rubber-band: fix MAIN too ("(b) fix it properly"); new Keynote player accepted on a byte-level argument (no re-export of old fixtures).
- Pin hold accepted: a pinned movie paints above authored content during its move (as bridges do).
- DeckLink field test POSTPONED to next week.

## Findings (owner-raised; symptom / expected / cause / evidence)
1. **Pins go dark during the move (S2 only).** Symptom: a pinned movie shows Keynote's poster (frame 0) for the whole Magic
   Move (~1.8 s, 108 frames), then reappears ~1.8 s ahead. Seen after `g 3` + advance on D1 in OBS; headless the same, and
   **D2/D3/D5 SEQUENTIAL pins too**. Expected: carried decoder painted throughout. Cause: `keepThroughBridge`
   (`live_continuity_js.py:1045-1049`) and `markTransition` (:781-784) hoist only `bridge` entries; a pooled/re-homed pin is
   remounted into the SOURCE slide's poster layer, which the player holds at opacity 0 during the WebGL move.
   **False green:** the probe sampler/scorer and the core's `isCompositing` (:1224) ignore ANCESTOR opacity, so Phase A's
   18/18 passed with dark pins. Prototype `pinhold` (stage-level hold for a pin's transition scene; variant core `0f086552`):
   0 gaps everywhere, positive control 108 frames. Evidence: main checkout `output/evidence/s2-dev/pingap/` (`SUMMARY.txt`,
   traces), `output/evidence/s2-dev/tools-2026-10-10/pingap/fixes.py`.
2. **Bridge "rubber band" (MAIN and S2).** Symptom: a second, frozen copy diverges from the carried movie during every bridge
   (OBS; reproduces headless). Expected: one copy. Cause: the core's bridge overlay moves LINEARLY while Keynote draws the
   movie's GL poster EaseInEaseOut (cubic-bezier .42,0,.58,1, 1.5 s); nothing hides the poster. No gate compared overlay
   vs GL mid-move. Fix on main in flight (easing + carry-cover gate); later hardening: hide the carried movie's GL quad via
   `patch_player`. Evidence: `output/evidence/s2-dev/rubber/` (scripts, runs, `s2D1_sheet.png`), OBS screencast
   `output/evidence/s2-dev/q7a-goto1/screencast-mainP2/sheet-3to4.png`.
3. **Current Keynote's export refused by the dashboard** ("This player version is not supported for live controls"):
   new player `17c0c938` = old `e9b2fad4` + two `,isEvalSupported:!1` PDF.js options. Fixed on main branch (`981d6df7`).
   Copy of the new player: main checkout `output/fixtures/keynote-player-17c0c938/main.js`.
4. **OPEN — P2 2→3 Dissolve on a transparent (fill-key) page** looks wrong in OBS: slide 3 is at full strength from the first
   frame (no fade-in) and slide 2's coloured squares go grey/white then fade to black. Possibly straight-vs-premultiplied
   alpha in the stock dissolve, or a capture artefact. Owner was to compare with Keynote itself
   (`~/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key`, do not save). Not investigated yet. Evidence:
   `q7a-goto1/screencast-diss/sheet-2to3.png`. Note the P2 FIXTURE's movies are gratings but its posters are the original
   clip, so P2 is unsuitable for judging hand-overs by eye — use the D decks or a real deck.
5. Slide-3 movies start ~0.33 s AFTER the dissolve ends (owner requirement met on main).

## Gate state on S2 `867e415c` (Phase D, before the findings)
D1 run_gates 3-wide failed=0 pending=0 (45 runs incl. Pass G 7/7); D2 decks 18/18; D3 Q2 P2 main-vs-S2 fast/slow/auto 15/15
each, tables identical. **Invalidated for pins by finding 1** (instrument blind to ancestor opacity). D4 (G2 seam), D5
(loop), Q6 (managed OBS), Q7b (dashboard eyeball) NOT run. Drivers: main checkout `output/evidence/s2-dev/tools-2026-10-10/phaseD.sh` / `phaseD45.sh` (paths inside point at the old gate worktrees — re-pin).

## Next steps, in order
1. **Main PR** (`claude/main-bridge-easing`): wait for the carry-cover gate implementer; full suites (pytest, test:ui,
   test:maps); Astra review; gates: carry-cover red (`--core-variant linear-bridge`) / null (hidden overlay) / green, full
   `run_gates.sh` 3-wide, and a deck round on the fresh `Minimal Alpha_DSK` export (new player). Push, open PR; owner merges.
2. **S2:** merge main in; implement the pin hold in core v6 (from `tools-2026-10-10/pingap/fixes.py`, own note kind e.g. `pin-hold-start`);
   port the easing to v6; instrument: `painted` = ancestor opacity product + not hidden + rect + readyState, sampled
   pre-paint (ResizeObserver per rAF); zero-tolerance in `score_continuity`; Pass G advance legs scored per frame with
   plan-derived "go-to source, advance across" cases; `isCompositing` walks ancestors; red control = unmodified core
   (D1 [1,3,4], D5 sequential ≈108 frames), positive control = injected N hidden frames; carry-cover gate on S2.
   Reproduce-first tests, full suites, Astra review.
3. **Re-run Phases A–D** on the final S2 head, then Q6 (managed OBS 25/30 + KBs; soak 4 min) and Q7 with the owner
   (Q7a external attach D1/D4; Q7b dashboard Keyer on D1–D5, dashboard from the S2 build).
4. Open item 4 (dissolve alpha) — investigate after the owner's Keynote comparison.

## Machine / coordination
- The owner's OBS was closed at handover. For Q7 it is launched with `--remote-debugging-port=9222`; never drive it without the owner's go.
- One heavy job at a time machine-wide (full suite, run_gates round, live headless gates). The arrow-key/presenter-keys
  session (PR #254) agreed to message before running full suites; its session has since been deleted.
- OBS page tools (read-only), in `output/evidence/s2-dev/tools-2026-10-10/`: `obs_sampler.py` (rAF DOM sampler over CDP), `obs_screencast.py`
  (CDP screencast); quitting the field tool (`q`) resets the page and drops the sampler.
- `scripts/live_fixture_session.py` is line-based (Enter advances); an arrow-key PR was spun off separately.
