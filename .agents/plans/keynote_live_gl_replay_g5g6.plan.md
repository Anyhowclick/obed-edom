# GL-replay G5 + G6 plan — probe `armed1to2`, P2 `glReplayCarry1to2`, re-qualification

Status: **rev 2 (2026-09-23)** — Fable HIGH rev 0, Opus EXTRA HIGH critique → rev 1; **owner accepted every recommended answer to the open questions (1–11) on 2026-09-23** → rev 2. Implementation in progress on `feat/gl-replay-g5g6`.
Spec: `.agents/handovers/keynote-live-continuity-2026-09-23-g5.md`. Parents: `keynote_live_gl_replay_arming.plan.md` §5, §9–§11;
the G3+G4 plan rev 3 §8 (merged with #214, removed from the tree; git history); `.agents/reviews/gl-replay-g3/gates-r3.md`. Cites at `a56474f3`.
probe = `scripts/live_continuity_probe.py`, hap = `src/obed_edom/html_alpha_probe.py`, p2v = `src/obed_edom/p2_verdict.py`,
p2s = `scripts/p2_recovery_html_adversarial.py`, G2 = `src/obed_edom/live_gl_replay_js.py`, core = `src/obed_edom/live_continuity_js.py`,
host = `src/obed_edom/live_host.py`. **No product file changes:** core, G2, host, `live_continuity.py`, `live_runtime.py` keep their
bytes and shas (`e9338aff…`, `4f8850e0…`).

## Critique table (rev 0 → rev 1)

| # | Rev-0 claim | Verdict | Evidence / change |
|---|---|---|---|
| C1 | P2 `auto` = inject the GL module | **BLOCKER** | `__OBED_CONTINUITY_INFO__` is set only by the host (host :71); G2 checks `canvas.width === INFO.authoredWidth` (G2 :1154) ⇒ `canvasShape`. §4.1 adds an auto-only INFO tag. |
| C2 | same | **BLOCKER** | `__obedLive` comes only from the host's serve-time `patch_player` (host :1028-1029); P2 serves `main.js` unmodified (hap :2939-2940); G2 ARM-POST needs `snap.ready === true` (G2 :1178-1181). §4.1 adds an auto-only serve-time patch. |
| C3 | "exactly one pooled entry" | **BLOCKER** | r3 gate 2: `2 pooled [1,2], 0 in document`. Now {carried} ∪ siblings, siblings retired at release. |
| C4 | `liveContinuity1to2` re-bound via `_merge_pool_into_media` | **BLOCKER** | Footprint-owner ids + no `presentedMediaTime` in the pool merge (p2s :1253-1290). Replaced by `carriedClock1to2` (§4.2 g). |
| C5 | Facts derived flag-on in `auto` | **BLOCKER** | `retire_fact` None on a flag-on runtime (probe :513-516), attach runs flag-off (host :866-867). Two fact sets, chosen per arm by reported mode. |
| C6 | Vgl screenshot reads LIVE unpoked | **MAJOR** | Stale-surface flake (research :178-180). New P5-0; poke + mask if needed. |
| C7 | Probe ctors inherit env | **MAJOR** | host :1004-1010. Explicit `gl_replay` in every ctor. |
| C8 | G2 `probe(rect)` + sha move | **MAJOR (not required)** | `sampleFrame(elId)` (core :183-237) gives the source counter; GL readback bundled with option (c) (OQ-4). |
| C9 | Hand-back "advance once, settle" | **MAJOR** | Explicit capture preconditions (§3.6); known-bads replaced. |
| C10 | Occluder mask by cell | **MAJOR** | GL band row 0 = bottom (G2 :539-547); explicit flip + test. |
| C11 | Edit `CARRY_CENSUS_JS`; keep-kinds for everyone | **MAJOR** | Changes off JS. Auto-only `GL_CARRY_CENSUS_JS` + auto-only keep-kinds union. |
| C12 | P2 auto writes to `OUT/` | **MAJOR** | `OUT/html-player` is the probe fixture, `OUT/report.json` copied by `run_gates.sh`. Auto writes under `OUT/gl-replay/`. |
| C13 | In-arm in-page read without pause | **MAJOR** | Unscorable (probe :1496-1500); `markerBands` flashes the poster. Arms read `stats()` only. |
| C14 | QUALIFIED_PLAN_SHA256 at p2s:3437; new parity test | **WRONG cite** | `live_continuity.py:627-632`, untouched; `tests/test_live_gl_replay_oracle_parity.py` exists. |
| C15 | P5-7 "may arm" | **corrected** | G2 one-shot (`state.down`, G2 :845-846, :1167-1168); `cleared` never re-arms ⇒ no `glreplay-live`, page == flag-off twin. |

## 0. Preconditions

- Freeze-control re-bracket merged (#187 `06014901`; `_score_freeze_control` p2v :2836).
- Go-to autoplay #203 `10e80e4f` is an ancestor of G-0 `9ad4fc69` and r3 `a9637d62`; gate 7 ran post-repair. Unmeasured: goTo 1 from 3, then advance to 2 (P5-7).
- OD-2 unchanged (attach ⇒ `unavailable`, host :866-867). OD-3 docs at G6 re-qualification (g3g4 :300, §7).
- G6-0 (blocking G6): P2's served `assets/player/main.js` sha == `live_runtime.PLAYER_SHA256`, else stop and ask the owner.

## 1. Facts relied on

| # | Fact | Source |
|---|---|---|
| F1 | Probe `ground_truth_plan` derives the flag-OFF plan; host `auto` derives `gl_replay=True` and injects G2 only when a `glReplay` boundary exists. | probe :476-480; host :864-880 |
| F2 | `retire_fact` matches only `action == "retire"`; on a flag-on runtime `rect_expectations` else-branch ⇒ LIVE when continuity on. | probe :513-516, :587 |
| F3 | Two-oracle record wired and inert without a handle; golden test pins it. | probe :317-408, :1462-1558, :1783-1806; hap :2164 |
| F4 | `__OBED_GL_ORACLE__` exists only in LIVE, deleted at stand-down; `glreplay-live` at publish; r3 settle→hash 97.8 ms. | G2 :928-961, :908 |
| F5 | Any GL call on the armed context outside `state.replaying` while LIVE/ARM-POST ⇒ `unflaggedPlayerCall`. No read may touch `handle.gl`. | G2 :284-288 |
| F6 | `toBuffer` flips y; `bandsOf` row 0 = bottom of the instance rect; backing store is authored size. | G2 :512-519, :539-547, :1150-1155 |
| F7 | rAF sampler lists `document` videos only; core `snapshot()` lists pooled decoders (`elId/currentTime/paused/readyState/inDocument`, `fromDom`), no carried stamp. | probe :284, :226-233; core :145-180 |
| F8 | Any gated boundary None ⇒ inconclusive; retired boundary needs its `refused*` half. | probe :2763-2770, :2729-2750 |
| F9 | `score_refusal` RED on painting overlap or ANY pooled asset entry. | probe :1228-1259 |
| F10 | `note()` stamps `sceneHash`; seam passes G2's six kinds; `glreplay-carried {elId, delta, candidates}`; `glreplay-release {ok, mode, reason, elId, retired}`. | core :707-711, :468-469, :1841, :599-605, :669-670 |
| F11 | P2: later-injected tag lands first; `main.js` served unmodified; no `__OBED_CONTINUITY_INFO__` / `__obedLive`. | dissolve_live :391-445; hap :2939-2940; host :71, :1028 |
| F12 | `refusedCarry1to2` requires `glReplayFallback == moduleAbsent`; `neverPooledEvidence` rejects an armed zone; `preserveDidNotBlockRestart` = positive pair OR `never_pooled.ok`. | p2v :786-907, :922-958; p2s :3677-3696 |
| F13 | P2 counter decode is screenshot-only; `sampleFrame(elId)` draws pooled or DOM decoders to a ≤320-px JPEG via 2D canvas, already used by P2. | p2s :173, :865-882, :1499; core :183-237 |
| F14 | In-page latency: `mutationScanMs`, `completedMs`; research 1.7–1.8 ms. | G2 :1119, :914-915; research :184 |
| F15 | Driver test counts `"id": "…"` literals == 14. | tests/test_p2_adversarial_driver.py:576-587 |
| F16 | r3 gate 2: 2 pooled (1 carried, 2 sibling), 0 in document, oracle LIVE n=24, paused DEAD, occluded 20/128; gate 4: `release retired [2]`, hand-off `remount-into-authored-layer`, 0 `remount-done`/`-footprint-rect`. | main checkout `output/gl-replay-g3-harness/g3/r3/gates.json` |
| F17 | Unpoked CDP burst over a replayed canvas can be stale (liveFrac 0.0044 at 2560×1440; 0.805 poked). | research :178-180 |
| F18 | Without `gl_replay`, the host reads `OBED_LIVE_GL_REPLAY`. | host :1004-1010 |

Assumptions (each settled by a gate): A1 screenshot oracle reads Vgl slide 2 LIVE (unpoked or poked+masked) → P5-0. A2 armed-arm
`continue1to2` is not None (code); True/False unknown → report-only. A3 V vs Vgl parity 0 outside the mask across sessions → P5-H.
A6 P2 `main.js` == `PLAYER_SHA256` → G6-0. A7 `sampleFrame` 320-px JPEG decodes the counter ±2 → G6-0. A8 the natural
reuse-skip/retire pair fires at 2→3 in auto → first G6 auto run.

## 2. Decisions

- **D1.** `--gl-replay off|auto` on probe and P2, default off; off byte-identical (HTML, page JS, verdicts, artifact keys); `run_gates.sh` unchanged. Every probe `LiveOutputHost(...)` passes `gl_replay` explicitly.
- **D2.** Two fact sets: `facts_off` (today) and, in auto, `facts_on` from `derive_plan(..., gl_replay=True)`. Each arm/pass is scored by the set its reported `glReplay.mode` selects (`injected` ⇒ on). `overall_status` asserts expected modes: A/C/Vgl `injected`, B/Voff/V `off`, attach `unavailable`.
- **D3.** `armed1to2` gated in armed A/C; `continue1to2` report-only there; attach keeps `refused1to2`; B unchanged.
- **D4.** No G2/core change. P2 counter = source (`sampleFrame(carried elId)`) + composite (screenshot). GL readback deferred to option (c) (OQ-4).
- **D5.** Stand-down latency report-only; 50 ms literal dropped.
- **D6.** Probe hand-back = ONE post-build-1 capture per pass (V, Vgl) outside a mask; ring parity stays with the harness.

## 3. G5 — probe

**3.1 CLI/ctors.** `parse_args` (:423-448): `--gl-replay {off,auto}` (default off), `--gl-force-fail REASON` (requires auto). Every
ctor passes `gl_replay` (:1295, :1387, :1958, :2413); attach passes `auto` in auto to prove `unavailable`.

**3.2 Facts.** `ground_truth_plan(export_root, slides, *, gl_replay=False)`. `armed_fact(plan, runtime, boundary_keys)` fail-closed
(`SystemExit`) unless exactly one `glReplay` boundary; returns `{movieKey, atScene, boundaryKey, verdictKey: "armed1to2", playerIndex,
originalOrdinal, assetKeys, rects, instanceId, instanceRect, movieSlot, slotRects, overrideSlots}`. `ARMED_VERDICT_KEY`. `armed` /
`armedBoundaries` added only for the flag-on plan (off key set unchanged). Explicit `glReplay` branch in `rect_expectations`, same output as the else-branch.

**3.3 `boundary_observer` + `score_armed`.** At settled slide 2, two reads ≥500 ms apart: `refusal_evidence` + `__OBED_GL_REPLAY__`
`{state, standDowns, events, stats()}` — no in-page oracle, no `markerBands`, no pause in arms. `score_armed` True iff all (missing ⇒ False, never None):
1. mode `injected`, version/sha pinned;
2. both reads `state == "LIVE"`, `standDowns == []`, `loopMode == "rvfc"`, `glErrors == 0`, same `epoch`, `iter`/`uploads` strictly increasing;
3. one `glreplay-arm` (`#atScene−1`), one `glreplay-live` (sceneHash ≥ `#atScene−1`, OQ-6), no standdown/handoff yet, zone `[pending→armed moduleReady]`, one `glreplay-carried` delta ≤ 0.02;
4. zero painting `<video>`s over `armed.rects`;
5. pool movie1 = {carried} ∪ siblings, all `inDocument` false, no `fromDom`; carried `paused` false, `readyState ≥ 2`, `currentTime` rising Δwall × [0.75, 1.25].

`score_refusals` → `score_positive_halves`. Armed boundary requires `armed1to2 is True`; `overall_status` drops `continue1to2` from gating and the None check for armed A/C.

**3.4 Vgl (auto).** Third pass `gl_replay="auto"` against `rect_expectations(plan_on, …)`; assert it differs from V only at (slide 2,
movie1). Slide 2 needs in-page `ok` with paused DEAD; both oracles LIVE; disagreement fails; zero painting `<video>`s. Poke per P5-0;
if on, the (0,0) poke pixel is masked from parity. Finding-2 green restated as positive; `BLACK_BEHIND_ROI` not retuned.

**3.5 Occluded cells.** `hap.score_live_coverage(..., occluded_cells=None)`; None = today's bytes; with a mask, band means over
non-occluded cells, fully-occluded bands excluded. Same-epoch mask, `screen_row = ROWS−1−gl_row`. Scored unmasked (report-only) and masked (gating, OQ-9).

**3.6 Hand-back (auto, V and Vgl).** After slide 2: one `execute("advance")`; poll ≤5 s for hash `#atScene+1`, `__obedLive.snapshot().ready`,
`!observe().busy`, and (Vgl) `glreplay-handoff` + `glreplay-release{mode:'handoff'}`; 2 rAF; capture screenshot, `PAINTING_VIDEOS_JS`,
`PRESERVE_SNAPSHOT_JS`, notes. Early or past-hash capture ⇒ inconclusive. `score_handback`: max|Δ| == 0 outside `toScreen(instanceRect ∪
movieSlot ∪ override slots ∪ green slot)` dilated 2 px (∪ poke); Vgl one painting movie1 `<video>` at `toScreen(instanceRect)` ±0.5 px with
elId == carried; `release.retired` == pooled − carried; zero `remount-done`/`-footprint-rect` for carried or its facade.

**3.7 Latency** report-only: `stats().mutationScanMs`, hand-off `completedMs`.

**3.8 Forced fail** (auto only; runs V + Vgl-forced only). Context manager prepends `<script id="probe-force-fail">window.__OBED_GL_REPLAY__={debugForceFail:R};</script>`
to `live_host_module.gl_replay_script`, asserts one seed + one `script#obed-gl-replay`, restores in `finally`. Artifact stamped
`glReplay.forcedFail`; status `forced-ok|forced-fail`, never `pass`; `run_gates.sh` never passes it. Scored with `facts_off`, must equal V:
slide 2 DEAD, `refused1to2` True, zone `…→retired failure/R` (or `moduleRetired`), no `glreplay-live`, parity 0. Reasons:
`planUnreadable`, `rvfcUnavailable`, `posterAmbiguous`, `occlusionTooHigh`.

**3.9 Tests.** `TestArmedFact`, `TestFactsPerArm`, `TestRectExpectationModel`, `TestArmedScoring` (each clause RED alone; 2-pooled GREEN),
`TestHandbackScoring`, `TestOccludedCells` (`tests/test_html_alpha_probe.py`), `TestGlReplayCli`, `TestForcedFailSplice`. Golden test and
`tests/test_live_gl_replay_oracle_parity.py` unedited.

## 4. G6 — P2

**4.1 Script (auto only; off unchanged).** `--gl-replay` via `_arg_value` (:847-855); auto outputs under `OUT/gl-replay/`. Injection
calls in order: `data-obed-p2-gl-replay="1"` (G2 body, `</script` escaped), `data-obed-p2-gl-info="1"`
(`__OBED_CONTINUITY_INFO__={authoredWidth, authoredHeight, viewportWidth, viewportHeight, installed:true}`), `inject_preserve`,
`inject_continuity_plan` ⇒ served plan < core < INFO < GL < … < main.js, asserted at boot. Handler serves `main.js` via
`live_runtime.patch_player` (disk untouched), asserts `__obedLive`. `gl-replay-inject.json` records G2 sha, patched `main.js` sha,
served order. Keep kinds = `PRESERVE_EVENT_KEEP_KINDS ∪ GL_REPLAY_KEEP_KINDS` in auto only. New auto reads: `GL_CARRY_CENSUS_JS` (split
at hand-off `t`, carried + facade), `__OBED_GL_REPLAY__` state at slide 2 and after build 1, ≥3 pool census reads in `[#2,#3)` ≥300 ms
apart, ≥3 `sampleFrame(carriedElId)` reads.

**4.2 `glReplayCarry1to2`** (p2v, beside :786). True iff all:
- (a) movie1 `glReplay` entry at `SLIDE2_MIN_HASH`, `fallback == "retire"`;
- (b) zone `[pending→armed moduleReady, armed→released handoff]`; one arm (#1), live, carried (delta ≤ 0.02), release `{mode:'handoff'}` with `retired` == pooled − carried; zero `preserve-refused`/`retire-boundary` for movie1 in `[#2,#3)`;
- (c) zero carry kinds before hand-off `t`; after: one `remount-into-authored-layer` for carried, zero `remount-done`/`-footprint-rect`;
- (d) every pool read: movie1 = {carried} ∪ siblings, `inDocument` false, no `fromDom`; carried unpaused, `readyState ≥ 2`;
- (e) `lingering_on_slide2.paintingCount == 0` (p2s :3089-3092);
- (f) `progressingIndexAfterFlip`: ≥4 decoded screenshot reads after flip, deltas mod 256 in [0,64), sum > 0; `sampleFrame` counters progress the same way; agreement report-only;
- (g) `carriedClock1to2`: pre-flip footprint owner == carried elId; carried `currentTime` strictly increasing, Δct/Δwall ∈ [0.75, 1.25] (`liveContinuity1to2` kept non-gating);
- (h) after build 1 `standDowns == ["canvasRemoved"]`, `state == "RETIRED"`; valid forward 1→2 hash; no `player-build-error`.

Finding slot 5: two `"id":` literals (`refusedCarry1to2` off / `glReplayCarry1to2` auto); driver test asserts ids by name, one 1→2 finding per run.

**4.3 `preserveDidNotBlockRestart`.** Unchanged off. In auto the first run records whether the natural pair fires (A8); only if not,
add `pooledNeverMountedEvidence` (beside :922), OR-ed in auto only.

**4.4 Tests.** Each clause RED alone, 2-pooled GREEN; `progressingIndexAfterFlip` wrap/null runs; `carriedClock1to2` sibling-clock
defence; keep-kinds off list unchanged, auto union covered; driver off index sha unchanged, auto order, INFO only in auto, `main.js` disk unchanged.

## 5. Flag-off contract

`run_gates.sh` host ×3 + P2 ×3 == G-0′. Probe off artifact: same key sets. P2 off: `OUT/html-player/index.html` sha,
`continuity-plan-inject.json`, `preserve-inject.json`, kept-kinds JS, `CARRY_CENSUS_JS` bytes unchanged; no `OUT/gl-replay/`. Product
files untouched (shas printed start and end).

## 6. Gates

Every new check shown RED on its known-bad and 0 control-vs-control before it counts. ≤3 headless Chromes; `run_gates.sh`, go-to runs
and P2 run alone; `pgrep -f headless=new` empty before each batch.

| Gate | Pass | Known-bad / control |
|---|---|---|
| G-0′ | `run_gates.sh` on `a56474f3` recorded | — |
| **G-OFF (blocking)** | branch == G-0′; §5 byte checks | — |
| G6-0 | A6, A7 | — |
| P5-0 | Vgl 2560×1440 n=2 poke off/on vs in-page | picks poke setting |
| P5-A ×3 viewports | A/C `armed1to2`; attach `unavailable` + `refused1to2`; B unchanged; Vgl slide 2 both LIVE, paused DEAD, mask 20/128, 0 painting; V/Voff == G-0′ | Vgl vs `facts_off` ⇒ RED; r3 forced shape ⇒ RED; two Vgl runs identical |
| P5-H | §3.6 at 3 viewports | V-as-Vgl ⇒ RED; 1-px poke outside ⇒ RED; undilated mask ⇒ RED; V vs V = 0 |
| P5-F | 4 reasons `forced-ok` | unknown reason ⇒ `forced-fail`; r3 `fail:` cross-check |
| P5-7 | show → goTo 3 → goTo 1 → advance 2: no `glreplay-live`, `retired cleared`, slide 2 == off twin | scored with `facts_on` ⇒ RED |
| P5-L | latency recorded | — |
| G6-P2 fast/slow/no-bridge | `glReplayCarry1to2` True (fast, slow); no-bridge False only on `continueThroughMovingMagicMove3to4`; others == off | GL tag removed ⇒ False (b); INFO removed ⇒ False (`canvasShape`); `posterAmbiguous` seed ⇒ False (b,f,g); off run scored by it ⇒ False |
| Re-qualification | all of the above + full suites | `.agents/reviews/gl-replay-g5g6/gates-r1.md` |

## 7. OD-3 docs (after re-qualification)

README after Qualification (:112-116): `OBED_LIVE_GL_REPLAY=auto|off` (default off); `continuity.glReplay.mode` values; attach ⇒
`unavailable`; `notCarried` still lists 1→2 (OQ-7); running probe/P2 with `--gl-replay auto`.

## 8. Work split and order

| Stream | Owns | Forbidden |
|---|---|---|
| **P probe** | probe, hap (`score_live_coverage` kwarg only), `tests/test_live_continuity_probe.py`, `tests/test_html_alpha_probe.py` | other src, p2*, G2, core, host, README |
| **Q P2** | p2v, p2s, `tests/test_p2_adversarial*.py`, `tests/test_p2_adversarial_driver.py`, README (last commit) | probe, hap, G2, core, host; `live_runtime.py`, dissolve_live import-only |
| **C gates** | `output/gates-g5g6/**`, pinned detached worktrees | src/tests/scripts (run only) |

Order: C runs G-0′ + G6-0 → P ∥ Q → Q's first auto run settles A8 → G-OFF → P5-0 → P5/G6 gates → Codex (GPT-5.6 Sol) → fixes →
re-gate → README → full suites → PR (no merge without the owner).

## 9. Risks

R1 A1 fails even poked ⇒ in-page-gated, screenshot report-only (owner call; weakens D-c). R2 A6 fails ⇒ new player sha in
`live_runtime` or drive P2 checks through `LiveOutputHost`. R3 Vgl in-page `pause()` shifts the carried clock before hand-back (masked,
recorded). R4 `_trigger_advance` fallback keys (dissolve_live :558+) could step past build 1 ⇒ inconclusive. R5 option (c) moves G2's sha;
GL counter readback goes there.

## Owner decisions (2026-09-23: all as recommended)

1. One PR, P and Q as separate commits.
2. `armedBoundaries` only in auto.
3. Latency report-only; propose p95 `completedMs` + 5 ms after 3 viewports × 2 runs.
4. Defer G2 GL readback to option (c); use `sampleFrame` + screenshot (departs from arming §5 — needs sign-off).
5. Probe keeps `refused1to2` when off: yes.
6. Accept `glreplay-live` at `#atScene−1` if the hash reaches `#atScene` with no stand-down (amends arming §5).
7. `notCarried` keeps listing 1→2 in v1, documented.
8. OBS attach out of scope (OD-2).
9. Occluder exclusion gating; drop if P5-0 shows unmasked passes at all 3 viewports.
10. Allow `--burst-poke` with the poke pixel masked if A1 fails unpoked.
11. Allow P2 auto to serve `patch_player(main.js)` (needed to arm at all).

OQ-11 note: `patch_player` is sha-pinned (`live_runtime.py:94-99`), the same gate the product host uses; a Keynote player change stops G6 at G6-0 exactly as it stops live output. Flag-off P2 is unaffected.

## Rev 2 amendments (owner decisions during implementation, 2026-09-23)
- **loopMode clause dropped** (probe `armed1to2` and P2 `glLiveOnSlide2`): G2's rAF watchdog flips `loopMode` to `'raf'` whenever 2 rAF ticks pass without a video frame (G2 ~:1027-1066), measured 11–21/150 `'raf'` reads while uploads ran at 30/s. Kept: LIVE, empty stand-downs, zero GL errors, same epoch, `iter`/`uploads` strictly increasing.
- **P2 auto Chrome keeps WebGL** (root cause of gates r1 G6 failure: `--disable-gpu` ⇒ no WebGL ⇒ player's non-GL path ⇒ G2 never arms).
- **3→4 owner coverage report-only in P2 auto only** (`owner_coverage_report_only`): P2's owner query lags the product's motion start (Codex Astra M). Identity, competitors, ambiguity, crossing identity and rVFC clock still gate. Stop-gap; **reverted** by the P2 harness fix (below).
- **One PR:** G5+G6 ships together with the P2 harness-fix work (key-code input, 3→4 query geometry, B-arm tail race, timing re-qualification) from the session "Fix P2 harness input and 3→4 query timing", which builds on this branch and reverts the stop-gap.
- ~~Known limit: P2's page goes hidden after the first CDP key event.~~ Resolved by the P2 harness fix (below).
- **Clause (c) as measured:** after the hand-off the zone is `released` (pin) and builds #3–#5 re-place the carried decoder in its authored layer again. Gated: exactly one carried-decoder `remount-into-authored-layer` at the hand-off scene, and zero `remount-done`/`remount-footprint-rect` for the carried decoder or its facade anywhere after. Later authored-layer placements are report-only.
- **Probe `owner` clause:** unresolved (`None`) pre-flip owner reads are ignored; ≥1 resolved owner is required and every resolved owner must equal the carried id (mirrors P2 `carriedClock1to2`).
- **P2 auto facts:** the WebGL availability probe runs on about:blank (a context made in the player page during ARM-PRE would be taken as the player's and stand G2 down); auto works on a private copy of the reused export; focus emulation is not used (it only masked the key-code defect; see P2 harness fix).
- **Reviewer for this session:** Codex GPT-6 Astra, high effort (owner, 2026-09-23).

## P2 harness fix (2026-09-23, folded into this PR)
- **Key input:** `p2_alpha_spike.ChromeCdp.key` no longer sends `nativeVirtualKeyCode` (as `live_host`). A/B on this fixture, one run per arm: native + focus emulation hung at #4 (CDP timeout); safe keys stayed `visible` with rAF running, drained 24/24 keys, with and without focus emulation.
- **3→4 owner query:** the capture collector starts its modelled R3→R4 move at the bound decoder's `__obedMotion.started`, accepted only for boundary `atScene` 8, the decoder's current generation, a finite stamp at or after the trusted advance keydown and not in the future (fallback: hash ≥ 8; `collector.flipVia` reports which). Measured: the stamp lands ~103 ms after the keydown in every arm, on the carried decoder only. GPU-on/replay-off, 4 captures: motion started ~1.7 s before #8, all ~126 modelled-null rows were owned at the measured rect, and the motion-started model vs measured rect had IoU ≥ 0.973 throughout.
- **Collector tail:** two frames (1 s timeout) before the dump, so the last capture is bracketed (B-arm sample 101).
- **Paint:** a video on a `document.hidden` page classifies `page-hidden` (records predating the field default it to false). A hidden page in a scored competitor sample is inadmissible: `visibleCompetitors` fails (`pageHidden` counts the samples).
- **Stop-gap reverted:** `owner_coverage_report_only` removed; `stableSlide4Owner` coverage gates in auto again.
- **Re-qualification** (fast profile, one Chrome, machine quiet; 3× flag-off, 3× `--gl-replay auto`): 6/6 `success`, freeze control `pass` 6/6, thresholds unchanged. Measured vs limit: max rAF gap 33.4–33.9 ms (≤ 100); trigger 7 rAFs (≤ 9) / 128.7–139.5 ms (≤ 190); frozen run 21–26 (≥ 6); rVFC advance ≥ 4.97 s (≥ 0.5); after-window null-owner run 0 in every arm (was 26–28); unbracketed 0; `flipVia` = motion in every arm.

## Review log (raw reviewer output not kept; conclusions only)
- Codex GPT-5.6 Sol r1 (70f22cf1): 2 BLOCKER (armed1to2 wrong sibling; P2 slide-2 LIVE ungated), 5 MAJOR, 3 MINOR — all fixed in bfaeffae.
- Astra M investigation (3→4 GPU-on): P2 owner query lags the product's motion start (#7 vs #8) ⇒ owner-coverage stop-gap; G2 already RETIRED.
- Astra H investigation (visible-page hang): P2 sends Windows key codes as macOS `nativeVirtualKeyCode` ⇒ hidden page / hang; host unaffected ⇒ P2 timing verdicts are screenshot-driven. Fixed by the harness-fix branch folded into this PR.
- Astra H r2 (d43de548): 0 BLOCKER, 1 MAJOR (forced-ok on invalid V reference), 5 MINOR — fixed in the following commit.
- Astra H r3 (fc5e79b0, harness fix): 0 BLOCKER, 1 MAJOR (hidden page skipped competitors, RED→GREEN), 3 MINOR (motion stamp not bound to the carried decoder; collector-tail timeout and driver ordering untested; `_derived_paint` docstring) — fixed in the following commit.
- Astra H r4 (04106ec9): all r3 findings closed; 2 MINOR doc wording fixes (README attach mode, gate-record player sha) applied.
