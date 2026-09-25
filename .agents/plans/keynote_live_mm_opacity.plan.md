# Magic Move translucent opacity: draw the authored opacity from the first frame of the move

**IMPLEMENTED (2026-09-25, pending PR)** on `claude/mm-translucent-opacity`. **APPROVED (owner, 2026-09-25)**, **rev 4**, 2026-09-25. Rev 1: Opus planner. Rev 2: Opus critic. Rev 3: Opus planner, rewritten for
**route (B)**, the owner's choice: a sha-pinned, in-memory player patch. Rev 4: Opus critic (§14 Critique log). Plan only: no product code, no
commits, no OBS, no Keynote.
**Builds on OD-2**: MERGED as #229 (`8fe3b551`); this branch (`claude/mm-translucent-opacity`) is rebased on it. It holds the
GL-replay default in Keyer mode, the binary-counter fixture and `scripts/managed_obs_qualify.py` / `scripts/obs_cadence_decode.py`.
Line numbers are read on this branch (`1de28cc2`).
Parents: `keynote_live_gl_replay_arming.plan.md` (owner answer D2, re-opened by decision 0 and now answered by B), the pruned
opacity plan `git show 0d511a9c^:.agents/plans/keynote_live_gl_replay_opacity.plan.md` (§0 measurements, F-1…F-12),
`.agents/reviews/gl-replay-managed/gates-r1.md` (M7 known limit).

## 0. Facts (code-read and offline, 2026-09-25; rev 2 re-read every player citation)

Offsets in §0 are **character** offsets into the UTF-8-decoded file (rev 1/2 convention). Byte offsets, which
`patch_player` works on, are +15 at every site cited here (e.g. `var T=…` is char 2190382, byte 2190397). §3 anchors are
exact byte strings, so offsets are informative only.

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

**Census of every export on disk.** 26 distinct Magic Move effects under the main checkout's `output/` (`gl-decks`, `p2-*`,
`qual-decks/D1–D6`; scratch scripts `scan_mm2.py`, `eoo.py`):
- exactly **one** translucent Magic Move slot: this slot 4 (P2 deck, Minimal Alpha_DSK, and the loop copy);
- every fade (1→0 or 0→1) is on the **leaf** with ancestors at 1, which the player already draws correctly;
- no wrapper-level fade; no `initialState.opacity < 1` outside slot 4;
- `effect_opacity_overrides` returns `Unsupported` for 17 of the 26 effects (`texturedRectangle.textColor` on text leaves,
  D1–D6; `transform.rotation.z`, Minimal S6→S7).


## 1. What the patched player computes (v1 semantics: faithful or unchanged)

The patched player computes one **static** per-leaf value at effect setup: the product, from the effect root down to and
including the textured leaf, of each node's value.
- **Node value** (`__obedNodeOpacity`, the same rule for the root, wrappers and the leaf):
  - with no `opacity` animation: `initialState.opacity`;
  - with exactly one `opacity` animation that has from == to and `fillMode "both"`: that constant. `fillMode "both"` holds the
    value before `beginTime` and after `beginTime + duration`, so the node is constant for the whole effect and the settle
    frame, whatever its timing;
  - otherwise the node is **unexpressible**: a from ≠ to animation (any fade, wrapper or leaf), two opacity animations, a
    constant animation with another `fillMode`, a `hidden` animation, `initialState.hidden`, a non-finite value, or a throw.
- One unexpressible node makes every leaf below it **legacy**: today's arithmetic, unchanged (per subtree, never global).
  A textured root is legacy too.
- So leaf fades keep exactly today's per-frame lerp. On disk every fade has ancestors at 1, where Keynote and today's player
  agree; a fade under a translucent constant wrapper stays today's look (residual, decision 5).
- Untouched on purpose: `e.parentOpacity` (still the root value, read elsewhere in the player).

For slot 4 the root is 1 (no animation), the wrapper animates 1→1 `both` (so 1, **not** its model 0.2947), and the leaf animates
0.2947→0.2947 `both` (so 0.2947). The product is **0.2947**, the same at t = 0, mid and settle. Nothing squares: each node
contributes exactly one value, its animated one when it has a constant animation and its model one otherwise.

## 2. Where the fix lives

- **(B) CHOSEN: an anchored, count-checked replacement set in `src/obed_edom/live_runtime.py:patch_player`** (:94–103). The
  patch is in memory only, so nothing on disk changes, and it is pinned to `PLAYER_SHA256` `e9b2fad4…`: any other player
  already refuses live output (:96).
  - Every WebGL effect that draws through `eB` is covered on every output: Magic Move (`pB`) and the content-aware
    `ca-text-shimmer`/`-sparkle` transitions (`SB`; `new eB(` occurs exactly twice).
  - It needs no GL wrapping, no draw identification and no G2 coupling.
- **Rejected: (A) MMO**, a GL-prototype-wrapping module with per-draw identification, MVP proofs and a G2 suspend/resume
  coupling. See rev 2 at `1de28cc2` (§1–§9 there). It was rejected by the owner for its surface, not because it was wrong.
