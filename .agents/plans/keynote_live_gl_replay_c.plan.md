# GL-replay option (c) — movie into the texture's inner instance sub-rect, plus G2 readback `probe(rect)`

Status: **rev 1 (2026-09-23)**. rev 0 by the first planner (Opus EXTRA HIGH); rev 1 is the second planner's critique pass (Opus HIGH, §13). Owner accepted 2026-09-23 (§0, §11). Implementation started.
Spec: `.agents/handovers/keynote-live-continuity-2026-09-23-g5.md` "Next" item 4. Parents: `keynote_live_gl_replay_arming.plan.md` §5, §10;
`keynote_live_gl_replay_g5g6.plan.md` C8, D4, owner decision 4, R5; `.agents/reviews/gl-replay-g3/gates-r3.md`; `.agents/reviews/gl-replay-g5g6/gates-r1.md`.
Cites are at `d56fb0dd` (branch `feat/gl-replay-c`). Abbreviations: G2 = `src/obed_edom/live_gl_replay_js.py`, core = `src/obed_edom/live_continuity_js.py`,
lc = `src/obed_edom/live_continuity.py`, host = `src/obed_edom/live_host.py`, probe = `scripts/live_continuity_probe.py`,
p2s = `scripts/p2_recovery_html_adversarial.py`, p2v = `src/obed_edom/p2_verdict.py`, tG2 = `tests/test_live_gl_replay_js.py`,
g3h = main-checkout `output/gl-replay-g3-harness/g3/` (git-ignored), r3 = `g3h/r3/gates.json`.

## 0. Closed owner decisions this plan carries

- **§11 answered** (owner, 2026-09-23): OQ-1 2D canvas + `texSubImage2D` (own FBO draw rejected: "a lot of work for marginal benefit"; it stays the fallback only if the uploads/s rule trips); OQ-2 bump to 2 — **REVERSED same day: stays 1** (gates r1 stopped at gate 2: core `live_continuity_js.py:531` refuses any module version ≠ 1 with `moduleVersion`, so v2 never armed; changing the core would break the byte-identical off path; the G2 sha pin identifies the bytes); OQ-3 compute in page (0.16 px is not visible); OQ-4 P2 only; OQ-5 gate if CvC passes, else report-only; OQ-6 harness-side splices.

- **Readback probe is IN scope** (owner, 2026-09-23): G2 gains `probe(rect)` (deferred from g5g6 C8/D4/owner decision 4). §4 designs it; §8 lists its consumers and their known-bads.
- OD-2 stands: attach stays not injected (host :866-867). The OBS/CEF upload-rate gap (≈14/s in OBS vs ≈30/s headless, measured 2026-09-23) is out of scope. It belongs to the attach qualification that follows (c).
- `OBED_LIVE_GL_REPLAY` stays default `off`. The off path stays byte-identical because G2 is injected only in `auto` (host :864-880).

## 1. Problem and measured current behaviour

| # | Fact | Source |
|---|---|---|
| F1 | The player uploads a poster canvas at the movie slot's texture size (960×276, RGBA/UNSIGNED_BYTE, flipY, premultiply). G2 adopts that texture as `posterTex`. | G2 :257-268 |
| F2 | G2 writes the carried decoder with `texImage2D(TEXTURE_2D, 0, intFmt, extFmt, type, video)` (G2 :325-341). It does this per player `clear` during the move (:437-448) and per fresh rVFC tick in LIVE (:1017-1021). `texImage2D` redefines level 0 at the video's 1920×540, and the test fake pins that redefinition. | G2 :335; tG2 :2474-2484 |
| F3 | The replayed movie draw maps the whole texture onto `slotRects[3]` = (105.123, 790.847, 960, 276). The DOM video is `instanceRect` = (109.35, 795.04, 951.54, 267.62), inset by ≈4.2 px on each side. | tG2 :62-79 |
| F4 | The export's movie node is a 956.54×272.62 layer. It holds a hidden 960×276 poster layer (textureType 5), the 951.54×267.62 video layer, and a 960×276 textureType-8 layer ABOVE the video (the frame). Relative to the frame layer (authored top-left 105.000, 791.000), the video sits at (4.352, 4.036). The export's source is a 1920×540 HEVC movie; the gate fixture `html-player` (and `html-disposable`) serves the 1920×540 H.264 counter movie (sha `8b205876…`) in its place. | `html-unmodified/assets/0C652BEB…/…json` events[2] `renderMovie`; `mdls` of both `Untitled.mov` copies |
| F5 | This stretches the video by +0.89 % in x and +3.13 % in y (aspect 3.478 against 3.556, the "~2 %"). It also covers the frame while LIVE. | arithmetic on F3, F4 |
| F6 | At build 1 the core hands the decoder to the DOM at `toScreen(GL.instanceRect)` (core :681-689). The edge moves 105/791 → 106/792 and 3–4 px of frame reappear. | gates-r3 "Build-1 move" |
| F7 | The existing instrument already measures the defect. The report-only `T-ring at P2c` (ring = slot − instance dilated 1 px − slot 4, armed vs control) reads **max 251 / fracOver8 0.767** (armed), **251 / 0.742** (armed-2) and **245 / 0.77** (armed-lb). The same ring after the hand-off reads 0 (P3/P4/T4/T5). | r3; g3h `analyse_g3.py` :189-201, :398-402 |
| F8 | The player is WebGL1. `main.js` calls only `getContext("webgl")` / `("experimental-webgl")`, with no attributes (so `preserveDrawingBuffer` false, `alpha` true), and there is no `blitFramebuffer`. It never calls `getError`, never sets `UNPACK_COLORSPACE_CONVERSION_WEBGL`, clears with `clearColor(0,0,0,0)`, and sets `TEXTURE_MIN_FILTER` `LINEAR`. | fixture `main.js` grep |
| F9 | The G2 sha is pinned in exactly one place, tG2 :140 (`4f8850e0…`). Host, probe and P2 read `js_sha256()` / `GL_REPLAY_VERSION` dynamically. P2 `_gl_boot_ok` (p2s :651) compares the **page's** `API.version` with the Python `GL_REPLAY_VERSION`. | host :963-970; probe :1635; p2s :485, :651, :3288-3289; grep |
| F10 | Between `d3fe55d9` (gates-g5g6 r3) and `d56fb0dd`, `src/obed_edom/live_*`, p2v and `html_alpha_probe.py` differ only in comments and docstrings, and `scripts/` does not differ at all. `GL_REPLAY_JS` sha `4f8850e0…` and core `e9338aff…` were recomputed today. | `git diff d3fe55d9 d56fb0dd` |
| F11 | Two existing tests pin contracts (c) changes: `tests/test_live_gl_replay_oracle_parity.py` `run_probe_js_in_node` (:356-360) fails on any published handle field missing from `HANDLE_FIELD_JS` (:259-274), and `tests/test_p2_adversarial_gl_replay.py` :568-572 asserts that no P2 read JS mentions `__OBED_GL_ORACLE__` (g5g6 rule "no in-page oracle in arms"). | grep |

