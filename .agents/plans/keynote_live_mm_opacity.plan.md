# Magic Move translucent opacity: draw the authored opacity from the first frame of the move

DRAFT for owner review, **rev 2**, 2026-09-25. Rev 1: Opus planner. Rev 2: Opus critic (see §12 Critique log).
Plan only: no product code, no commits, no OBS, no Keynote.
**Builds on OD-2**: MERGED as #229 (`8fe3b551`, 2026-09-25); this branch is rebased on it. It holds the GL-replay default in
Keyer mode, the binary-counter fixture and `scripts/managed_obs_qualify.py` / `scripts/obs_cadence_decode.py`. Line numbers
below were read at `386f28f2`; OD-2 changes only `live_host.py` in `src/` (≤ 4 lines shift) and leaves the G2 bytes identical.
Parents: `keynote_live_gl_replay_arming.plan.md` (owner answer D2: fix opacity without editing `main.js`), the pruned
opacity plan `git show 0d511a9c^:.agents/plans/keynote_live_gl_replay_opacity.plan.md` (§0 measurements, F-1…F-12),
`.agents/reviews/gl-replay-managed/gates-r1.md` (M7 known limit).

## 0. Facts (code-read and offline, 2026-09-25; rev 2 re-read every player citation)

**Finding (owner, M7 2026-09-25).** P2 fixture, Magic Move 1→2. Slot 4 is the green square (authored α 0.29468628764152527).
Keynote draws it translucent for the whole move. The export's WebGL draws it opaque. With GL replay ON it is opaque during the
move and for about 1 s after settle, until G2 goes LIVE and applies its override. With GL replay OFF it is opaque until
build 1 hands back to the DOM. Recording `qualify-home/recordings/g2-20260925-104512/`: (26,175,0) opaque vs (6,52,0)
translucent (175 × α = 51.6, so the recording is the premultiplied composite over black).

**Root cause in the player.** Player `assets/player/main.js` is sha `e9b2fad4…` (= `live_runtime.PLAYER_SHA256`). It is one
minified line, so citations are byte offsets. The same bytes are in `output/p2-binary`, `output/p2-recovery`, `output/gl-decks`.
- `setupTexture` (byte 2263031) calls `textureInfoFromEffect(A.kpfLayer, …, A.baseLayer.initialState.opacity, B)`.
  `textureInfoFromEffect` (byte 2263358) recurses with `e.parentOpacity` **unchanged** (byte 2264145). So every textured leaf
  gets `parentOpacity` = the effect **root** opacity (1). No intermediate wrapper's `initialState.opacity` or `opacity`
  animation is ever read.
- Magic Move (`class pB`, byte 2259419) builds one `eB` per texture, in `effect.textures` order, and `drawFrame` loops them in
  that order with no skip (byte 2260475): a hidden leaf still draws, with `Opacity` 0.
- Each `eB` creates its **own** `BB` shader object and program (`new BB(A)`, byte 2191945). Uniform qualifiers are per `BB`
  (`this._uniforms`, byte 2184896). A program is never shared between slots or reused by a later effect.
- Per frame the renderer does `clearColor(0,0,0,0)`, one `clear`, then draws every `glProgram` on that canvas
  (`animate`, byte 2265926). After `durationMax` it draws once more with `isCompleted` and stops: that last frame is the
  settle frame that persists on the canvas.
- Per draw (`QB.renderFrameWithContext`, byte 2189761): `case "opacity": d = from, U = to`, then
  `T = hidden ? 0 : parentOpacity * leaf.initialState.opacity; d !== U && (T = eased lerp); setGLFloat(T, "Opacity")`
  (byte 2190382). **A constant (from == to) leaf opacity animation is ignored.** The no-animation branch of `eB.drawFrame`
  does the same (byte 2192635).
- Order inside one draw: `setGLFloat(Opacity)`, `setMat4(MVPMatrix)`, `bindTexture` on the current unit, then
  `drawWithShader` → `activate()` (`useProgram` + flush of changed uniforms, `uniform1f` before `uniformMatrix4fv`) →
  `drawArrays`/`drawElements` → `deactivate()` (bytes 2179107–2180463, 2187934). So `useProgram(P)` precedes every draw.
- Uniform writes are cached per qualifier: `setProposedGLfloatValue` marks a write only when the value changes
  (byte 2181695). For a constant T the player issues `uniform1f(Opacity)` once, at the effect's first draw.
