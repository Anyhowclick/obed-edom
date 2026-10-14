# Handover: Stage B implementation, paused after review r1 (2026-10-13, late)

Read first, with `keynote-live-continuity-2026-10-13.md` (overall state) and the plan
`.agents/plans/keynote_live_continuity_stage_b.plan.md` (rev 3.5, approved: every OQ per rec; plan critique closed after
Astra high r1–r3). Owner paused for the night after one review round; resume in the S2 follow-ups session (owner: "this
session" orchestrates B).

## Update 2026-10-14: review loop closed (r1–r9)
- Commits: r1 fold `9bf912b6`, r2 `51ee3be2`, r3 `c047e271`, r4 `3ee6f7f9`, r5 `51749efc`, r6 `b1264033`, r7 `060818da`, r8 `2f418b8b`. Reviews r1–r9 in `.agents/reviews/stage-b/` (Opus 5.5 high, one resumed reviewer). Owner session override: mediums/lows folded through r5; r6+ major/blocker only. **r9: 0 blocker, 0 major.**
- Not folded (low, carried from r7): (1) revert the paint sampler to the rAF `ts` for byte identity with S3 (equal by spec, unmeasured); (2) frames skipped at move start under the `readyState < 2` exemption are still paint-scored — raise with the owner if Phase 0 shows it.
- WS-F interfaces frozen in plan §4 ("WS-F interfaces frozen after review r1": binding source `window.__OBED_CONTINUITY__`, keyword-only builder, page API, writable object, decoder re-resolution, call-time seam lookup, instrument install order via host `pre_navigation_scripts`, variants API).
- `ALPHA_DSK_PLAN_SHA256` re-pinned to the repaired full fixture `c9e54655…` (new `tests/fixtures/live_continuity/alpha_dsk_repaired_full/`, excluded from runtime censuses). Core sha `6c687c47…`.
- **Provisional constants awaiting Phase 0 re-bank** with the new instrument: `ALPHA_POSTER_FLOOR` 2.5 (dSep; run2-cmp used the experiment's fixed-centre reference and cannot register it), hold margins, `MAX_INTER_FEED_GAP_MS` 50. Phase 0 also records `callbackCostP95Ms`, `hiddenGapFrames`, `canvasLingerMs`, and compares feed gaps instrument on/off.
- Touched-file suites green at `2f418b8b` (`-n 2`); full suites not run.
- **D7/D7s authored + V4 passed (owner, 2026-10-14).** Generator `output/fixtures/qual-decks/author/gen.py` (D7/D7s + tag PNGs at their aspect; D1–D6 scripts byte-identical), base = built `Continuity/D1.key` (owner's call; sha `19130c0e…` unchanged), movies patched After Transition / play-across off (`iwa_movies.patch_movie_autoplay`). Decks `~/Desktop/Convert wall to 16x9 CGs/Continuity/built/D7{,s}.key`, exports `Continuity/D7{,s}-html` — **never under main `output/`** (a copy there broke the real-export censuses for every session; trashed). Plans: D7 `0e257092…` (@2/@4 fed bridges A+B, @6 fed pins `to: null`), D7s `3d1a0bd1…` (@2/@4 fed bridges, both flagged). WS-D still has to commit their slide JSONs under `tests/fixtures/live_continuity/qual_decks/` with plan-sha pins. Keynote osascript runs are classifier-blocked from this session; the owner runs them.
- **Phase 0:** the `bf1c093f…` export is gone with its worktree; use `7e3c9301…` (this worktree's `output/.html-preview/`) for the stall/paused-frame checks; qualification needs a fresh re-prepare of the edited deck. Loop `scratchpad/phase0/loop.sh N` (glfeed direct arm, real clock, load guard < 3); not yet run (owner gave Line Draw priority). Floors re-bank after WS-F (needs a real feed for the new instrument).
- **Phase 0 results (2026-10-14, evidence main `output/evidence/stage-b-2026-10-13/phase0/`).** (a) First-feed stall: 10 real-clock glfeed `direct` runs × Alpha 5to6/6to7/7to8 on `7e3c…`: 0 refusals, first feed 14–32 ms into the move, max gap after it 33.4 ms (one missed vsync), move rAF max 33.5 ms — the 357 ms stall did not recur; nothing over 2 frames, so nothing to bring to the owner before the contract freezes. (b) Paused-element upload (counter movie, 20 trials headless + 20 visible): `texImage2D(paused video)` = last rVFC-presented frame in 38/40, never the `currentTime` frame when they differ; 2/40 uploaded one frame newer (presented at pause before its rVFC callback), and visible 1/20 advanced one frame AFTER pause (`VideoFrame` in the same task gave the same newer frame). → No `VideoFrame` fallback (it is no better). **Open for the owner before qualification:** `holdFrame` is exact (0 tolerance) against the instrument's last rVFC target; ~1 in 20 holds may land one frame newer — measure in the real move, then bring the gate cost (instrument scope).
- **Main merged** into stage-b (`480f3297`, via the app's sync): Line Draw/mm-fade runtime changes; player True/rendering pins and detach served pins recomputed; MM-opacity-off digests unchanged (take hook intact, one call site, index 11; WS-R fixed tests that assumed it was last). Pre-existing first-pass failure found by the wider run: `tests/test_p2_adversarial_gl_replay.py::test_off_gl_arm_serves_the_hook_only_bytes` (off arm now includes the no-op take call by design) — fix the test (WS-R brief ready; held while the CEF session's live OBS passes run).
- Next: Phase 0 + CEF step (machine window, owner go), then WS-F with the frozen interfaces, WS-P, full suites, §5 Q1–Q7. D7/D7s decks still need the owner's Keynote go.

## State
| Thing | State |
|---|---|
| Branch | `claude/stage-b-implementation` in worktree `s2-followups-dsk-deck-902af1` (cut from main incl. C #264, S3 #266, T #267 + B plan docs). Local only — not pushed, no PR. Venv + `dashboard/node_modules` synced. |
| `999e32a6` | Sol-high first pass of WS-D, R, H, G (24 files). Touched files green: 3943 passed, 1 skipped (`-n 2`). Core sha `49574c94…`; host pin fixed by coordinator. **Full suites NOT run** (3.12 + 3.10 floor + `npm run test:ui`/`test:maps`). |
| WS-F (feed module `live_mm_feed_js.py`) | **Not started.** Plan: after the CEF dev-loop step. Its brief must freeze the interfaces in review r1 Medium 4 + M4 (builder signature, binding source, take hook, telemetry fields, variants API). |
| WS-P (README + SKILL docs) | Not started (after behaviour settles; Codex cannot write `.agents/` — use a scratch copy). |
| Review r1 | `.agents/reviews/stage-b/review-r1.md` (Opus 5.5 high): **1 blocker, 4 major, 5 medium, 10 low — none folded yet.** Round 1 → fold all severities. Main issue: WS-G's in-page instrument emits no reads, so no feed/hold verdict or red control can score (B1), and rows aren't scoped per move (M1). D/R/H close. |
| Phase 0 (pre-launch dev loop) | **Not run** (machine load / peer OBS qualification). ≥ 10 real-clock runs per Alpha move for the first-feed stall; GPU-Chrome check that a paused element yields the last presented frame (decides the VideoFrame fallback); `ALPHA_POSTER_FLOOR` re-score of `run2-cmp/direct` (r1 Medium 5). Harness: main checkout `output/evidence/stage-b-2026-10-13/glfeed/`. Use the edited, repaired export `bf1c093f…` (competent-margulis worktree `output/.html-preview/`) for Alpha. |
| CEF dev-loop step | Owner's conditional OBS go (load permitting). Before WS-F starts. |
| D7/D7s decks | Coordinator: extend `output/fixtures/qual-decks/author/gen.py`; owner's conditional Keynote go (load permitting); then owner's V4 eyeball. Needed before WS-G qualification. |

## Next steps (in order)
1. Fold r1: one Sol-high fix brief per stream with the reviewer's exact fix wording (G: B1, M1, M2, M3, Medium 1/2/5, probe
   lows; R: Medium 3, js lows, test 1b; H: host lows; D: R11 lift case, plan-sha test). Decide M4 + Medium 4 (freeze the F
   interfaces) first — recommend: F reads bindings from `window.__OBED_CONTINUITY__`'s served runtime, static import like G2.
2. Review r2 (Opus 5.5 high), fold; r3; from r4 only major/blocker.
3. Phase 0 + CEF step (send "need window" first), then WS-F with the frozen interfaces, then WS-P.
4. Full suites (3.12, 3.10 floor, UI, maps) before any PR; then §5 qualification Q1–Q7.

## Machine / coordination
- One heavy job machine-wide: send "need window"/"done" to peers before full suites, `run_gates`, Chrome or OBS. At pause
  time the CEF/OBS placement session was running a live managed-OBS qualification (two passes, ~45–60 min each).
- Sol implementers: `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write -C <worktree>`; they must
  not run git or full suites; use `.venv/bin/python -m pytest <files> -n 2`. Briefs: session scratchpad `impl/` (lost with
  the session — rewrite from plan §4 + this file).
- Exact-frame evidence `output/evidence/mm-freeze-2026-10-13/` and `stage-b-2026-10-13/` stay until B qualifies.