- (b) continuity core and (c) G2-only stay rejected for rev 2's reasons: a DOM-only core, and G2 acts only from ARM-POST on
  allowlisted decks.

## 3. Exact replacements (all on sha `e9b2fad4…`; each anchor `count == 1` before replacing, each replacement `count == 1` after)

The existing `_ANCHOR` observation hook is unchanged. The replacements live in one tuple, `_MM_OPACITY_REPLACEMENTS`, applied
only when `mm_opacity=True`. Rev 4 cut rev 3's six anchors to **four** (R5, added after live MO-2, makes **five**; R1 also refuses nested animation groups, Opus r1 F4): the leaf is valued by the same node rule at setup, so
the per-frame `__obedOp` flag (rev 3 R3, R4) and its fade arithmetic are gone.

| # | Where (byte) | Before | After |
|---|---|---|---|
| R1 | `fB.textureInfoFromEffect` definition (2263373) | `textureInfoFromEffect(A,B,g,C,Q){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,A.textureId){` | `__obedNodeOpacity(A){try{var B=A.initialState,g=null,C=0,Q=A.animations\|\|[];for(var e=0;e<Q.length;e++)for(var t=Q[e].property?[Q[e]]:Q[e].animations\|\|[],i=0;i<t.length;i++)"opacity"===t[i].property?(g=t[i],C++):("hidden"===t[i].property\|\|t[i].animations)&&(C=2);var o=B.hidden\|\|C>1?null:g?g.from.scalar===g.to.scalar&&"both"===g.fillMode?g.to.scalar:null:B.opacity;return"number"==typeof o&&isFinite(o)?o:null}catch(E){return null}}__obedChainOpacity(X,A){if(null===X)return null;var B=this.__obedNodeOpacity(A);return null===B?null:(void 0===X?1:X)*B}textureInfoFromEffect(A,B,g,C,Q,X){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,e.obedOpacity=void 0===X?null:this.__obedChainOpacity(X,A),A.textureId){` |
| R2 | recursion (2264160) | `this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q)` | `this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q,this.__obedChainOpacity(X,A))` |
| R3 | `QB.renderFrameWithContext` Opacity write (2190397) | `d!==U&&(T=d+(U-d)*K),A.setGLFloat(T,"Opacity")` | `d!==U&&(T=d+(U-d)*K),null!=e.obedOpacity&&(T=e.obedOpacity),A.setGLFloat(T,"Opacity")` |
| R4 | `eB.drawFrame` no-animation branch (2192650) | `var w=e.initialState.hidden?0:this.parentOpacity*e.initialState.opacity;` | `var w=e.initialState.hidden?0:null!=e.obedOpacity?e.obedOpacity:this.parentOpacity*e.initialState.opacity;` |
| R5 (added in implementation) | `animateEffectWillBegin` DOM swap (2317031) | `Q&&setTimeout(this.handleAnimateEffectDidBegin.bind(this,Q),0)` | `Q&&this.handleAnimateEffectDidBegin(Q)` |

(`\|` above is a Markdown escape of `|`.)

- **How it works.**
  - `setupTexture`'s call (byte 2263111) is **not** changed. It passes 5 arguments, so `X` is `undefined` at the root: the root
    (textured or not) gets `obedOpacity` `null`, and R2 multiplies the root's own node value at the first descent.
  - At a textured leaf, R1 stores the full product including the leaf's own node value, or `null` (legacy).
  - R3 and R4 compute today's `T`/`w` first, unchanged, and replace it only when `obedOpacity` is set. In
    `renderFrameWithContext`, `e` is the loop's `g.textureInfo` and is never reassigned in the loop; in R4 `e` is
    `this.texture`. Both are the objects R1 built (`setupTexture` → `textures` → `eB`).
  - Class bodies are strict mode; every added name is a method, a parameter or a property (no implicit globals). Every name
    carries an `__obed`/`obed` prefix, which occurs 0 times in the stock player.
- **Measured, 2026-09-25, scratch** (`scratchpad/patch_c.py`, `beh_c.py`, `census_c.py`; no Chrome):
  - all four anchors `count == 1` on the real bytes, every replacement `count == 1` after; `node --check` passes;
  - the real patched `QB` and `fB` methods, extracted and run in Node on `effect_1_to_2.json` (easing stubbed linear), give
    Opacity per slot `[1,1,1,1,0.2947]` at p = 0, `[1,0,1,1,0.2947]` at 0.5 and 1; stock gives `[1,1,1,1,1]` / `[1,0,1,1,1]`.
    Identical to rev 3's six-anchor result.
- **Refusal.** A missing or duplicated anchor raises `LiveRuntimeUnsupported`, as `_ANCHOR` does. On the pinned sha this is a
  static fact that the tests prove.

## 4. Why the patch is safe to reason about

- **One writer.** The player's own `setGLFloat(T,"Opacity")` carries the corrected T. The per-qualifier cache (§0) then writes
  `uniform1f` once for a constant T, exactly as today. No external `uniform1f`, so there is no stickiness to undo and nothing
  that can double-apply.