- Geometry: translation uses its own eased z; scale and rotation use the eased z of the **last** animation in the leaf's list
  (loop variable `Z`, byte 2190119). `beginTime`/`duration` are honoured only for opacity.
- The shader is `gl_FragColor = vec4(Opacity) * mix(Texture2, Texture, mixFactor)` (byte 1986335), `Texture2` = unit 0,
  `Texture` = unit 1 (byte 2191945), blended with `blendFunc(ONE, ONE_MINUS_SRC_ALPHA)`: `P = O·S + (1 − O·S_a)·B`.
- `singleTextureOpacity` occurs **0** times in `main.js`.
- The canvas backing store is always the authored slide size (`createCanvasElement`, `slideWidth × slideHeight`); the viewport
  only changes CSS scale. One canvas per scene is reused by every WebGL effect of that scene (`this.canvasId`, byte ~2313700).

**Export encoding, slot 4** (`tests/fixtures/live_continuity/effect_1_to_2.json`):

| Node | `initialState.opacity` | Opacity animation | Other |
|---|---|---|---|
| Wrapper | 0.2947 | `opacity` 1 → 1, EaseInEaseOut, `fillMode both`, 1.5 s | |
| Leaf | 1 | `opacity` 0.2947 → 0.2947 (last in list) | scale ×1.983/×1.994 and translation (240.4, 28.0), all EaseInEaseOut 0–1.5 s; `singleTextureOpacity` 0.2947; no `contents` animation |

Keynote's presented opacity is the product over the chain of each node's animated value, or its model value when the node
has no animation: 1 × 0.2947 = **0.2947, constant for the whole move and after** (after the move the model values give
0.2947 × 1, the same). The player computes 1 × 1 = **1**.

**Absolute, not multiplicative.** For a chain whose every opacity animation is constant, the authored value is a constant, so
MMO writes that absolute value. A correction factor `authored / playerComputed` is equal here and buys nothing in v1; it would
only matter for fades, which v1 excludes (§1). A later fade extension would have to track the player's own `Opacity` writes
per program and scale them, because the player's cache hides unchanged values.

**Census of every export on disk.** 26 distinct Magic Move effects under the main checkout's `output/` (`gl-decks`, `p2-*`,
`qual-decks/D1–D6`; scratch scripts `scan_mm2.py`, `eoo.py`):
- exactly **one** translucent Magic Move slot: this slot 4 (P2 deck, Minimal Alpha_DSK, and the loop copy);
- every fade (1→0 or 0→1) is on the **leaf** with ancestors at 1, which the player already draws correctly;
- no wrapper-level fade; no `initialState.opacity < 1` outside slot 4;
- `effect_opacity_overrides` returns `Unsupported` for 17 of the 26 effects (`texturedRectangle.textColor` on text leaves,
  D1–D6; `transform.rotation.z`, Minimal S6→S7).

## 1. v1 scope: what is patched

MMO's patch set for a move is **exactly** `effect_opacity_overrides(effect)["opacityOverrides"]` (unchanged function, so
G2's `glReplay` entry and MMO can never disagree), minus slots that fail the MMO-only rules. That function already enforces:
closed vocabulary (`_check_effect_encoding`), single chain, no fade on any node, no `hidden`, product == `singleTextureOpacity`
within 1e-6, α < 1, unique size.

MMO-only rules (offline, per slot):
1. The transition name is `apple:magic-move-implied-motion-path`.
2. No `contents` animation on the leaf (keeps `mixFactor` 0 during the move, so unit 0 is the sampled texture).
3. Every animation on the leaf shares one `timingFunction`, `beginTime` and `duration` (so the player's MVP lies on the
   from→to segment at one z; §0 Geometry).

Failures become `excluded{slot, reason}`; an `Unsupported` transition becomes `excluded: [{"slot": null, reason}]`. Everything
excluded keeps today's look. Multiple translucent slots in one move are supported when each passes; none exists on disk (D3).

## 2. Where the fix lives

**(a) A standalone player-draw patch module: CHOSEN.**
- New file `src/obed_edom/live_mm_opacity_js.py` ("MMO"), a sibling of G2 with its own `MM_OPACITY_VERSION = 1` and
  `js_sha256`. It sets `Opacity` for identified draws on every player frame of the move, including the settle frame.
- It is injected by the host **independently of continuity and GL replay**, so the GL-replay-on path, the GL-replay-off path,
  decks with no movies and HDMI are all covered.
- No `main.js` edit (arming D2): prototype wrapping only, like G2. The host's `patch_player` stays an observation hook
  (`live_runtime.py:94`) and already refuses any other player sha.

