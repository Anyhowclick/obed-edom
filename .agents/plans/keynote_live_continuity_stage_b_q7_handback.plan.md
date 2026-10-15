# Stage B Q7 round 2 — seamless hand-back (plan r3 + critique-r3 folds)

Owner decision 2026-10-15: option A (keep the GL canvas live through Keynote's post-animation linger); B is the fallback.
Planner Codex GPT-6 Astra high (r1–r3); critic Opus 5.5 high (r1–r3: 0 blockers; r1 2 major, r2 1 major, r3 1 medium + 3 low, folded below by the coordinator).
Owner answers 2026-10-15 (§7): plan approved; tolerance ≤ 2 source frames + no poster exposure; feed-off held+1 report-only; pixel-exact/lossless OBS deferred.
Evidence: owner Q7 attempt 2 (managed OBS, D7 ×3) + coordinator headless managed-OBS repro (results in `output/evidence/stage-b-2026-10-13/q7-attempt2/`).

Baseline: `51ead0a8` at `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7`. Implement on `claude/stage-b-implementation` in `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1`. The inspected runtime/core/feed/instrument files match between worktrees. Extend rev 3.5 and the frozen WS-F interfaces only as specified below.

Re-verified against the real [player main.js](</Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/D7/html-player/assets/player/main.js>), SHA-256 `17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91`, D7 JSON and repository sources linked below. Retain Stage T’s fixture findings and critique r2’s corrected log interpretation. No files changed.

**1. Feasibility spike first**

D7’s three Magic Moves have zero nested effects: `handleEffectDidComplete()` does not cause their swap. The actual path is:

`setTimeout(currentSceneDidComplete, duration + 100 ms)` → `s(advanceToNextBuild)` → `jumpToScene` → `s(jumpToScene_partThree)` → `jumpToScene_partFour` → `displayScene`.

Here `s` delays 100 ms, explaining the approximately 300 ms linger. `WaitingToJump` can extend it when destination textures are unavailable; the runtime’s additional `loadScene(B+1)` preload exists only with MM opacity enabled.

Use scratch copies of repaired D7. Run headless, then one hidden managed-OBS run covering both feed arms and opacity on/off.

| Candidate | Decision |
|---|---|
| Reuse the core’s `window.requestAnimFrame` wrapper | **Preferred spike candidate.** Give each executing callback a token recorded by the feed’s `clear` wrapper against the exact canvas/context. Once normal scheduling ends, invoke the attributed bound `fB.animate` once per rAF while admitted. |
| Narrow `fB.animate()` player patch | Use if reliable callback attribution fails. Reuses the complete draw sequence but changes player bytes and requires scratch pins to satisfy `_pinned`. |
| G2 replay machinery | Reject for this round: separate lifecycle, GL-state recording and handoff responsibilities. |
| Feed-owned recorded draw replay | Reject: duplicates complete GL-state replay, including cached uniforms. |

The player has one `requestAnimFrame(` call site, but both transition renderers and `glContentsRenderer` use `fB`. A “last cleared context” association is therefore insufficient.

The real `fB.animate()` clears and draws after `elapsed > durationMax`; `pB` delegates to `eB`, whose progress clamps to 1. Verify that repeated endpoint draws preserve the complete frame, including artwork. Do not rerun setup, advance effects or alter scene timing.

Admission and stopping:

- Admit only a continuously claimed entry in state `fed`. Held/`once` entries do not request redraw; their last textures remain intact.
- Associate callback token, canvas object, exact GL context, generation and boundary visit. Install the core wrapper when any entry is a bridge **or has `feed`**; cover non-bridge feed boundaries, including D7 b2to3. Verify that `stampGlStart()` remains harmless without bridges.
- Before every extended tick, **before any clear**, check connectivity, exact context ownership, current visit and feed viability. Never resolve ownership by canvas ID.
- Canvas detachment is the general stop. The existing pre-teardown `take(controller, scene)` hook is an earlier stop only on automatic-play jumps. Also stop on navigation/reset, context loss or any would-be stand-down condition.
- Failed extension admission must not call `standDown()`. Temporary duplicate decoder identities must end extension without triggering `onStandDown` → `posterHold` → `pause`. Normal animation-frame semantics remain unchanged.
- Own cancellation explicitly: the player never cancels its rAF, does not clear `animationRequest`, and `PB.destroy()` leaves `glRenderer`. Every D7 move uses `0-canvas`; the existing consecutive-move chain tests replacement by a different canvas object/context.

Spike pass, per continuous entry on all three D7 boundaries:

- Uploads cover the linger: the last upload occurs in the frame **immediately preceding the `closedAt` frame**, using §3’s shared frame indexing.
- Linger inter-feed gaps stay **≤`MAX_INTER_FEED_GAP_MS` = 50 ms**.
- Metadata hand-back delta is nonnegative and **≤2 source frames**, scored as defined in §3.
- No DOM-observed static-poster exposure under §4; geometry, labels and artwork order remain correct; no additional GL errors.
- In both arms, `once` retains exactly one upload per bound texture and stays paused until hand-back. No-module and non-feed behavior remain unchanged.

Choose the winning candidate from measured results. If A cannot preserve lifecycle/rendering safety or produces linger gaps above 50 ms, use the authorized **B fallback**: pause at the terminal feed and resume at swap without seeking. Record its approximately 300 ms freeze. Missing instrumentation alone does not establish that A is unsafe.

**2. Minimal implementation and contract**

Repository paths below are relative to the absolute baseline root above; links identify the re-verified sources.

| Files/functions | Change |
|---|---|
| [live_continuity_js.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/src/obed_edom/live_continuity_js.py): rAF wrapper; stage observer; `carry`, `bindFacade`, `tryRemount` | Enable bridge-or-feed callback attribution/extension if that candidate wins. Add §4’s interim sibling placement; preserve the existing final movie-layer re-home. |
| [live_mm_feed_js.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/src/obed_edom/live_mm_feed_js.py): `wrapContext`, `feedAtDraw`, `finishFrame`, `take`, `reset` | Record the executing callback token at `clear`; expose narrowly scoped association and side-effect-free final-frame admission; invalidate extension at take/reset and detachment. |
| [live_runtime.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/src/obed_edom/live_runtime.py): `patch_player` | Change only if the player-patch candidate wins. Keep extension independent of opacity and leave `patch_rendering` unchanged. |
| Existing runtime/core/feed tests and digest assertions | Update for changed behavior and bytes only. |

Freeze the additive page-hook contract after the spike: per-callback token attribution, exact canvas/context and generation/visit ownership, cancellation, and readable extension availability. An unavailable hook must prevent a passing A `handbackContinuity` result.

Preserve runtime-plan schema, binding derivation, Python `mm_feed_script()` signature, seam v1, writable APIs and dynamic seam lookups. No re-claim, re-upload or recovery after stand-down before the existing reset boundary; retained-frame claims still require usable context and bindings.

Product eligibility and `MM_FEED_MANAGED_OBS` stay unchanged until Q6 passes. Keep qualification constructor overrides. With no injected module, extension is inert. Do not modify G2 replay, broaden carry eligibility or edit `scripts/mm_opacity_probe.py`.

Pins follow actual byte changes:

- No-player-patch winner: no `SUPPORTED_PLAYERS` re-pin.
- Player-patch winner: serially recompute patched-output slots **[0] and [1] for both supported stock hashes**, on Stage B’s own branch. Stock hash keys and rendering-only slot **[2]** remain unchanged.
- Update changed core/feed digests, including both `PINNED_MM_FEED_SHA256` assertions and [detach_experiment.py’s `CORE_SHA256`](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/scripts/detach_experiment.py:76), asserted by [test_detach_experiment.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/tests/test_detach_experiment.py:156). Re-run DX evidence used to qualify the changed core; old-SHA evidence remains historical.
- Never copy the parallel main/MM-fix branch’s pins.

**3. Repair fixtures and close measurement gaps**

Stage T confirms the same S3 JSON defect, SHA-1 `7bdc0b09…`, in:

- `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D7-html`
- `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/D7/html-player`
- `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/D7/html-unmodified`

Rebuild all three from the existing Stage-T-repaired prepare/export path. Preserve original D7 separately as the refusal control; do not hand-patch a texture ID. Derive bindings from repaired served JSON and visually check TA through settled S3. D7s and Alpha currently return `json_hits == []`; recheck staged copies.

Add `preview_textures.json_hits(export_root, slides) == []` as a precondition **only for feed/qualification paths**: `managed_obs_qualify.feed_fixture_facts()` and feed staging, the probe’s feed path, and `run_gates.sh` D7/D7s staging. Check actual served bytes before deriving facts or launching the browser/OBS. Inspection failure or hits refuse with slide/leaf diagnostics; record fixture identity and JSON hashes.

In [scripts/mm_feed_instrument.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7/scripts/mm_feed_instrument.py):

- **Departure attribution:** arm decoders and pending visits before departure. `mediaEvent()` must retain the actual intercepted `pause()` before a GL serial exists; later associate it uniquely by entry, decoder, generation and visit. Ambiguity stays unreadable; never synthesize a pause from module telemetry.
- **Read window:** retain each visit through canvas removal and its first **three DOM-presented rVFC frames**, with a bounded timeout. Include the final destination and settled artwork reads. Missing completion is unreadable. **Do not change `drive_and_sample()` timing or shared dwells.**
- **Frame accounting:** `closedAt` is `document.timeline.currentTime` from the first `riderTick` seeing the canvas disconnected, not the exact removal instant. Associate uploads and rider reads with a shared browser-frame index/timestamp; do not subtract callback `performance.now()` upload stamps from `closedAt`. Use callback timestamps only for same-clock inter-feed gaps.
- **`handbackContinuity`:** independently record each entry’s last successful upload-associated rVFC `mediaTime` before removal and first rVFC-presented `mediaTime` after visible destination placement, including §4’s interim slot. Record timestamps, frame identities, delta and the DOM condition. This is a metadata proxy, not pixel-exact presentation proof.
- Require a nonnegative media-time delta. Derive source-frame duration from the movie’s readable rVFC `mediaTime` steps, round the delta to source frames, then require **≤2 source frames**: one source frame plus one metadata-slack frame. Missing or ambiguous frame duration is unreadable. Do not hard-code 30 fps or a 66.7 ms boundary.
- Score both arms; retain exact-hold checks. Feed-off’s stricter first-advancing-picture held+1 result remains **report-only pending §7**.
- Preserve 0.25/0.5/0.75 animation reads independently of extra linger draws. Re-record `framesFed`, maximum/p95 inter-feed gaps and endpoint reads. Report `canvasLingerMs` from the **last upload’s frame timestamp → `closedAt` frame timestamp**, with the frame-index gap authoritative: A requires adjacent frames, including at 25 fps.

Update `_visit_record()`, scorers, `scripts/live_evidence_contract.py`, feed-path consumers and contract tests together. Missing endpoints, attribution, DOM coverage, frame mapping or buffer completeness produce INCONCLUSIVE/INVALID, never pass.

Leave `counterFromGl` on the existing **Open** list; fixing it is outside this round and is not a prerequisite for the new metadata verdict. Its unreadable `feedLive` result remains unreadable and cannot be counted green in later qualification.

**4. Poster exposure and controls**

Use critique r2’s corrected count: **five of six hand-backs expose a static movie canvas for one frame—both movies in three; movie B only in both ctx1**. The both-movie cases are feed ctx2 and feed-off ctx2/ctx3. Feed ctx3 is clean; events 12572/12573 were +50 ms `tryRemount` retries. Movie B’s destination video can be created in a later task than A’s.

The real player’s `displayScene` creates the static movie layer, not the destination `<video>`. Movie-start proceeds through `playCurrentScene` → zero-delay `renderEffects`/`animateEffects` → `renderMovie` → `I.replaceChild(G,a)`, potentially in separate tasks per movie.

Make the minimal core-only fix:

- From a stage `MutationObserver` callback triggered by `displayScene` insertions, place **every carried decoder for the boundary** visibly at `dst.rect` before the next rAF/paint.
- Insert it as the **next sibling of the interim anchor**: the ancestor of the static movie canvas at `dst.rect` that is a direct child of the destination slide's root layer (it equals or contains `a`, the node `renderMovie` replaces via `getElementById("layer"+layerId)`, whose shape varies: `layer149<layer148<layer147`, `layer164-isPlaying<layer164<layer163`). Above its static canvas, below later authored label layers. Never place it inside `a`: do **not** reuse `tryRemount`'s `posterCanvas.parentNode.insertBefore(v, posterCanvas.nextSibling)` insertion; reuse only its measure-and-correct sizing. The existing later-label-order check catches decks that group a label with the movie.
- Perform the interim move under `beginMove` (detach-observer guard); `tryRemount` skips a decoder marked interim until `carry()` runs (departure `scheduleRemount` +50…+2000 ms and hash-change +80/+400 ms retries must not pull it out).
- Spike: confirm the location hash already names the destination scene when the `displayScene` observer callback runs; otherwise key the boundary on the take hook's scene argument.
- Do not assign interim placement to `__obedLayer` or `__obedParent`. Preserve the old matching identity so `carry()`’s synchronous remount and `bindFacade(rehomed)`’s `layer !== real.__obedLayer` check still recognize the final destination layer. Keep interim bookkeeping separate.
- Let existing `carry()`/`bindFacade(rehomed)` complete final movie-layer placement with attempt-1 z-order handling unchanged. A not-yet-carried movie's interim slot must survive `replaceChild` (the carried movie leaves it earlier: `carry()`'s synchronous `tryRemount` moves it before `replaceChild`, then `bindFacade`'s observer re-homes it in the same microtask checkpoint); later facade creation or +50 ms retries must not supply the first visible frame.
- Use `take` for early extension cancellation/preparation when it fires; destination observation and canvas detachment cover the general path.

Fold the DOM condition into `handbackContinuity`. In the **same `riderTick` that records `closedAt`**, and subsequent hand-back frames, each entry’s decoder must be connected, visible inside the stage rather than parked under `body`, have opacity product >0, and follow its static movie canvas in DOM paint order within the same stacking context. Preserve later-label order through final re-home. Missing structural evidence is unreadable; a visible static-poster exposure fails.

Do not use `elementFromPoint`; it returned the stage div. These checks detect the observed DOM exposure condition without claiming compositor pixel equivalence. Lossless OBS capture is unnecessary for this gate.

| Measurement | Passing control | Failure/unreadable control |
|---|---|---|
| Departure/exact hold | Real pause-before-context feed-off | Existing `no-pause`; missing attribution → unreadable |
| Metadata continuity | A enabled | `--feed-tamper no-linger` reproduces ≈300 ms/nine-source-frame jump; missing endpoint → unreadable |
| Poster-free DOM hand-back | Interim sibling placement before rAF, then final re-home | Core variant delays interim placement across one rAF; zero-delay twin passes |
| Fixture precondition | Repaired D7, D7s, Alpha | Original D7 refuses |

Retain existing ordinal, after-feed, hold-upload-kill, from-only and artwork controls with their registered expectations. Feed-off remains red against the explicit continuous-feed expectation. Reuse existing hold/resume verdicts; add no separate feed-off verdict.

**5. Lower-priority feed-off resume fix**

Hypothesis: `carry()` clears `__obedPosterHeld` before destination placement, allowing facade/remount playback too early or repeatedly. `presentedFrames 97→99` alone cannot distinguish a skipped source frame from a missed callback.

Measure actual pause/play order, rVFC media times/counts and visible destination placement using corrected attribution. Compare with a scratch variant that retains the hold through §4’s visible interim placement, then performs one guarded resume before paint; later movie-layer re-home must not resume again.

Adopt that minimal ordering change only if evidence improves. No backwards seek or arbitrary delay. Keep it separately reviewable from linger extension; report held+1 strictness without enforcing it until the owner answers.

**6. Disjoint streams, tests and qualification**

After the spike freezes the hook contract, use **one Codex GPT-5.6 Sol, high, per implementation stream**.

| Stream | Exclusive ownership |
|---|---|
| R — player/core | `live_runtime.py`, `live_continuity_js.py`, corresponding tests, `continuity_core_variants.py` and tests |
| F — feed lifecycle | `live_mm_feed_js.py`, its tests, `mm_feed_variants.py` and tests |
| G — measurement/harness | `mm_feed_instrument.py`, `live_continuity_probe.py`, `managed_obs_qualify.py`, `live_evidence_contract.py`, `run_gates.sh`, corresponding tests |
| Coordinator | External fixtures, `tests/fixtures/live_continuity/**`, deck expectations, documentation and final digest-only updates, including `scripts/detach_experiment.py:CORE_SHA256` |

Coordinator updates pins after stream edits stop; re-derive `D7_PLAN_SHA256`/`D7S_PLAN_SHA256` after G stops and change them only if derived plans change. Keep real exports outside main `output/`.

Minimal new automated coverage:

- One parametrized fake-GL extension test: detach, take, would-be stand-down, context loss and absent module; assert draw/upload counts, including mixed continuous/once entries and feed-only wrapper engagement. Use the existing real D7 chain for consecutive same-ID replacement; no extra revisit test.
- One fake-DOM core case in the real order `createNodes` → `setAttribute` (`carry` → synchronous `tryRemount`) → `replaceChild` → observer: the other movie stays connected in its interim slot, the carried decoder ends in G after the microtask (never left on the stage-root append), matching fields are preserved until final re-home, and label order is intact.
- One parametrized hand-back scorer test: pass, nine-frame failure, DOM exposure and unreadable evidence; cover adjacent-frame accounting at 25/30 fps and acceptance of rounded held+2.
- One pause-before-context attribution test and one original-D7 fixture-refusal test.
- Update existing patch-anchor/pin tests only as needed. Use real-player controls to validate scheduling, callback attribution and paint order.

Qualification order:

1. Repair fixtures; complete scratch headless → hidden managed-OBS spike.
2. Implement; run targeted tests and controls, including refreshed DX evidence for the changed core.
3. Headless **D7 → D7s → Alpha**, both arms, existing viewports, opacity-off/attach controls and real-clock repeats.
4. Restart owner **Q7 on repaired D7**, then D7s/Alpha and existing attach, D1 and end-of-show checks.
5. Complete outstanding Q2–Q6 and regression equality checks; defaults change only after Q6 passes.
6. Before PR, run full Python suites on **3.12 and an isolated 3.10 environment installed from `uv.lock`**, plus dashboard `test:ui` and `test:maps`. Run heavy jobs serially. Investigate existing environment/test issues only if they block required checks; do not weaken tests.

**7. Owner questions, with recommendations**

- **Metadata tolerance:** recommend a nonnegative delta of **≤2 source frames**, using rVFC-derived source-frame duration and comparison after rounding to frames. This comprises one source frame plus one metadata-slack frame; enforce the DOM poster-exposure condition separately.
- **Feed-off held+1 strictness:** recommend keeping it **report-only until answered**, while retaining readable exact-hold, no-seek and no-restart checks. Prioritize removal of the nine-frame jump.
- **Pixel-exact matching and lossless OBS capture:** recommend deferring them. Choosing them adds counter/source-frame matching, consecutive lossless capture, synchronization, decoding/storage and additional readability controls to the gate; metadata plus DOM evidence does not provide that stronger guarantee.
- **Spike winner and player pins:** recommend the no-player-patch rAF candidate if attribution and lifecycle checks pass. The measured winner determines whether `SUPPORTED_PLAYERS` re-pins: none for unchanged player bytes; slots [0]/[1], serially on Stage B, if the player patch wins.
- **If A fails its safety/cadence criteria:** recommend the already-authorized B fallback, with its measured freeze explicitly recorded.