- **Static per effect.** The whole product is computed once in `setupTexture` (per effect, per play); no per-frame logic is
  added.
- **Faithful or unchanged.** Every case the rule cannot express keeps today's arithmetic (§1).

## 5. Blast radius (census, offline, pinned as a test)

Scope: only `eB` consumes the changed value (R3, R4). Verified on the bytes: `textureInfoFromEffect` has one definition, one
caller (`fB.setupTexture`) and the recursion; `setupTexture` has one caller (`fB.draw`, every effect type); `renderFrameWithContext`
has one definition and one caller (`eB.drawFrame`); `new eB(` occurs twice, in `pB` (Magic Move) and `SB` (whose subclasses `RB`,
`uB` are the `ca-text-shimmer`/`-sparkle` transitions; their text leaves go to `JB`/`mB`, not `eB`). Builds (`buildIn`/`Out`,
`smartBuild`) never construct `pB`/`SB`/`eB`. Every other class receives `obedOpacity` on its textures and never reads it.

Census over every export under the main checkout's `output/` (the 20 `header.json` roots), with effects de-duplicated by
content. Scratch `scratchpad/census_b.py` mirrors old vs new in Python at p ∈ {0, 0.5, 1}:
- 26 Magic Move transitions, 0 shimmer/sparkle transitions, **110 `eB`-drawn leaves**; 51 fall back to the legacy value (all via a leaf `hidden` animation; values unchanged, Opus r1 F11);
- rev 4's four-anchor mirror (`census_c.py`) gives the same result;
- **exactly one leaf changes: the 1→2 Magic Move slot 4, 1 → 0.2947 at all three points** (P2, `p2-binary`, `p2-loop` and
  `gl-decks/Minimal Alpha_DSK` share the same effect);
- every other leaf, including the 3→4 move, the Positive Control moves, the D1–D6 text moves and every fade, is identical.

**Pinned test** (W1): the same old/new mirror lives in `tests/test_live_runtime.py`. It runs on the committed
`tests/fixtures/live_continuity/` effects (P2 1→2 must change slot 4 only; every other committed effect must be unchanged) and,
REAL-gated, sweeps `output/` and asserts the changed set equals `{1→2 slot 4}`. "Unchanged" is **exact float equality**
(the scratch used 1e-9): an unchanged leaf must feed the same bits to `uniform1f`. The mirror is backed by the Node
behavioural test on the real extracted methods, so it cannot drift from the bytes unnoticed.

## 6. Versioning, switch, host wiring

- **`RUNTIME_VERSION` stays 2; no new version constant.** It versions the observation contract, not rendering. Its
  consumers (in-page literal `live_runtime.py:63`; start log `live_host.py:1033`; goto-autoplay gate `:1159`, `:1316`;
  `web/live.py:239` `runtimeRevision`; P2 boot check `p2_recovery_html_adversarial.py:662`; `scripts/live_host_probe.py:130`;
  tests `test_live_host.py:36`, `test_p2_adversarial_gl_replay.py:752`) all concern the hook, which B leaves byte-identical.
  A bump would defer every goto autoplay (constant only) or break off-path identity (constant + literal). Rev 3's
  `PLAYER_PATCH_VERSION` is dropped: the served `main.js` sha already identifies the rendering bytes exactly.
- **API.** `patch_player(player, *, mm_opacity: bool = True)`. With `False`, the output is byte-identical to today's
  (observation hook only; pinned by a test that hashes the synthetic-player output both ways).
- **Switch.**
  - `LiveOutputHost(mm_opacity=_UNSET)`, where the ctor wins over env `OBED_LIVE_MM_OPACITY`. Values are `off|auto` (trimmed,
    any case). Anything else raises in `start()` before the log, the server or CDP, like `GL_REPLAY_ENV` (`live_host.py:1037–1043`).
  - Default **`auto` on every output**: HDMI, managed OBS, external attach.
  - `start()` calls `patch_player(player, mm_opacity=pref == "auto")` (`live_host.py:1064`).
  - `web/live.py` passes no kwarg (env default), so it needs no code change.
- **Report.**
  - `output.mmOpacity = {"mode": "on"|"off", "sha256": <sha of the served main.js>}` (`:1006` area). It reaches the session
    identity (`web/live.py:240`, `"output": {**host.output, …}`) automatically.
  - The start log gains `mmOpacityPreference`.
  - Nothing runtime to surface: there are no runtime proofs.

## 7. G2 interaction (patch on; with patch off G2 is byte- and behaviour-identical to today)

With B the player writes `Opacity` 0.2947 for slot 4's program on the first frame. G2's capture replay reads
`restOpacity = [1, 0, 1, 1, 0.2947]`, and `proveOpacity` requires `restOpacity === 1` (`live_gl_replay_js.py:807`). So slot 4
becomes `glreplay-opacity-unproven{slot 4, "rest-opacity"}`: no override is applied, and LIVE replays **rest = 0.2947**, the
correct pixels. The stand-down replay (`rest: true`, :927) is now translucent (better than today).