## 2. Geometry of the inner sub-rect

**Inputs.** All inputs are already in the runtime entry, validated at G2 :92-124 and :1235-1300:
- `S = slotRects[movieSlot]` is authored px from the transition effect's geometry (lc :570-577, :614-615).
- `T = slotSizes[movieSlot]` is in texels.
- `I = instanceRect` is authored px: the movie layer plus the video sub-layer's relative rect (lc :1101-1127), bound by `_destination_instance` (lc :884-905) into the entry (lc :811-820).

**Mapping.** `sx = T.w/S.w`, `sy = T.h/S.h`. Then:
- `x0 = R((I.x−S.x)·sx)` and `x1 = R((I.x+I.w−S.x)·sx)`;
- `y0` and `y1` follow the same pattern in y;
- everything is clamped to `[0, T.w] × [0, T.h]`;
- `inner = {x: x0, y: y0, w: x1−x0, h: y1−y0}` in top-down texel coordinates.

`R` is round-half-up: JS `Math.round`, and Python `math.floor(v + 0.5)`. Python's `round` must not be used because it rounds half to even and would break parity. Rounding both edges to nearest (rather than origin plus size) keeps each edge within 0.5 texel of the authored edge.

**Fixture.** The unrounded edges are (4.2268, 955.7668, 4.1931, 271.8131), which gives `inner = {4, 4, 952, 268}` at scale 1. The margins are L 4.227, R 4.233, T 4.193 and B 4.187 px. The DOM layer tree (F4, offset 4.352/4.036) rounds to the same rect, so the plan fields and the export agree to 0.16 px.

**GL rows.** The poster signature requires `UNPACK_FLIP_Y` true (G2 :263-264), so texture row 0 is the poster's bottom row. The sub-upload therefore uses `yoffset = T.h − y1` (= 4) with the poster's own unpack flags. Under the same flip rule, the inner canvas lands upright.

**Residual against the DOM target.** The GL-drawn video spans authored x 109.12–1061.12 and y 794.85–1062.85. The DOM `instanceRect` spans 109.35–1060.89 and 795.04–1062.66, so every edge is within 0.23 px. The aspect is 952/268 = 3.552, against 3.556 for both the video and the DOM rect (0.1 %, previously 2.2 %).

**DPR and viewport.** Neither enters.
- The backing store is authored size at every viewport; `canvasShape` asserts this at G2 :1152-1156.
- The inner rect is in texels.
- CSS scales the canvas with the same stage map that `toScreen` (core :346-350) applies to the hand-off target.
- So the GL-drawn video and the DOM video coincide up to the residual × `s`, which is ≤ 0.31 screen px at 2560×1440.
- **Filter footprint.** The poster texture is sampled `LINEAR` (F8) and the canvas is CSS-scaled bilinearly, so each inner edge bleeds up to ≈ 15 % video into the adjacent canvas pixel, and that pixel reaches up to 3 screen px at 2560 (e.g. authored row 794 → screen rows 1058–1060, where `toScreen(I).y − 1` = 1059.05). Every ring check therefore dilates the instance by **2** screen px at non-1920 viewports (`HANDBACK_DILATE_PX`); 1 px is enough only at scale ≤ 1 (checked for 1920 and 1600×1000).

**Containment (fail closed).** Every margin `I − S` must be ≥ −0.5 authored px, the same lower bound as core `handbackRectOk` (core :613). `inner.w` and `inner.h` must each be ≥ 1 texel. Otherwise the entry is invalid: the page refuses it with `planUnreadable`, and `validate_gl_replay_entry` returns None, so the host reports "GL replay entry is not usable" (host :876-878). No upper bound is added: the core's ≤ 8 px bound remains the core's hand-back rule.