**(b) Inside the continuity core: rejected.** The core is DOM-only and injected only when a continuity plan qualifies
(`live_host.py:1047`); every core byte re-opens P2 (pinned `e9338aff…`, `test_live_continuity_js.py:38`).

**(c) Inside G2 only: rejected.** G2 is injected only for an allowlisted `glReplay` boundary with GL replay on
(`live_host.py:877–890`) and acts only from ARM-POST (`live_gl_replay_js.py:1157`); the GL-off path and every other deck would
stay opaque.

**G2's override stays necessary.** While G2 owns the canvas (ARM-POST, LIVE) MMO steps aside (§5), because G2's proofs and
ablation replays must see the player's own uniform state.

## 3. Offline contract (`live_continuity.py`)

- New `mm_opacity_table(export_root, slides, *, resolver=safe_export_file) -> dict | Unsupported`. It walks non-skipped
  slides in player order with the same scene arithmetic as `derive_plan`. Extract the header read and cumulative-events loop
  (`live_continuity.py:1376–1416`) into one helper used by both; `derive_plan` output must stay byte-identical. It must **not**
  inherit `derive_plan`'s whole-deck refusal of unknown transitions (`:1467`): non-Magic-Move transitions are simply skipped.
- For each slide whose transition is a Magic Move and that has a next slide, one move entry keyed by
  `moveScene = scene(dst) − 1` (the hash the player holds for the whole move: `p2_verdict.py:95`, G2 `:1250`):

  `{"canvas": {w, h}, "moves": [{"moveScene", "slotCount", "patches": [{"slot", "opacity", "texW", "texH", "fromRect",
  "toRect"}], "excluded": [...]}]}`

- `slotCount`, `opacity`, `texW/texH`, `toRect` come straight from `effect_opacity_overrides` (`slotSizes`, `opacityOverrides`,
  `slotRects`). `fromRect` is the same rect formula (`:559–576`) with the `from` values; extract that formula into a helper
  taking `from`/`to`, with a byte-identity test on `effect_opacity_overrides` for P2, `gl-decks` and every pinned fixture.
- Only an unreadable export makes the whole table `Unsupported`. Entries with no patches are dropped; empty `moves` means
  `notApplicable`.

## 4. Runtime module (MMO)

**Install.**
- `<script id="obed-mm-opacity">` with the validated table embedded (`</` escaped, as `gl_replay_script` does at :1418).
  Served before the continuity plan/core/G2 tags and before `main.js`.
- It wraps `WebGLRenderingContext.prototype` (and WebGL2 when present): `activeTexture`, `bindTexture`, `texImage2D`,
  `texSubImage2D`, `uniformMatrix4fv`, `clear`, `drawArrays`, `drawElements`, `getUniform`.
- It captures the native function of **every** GL method it calls, wrapped or not (`uniform1f`, `useProgram`,
  `getParameter`, `getUniform`, `getUniformLocation`, `getActiveUniform`, `getProgramParameter`, `isContextLost`), at install,
  and calls only those. G2 later wraps MMO's wrappers (`wrapContexts`, :285) and never sees or records MMO's own calls.
- It refuses to install (`installRefused`, nothing wrapped) if any target method already carries `__obedGlReplay`, or if
  WebGL is absent.
- It publishes `window.__OBED_MM_OPACITY__ = {version: 1, events, stats()}`. A `debugForceFail` seed is taken only from a
  pre-existing partial object, exactly like G2's (:20–22, :65).

**Always-on bookkeeping** (every context, cheap, rare calls): texture → last upload size (same size derivation as G2's
`onPlayerUpload`), per-unit bindings, per-program last `uniformMatrix4fv`. Uploads happen before the move's first draw, so
this cannot wait for arming.