| Option | G2 bytes | Plan/allowlist | Reporting | Cost |
|---|---|---|---|---|
| **(iii) leave G2 as is: RECOMMENDED** | unchanged | unchanged | one `rest-opacity` note on slot 4. This is the documented fail-closed meaning ("the player already draws its own value; keep it"), and it is now correct pixels | none; re-baseline the facts below |
| (i) accept `\|rest − override\| ≤ 1e-6` as proven no-op | +1 line at :807 | unchanged | clean | re-pin `PINNED_JS_SHA256` (`tests/test_live_gl_replay_js.py:140`), OD-2 `G2_SHA` and the `frozen` KB sha; `GL_REPLAY_VERSION` stays 1 (core :531); targeted re-qualification (headless gates 1, 2, 6, N1–N3, P2 G2 arm, managed M1–M5) |
| (ii) drop the override offline when the patch is on | unchanged | `derive_plan`/`to_runtime` depend on the patch mode, so a second `QUALIFIED_PLAN_SHA256` entry, P2 plan literals, host plumbing | clean | largest; couples continuity derivation to a player option |

Why (iii) is safe:
- No gate asserts `opacityUnproven == []` on a live run. It is asserted only in Node sandbox tests over the fake settle frame
  (rest 1), which are unaffected.
- `p2_verdict` only keeps the note kind (:162). The core only lists it (`live_continuity_js.py:469`).
- **No double application by construction**: G2 applies no override on slot 4 (`unproven` deletes it, :670), and the player
  wrote the value once. MO-4 proves it on pixels: patch-on G2 LIVE == patch-off G2 LIVE (override α), ±0; an α² bug reads
  darker.
- Re-checked paths: `rest-opacity` fails before any ablation replay of slot 4 (:807), so `skip`/`only` replays never run for
  it; LIVE `opacityFor` returns rest 0.2947 (:495–499); `standDown` writes back only slots with overrides (none) and replays
  rest (:888–927), translucent; `score_armed` (`live_continuity_probe.py:1554`) does not read unproven notes; `p2_verdict`
  lists the kind only as a fetch filter (`GL_REPLAY_KEEP_KINDS`, :156).
- With the note now expected, a harness that reads notes asserts the **exact** set `[{4, "rest-opacity"}]` (patch on) and
  `[]` (patch off), so a second unproven slot cannot hide behind it.

**Re-baselines under (iii)** (measured in Q0, never retuned):
- `restOpacity` / `opacityAfterProofs` slot 4 = 0.2947.
- `opacityUnproven = [{4, "rest-opacity"}]`.
- **`occludedBands`**: G2's marker swap runs before any override, and now sees the square translucent, so the bands under it
  stop reading occluded. This is expected in `managed_obs_qualify.EXPECTED_STATS` (:106, 20/128), in the gate-r2 and OD-2
  records, and in any probe expectation. Those bands then score as live, which is correct. The probe's V arms read G2's own
  mask (`occluded_screen_cells`, `live_continuity_probe.py:2405`) and follow automatically.
- **M3** (`managed_obs_qualify.py:880–905`): with the patch on, `g2-off-S` is translucent, so "edge: G2-S == round(g2-off-S ×
  0.2947)" would square and "KB: g2-off-S T alpha fails the slot check" would pass. Both move to the `mm-off` twin (§8).

## 8. Harness parity

| Harness | How it gets the patch | Re-baselines |
|---|---|---|
| `scripts/live_continuity_probe.py` | through `LiveOutputHost` (default `auto`); no MMO KB arm here (the MMO known-bad lives in `mm_opacity_probe.py`; Opus r1 F5) | no G2 fact asserted; V/Voff re-confirmed at default `auto` (round `01a9ff55`: identical to baseline) |
| `scripts/managed_obs_qualify.py` | through `LiveOutputHost`; refuses to start if `OBED_LIVE_MM_OPACITY` is set (as for GL replay, :27); new `mm-off` twin sessions pass `mm_opacity="off"` | `EXPECTED_STATS.occludedBands`. M3's edge check `round(g2-off-S × 0.2947)` and its KB assume `g2-off` is opaque, so the opaque reference moves to the `mm-off` twin. `T alpha (G2-S)` 75 is unchanged |
| `scripts/p2_recovery_html_adversarial.py` | today it serves the **stock** `main.js` from disk unless `--gl-replay auto` (`_patched_main_js` is called only under `gl_auto`, :3332). Gains `--mm-opacity auto\|off` (default `auto`): `auto` serves `patch_player(raw, mm_opacity=True)` in **every** arm; `off` keeps today's bytes per arm (stock for non-GL arms, `mm_opacity=False` under GL). Records `mmOpacity` beside `patchedMainJsSha256` (not pinned). The test's `patch_player` monkeypatch lambda (`test_p2_adversarial_gl_replay.py:739`) takes the new kwarg | slide-2 screenshot scores (`greenFront` still greenish over a neutral grating, since G − R ≈ 43 > 15); `greenTranslucentPre` is on DOM slide 1, so it is unchanged; any move is root-caused |
| `src/obed_edom/html_alpha_probe.py`, `html_preview.py` | serve the unmodified `main.js` (a paint-oracle probe and the dashboard preview, not on air) | none; out of scope (§13) |