**Hand-off, guard G and the stash rule are unchanged.** (c) changes only the texels G2 writes into `posterTex`. Everything else is untouched:
- the pooled, never-mounted decoder;
- the armed hold in `swallowClear` (core :1671-1686, note `glreplay-hold`);
- stash on the move scene;
- `release(movieKey, {rect: slotRect})` (G2 :911), which `handbackRectOk` accepts (core :608-619);
- the remount at `toScreen(GL.instanceRect)` (core :681-689).

At `canvasRemoved`, `restorePoster()` (G2 :887) writes the full poster into a context whose canvas has already left the DOM. The only visible effect of (c) is that LIVE geometry now equals hand-off geometry, so build 1 stops changing the ring.

## 3. Decisions

- **D1 Upload mechanism (OQ-1).** Keep the movie texture at poster size.
  - Replace `uploadInto` (G2 :325-341) with `uploadVideo`: `drawImage(video, 0, 0, inner.w, inner.h)` into one id-less, never-attached 2D canvas of `inner` size (created at install with plain `getContext('2d')`: no `willReadFrequently`, which would force a CPU canvas), then `texSubImage2D(TEXTURE_2D, 0, x0, T.h−y1, extFmt, type, innerCanvas)`. The unpack flags and texture binding are saved and restored exactly as :329-338 does today, in a `finally`.
  - Unlike `uploadInto` (whose `catch (e) {}` makes a throwing upload a silent freeze), a caught exception goes to `requireGlClean(false, {call: 'uploadVideo', error})`, as the `requireGlClean` contract at G2 :179-181 already states. `state.uploads` counts only uploads that returned.
  - Both call sites (:446, :1019) switch to it. No whole-texture video upload remains (no stretch fallback).
  - Margin texels are never written, so the frame stays byte-identical to the player's poster.
  - Rejected alternative: our own FBO draw. It needs program, buffer, attrib, viewport, blend, scissor and depth save/restore around a frame we replay verbatim.
  - Rejected alternative: `texSubImage2D(video)`. It cannot scale 1920×540 into 952×268.
  - Rejected alternative: `blitFramebuffer`. It is WebGL2-only (F8).
- **D2 Inner-rect source (OQ-3).** Compute the rect in page from the existing entry fields; no plan-shape change. `QUALIFIED_PLAN_SHA256` (lc :627-632), the P2 injected plan, `CONTINUITY_VERSION` 5 and the core sha are untouched.
- **D3 Failure paths add no new stand-down reason.** The closed set (tG2 :188-205) holds.
  - A failed containment or size check fails as `planUnreadable` (§2).
  - If `getContext('2d')` returns null at install, the module refuses with `glReplayUnavailable` by calling the existing `requireWrappers(!!ctx)` (G2 :184). No rename: the single-site test counts the literal and its constant uses, not helper calls (tG2 :175-185, :235-257).
  - A sub-upload into a texture that is not poster-sized raises INVALID_VALUE and writes nothing. No new `getError` call is added. In LIVE the same tick's `sampleOnce` `getError` (G2 :572-576) turns it into a `glError` stand-down. In ARM-PRE the error stays latched (the player never calls `getError`, F8) until ARM-POST's first `sampleOnce` inside `markerSwap`, which stands down as `glError` before LIVE. The texture can be off-size only if `restorePoster` failed after `markerSwap`'s 8×8 paint (G2 :343-361, :828; that failure latches its own error, caught at the tick-start check :1003-1005), or if the player redefines its poster texture mid-move. Today both cases are masked by the next whole-texture video upload.
- **D4 One new stat.** `stats().innerRect` (texels). Upload rate stays derivable from `iter`/`uploads`.
- **D5 `probe(rect)`**, specified in §4.
- **D6 Version (OQ-2).** Bump `GL_REPLAY_VERSION` 1→2 and the `API.version` literal (G2 :32, :60).

## 4. `probe(rect)`: contract for every consumer

- **Where.** The method lives on `window.__OBED_GL_ORACLE__`, which exists only in LIVE (published at G2 :928-961, deleted at :908).
- **Call and result.** `handle.probe(rect) → Promise`.
  - `rect` is `{x, y, w, h}` in authored px, top-left origin, the same space as `handle.rect`.
  - On success it resolves to `{ok: true, epoch, iter, t, vt, rect, width, height, alphaMin, pixels}`. The returned `rect` is the integer authored rect actually read, after `toBuffer` rounding and clamping (G2 :512-520). `pixels` is a plain array of `width·height·4` RGBA bytes with rows **top-down**. Consumers read counter-sized ROIs (≈ 42×14), so a plain array is small. Python reshapes it and saves the evidence PNG, which avoids a second 2D canvas and PNG encoding in page.
  - Otherwise it resolves to `{ok: false, reason}`: `'badRect'` for a non-finite rect or w/h ≤ 0 (immediately), or `'standDown'` for probes still pending at stand-down.