**Identification during the move** (per context, WeakMap state; nothing keyed on minified names):
- *Arm.* At the context's first draw: hash number == some `M.moveScene`; `gl.canvas.id` matches `^\d+-canvas$`; the canvas is
  inside `#stage`; canvas backing size == table `canvas` (G2's `canvasShape`, :1230; viewport-independent, §0).
- *Frame.* A frame is delimited by `clear`. The k-th draw of a frame maps to slot k.
- *Pin*, at the first draw with ordinal k that has a patch:
  - `P = getParameter(CURRENT_PROGRAM)` (client-side state in Chrome), not pinned to another slot;
  - P's active uniforms include `MVPMatrix, Opacity, mixFactor, Texture, Texture2`;
  - `getUniform(P, mixFactor) === 0`;
  - the texture bound on the unit `Texture2` samples has a last upload of exactly `texW×texH`;
  - P's last `uniformMatrix4fv`, decoded like G2's `decodeMvp` (:713), lies on `lerp(fromRect, toRect, z)` within **1 px per
    edge** for one fitted z ∈ [−0.01, 1.01];
  - then read `playerValue = getUniform(P, Opacity)` once.
- *Every later draw at ordinal k*: same program, texture size and MVP checks; then native `uniform1f(loc, opacity)` and
  forward. **Set before every draw, absolute**, so the player's cache never matters during the move.
- *Frame check.* At each `clear`, the previous frame's draw count must equal `slotCount`, and a pinned program must never
  appear at another ordinal. (The settle frame has no following `clear`; its per-draw checks still apply.)
- *Fail closed.* Any failed check → `stop(reason)`, reasons `count`, `program`, `uniforms`, `mixfactor`, `size`, `mvp`,
  `canvas`, `glError`:
  - write back `playerValue` to every pinned program (native `useProgram(P)`, `uniform1f`, restore the previous program),
    then one native `getError` (→ `glError` note only; **never** a per-draw `getError`: it stalls and clears the flag);
  - then pass through for that context for good (today's look from that frame on);
  - emit `mmopacity-stop{moveScene, slot, reason}`. Write-back is skipped on `isContextLost()`; canvas removal needs none.
- *Lifetime.* A pinned program is patched until stop or canvas removal, whatever the hash does, except while G2 owns the
  canvas (§5).
- *Cost.* Idle: one WeakMap lookup per wrapped call. Armed: per patched draw, one client-side `getParameter`, a 4×4 decode,
  one map lookup, one `uniform1f`. Sync `getUniform`/`getActiveUniform` reads happen once per pin. Report-only in MO-2.

## 5. Interaction with G2

**Why G2 needs MMO out of the way.** MMO leaves `Opacity` = α sticky on program 4. G2 captures `restOpacity` by `getUniform`
in a capture replay (:516–521) and requires `restOpacity === 1` (:807). Its ablation replays (`only: i, value: 0`) must also
reach the GPU unaltered. Without a hand-back G2 would mark slot 4 `rest-opacity` unproven and LIVE would replay **opaque**.

**Hand-back (D4; rec: implicit suspend, no G2 bytes).**
- MMO's `drawArrays`/`drawElements`/`getUniform` wrappers, on an armed context, read `window.__OBED_GL_REPLAY__`. When it is
  `version === 1`, `state` is `ARM-POST` or `LIVE`, and its last `glreplay-arm` event's `canvasId` is this context's canvas,
  MMO is **suspended**: on entering suspension it writes back `playerValue` natively (as in stop), then passes through.
- When G2 later reads `STANDDOWN`/`RETIRED` while the canvas still draws, MMO **resumes** (per-draw absolute write), so G2's
  stand-down replay (`replayFrame({rest: true})`, :927) shows the translucent square instead of opaque.
- Every G2 draw and uniform read in ARM-POST passes through MMO first (G2 replays call the prototype, whose inner layer is MMO),
  so the property "G2 never sees α" does not depend on G2's internal call order.
- `version` and `state` are already a public cross-module contract: the core reads both (`live_continuity_js.py:528–533`).
- G2's bytes, sha, OD-2's `G2_SHA`/`KB_SHAS` and G2's qualification are **untouched**. MO-4 is the interplay gate.
- *Alternative (explicit release):* one guarded `mmo.release(state.gl)` as the first statement of `armPost()` (:1157). It makes
  the hand-off visible in G2's bytes but changes G2's sha (re-pin `PINNED_JS_SHA256` :140, OD-2 `G2_SHA` and the `frozen` KB
  sha; `GL_REPLAY_VERSION` stays 1 because the core retires any other version, :531), forces a targeted G2 re-qualification
  (headless gates 1, 2, 6, N1–N3, the P2 G2 arm, managed M1–M5), and leaves every stand-down from ARM-POST on opaque until
  build 1.

**No double application.** Both modules write the same absolute value from the same function (§1). Neither multiplies by the
current uniform, so 0.29² cannot arise. MO-1's α² splice is the KB that proves the gate would see it.

**No flash.** Suspension, `markerSwap`, `proveOpacity` and the first LIVE `tickOnce` run in one rAF task (`poll` → `armPost`,
:1266–1268, :1180); only the task's final buffer is presented. G2 records only player calls, so the settle frame is unchanged
(88 calls).

**Residuals (D5).**
- G2 goes LIVE with slot 4 `opacity-unproven` for another reason (ablation, size, mvp): LIVE replays rest → the square pops
  translucent → opaque at LIVE until build 1. Today it is opaque throughout.
- MMO `stop` mid-move: translucent → opaque pop until build 1 (or G2 LIVE).
- With the explicit-release alternative only: any G2 stand-down from ARM-POST on → opaque until build 1.

## 6. Host wiring (`live_host.py`)

- **Flag.** `LiveOutputHost(mm_opacity=…)` wins over env `OBED_LIVE_MM_OPACITY`, values `off|auto` (trimmed, any case);
  anything else raises before logs, the server or CDP start, exactly like `GL_REPLAY_ENV` (:1019–1025). Default `auto` on
  every output (D2), independent of the continuity checkbox and of GL replay.
- **Resolve.** `_resolve_mm_opacity()` runs before `_resolve_continuity_static`: `Unsupported` → `unavailable` + reason; no
  moves → `notApplicable`; otherwise `injected` with `mm_opacity_script(table)`. No G2 equality guard: equality holds by
  construction (§1) and is pinned by a W1 test on P2.
- **Inject.** `continuity_script = mmo_script + (continuity + G2 if plan else "")` (:1047). Served order
  `overlay < mmo < plan < core < G2 < fit < main.js` (`:431`).
- **Report.** `output.mmOpacity = {mode, reason?, version, sha256, moves}` and a `mmOpacity` start-log record. Runtime
  `mmopacity-stop` events stay in the page API (D2).
- **Off.** Nothing is injected or evaluated; every served byte is today's.

## 7. Qualification before product code (Q0, scratch, headless first)

- **Q0a.** Headless, `output/p2-binary`, GL replay off and on. A scratch **innermost** logger (§8 install rule) records every
  call of the 1→2 move per frame: draws/frame, program per ordinal, unit bindings and upload sizes, `mixFactor`, every
  `uniform1f`/`uniformMatrix4fv` per program, the canvas and hash at first draw.
  - Must show 5 draws in every frame, a stable program per ordinal, unit-0 texture 178×157 at ordinal 4, the MVP on the
    from→to segment within 1 px, and one new canvas/context per move.
  - Must read B under ROI_top (§8) every frame: it must equal the empty-canvas patch within 1, or ROI_top is shrunk.
  - Must show the 3→4 move leaves MMO idle (no entry, no arm).
  - Reconcile the F-10 sentinel ("the frame re-sets `Opacity` for programs 0–3 but not 4",
    `tests/test_live_gl_replay_js.py:26–31`) with the per-qualifier cache of §0. The design does not depend on it; the
    fixture's provenance does.
  - Output: sanitized `tests/fixtures/mm_opacity/move_frames.json` with `_provenance`.
- **Q0b.** Scratch patch plus the MO-1 instrument on the same run: patched reads exact, unpatched FAILs (KB), two unpatched
  runs read identically (CvC).
- **Q0c.** Q0a in managed OBS CEF, one take. One OBS at a time, no headless Chrome alongside.

## 8. Gates (blocking unless marked report-only)

**Rule.** A check counts only if its KB (today's bytes) FAILs and its null/CvC reads 0 first. Lossless recordings only
(`utvideo/yuv420p`); binary-counter fixture `output/p2-binary`; one OBS at a time, no headless Chrome during OBS runs; at most
3 headless Chromes.

**Instrument (in page, harness-only; `scripts/mm_opacity_probe.py`).**
- Installed with `Page.addScriptToEvaluateOnNewDocument`, so it runs before every page script and is the **innermost**
  wrapper holding true natives. It sees player draws, MMO's writes and G2's replays alike, and its own `readPixels` never pass
  through G2 (a later, outermost install would be recorded into G2's settle frame and trip G2's unflagged-call guard in LIVE).
- At each ordinal-k draw it reads `B` (ROI, before the native draw) and `P` (after).
- ROI: `fromRect ∩ toRect`, eroded 4 px: inside the square at every z.
- `S` from the MMO-off twin, where `P = S` whatever `B` is; S must be constant, max − min ≤ 1.
- Per pixel, per frame: `E = α·S + (1 − α·S_a)·B`, over premultiplied RGBA; also `α_eff` fitted on G.

**Recording reference (OBS).**
- ROI_top = `fromRect ∩ toRect` minus the movie `instanceRect` (pad 2), eroded 4 px ≈ x 793–810, y 727–785 (Q0a confirms
  what lies beneath).
- `E = α·S_off + (1−α)·B_frame`: `S_off` = the MMO-off take's ROI median over its move frames; `B_frame` = same-frame read
  of an empty canvas patch (x 1150–1200, y 690–780). No RGB value is hard-coded; the tone curve (OD-2 finding 1) is absorbed
  by τ, which is calibrated on slide-1 DOM frames of the same take.

| Gate | Pass | KB (must FAIL) | Null / CvC |
|---|---|---|---|
| **MO-1 per-frame exactness, headless** (GL off; GL on; 1920×1080) | every player frame of the move is probed (probed == frames, ≥ 20); each frame to build 1: max \|P − E\| ≤ 1, α_eff within 1/255 of α | MMO off → α_eff = 1; splice α² → FAIL | MMO-off vs MMO-off-2: residual 0 with α = 1, S series identical; 3→4 move pixel-identical MMO on vs off |
| **MO-2 managed OBS recording** (`--arm mmo`, rates 25 and 30 × sessions g2 and g2-off, MMO `auto` and `off`, n = 1; CvC pair at g2/25; new phase `mm-move` just before `advance`) | R1: 0 frames within τ of `S_off` on ROI_top from `mm-move` to build 1. R2: every frame \|ROI_top − E\| ≤ τ. R3: first GL move frame vs last slide-1 DOM frame, last pre-build-1 frame vs first DOM frame, each ≤ τ. R4: key alpha (GetSourceScreenshot at settle, g2-off) on ROI_top within τ_key of the slide-1 DOM key on the same ROI. Report-only: wrapper time per frame p50/p95, cadence | `off` twin FAILs R1–R4 | τ = max(on vs off slide-1 DOM frames, instrument \|DOM − E\| on slide-1 frames) + 1; τ_key likewise from slide-1 key frames; CvC reads ≤ 2 before τ is set |
| **MO-3 MO-1 inside CEF** (one extra **unrecorded** managed session) | same pass as MO-1 | | |
| **MO-4 G2 interplay** (headless P2 G2 arm + one managed g2 take from MO-2) | `restOpacity[4] === 1`; `opacityUnproven == []`; override applied; MMO suspended exactly once, 1 program written back, 0 MMO writes while suspended; G2 LIVE `greenRGB` equal to the MMO-off G2 run (±0); frameLen 88; occluded 20/128. Forced G2 stand-down in ARM-POST: the stand-down replay reads α_eff = α | splice MMO without the suspend check → `rest-opacity` unproven and LIVE opaque | MMO-off G2 vs itself |
| **MO-5 MMO fail-closed** | Node sandbox: every reason. Headless: `mvp` (at pin) and `count` (mid-move) via seed: one `mmopacity-stop`, write-back done, α_eff = 1 from the failing frame on, 0 GL errors | bogus reason must not read as expected | MMO-off frames equal |
| **MO-6 regression** | P2 verdict fast/slow/bridge-off (MMO injected via W5), probe A/B/C + V/Voff at 3 viewports, `2x`/`positive` cadence arms within OD-2 limits, M8, full suites (`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`) | any change is root-caused, never retuned | |
| **MO-7 owner eyeball** | on vs off, GL on and off, side by side (`--keep-recordings`) | | |

## 9. Work streams (disjoint files; Opus MEDIUM implementers; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | scratch | Q0a–Q0c. **Blocks all.** |
| W1 | `src/obed_edom/live_continuity.py`, `tests/test_live_continuity.py` | §3; byte-identity tests for `effect_opacity_overrides` and `derive_plan`; MMO-only exclusions; P2 table == G2 entry overrides; `gl-decks` parity (one patch, slot 4) |
| W2 | `src/obed_edom/live_mm_opacity_js.py`, `tests/test_live_mm_opacity_js.py`, `tests/fixtures/mm_opacity/` | §4–§5; Node sandbox with a scripted multi-frame fake GL: pin rules, set-before-every-draw, write-back ordering, every stop reason, suspend/resume on G2 state and canvas id, install refusal after G2, pinned sha, table validator mirrored in Python; cross-module test with the real G2 bytes (rest 1, override applied, one suspension) |
| W3 | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | §6: precedence table, invalid env refused before resources, served order, off byte-identity, report |
| W4a | `scripts/mm_opacity_probe.py`, `tests/test_mm_opacity_probe.py` | instrument, scorer, KB splices (synthetic tests) |
| W4b | `scripts/managed_obs_qualify.py`, `scripts/obs_cadence_decode.py`, their tests | `--arm mmo`, phase `mm-move`, ROI series, R1–R4; imports W4a |
| W5 | `scripts/p2_recovery_html_adversarial.py`, its tests | inject MMO first (`GL_SERVED_ORDER` :351 gains `mmo`), parity with the product |

- If D4 = explicit release, W2 adds `release(gl)` and a W6 edits `live_gl_replay_js.py` + re-pins, and the G2
  re-qualification list of §5 joins the gates.
- **Order.** W0 → (W1 ∥ W2) → (W3 ∥ W4a) → W4b → W5 → gates → docs (README, SKILL, runbook, handover, hall) → Opus review →
  one PR. No merge without the owner.
- **Reviewer brief.**
  1. Can MMO ever patch a draw that §4 did not prove?
  2. Can any path leave α on a program while G2 reads or replays it?
  3. Does MMO call only natives, so none of its calls reach G2's recorder?
  4. Does `off` inject nothing?
  5. Does every threshold trace to a measurement or an in-run CvC?

## 10. Owner decisions (each with a recommendation)

0. **Route (coordinator, re-opens arming D2).** D2 said "no `main.js` edit" because an edit breaks on a Keynote update. The
   host already serves an in-memory, sha-pinned, anchor-counted patch of `main.js` (`live_runtime.patch_player`,
   `live_runtime.py:94–103`), and any other player sha already refuses live output, so that failure mode is fail-closed today.
   The defect sits in one unique expression (`var T=i.hidden?0:e.parentOpacity*i.opacity;d!==U&&(T=d+(U-d)*K)`, count 1,
   byte 2190382) plus the parent-opacity recursion (byte 2264145) and the no-animation branch (byte 2192635).
   - **(A) MMO, this plan:** GL prototype wrapping, per-draw identification + MVP proofs, G2 suspend coupling; no player bytes.
   - **(B) Player patch:** two or three anchored replacements in `patch_player` so the player computes Keynote's value itself
     (chain product of each node's animated-else-model opacity; constant leaf animations honoured). No GL wrapping, no draw
     identification, every Magic Move and every output covered, no G2 suspension. Costs: rendering (not just observation)
     moves into `patch_player` (`RUNTIME_VERSION` bump, P2/probe re-run); G2 would read `restOpacity` 0.2947 ≠ 1 on slot 4, so
     G2 needs a decision (accept rest == override as proven — G2 re-pin + targeted re-qualification — or drop the override
     offline); wrapper-level fades stay out of scope as in (A).
   *Rec: (B)* — far smaller surface and generic; if chosen, the planner redoes §2–§9 for (B) as rev 3 (§0, §1 census, §7 Q0
   and the §8 gate instruments carry over). Decisions 1–5 below were written for (A); 1–3 and 5 still apply to (B).

1. **Scope.** *Rec: every Magic Move in the deck*, gated per transition by the closed vocabulary. Alternative: `glReplay`
   boundaries only, which leaves GL-off and movie-free decks opaque.
2. **Default and surfacing.** *Rec: `auto` on HDMI, managed OBS and external attach*, independent of the continuity checkbox
   and GL replay; `OBED_LIVE_MM_OPACITY=off` opts out; `mmopacity-stop` goes to the page API and session log only in v1.
   Alternative: mirror GL replay (on only under managed OBS).
3. **v1 support set.** *Rec: constant-opacity slots only (§1).* Before default-on, the owner authors one small Q-deck: a
   translucent object that fades across a Magic Move, two translucent objects, a translucent object in a group, and α₁ → α₂
   between slides, so the exclusions are **measured** refusing (precedent: arming D3).
4. **G2 hand-back.** *Rec: implicit suspend* on G2's public `state` + armed `canvasId` (§5): no G2 bytes change, no G2
   re-qualification, stand-downs stay translucent. Alternative: explicit `release` line in G2's `armPost` (visible in G2's
   bytes; costs a G2 re-pin, a targeted re-qualification incl. managed M1–M5, and opaque stand-downs).
5. **Residuals.** *Rec: accept for v1* the §5 residual pops (G2 slot-4 unproven at LIVE; MMO stop mid-move); follow up if
   ever seen on air.
## 11. Risks and out of scope

**Risks.**
1. Player-internal structure (one draw per texture in order, one program per `eB`, unit 0 sampled, one mat4 uniform) rests on
   the §0 code-read plus Q0. A Keynote update changes the player sha and `patch_player` refuses the host outright
   (`live_runtime.py:96`).
2. Only **one** translucent-Magic-Move instance exists on disk; every other shape is excluded by rule until D3's deck exists.
3. 17/26 real Magic Move effects fall outside the vocabulary and get no patch (none is translucent today).
4. Wrapper order: asserted at MMO install; the W2 cross-module test pins it.
5. The instrument's `readPixels` perturbs timing, so it never runs in a recorded or cadence session.
6. Recording YUV/4:2:0 and tone-curve error are absorbed by in-take τ, never assumed 0.
7. Suspension reads G2's `state` and events: a future G2 change to either must keep the W2 cross-module test green.

**Out of scope.** Fades or any from ≠ to opacity; wrapper fades; groups; other WebGL effects that share `eB` (content-aware
builds and transitions, `class SB`, byte 2260586; a WebGL build drawing on the move canvas fails closed on `count`); extending
the vocabulary; go-to and backward navigation (DOM-painted destinations; if the player ever animated one, MMO arms by hash and
applies the same proofs); any `main.js` edit; G2's LIVE semantics; the midtone LUT (OD-2 finding 1).

## 12. Critique log (rev 1 → rev 2)

Coordinator (post rev 2): OD-2 merged (#229), base updated, old D6 (timing) dropped; decision 0 added.

| # | Class | Change |
|---|---|---|
| 1 | correctness | OD-2 ref: no `origin/` branch exists; pinned the local branch tip `209063b5` (rev 1 said `69588782`, an ancestor). |
| 2 | correctness | §0 re-verified: per-`eB` programs and per-program qualifiers (no cross-slot cache), draw-per-texture with no skip, `useProgram` before every draw, one `clear` per frame, canvas backing = authored size, one canvas per scene. Root cause and the product value confirmed, including after the move. |
| 3 | correctness | Absolute vs multiplicative: justified absolute for the v1 set; noted what a fade extension would need. |
| 4 | correctness | The player applies the **last** animation's easing to scale/rotation; the one-z MVP proof needs shared timing, added as MMO rule 3. |
| 5 | simplification | Patch set = unchanged `effect_opacity_overrides` output minus MMO-only rules. Dropped rule 8 (`playerOpacity`), the refactor of per-slot work, and the host's G2 equality guard (equal by construction). |
| 6 | correctness | `mm_opacity_table` must not inherit `derive_plan`'s whole-deck refusal of unknown transitions; last slide has no entry. |
| 7 | correctness | MMO must capture natives for every GL method it **calls**, not only the ones it wraps; otherwise its calls reach G2's recorder. Upload/binding bookkeeping is always on (uploads precede arming). No per-draw `getError`. |
| 8 | correctness | Hand-back: rev 1's explicit release left **every** stand-down from ARM-POST on opaque (G2's stand-down replay uses program state), not only LIVE-guard ones. New rec: implicit suspend/resume on G2's public `state` + `canvasId`, zero G2 bytes, no G2 re-qualification; explicit release kept as the alternative. |
| 9 | missing | Residual added: G2 LIVE with slot 4 unproven for another reason pops translucent → opaque. |
| 10 | gate | Instrument moved to `addScriptToEvaluateOnNewDocument` (innermost). Rev 1's outermost install after load would have its `readPixels` recorded into G2's settle frame (frameLen ≠ 88) and trip G2's unflagged-call guard in LIVE. |
| 11 | gate | MO-1 frame floor: "probed == player frames" instead of a rate formula the instrument's own stalls could fail. Dropped the letterbox arm from MO-1 (canvas backing is viewport-independent; MO-6 covers viewports). Added the 3→4 move as a free null. |
| 12 | gate | MO-3 key alpha folded into MO-2 as R4 and referenced to the slide-1 DOM key, not a hard-coded 75 ± 3 (tone curve). MO-8 cost folded into MO-2 report-only. MO-2 trimmed to n = 1 per cell plus one CvC pair. MO-5 headless reduced to one pin-time and one mid-move reason; all reasons in the sandbox. |
| 13 | missing | Q0a now checks what lies under ROI_top each frame, one context per move, and the 3→4 idle case. |
| 14 | simplification | Work streams 8 → 7 (G2 edit only under the explicit alternative); owner decisions 10 → 6: dropped gate reference (D7) and P2 parity (D9) as technical, merged surfacing into default, merged re-qualification into hand-back. |