## 9. Qualification before product code (Q0; one headless Chrome at most)

- **Q0a (done offline, §3).** Anchor counts, `node --check`, and the Node behavioural run on the extracted methods.
- **Q0b (headless, `output/p2-binary`, GL replay off and on, patch on and off).**
  - A scratch innermost logger (§10 install rule) records per frame every `uniform1f(Opacity)` per program.
  - It must show slot 4's program written 0.2947 at the effect's first draw, and every other program identical on vs off.
  - It reads the G2 facts of §7 (rest, unproven, **occludedBands**).
  - It validates the MO-1 instrument: patched reads exact, patch-off FAILs, and two patch-off runs read identically.
  - It records the settle-frame buffer hash of the 1→2 and 3→4 moves, twice per mode, to prove MO-5's CvC reads 0.
  - It reconciles the F-10 sentinel with the §0 cache (fixture provenance only).
- **Q0b RESULT (2026-09-25, headless, 8 runs + 2 full-call, load 7.5–11.4):** slot 4 written α once at the move's first
  draw and α on all 84 move draws (off: 1); ordinals 0/2/3 and 3→4 identical on vs off; slot-1 fade differs only by frame
  timing (on–off 0.0039 ≤ off–off 0.0045). G2 patch on: rest = after-proofs `[1,0,1,1,0.2947]`, unproven exactly
  `[{4, rest-opacity}]`, **occludedBands 0/128**, LIVE, frameLen 88, 0 glErrors; patch off identical to today (20/128).
  LIVE green on vs off ±0 (≈ 8.9, 51.6, 0, 74). 3→4 settle hash equal in every pairing; 1→2 differs on vs off.
  **Instrument amendments:** (1) the 4-px erosion catches the square's 1-px AA edge at ~2× (x = 793, α 218 → 3.06–10.7);
  scale-aware erosion (≥ 5 px) reads ≤ 0.50, and the scorer requires S opaque in the ROI; (2) GL-on 1→2 settle hash
  carries the movie frame at the advance, so the movie instance rect is masked. **F-10 sentinel does not hold on the real
  player:** no settle-frame `uniform1f(Opacity)` for any program (cache writes only on the first frame and slot-1 fade
  steps); harmless, G2 writes `Opacity` before every replayed draw. Every GL-on run retires `canvasRemoved` after the slide
  change, on and off alike. W6 not needed (only `managed_obs_qualify.EXPECTED_STATS` asserts occludedBands).
- **Q0c.** Q0b's logger in managed OBS CEF, one take. One OBS at a time, with no headless Chrome alongside.

## 10. Gates (blocking unless marked report-only)