- **When it is served.** At the **next** LIVE tick (rVFC or rAF watchdog), immediately after `replayFrame()` and `sampleOnce()` inside `tickOnce` (G2 :1008-1013), under the module's own `replaying` depth. That is the same place the per-tick band read happens today, so the read sees exactly the frame about to be composited: `preserveDrawingBuffer` is false (F8 defaults), and a read outside the tick would see a cleared buffer.
- **What it never does.** `probe()` issues no GL call synchronously, never pauses, never marker-swaps, and never touches player state.
- **Encoding.** Row flip, `alphaMin` and `Array.from` run after `replaying` drops back to its previous depth. No GL is involved, so there is no `unflaggedPlayerCall` exposure (G2 :284-288). (`readPixels` is in the wrapper's `SKIP` set, G2 :236, so it is never recorded as a player call either.)
- **`alphaMin`.** The drawing buffer has alpha (F8) and the player clears to `(0,0,0,0)`. Over the movie the opaque slot-0 background and premultiplied `ONE, ONE_MINUS_SRC_ALPHA` blending should leave alpha 255. This is unverified (§12), so the first CvC read settles it. If the control reads < 255 there, that is an instrument fact to escalate, not a product failure.
- **Errors.** A `readPixels` error goes through `requireGlClean` like `sampleOnce` (G2 :572-576).
- **Stand-down.** Stand-down resolves pending probes next to the collectors (G2 :851-852).
- **Consumer rule.** `ok: false`, `alphaMin < 255` or a missing `probe` counts as a failed read, never as a raise. Every consumer wraps the call in a 2 s `Promise.race`. A consumer touches only `handle.probe` and `handle.rect`: never `.gl`, `markerBands`, `pause` or `resume`. This is the P2 carve-out from the g5g6 "no oracle in arms" rule (F11). `probe` is observation-only by construction, served inside the module's own tick.

## 5. Change list

| File | Change |
|---|---|
| G2 (JS) | `innerRectOf(entry)` and its use in `validEntry` (:92-124). State: `inner`, `innerCanvas`, `innerCtx`, `probes`. Install (:1199-1218) creates the inner canvas and 2D context and calls the existing `requireWrappers(!!ctx)` (:184). `uploadVideo` replaces `uploadInto` (D1). `probe` is added to `publishHandle`, served in `tickOnce`, and resolved in `standDown` (§4). `statsOf` (:204-223) gains `innerRect`. `API.version` 2. |
| G2 (Python) | `inner_texel_rect(entry)` mirrors `innerRectOf` with round-half-up and the same operation order, `(I.x − S.x) * (T.w / S.w)`, so the IEEE results match. `validate_gl_replay_entry` (:1235-1300) returns None when it is None. `GL_REPLAY_VERSION = 2`. One docstring line. |
| oracle parity test | `tests/test_live_gl_replay_oracle_parity.py` `HANDLE_FIELD_JS` (:259-274) gains a `"probe"` recipe (F11). Without it `run_probe_js_in_node` fails on the new handle field. No other edit. |
| probe | `handback_hook` (:2562-2573) gains a keyword `capture_live=False`. When it is True, the hook captures `sink["live"]` = `{stageMap, frame}` (two rAF, then one screenshot, no poke) before `capture_handback` advances. It is True only at the V and Vgl call sites of the gl-auto run (:3863, :3887). `run_forced_fail` (:3717, :3728) and the off path are untouched. New pure `live_ring_mask` and `score_live_ring(v_sink, g_sink, armed)` (N3). Wiring at :3877-3897 writes `result["liveRing"]`. `gl_replay_reasons` (:3560-3580) fails on False and reports None as inconclusive. The probe does not call `probe()` (OQ-4). |
| p2v | `progressingIndexAfterFlip` (:1023-1049) takes `gl_probe_indices` (min 3, the same `_index_series_progress` step/advance rule) as a third **gating** series, and the agreement report gains `glForward`. `glReplayCarry1to2` (:1330-1436) passes it through clause (f), with the reason naming every failing series. No decoder move and no public rename (nothing outside p2s decodes). |
| p2s | `GL_PROBE_READ_JS`: an async read (`await_promise=True`) of `handle.probe(ROI)` with a 2 s race. The ROI is `index_patch_roi_for(instanceRect)`, computed in Python from the injected plan's entry and substituted as a literal. `_gl_slide2_reads` (:679-698) calls it right after `GL_SLIDE2_READ_JS`, decodes the `pixels` with `_decode_index_patch(arr, (0, 0, w, h))`, stores `glProbeIndex`/`glProbeMeta` and saves `gl-probe-{i}.png`. The call site :4223-4231 passes the series. These are auto-only reads (:3523), so off JS, off report keys and finding ids are unchanged. |
| host, core, lc, `live_runtime.py`, `html_alpha_probe.py`, README | **No change.** The host reports the new sha/version dynamically (:963-970). The README paragraph (:119-127) stays accurate. |

The core and the P2 injected plan are not touched. The P2 harness and verdict change **only** to consume the owner-decided probe (auto path). G-OFF proves the off path unchanged.

## 6. Sha, version and allowlist moves

- The G2 `js_sha256` moves from `4f8850e0…`. It is re-pinned at tG2 :140 **last**, by the test author, after every other G2 test is green.
- `GL_REPLAY_VERSION` 1→2 (tG2 :148-150) if OQ-2 is accepted. Consequence: an old-bytes splice (page `API.version` 1) fails P2 `_gl_boot_ok` (F9) before any clause is scored, so old bytes are never a P2 known-bad. The probe (:1635) and host compare only Python-side values, so there old bytes are fine.
- Grep at `d56fb0dd`: `4f8850e0` appears in code only at tG2 :140. Every other hit is in `.agents/` history docs, which stay as they are.
- Unchanged: the core `PINNED_CORE_SHA256 e9338aff…`, `CONTINUITY_VERSION` 5, `QUALIFIED_PLAN_SHA256`, `PLAYER_SHA256`/served patched `main.js`, the P2 fixture `index.html` `5908d479…`, `preserve-inject.json` `53cf8339…` and `continuity-plan-inject.json` `91a29d5e…`.
- `gl-replay-inject.json` (auto) records the new G2 sha.

## 7. Unit tests

**tG2.** The fake platform is extended first, and each new test is proved RED on the `4f8850e0` bytes before it counts. Fake changes:
- `texSubImage2D` gets real sub-region semantics (size kept; out of bounds is INVALID_VALUE with no write) instead of the alias at :752. The texture's `texel(tx, ty)` becomes a composite (sub-region over the previous texels). `tex.colour`, which `_draw` uses for `drawnColours`, becomes the colour of the centre texel, so a LIVE draw still reports `VIDEO_COLOUR` and a restored poster reports `POSTER_COLOUR`;
- `FakeCanvas.getContext('2d')` (:886-890) returns a fake 2D context whose `drawImage(src, …)` copies `src.__colour` onto the canvas (plus an optional `drawImageThrows` switch). Until this lands, every sandbox test refuses at install (`glReplayUnavailable`), because today the fake returns null for `'2d'`.

Tests:
1. The stretch positive-control test (:2474-2484) is replaced by an inner-rect positive control, which is RED on the old bytes:
   - LIVE `posterTexture` keeps `POSTER_SIZE`;
   - no `texImage2D` has a video source;
   - exactly the region (4, 276−272, 952, 268) is written per upload;
   - margin texels equal the original poster and interior texels come from the video.
2. Per-clear (ARM-PRE) uploads use the same path.
3. Inner-rect math, with JS↔Python parity on the fixture ({4,4,952,268}) and on mutations: a 2× texture scale, `.5` edges (half-up), instance == slot (full texture), margin −0.4 (clamped, OK), margin −0.6 (`planUnreadable`, Python None), inner < 1 texel (refused).
4. The compositor canvas is created once, has no `id`, is never attached, and one 2D context is reused. A null 2D context gives `glReplayUnavailable` and installs nothing.
5. Fail-closed upload paths:
   - `drawImageThrows` in LIVE ⇒ one `glError` stand-down, with `unpack` flags and binding restored (as `test_throwing_poster_restore_…` asserts at :2658-2668) and the poster restored. This is RED on the old bytes as the new-mechanism control, not as a regression;
   - the player redefines its poster texture to another size mid-move ⇒ `glError` at ARM-POST, before LIVE, with no whole-texture video upload anywhere.
6. The existing poster-restore matrix (:2522-2610) passes unchanged. `test_restore_with_a_silent_gl_error_is_not_reported_restored` (:2701-2719) **changes**: after a failed restore the texture keeps `POSTER_SIZE` with video in the inner rect, instead of `VIDEO_SIZE`. It stays `!= originalPoster`, and the `drawnColours` assertion holds through the centre-texel rule.
7. The reason set is unchanged (:188-257). No helper rename.
8. `probe`:
   - the handle fields (:1610-1626) gain `probe`;
   - it is served on the next tick after the replayed draws with `replaying > 0`, and no GL call happens synchronously;
   - rows come back top-down in `pixels` (a rect straddling two fake colours vertically);
   - rect rounding and clamping, and the returned rect;
   - `badRect` resolves immediately;
   - pending probes resolve `standDown`;
   - it is served in rAF/paused mode;
   - `epoch` equals `handle.epoch`;
   - `alphaMin` is reported.
9. `stats.innerRect`.
10. The sha pin (last).

`tests/test_live_gl_replay_oracle_parity.py`: only the `"probe"` entry in `HANDLE_FIELD_JS` (F11). The probe's in-page oracle JS is unedited.

**`tests/test_live_continuity_probe.py`.**
- `score_live_ring`: GREEN on identical frames. RED on a synthetic frame with video pixels in the ring. RED on a synthetic 1-px edge bleed at 2560 when the dilation is 1 px, and GREEN at 2 px (this pins §2 "Filter footprint"). Override and green slots are masked. Stage-map scaling. Inconclusive on a missing or invalid capture.
- The hook captures `live` before the advance only when `capture_live=True`. The `run_forced_fail` and off/`facts_on is None` paths record nothing new.

**p2 tests** (`test_p2_adversarial*.py`, `test_p2_adversarial_driver.py`).
- Each (f) series is RED alone (composite, `sampleFrame`, GL probe), and a 2-pooled run is GREEN.
- `test_gl_reads_never_touch_the_oracle_handle` (:568-572) keeps its four constants. A new sibling test pins `GL_PROBE_READ_JS`: it names `__OBED_GL_ORACLE__`, calls `.probe(` exactly once, and contains no `.gl`, `markerBands`, `.pause(` or `.resume(`.
- Off JS/keys and the driver finding ids/count are unchanged.
- The auto read order is sampleFrame then probe.

## 8. Gates

Every new check must read RED on its known-bad (KB) and 0 / identical control-vs-control (CvC) **before** it counts. Discipline:
- ≤ 3 headless Chromes;
- `run_gates`, go-to arms, Q3 and every P2 run each run alone;
- `pgrep -f headless=new` empty before each batch;
- clean detached gate worktree with a fixture symlink;
- shas printed at start and end;
- no Keynote, no OBS.

**KB splices** are observation-only harness wrappers, never product code. Each asserts exactly one substitution and prints the resulting sha.
- **old-bytes:** `live_gl_replay_js.GL_REPLAY_JS` is set to `git show d56fb0dd:` bytes, and sha == `4f8850e0…` is asserted. g3h runs LiveOutputHost in-process. probe and P2 run through a `runpy` wrapper that patches the module first.
- **frozen-upload:** the new module text with the LIVE `perLiveUpload()` call removed, so the GL composite freezes while the decoder keeps running.
- **A KB counts only when it fails for the right reason.** The named check must go RED. Any other check that also goes RED is listed in the record. A KB that goes RED first on something unrelated (e.g. P2 `_gl_boot_ok` on an old-bytes version mismatch, §6) is invalid. So old bytes are used only in g3h and the probe, and frozen-upload (version 2) is used in P2.

| Check | Where | Pass | KB ⇒ RED | CvC |
|---|---|---|---|---|
| **N1 LIVE ring** (promotes `_report T-ring at P2c`) | g3h `handoff_checks` (:398-402), gates 4/4b, tags P2-settled-slide2, P2b, P2c | ring max ≤ 2 (same rule as T-ring) | r3 recorded 251/251/245 on `4f8850e0`, plus a fresh `armed-oldbytes` arm | control-2 vs control ≤ 2 (expect 0) |
| **N2 build-1 ring burst** | g3h, burst B00–B09 (`g3_flow.py` :316-329) | every armed B-shot's ring ≤ 2 against control P2c **or** control P3 | `armed-oldbytes` pre-advance shots match neither | control's own burst against its own P2c/P3; if CvC fails, report-only (OQ-5) |
| **N3 probe live ring** | probe P5-A (3 viewports), V vs Vgl `sink["live"]` | max == 0 over `toScreen(S) − dilate(toScreen(I), 2) − dilate(override ∪ green, 2)`, rasterised with `handback_parity`'s floor/ceil rule (probe :2624-2626). The dilation is 2, not 1: see §2 "Filter footprint"; with 1 px, (c) itself would read RED at 2560 on the top and right edges. | Vgl-oldbytes (the stretched video fills the ring) | V vs V and Vgl vs Vgl across sessions: 0 at every viewport |
| **N5 P2 (f) GL series** | G6-P2 auto fast ×2 / slow / no-bridge | `glReplayCarry1to2` True with the GL series ≥ 3 decoded and progressing | frozen-upload ⇒ (f) False naming the GL series; off report scored ⇒ False | fast vs fast-rep2 identical findings |
| **A7′ instrument** | P2 auto (4 runs × `GL_POOL_READS_N` 4 = 16 pairs) | ≥ 12 same-read pairs, probe vs `sampleFrame` \|Δ\| ≤ 2; control reads `alphaMin` 255 | pairing each probe with the previous read's `sampleFrame` (≈ 350 ms apart) gives \|Δ\| ≫ 2 | — |

**Re-qualification (all on the (c) tip, full re-gate).**
- **G-OFF (blocking):** host ×3 viewports and P2 off fast/slow/no-bridge, compared with the baseline.
- **g3h gates:** 1 install order; 2 (frameLen 88, occluded 20/128, oracle LIVE n=24, paused DEAD, carried/pool; report uploads/s against r3 ≈ 30/s — a drop > 10 % stops the round and goes to the owner under OQ-1, it is not waved through); 4 and 4b (existing checks, plus N1/N2); 6 fail-closed (20 forced plus 3 late); 7 go-to; Q3 20-min soak (heap, 0 GL errors, dropped frames), because the per-frame path changed.
- **G5:** P5-A ×3 plus 2 reps at 2560 (+N3), P5-H ×3, P5-F, P5-7, P5-L.
- **G6:** P2 auto fast ×2 / slow / no-bridge (+N5) and A7′.
- Then the full suites: `uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`.
- The record goes in `.agents/reviews/gl-replay-c/gates-r1.md`.

**Reused, not re-run.**
- G-0 baseline = `output/gates-g5g6/{g0,r3}` (F10: runtime bytes identical to `d56fb0dd`).
- The P5-0 poke decision (poke off; N1–N3 read static ring pixels, so staleness cannot matter).
- A7 (the `sampleFrame`/screenshot pairing is unchanged).
- G6-0 A6 is re-printed only.

Harness copies go to new git-ignored dirs `output/gates-glc/` (from `gates-g5g6/run_gates_g5g6.sh`, unchanged) and `output/gl-replay-c-harness/g3/` (from g3h, with the `analyse_g3.py` edits for N1/N2 and the two splice arms).

## 9. Risks

- **R1 Per-frame 2D draw cost.** A software-backed canvas could lower the upload rate. Headless is measured against r3; OBS is the next item and should record per-upload cost there.
- **R2 Colour and scaling through the 2D canvas.** Pixels inside the movie may differ from the direct video texture. They are masked in every parity check. A7′ and N5 cover counter decoding.
- **R3 One fixture.** slotRect against the DOM tree differs by 0.13/0.16 px here. The owner decks plan `pin`, so no second `glReplay` deck exists (arming §6 Q4).
- **R4 Edge residual.** The texel-4 column is now all video, against 0.77 in the DOM. That is a ≤ 1 px difference at the inner edge, plus the one-texel `LINEAR` footprint. N1 masks it with 1 px (at scale ≤ 1) and N3 with 2 px (§2). The unit tests pin the offsets exactly.
- **R5 Non-poster-sized texture.** It fails closed as `glError` (D3), not as a silent stretch.
- **R6 Brittle splices.** Exactly-one-substitution asserts guard them. The splice lives only in the gate harness.
- **R7 A probe that never resolves.** For example, if ticks stop; consumers race 2 s and fail the read.

## 10. Implementation streams (one PR; three Opus MEDIUM implementers, disjoint files; Codex GPT-5.6 Sol review; no Opus review rounds)

| Stream | Owns | Forbidden |
|---|---|---|
| **S-G** G2 | `src/obed_edom/live_gl_replay_js.py`, `tests/test_live_gl_replay_js.py`, `tests/test_live_gl_replay_oracle_parity.py` (the `"probe"` recipe only) | all else |
| **S-P** probe | `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py` | src (imports only), p2* |
| **S-Q** P2 | `src/obed_edom/p2_verdict.py`, `scripts/p2_recovery_html_adversarial.py`, `tests/test_p2_adversarial.py`, `tests/test_p2_adversarial_gl_replay.py`, `tests/test_p2_adversarial_driver.py` | G2, probe, host, core, lc |
| **C** gate runner (coordinator) | `output/gates-glc/**`, `output/gl-replay-c-harness/**`, pinned detached worktrees | src/tests/scripts (run only) |

**Order.**
1. S-G, S-P and S-Q start in parallel, with no cross-stream imports. S-Q codes against §4 and tests with fakes. S-P touches no G2 API.
2. S-G lands the fake-platform extension (§7) before its own RED tests. It is S-G-internal and blocks nobody else.
3. C starts the day S-G's inner-rect commit is green: N1 first, including its KB and CvC.
4. KBs and CvC for N1, N2, N3, N5 and A7′.
5. G-OFF.
6. Full gates.
7. Codex review.
8. Fixes, then re-gate.
9. S-G re-pins the sha last.
10. Full suites.
11. PR (no merge without the owner).

**Brief lessons for every implementer.**
- Prove new tests RED on the pre-change bytes.
- The sandbox must run the module in sloppy mode.
- Force paths are forced, not grepped.
- Stage only owned paths.
- Apply the reviewer's exact wording, or bring a measured refutation.

## 11. Open questions (all CLOSED 2026-09-23 as recommended — see §0)

1. **OQ-1 Upload mechanism.** Recommend a 2D-canvas intermediate plus `texSubImage2D` into the inner texel rect (D1). The alternative is our own FBO quad draw, which avoids the 2D canvas but saves and restores most WebGL state around a verbatim replay.
2. **OQ-2 Version.** Recommend `GL_REPLAY_VERSION` 1→2, because behaviour and the handle contract change. The alternative is to keep 1 and rely on the sha.
3. **OQ-3 Inner-rect source.** Recommend computing it in page from the existing `slotRects`/`slotSizes`/`instanceRect` (no plan, allowlist or P2-injected-plan change). The alternative is a new offline plan field from the export's layer tree, which is 0.16 px truer on this fixture but moves `QUALIFIED_PLAN_SHA256` and the P2 injected plan.
4. **OQ-4 Probe consumers.** Recommend **P2 only**: clause (f) gates the GL series (N5), plus the A7′ pairing. rev 0 also gated a probe Vgl `glProbeCounter` at 3 viewports. That adds no evidence, because the drawing buffer is authored-size at every viewport (asserted by `canvasShape`, G2 :1152-1156), so the readback cannot vary with viewport. It would also have forced the decoder out of p2s and an S-Q→S-P ordering dependency. The alternative (rev 0) is to add N4 in the probe.
5. **OQ-5 N2 build-1 burst ring.** Recommend gating if CvC passes. Otherwise it stays report-only, and N1 plus the existing post-hand-off T-ring carry the build-1 claim.
6. **OQ-6 Known-bad construction.** Recommend harness-side module-text splices (old bytes, frozen upload). The alternative is a product debug seed (a `debugForceFail`-style `debugStretch`/`debugFreeze`), which keeps a dead path in product.

## 12. Facts I could not verify

- Whether Chrome/CEF GPU-accelerates a 952×268 2D canvas, which decides a GPU-to-GPU copy against a readback per frame.
- The drawing-buffer alpha over the counter ROI (default `alpha: true` context). That is why `alphaMin` is gated.
- Whether the player re-uploads the poster during the move. (The filter is known: every `TEXTURE_MIN_FILTER` in `main.js` is `LINEAR`, F8.)
- Whether the control has an intermediate ring state during build 1 (N2 CvC decides).
- The g3h arm captures behind r3 were pruned (only `gates.json` remains), so N1's KB numbers are recorded values plus one fresh old-bytes arm.
- "Guard G" is named from gates-r3 (`glreplay-hold {via: stage}`). Its exact G3-plan definition is only in git history and was not re-read.

## 13. Critique pass (Opus HIGH, 2026-09-23)

Checked against `d56fb0dd`, the fixture (`output/p2-recovery/html-adversarial/`) and g3h r3. No product code or tests edited, and nothing run live.

**Verified as written.** F1–F3, F5–F7 and F10, and every G2/tG2/lc/host/core line cite in §1–§3 except those fixed below. The inner rect {4,4,952,268}, edges (4.2268, 955.7668, 4.1931, 271.8131), `yoffset` 4, the 0.23 px residual, the aspects 3.552/3.556/3.478 (2.2 %), and ≤ 0.31 screen px at 2560 were all recomputed. The export's layer tree independently gives the frame layer at (105.000, 791.000) and the video at (109.352, 795.036), which rounds to the same rect. The GL-row derivation (flipY sub-upload → `T.h − y1`) holds. JS `Math.round` against Python `floor(v + 0.5)` agrees on ±x.5.

**Blockers**
- **B1: N3 as written would fail on (c) itself.** `LINEAR` texture filtering plus bilinear CSS scaling spread each inner edge over one texel. At 2560 that reaches screen px 1058 (top) and 1416 (right), outside a 1-px dilation of `toScreen(I)`, and N3 demands max == 0. Fix: N3 dilates by 2 px (`HANDBACK_DILATE_PX`, the value the existing hand-back parity already uses), reuses its floor/ceil rasterisation, and gets a unit test that pins 1 px ⇒ RED and 2 px ⇒ GREEN. (§2 "Filter footprint", §8, §7.) N1 at 1920/1600 checks out at 1 px.
- **B2: two existing tests break, and rev 0 said they were untouched.** `tests/test_live_gl_replay_oracle_parity.py` rejects the new `probe` handle field (no `HANDLE_FIELD_JS` recipe). `tests/test_p2_adversarial_gl_replay.py` :568-572 forbids P2 reads of `__OBED_GL_ORACLE__`. Fix: S-G owns the one-line recipe. S-Q adds `GL_PROBE_READ_JS` outside that tuple, plus a sibling test that pins exactly what it may touch. §4 now states the P2 carve-out from the g5g6 "no oracle in arms" rule. (F11, §4, §5, §7, §10.)

**Majors**
- **M1: silent freeze.** `uploadInto`'s `catch (e) {}` makes any throwing upload a silent frozen movie. (c) adds `drawImage` as a new throw point (e.g. a tainted source). `uploadVideo` now routes a caught exception to `requireGlClean`, per that helper's own documented contract (G2 :179-181), and restores its state in `finally`. A test was added. (D1, §7 test 5.)
- **M2: wrong error mechanics and wrong test.** D3 said "the next tick's `getError`" and added a new `getError` in ARM-PRE. In fact the same tick's `sampleOnce` catches it in LIVE, and ARM-POST's first `sampleOnce` catches it in ARM-PRE (the player never calls `getError`). No new `getError` is added. Rev 0's test 5 (`restoreSilentError` ⇒ glError) did not distinguish (c), because the restore's own latched error already stands down at the tick-start check. It is replaced by an off-size-poster test and the throw test. The existing test at :2701-2719 **must change** (`VIDEO_SIZE` → `POSTER_SIZE` with video inside). Rev 0 claimed the restore tests pass unchanged.
- **M3: fake prerequisites.** The fake's `getContext('2d')` returns null today, so every sandbox test refuses at install until the fake grows a 2D context. `drawnColours` needs a rule for a mixed texture (centre texel). (§7.)
- **M4: KB validity.** P2 `_gl_boot_ok` compares the page `API.version` with the Python constant, so an old-bytes splice fails P2 boot before any clause is scored (it is RED for the wrong reason). Old bytes are now limited to g3h and the probe, and §8 now requires each KB to fail for the named reason. (F9, §6, §8.)
- **M5: N4 cut (over-engineering).** A viewport-independent readback is guaranteed by construction (authored-size backing store, `canvasShape`). N4 only drove a decoder move into p2v, an S-Q→S-P ordering dependency and a second scorer. P2 (f) plus A7′ is the probe's consumer (OQ-4 flipped). So there is no `decode_index_patch` move (rev 0's "unchanged bytes" move was impossible anyway: its default argument `INDEX_PATCH_ROI` lives in p2s) and no public rename. Also, `tests/test_html_alpha_probe.py` does not import `_decode_index_patch`; it only mentions it in a docstring.

**Minors**
- `probe` returns `pixels` (a plain top-down RGBA array) instead of a PNG `dataURL`. That drops the second in-page 2D canvas, the `toDataURL` and the fake's encoder. Python saves the evidence PNG.
- No `requireWrappers` → `requirePlatform` rename. Rev 0's rationale was wrong: the single-site test counts the literal and constant uses, not helper calls.
- `handback_hook` capture is opt-in (`capture_live`), so `run_forced_fail` (P5-F) is untouched.
- The A7′ ROI-shift sub-check was cut; the existing neutrality gate already fails a misplaced ROI closed. The pair count is sourced (4 runs × 4 reads).
- An uploads/s drop > 10 % against r3 now stops the round (OQ-1 escalation) instead of being report-only.
- F4 clarified: the gate fixture serves the H.264 counter movie, not the export's HEVC. F8 gained player facts: no `getError`, no colorspace flag, `clearColor(0,0,0,0)`, `LINEAR` everywhere. That resolves one §12 unknown.
- Cite fixes: the `requireGlClean` contract is at :179-181; the forced-fail hooks are at :3717/:3728; the Vgl hook is at :3887.

**Checked and left as is.** The OQ-1 2D-canvas + `texSubImage2D` approach is right. WebGL1 has `texSubImage2D(TexImageSource)`. Sub-uploads keep the texture poster-sized, so no mip or NPOT change. The flip and premultiply flags are the poster's own. The player never sets the colorspace flag. Only the active unit's binding is touched, and it is restored. First frame and `ended` are gated as today by `readyState ≥ 2` and rVFC. Context loss needs nothing new (a 2D canvas is unaffected). The per-frame cost is gated via the uploads/s rule. OQ-3 is deterministic and DPR-free, and it agrees with `toScreen(instanceRect)`. The core's `handbackRectOk` (−0.5…8) still governs the hand-back independently. The streams are disjoint after the parity-test assignment. The core, `QUALIFIED_PLAN_SHA256`, the P2 injected plan and the host really are unchanged: no plan field, and the host reads the sha/version dynamically.

**Disagreements left for the owner.**
- N2 (build-1 burst) is extra harness for a claim N1 + the post-hand-off T-ring already bracket. I kept it under OQ-5 rather than cutting it.
- `alphaMin` gating depends on an unverified drawing-buffer alpha. It is kept, with the rule that a control read < 255 is an instrument escalation, not a product failure.