**Rule.**
- A check counts only if its KB (**patch off = today's player bytes**) FAILs and its null / control-vs-control (CvC) reads 0
  first.
- Lossless recordings only (`utvideo/yuv420p`), on the binary-counter fixture `output/p2-binary`.
- One OBS at a time, no headless Chrome during OBS runs, and at most 3 headless Chromes.

**Instrument** (`scripts/mm_opacity_probe.py`). With B the shader is untouched and the only change is the value the player
passes to `uniform1f`, so the headless proof is the uniform in effect at each draw, plus one pixel check at settle. Rev 3's
per-frame `readPixels` pair (a sync stall on every frame, inside G2's recording window) is dropped.
- It is installed with `Page.addScriptToEvaluateOnNewDocument`, so it is innermost and holds true natives. It wraps
  `useProgram`, `uniform1f`, `clear`, `drawArrays`, `drawElements`; it only records (program → last `Opacity` value, and at
  each draw the value in effect for the current program with its clear-delimited ordinal). Its only own GL calls are
  `getUniformLocation`/`getParameter` once per program and one `readPixels` pair at the settle draw, all skipped by G2's
  `SKIP` (`live_gl_replay_js.py:251`).
- Pixel check, settle draw only (the last player frame of the move, at ordinal 4): B (ROI, before) and P (after), ROI =
  `fromRect ∩ toRect` eroded 4 px; S from the patch-off twin (P = S whatever B is); `E = α·S + (1 − α·S_a)·B` over
  premultiplied RGBA.
- A GL-on run is **void** (neither pass nor fail) if G2 stands down in either twin.
- The **recording reference** is rev 2's ROI_top (≈ x 793–810, y 727–785; under it only the transparent canvas or the black
  sentinel). `E = α·S_off + (1−α)·B_frame`, where B_frame is a same-frame read of an empty canvas patch. τ is calibrated on
  slide-1 DOM frames of the same take.

| Gate | Pass | KB (must FAIL) | Null / CvC |
|---|---|---|---|
| **MO-1 uniform + settle blend, headless** (GL replay off; on; 1920×1080) | every slot-4 draw of the move, from the **first** (≥ 20 draws), and every G2 LIVE replay draw to build 1: `Opacity` in effect == α (float32); every other ordinal's value sequence identical to the patch-off twin; settle max \|P − E\| ≤ 1 | patch off → 1; splice `__obedNodeOpacity` returning the model value → α² → FAIL | patch-off vs patch-off-2: uniform logs identical, settle P identical |
| **MO-2 managed OBS recording** (`--arm mmo`: rates 25 and 30 × GL-replay sessions g2 and g2-off × patch on/off, n = 1; CvC pair at g2/25; phase `mm-move` just before `advance`) | R1: 0 frames within τ of `S_off` on ROI_top from `mm-move` to build 1. R2: every frame \|ROI_top − E\| ≤ τ. R3: first GL move frame vs last slide-1 DOM frame, and last pre-build-1 frame vs first DOM frame, each ≤ τ. R4: key alpha (GetSourceScreenshot at settle) on ROI_top within τ_key of the slide-1 DOM key. Report-only: cadence vs patch-off | patch-off twin FAILs R1–R4 | τ = max(on vs off slide-1 DOM frames, instrument \|DOM − E\| on slide-1 frames) + 1; τ_key likewise; CvC reads ≤ 2 before τ is set |
| **MO-3 MO-1 inside CEF** (one extra **unrecorded** managed session) | as MO-1 | as MO-1 | as MO-1 |
| **MO-4 G2 interplay** (headless P2 G2 arm + the MO-2 g2 takes) | option (iii) facts of §7; LIVE `greenRGB` and the MO-1 residual equal to the patch-off G2 run (±0); a forced stand-down (`debugForceFail` seed) replays at α_eff = α; with patch off, every G2 fact equals gates-r2/OD-2 (rest `[1,0,1,1,1]`, 20/128) | patch-on with the α² splice of MO-1 → LIVE darker than patch-off → FAIL | patch-off G2 vs itself |
| **MO-5 blast radius** | offline census test (§5) green; live: the **settle-frame** buffer hash of the 3→4 move and of one Positive Control Magic Move, patch on vs off, identical (per-frame hashes depend on rAF timing and cannot be compared across runs) | the 1→2 settle hashes differ on vs off | on vs on identical first (Q0b) |
| **MO-6 regression** | P2 verdict fast/slow/bridge-off (patched via W5), probe A/B/C + V/Voff at 3 viewports, OD-2 M-gates touched by §8's re-baselines, `2x`/`positive` cadence arms within OD-2 limits, full suites (`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`) | any change is root-caused, never retuned | |
| **MO-7 owner eyeball** | patch on vs off, GL replay on and off, side by side (`--keep-recordings`) | | |

## 11. Work streams (disjoint files; Opus MEDIUM implementers; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | scratch | Q0b–Q0c. **Blocks W4 re-baselines and the gates**; W1–W3 may start from §3. |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | §3 replacements (four), `mm_opacity` kwarg. Tests: count-check refusal per anchor (0 and 2) on synthetic players (monkeypatched sha, as today); off byte-identity; REAL-gated anchors-on-real-bytes + `node --check` + the Node behavioural test on extracted methods (§3); the §5 census mirror |
| W2 | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | §6 precedence, refusal before resources, report, start log |
| W3 | `scripts/mm_opacity_probe.py`, `tests/test_mm_opacity_probe.py` | instrument, scorer, KB splices (synthetic tests) |
| W4 | `scripts/managed_obs_qualify.py`, `scripts/obs_cadence_decode.py`, their tests | `--arm mmo`, `mm-off` twins, phase `mm-move`, ROI series, R1–R4, M3 reference move, env refusal, `EXPECTED_STATS` re-baseline |
| W5 | `scripts/p2_recovery_html_adversarial.py`, its tests | `--mm-opacity`; serve the patched bytes in every arm under `auto` (§8); report field |
| W6 | `scripts/live_continuity_probe.py`, its tests | only if Q0b shows an asserted G2 fact moving (§7) |

- **Order.** W0 ∥ (W1 → (W2 ∥ W3)) → (W4 ∥ W5 ∥ W6) → gates → docs (README, SKILL, runbook, handover, hall, the arming plan's
  D2 line) → Opus review → one PR. No merge without the owner.
- **Reviewer brief.**
  1. Is every anchor unique and every replacement unique on the pinned bytes?
  2. Is the legacy path's arithmetic exactly today's?
  3. Can any chain get the wrapper's model value instead of its animated value?
  4. Does `off` serve today's bytes?
  5. Does every threshold trace to a measurement or an in-run CvC?

## 12. Owner decisions (each with a recommendation)

**APPROVED 2026-09-25:** route B; decisions 2–6 as recommended. Dashboard preview upgrade = follow-up (§13).

0. **Route: ANSWERED (B)**, 2026-09-25.
1. **Scope: MOOT.** B is inherent to every `eB` effect on every output, and the census shows only slot 4 changes on disk.
2. **Default and surfacing.** *Rec: `auto` on HDMI, managed OBS and external attach*, independent of the continuity checkbox and
   GL replay. `OBED_LIVE_MM_OPACITY=off` (or ctor `mm_opacity="off"`) serves today's bytes. Reported as
   `output.mmOpacity` plus the start log; there is no runtime surfacing because there are no runtime proofs.
3. **v1 support set.** *Rec: faithful-or-unchanged as in §1*: chains of constant (`both`) values exact; any fade, `hidden`,
   multi-animation or non-`both` node leaves its subtree unchanged. Before default-on the owner authors one small Q-deck (a
   translucent object fading across a Magic Move, two translucent objects, one in a group, α₁ → α₂ between slides, a
   translucent wrapper that fades). Each case is measured either exact or unchanged, never wrong.
4. **G2 with B.** *Rec: (iii) leave G2 as is.* The `rest-opacity` note on slot 4 is G2's documented fail-closed path, and it
   now yields correct pixels. Zero G2 bytes, zero allowlist change, no G2 re-qualification; harnesses assert the exact note
   set. Choose (i) if the note must disappear, at a G2 re-pin plus a targeted re-qualification.
5. **Residuals.** *Rec: accept for v1*:
   - fades under a translucent constant wrapper, and wrapper fades, keep today's look (none on disk);
   - the dashboard preview (`html_preview.py`) and the paint-oracle probe still serve the stock player, so the preview shows
     the square opaque during the move while the output is translucent.

(Rev 3's decision 6 is closed as a fact: `RUNTIME_VERSION` stays 2 and no new version constant is added, §6.)

6. **Authored-value oracle (IWA).** *Rec: add one offline test*: read the P2 square's authored opacity from the source `.key`
   with the existing shape-style resolver (`iwa_runs.py:671`) and assert it equals the patch's chain product (0.2947); run the
   same on the Q-deck's shapes. It replaces the export's self-consistency check (product == `singleTextureOpacity`) with an
   independent one. Shapes only; no runtime or host dependency.

## 13. Risks and out of scope

**Risks.**
1. B edits rendering bytes. A Keynote update changes the sha and the host refuses it as today (`live_runtime.py:96`). The
   anchors are exact strings, so a silently shifted meaning is impossible on the pinned bytes.
2. Only **one** translucent `eB` leaf exists on disk. Every other shape is argued from the code-read until decision 3's deck
   exists.
3. The mirror/census uses exact equality; a future export with a non-1 root would change bits on "unchanged" leaves
   (`(1·root)·…` vs `root·leaf`) and the REAL-gated census would flag it before release.
4. G2 re-baselines (occluded bands) may move probe/managed expectations. They are re-measured with a KB, never retuned.
5. The instrument's `readPixels` perturbs timing, so it never runs in a recorded or cadence session.
6. Recording YUV/4:2:0 and tone-curve error are absorbed by an in-take τ, never assumed 0.

**Out of scope.**
- Per-frame wrapper fades.
- Leaf `hidden` animations.
- Non-`eB` WebGL effects (their own classes never read the changed values).
- Extending the `effect_opacity_overrides` vocabulary.
- The paint-oracle probe (`html_alpha_probe.py`) stays stock by design: it refuses a changed `main.js` (`:3024`) and measures
  the player as exported.
- **Follow-up (owner 2026-09-25, not urgent):** dashboard preview (`html_preview.py`) serves the same rendering replacements, so
  authors see Keynote's opacity. Needs the replacements split from the observation hook in `live_runtime.py` (a
  rendering-only function), the preview's `player_digest` / cache contract (`html_preview.py:686`) to key on the served bytes,
  and its own on/off parity test. Separate small PR after this one lands.
  Planned and approved in `dashboard_preview_mm_opacity.plan.md` (serve-time patch; cache and `player_digest` stay stock).
- G2's LIVE semantics.
- The midtone LUT (OD-2 finding 1).
- **Fixed in implementation (R5):** a one-frame DOM+GL double image at a translucent Magic Move start (seen in managed OBS;
  0 of 30 sessions after the fix).

## 14. Critique log

### rev 1 → rev 2

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

### rev 2 → rev 3 (owner chose route B; Opus planner)

| # | Class | Change |
|---|---|---|
| 15 | route | §2–§11 rewritten for (B), the in-memory player patch. MMO (A) reduced to a pointer to `1de28cc2`. §0 facts, the census, the Q0 idea and the blend instruments kept. |
| 16 | correctness | §0 offsets labelled as character offsets; byte offsets are +15 at every cited site. §3 anchors are byte strings with `count == 1` measured on the real bytes. |
| 17 | correctness | Exact R1–R6 replacements. The wrapper's **animated** value is used, not its model value (slot 4: 1, not 0.2947, so 0.2947 and not 0.2947²). A has-animation flag replaces `d !== U`. The no-animation branch is covered. `setupTexture`'s call is unchanged (root handled at first descent). `e.parentOpacity` is untouched (53 other readers). |
| 18 | decision | Wrapper fade / `hidden` / multi-animation / non-`both` constant → legacy for the whole chain (faithful or unchanged). Leaf fades are multiplied by the parent product (Keynote-correct; identical on disk). |
| 19 | measured | Scratch `patch_b.py`/`beh.py`: anchors unique, `node --check` OK, extracted real methods give slot 4 = 0.2947 at p 0/0.5/1 with all other slots unchanged. |
| 20 | blast radius | Only `eB` consumes the change (Magic Move + shimmer/sparkle). Census `census_b.py`: 110 `eB` leaves on disk, one change (1→2 slot 4). Pinned as a W1 test (committed fixtures + REAL-gated sweep). |
| 21 | deviation | `RUNTIME_VERSION` not bumped: it versions the observation contract, and a bump either defers every goto autoplay (constant only) or breaks off-path byte identity (constant + literal). Added `PLAYER_PATCH_VERSION` instead; owner decision 6. |
| 22 | G2 | With B, G2 reads rest 0.2947 on slot 4, so it is `rest-opacity` unproven and LIVE replays the correct rest. Recommended (iii): no G2 change. (i) and (ii) costed. Re-baseline found: G2's marker-swap `occludedBands` (20/128) changes because the occluder is now translucent. |
| 23 | harness | P2 calls `patch_player` directly and needs `--mm-opacity`. Host-based harnesses inherit the default. Managed M3's opaque reference moves from `g2-off` to an `mm-off` twin. Preview/paint-oracle stay stock (out of scope). |
| 24 | correction | Rev 2 row 10's rationale is inaccurate: G2 never wraps `get*`/`read*` (`SKIP`, `live_gl_replay_js.py:251`), so an outer instrument's `readPixels` would not be recorded. The `addScriptToEvaluateOnNewDocument` install is kept anyway (true natives, simplest reasoning). |
| 25 | simplification | Dropped `mm_opacity_table`, the MMO JS module, runtime proofs, fail-closed runtime reasons (MO-5 of rev 2) and the G2 suspend coupling. Work streams 7 → 7 but far smaller (W1 is the core); owner decisions 1 moot, 4 re-cast for B, 6 new. |

### rev 3 → rev 4 (Opus critic)

| # | Class | Change |
|---|---|---|
| 26 | verified | Re-ran all rev 3 anchor counts (6 × `count == 1`), `node --check`, `beh.py` and `census_b.py` on the real bytes: results reproduce. R1–R6 were correct: no squaring (each node contributes one value), per-subtree fallback, `fillMode both` makes a constant node constant for any `beginTime`/`duration` and at settle. |
| 27 | simplification | Six anchors → **four**. The leaf is valued by the same node rule at setup (R1 stores the full product), so rev 3's R3/R4 per-frame `__obedOp` flag and the fade arithmetic are gone; R3 (was R5) becomes one `null!=e.obedOpacity&&(T=…)`. Scratch `patch_c.py`/`beh_c.py`/`census_c.py`: anchors unique, `node --check` OK, same outputs, same census (1 of 110 leaves changes). |
| 28 | decision | Leaf fades are now **unchanged** (legacy) instead of multiplied by the parent product: identical on disk, removes untested new behaviour; a fade under a translucent wrapper joins the residuals (decision 5). |
| 29 | correctness | Census class list verified on the bytes (one `textureInfoFromEffect` caller, one `renderFrameWithContext` caller, `new eB(` only in `pB` and `SB`; `RB`/`uB` extend `SB`; builds never reach `eB`). Census/mirror must use exact float equality, not 1e-9. |
| 30 | correctness | P2 adversarial serves the **stock** `main.js` unless `--gl-replay auto` (`_patched_main_js` only under `gl_auto`, :3332): rev 3's "passed through" would leave P2's fast/slow/bridge-off arms unpatched. `auto` now serves the patched bytes in every arm; the test's monkeypatch lambda takes the kwarg. |
| 31 | simplification | `PLAYER_PATCH_VERSION` dropped (the served `main.js` sha identifies the bytes); decision 6 closed as a fact. `RUNTIME_VERSION` consumers re-checked: all concern the unchanged hook; `output.mmOpacity` reaches the session identity via `host.output`. |
| 32 | G2 | (iii) re-checked on every path (proof order, LIVE `opacityFor`, stand-down write-back/replay, `score_armed`, `p2_verdict` filter, core relay): safe. Added: harnesses assert the exact unproven set so a second unproven slot cannot hide; M3's two checks named explicitly; V-arm occlusion follows G2's mask. |
| 33 | gate | MO-1 re-cast as uniform-in-effect at every slot-4 draw + one settle pixel blend (B leaves the shader untouched); drops the per-frame `readPixels` stall inside G2's recording window. GL-on runs void on any G2 stand-down. |
| 34 | gate | MO-5 per-frame hashes are not comparable across runs (the move is paced by wall-clock rAF); replaced by settle-frame hashes, CvC in Q0b. |

