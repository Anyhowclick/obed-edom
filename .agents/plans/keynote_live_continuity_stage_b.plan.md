# Live continuity, Stage B: carry under artwork via the GL texture feed, N carries per boundary, qualify Alpha_DSK

Status: **DRAFT rev 3.1 (2026-10-13), planning only.**
- **Critique r2 (rev 3.1):** (B1) the seam gains `claim()`: the core cannot otherwise tell a fed entry from a poster hold when the host does not inject the module. (M1) the hidden ride and poster hold live inside `keepThroughBridge`/`keepThroughPin`, and every `play()` site respects the hold. (M2) the binding uses the regular ordinals only, which are the same in both player variants, because limit 5 is explained. `to: null` requires the single-texture program. (M3) limit 6 is explained. `labelsOverFeed` and Alpha `feedLive` are defined in-frame and in a single run, and two red controls are corrected. (M4) the stall fallback is replaced, because the player makes a fresh GL context per transition. (M5) Q6 gets a way to inject the module, plus a CEF dev-loop step. (M6) the tone-curve step is now in "What the owner sees" and the residuals. Post-C `lc` citations are fixed.
- **Order is C → S3 → B** (Stage C OQ-C2). B rebases onto C (PR #264) and then S3. After S3 the allowlist is gone, so B's oracle is the plan-sha tests plus S3's negative corpus.
- **OQ-B1 RESOLVED (owner):** the GL texture feed is proven, and B is built around it. The **poster hold** is the fallback whenever the feed is unavailable or stands down. Rev 2's "bridge hold under artwork" is dropped.
- **Still open from rev 2:** OQ-B2 is "probably" yes and is confirmed here (§7). OQ-B6 = yes.
- **Reads:** this worktree (`1138e220`), `origin/claude/stage-c-orchestration` (`a135ad5e`), and the feed evidence in `…/scratchpad/glfeed/`. Parent plan: `keynote_live_continuity_generalisation.plan.md`.
- **Citation prefixes:** `lc` = `src/obed_edom/live_continuity.py` (post-C names), `js` = `src/obed_edom/live_continuity_js.py`, `probe` = `scripts/live_continuity_probe.py`, `host` = `src/obed_edom/live_host.py`.

**Goal (owner, 2026-10-13).** Qualify a real deck: `Alpha_DSK.key` (H.264 export `output/.html-preview/3b9019f0…-p3-r1/html`) derives with every same-movie Magic Move carried and passes the probe green. Authored artwork stays above the video **during the move and once the slide settles**.

**Owner decisions that still govern (not reopened):**
- Pin hold accepted.
- R9.
- A runtime carry refusal lasts until the next go-to.
- Main freeze bracket option A.
- Decision 14.
- Instrument scope = catch what the owner's eyes can catch.
- Exact canonical asset matching.
- objectID-only runtime identity.
- Stage C's R11 and the superseded dashboard gate.

## 1. Evidence (rev 2 §1 stands; changes only)
- **Alpha_DSK boundaries.** Unchanged from rev 2's table:
  - 3→4 untitled bridge (no artwork, carried today).
  - 5→6 and 6→7 wa0125 bridges, refused `overlap`.
  - 7→8 two bridges (wa0121, wa0125), both refused `overlap`.
  - 8→None, no runtime entry.
  - Every destination p6/p7/p8 is `[auto movie-start, transition]`, so it settles into its DOM layers.
  - The tags cover 3.3–8.3 % of the video, so no tolerance threshold can qualify them.
- **Post-C hook point.**
  - `_overlap_refusal` now returns `(code, reason)`: `R11` for an unmeasured movie above, else `overlap`.
  - `_carry_refusal` passes that result through.
  - `_magic_move_movies(…, onward)` refuses R11 when the destination's own next transition is unmeasured.
  - B intercepts only the `overlap` code. R11 stays a refusal.
- **Where the carried decoder paints today.**
  - During the ride it sits on `#body`, above the GL canvas (`js:1157-1161`).
  - A settled pin is re-homed into its poster's authored layer (`js:1698-1755`, `:1812-1901`).
  - A settled bridge stays a `#body` overlay (`js:2140-2144`).
- **The feed experiment.** Headless Chrome on Alpha 6→8, 8→9 and 9→10, with 9→10 carrying 2 movies.
  - **Mechanism:** at the carried movie leaf's draw, `texImage2D(video)` into **both** textures the leaf crossfades: unit0 = outgoing, unit1 = the `contents` to-texture.
  - **Result:** the player itself draws the movie in slot order, with Keynote's easing. Labels and the divider stay on top. The 0.61 tag boxes composite over live video (coefficient k median 0.385–0.387 against an expected 0.388). 0 GL errors, and every video frame was delivered.
  - **Cost:** 0.3–0.7 ms p95 per frame, against 6–10 ms for 2D-canvas staging.
  - **Binding:** by draw index plus the upload ordinals and sizes of unit0/unit1 taken from the export JSON, re-keyed on texture identity after the first feed. **Never by texture id:** 9→10 WA0125's outgoing texture `309718…` is WA0121's poster, and a label draw uses the 13×404 divider texture.
- **Experiment limits (rev 3.1 status):**
  1. It fed a **separate** muted `<video>`, not the carried decoder. **Open → closed by Q3** (D7/D7s `feedLive` on the carried decoder). The contract does not depend on it.
  2. It ran mostly on a virtual clock. **Closed:** the real-clock direct runs (`out/run2-direct-realclock`) show 0 refusals, feed p95 0.4–0.7 ms, rAF max 33 ms and 0 GL errors on all three moves.
  3. It ran only in headless Chrome. **Open → dev-loop step + Q6** (§2.1 Host). CEF evidence in the repo: G2 already runs WebGL with `drawImage(video)` → `texSubImage2D(canvas)` in OBS 32.2.2 / CEF 127 (`.agents/reviews/gl-replay-managed/gates-r1.md`, M1–M6). Direct `texImage2D(HTMLVideoElement)` is unproven there.
  4. One 357 ms stall in 1 of 6 runs (`run2-cmp/direct/6to7`). The first feed itself took 0.1 ms at 26 ms; the next rAF came at 382.6 ms, so the stall is a whole-page gap, not upload time. Under a real clock the whole Keynote move would jump ~21 frames. **Open → dev loop** (§2.1 warm-up).
  5. Upload counts 13/12 and 20/17. **Closed:** every extra upload is a MM-opacity hand-back texture. `__obedHandbackTextures` (`live_runtime.py:34-54`, called at `:83`) runs after `setupTexture`'s loop and `createTexture`s a next-slide texture for each scaled leaf that has no `contents`.
     - 8→9: #13 266×59 for label box d7.
     - 9→10: #18–20 (287×77, 259×58, 189×91) for label boxes d5/d7/d11.
     - These uploads always follow every regular upload. They are also runtime-conditional: the hand-back returns early unless the next slide's texture cache is loaded.
  6. 9→10 label draw 7 at k 0.07–0.34. **Closed:** draw 8 (the label text leaf, whose outgoing texture is the 13×404 divider, a texture-id defect) is drawn over it.
     - On draw 7's pixels not covered by any later quad, k = 0.388–0.390 in both arms at all three reads.
     - On the covered pixels, k tracks draw 8's mixFactor: 0.13 / 0.50 / 0.88 → k 0.054 / 0.193 / 0.338 (scratch `critic-r2/k7.py`).

## 2. Design

### 2.1 (1) Carry under artwork: feed in the move, re-home at settle, poster hold as fallback
**Python (`lc`, WS-D)**
- **The lift.** In `_carry_refusal`, an `overlap` result is not a refusal when the destination **settles into DOM**:
  - `len(events) == 2`;
  - `events[0]["automaticPlay"] is True`;
  - ev0's whole effect tree is only `apple:movie-start` / `renderMovie`.
  - The carry is then marked `under_artwork`. Any other overlapping destination keeps `overlap` (→ retire, or glReplay for a click-driven pin, a disjoint domain). R11 is untouched.
- **Binding data (`feed`)**, emitted on each under-artwork entry when it can be bound:
  - `{"draw": d, "drawCount": n, "from": {"upload": i, "size": [w, h]}, "to": {"upload": j, "size": [w, h]} | null}`.
  - Built by walking the boundary transition's leaves in player order (`textureInfoFromEffect`; port `glfeed/spec.py` `_leaves`, one draw per textured leaf, uploads = leaf texture then its `contents` to-texture).
  - The movie leaf is found **by geometry, not texture id**:
    - take the one transition slot that starts at the source movie layer's rect (the `_bridge_slot_chain` rule, post-C `lc:1576-1609`);
    - that slot's subtree must hold exactly one textured leaf;
    - its centre must match the movie centre within 2 px.
  - **Ordinals are the regular uploads only** (leaf texture, then its `contents` to-texture). They are the same in both player variants, because the hand-back uploads always come after them (limit 5). Nothing models the hand-back.
  - `to` is the leaf's `contents` to-texture.
    - `to: null` (from-only) is allowed only for a leaf whose scale stays 1→1, because `live_runtime`'s hand-back skips `1===sx&&1===sy`.
    - The player then draws that leaf with the single-texture program: `isBlending = !!toTexture` (main.js `prepareAnimationWithContext`), so no `mixFactor` is set.
    - A scaled movie leaf without `contents` is not bound (reason `hand-back leaf`): the hand-back could crossfade it into a next-slide texture.
  - Not uniquely bindable → the entry keeps `underArtwork` with no `feed` (poster hold), recorded per entry with a reason.
- **Probe-only facts** (not in `to_runtime()`): `ContinuityPlan.artwork_above` (rev 2) and `ContinuityPlan.feed_draws` (per fed boundary: draw table with layer sizes, label-box opacities, and the fed leaves' objectIds).

**Feed module (new sibling, WS-F): `src/obed_edom/live_mm_feed_js.py`**
- Like G2: its own `MM_FEED_VERSION = 1` and pinned sha, so its bytes never ride on the continuity sha. Injected by the host only when the runtime plan has a `feed` key.
- **Hooks:** `getContext` for `/^\d+-canvas$/` WebGL contexts (G2's `CANVAS_ID_RE`; chains with G2's wrapper). On that instance it wraps the texture, bind, pixelStore, program, uniform, clear and draw calls.
- **Arming and claim:**
  - When the hash reads `atScene-1` with the player idle on the source slide, resolve `seam.feed.decoderFor(objectId)`, warm up, and call `seam.feed.claim(objectId)`.
  - Only a claimed entry is fed. Contexts are wrapped only while one of the module's entries is armed, so a G2 context is never touched.
- **Per frame:**
  - Count uploads and draws.
  - At draw `d`, verify that unit0 (and unit1 when `to` is set) were uploaded in this move with the planned ordinal and size, and that the active unit is 0.
  - Then check the program: with `to` set, `mixFactor` must be set; with `to: null`, the active program must have no `mixFactor`.
  - Then `texImage2D(decoder)` into the planned textures under each texture's own FLIP_Y/PREMULTIPLY state, and restore GL state.
  - The first good feed records texture identity.
  - Any of the following → **stand down** for that entry until the next go-to: a later identity change, two fed leaves sharing a texture object, a `getError` after the frame's last draw, a binding mismatch, no feed by the end of the first frame that has draws, a lost context, or a decoder with no single identity match. Standing down means: stop feeding and call `seam.onStandDown(objectId, reason)`.
  - The textures keep the last fed frame, which is the "one-time paused-frame upload" for free when GL already ran.
  - `readyState < 2` at a draw (e.g. the decision-14 wrap) skips that draw's feed only. The inter-feed gap excuses that frame.
- **Warm-up (limit 4):**
  - The player creates a **fresh GL context per transition** (one `0-canvas` context per move, at 1542 / 6050 / 10097 ms in `run2-cmp/direct`). So no warm-up inside the player's context can precede the first feed.
  - Warm up at the claim by uploading each claimed decoder once into a texture in a **module-owned** WebGL context.
  - Dev loop: ≥ 10 real-clock runs per Alpha move. If any first-feed gap over 2 frames remains, bring its rate and measured hitch to the owner before the contract freezes. There is no in-player fallback.
- **Publishes** `window.__OBED_MM_FEED__`: per-entry state `armed|fed|stoodDown(reason)`, frames fed, max inter-feed gap, p95 ms.

**Core (`js`, WS-R)**
- **Hidden ride.** For an `underArtwork` entry, the branch lives **inside `keepThroughBridge`/`keepThroughPin`**. Every ride start funnels through them: `markTransition` `js:791-796`, `keepAtSlot` `js:1311-1315`, every `tryRemount` retry `js:1633`, and the departure path stash → `scheduleRemount`.
  - The branch is a `hidden` flag on `rideTransition` that sets `opacity: '0'` and keeps its ownership token, so no visible ride can take the decoder over. The decoder stays attached on `#body`, still decoding: the experiment's opacity-0 video delivered every frame.
  - `keepAtSlot` hands off for a next entry with `underArtwork` whether it is a **bridge or a pin**. Otherwise a held overlay keeps `opacity: '1'` every frame (`js:1336-1338`), and `keepThroughPin` refuses `__obedBridged34` (`js:1231`).
  - **Claimed** (`seam.feed.claim` before departure): the decoder keeps playing.
  - **Otherwise poster hold.** At hidden-ride start, `pause()` and set `__obedPosterHeld = true`, then note `poster-hold {elId, t}`. `onStandDown` mid-move does the same.
  - While the flag is set, every core `play()` site skips the decoder:
    - stash's keep-warm `js:974-977`, which runs at departure **after** `noteDeparture`;
    - the 200 ms sweep `js:1973-1988`;
    - `tryRemount` `js:1651-1654`, `:1737-1740`, `:1789-1792`;
    - the `bindFacade` swap `js:1876-1879`;
    - `bridgeTo34`.
- **Settle re-home (kept from rev 2).** The `underArtwork` bridge keeps the `bridge-3to4` note and then takes the pin re-home path:
  - `rehome = !!entry.underArtwork || !!preserved.__obedBridged34`;
  - `bindFacade(el, preserved, true)` + `scheduleRemount('pin-rehome')`;
  - no `src` on the stub (`js:2211`);
  - `carry()`'s bridge branch becomes `bridge && !entry.underArtwork`.
  - `carry()` clears `__obedPosterHeld` before `scheduleRemount('pin-rehome')`, with note `poster-resume {elId, t}`. The re-home's own `play()` then resumes the decoder. Pins already re-home.
- **Seam.** `window.__OBED_P2_PRESERVE__.feed = {version: 1, decoderFor(objectId), claim(objectId), onStandDown(objectId, reason), note(kind, detail)}`.
  - It is installed for every plan with a `feed` key, whatever the host resolved. The plan sha does not depend on the output.
  - With the module absent, nothing claims, so every flagged entry gets the poster hold.
  - G2's seam is unchanged.
- **Versions.** `CONTINUITY_VERSION` 6→7, `__OBED_P2_PRESERVE__.version` 9→10, re-pin `PINNED_CORE_SHA256` and its mirrors.

**Host (`host`, WS-H)**
- `_resolve_mm_feed()` mirrors `_resolve_gl_replay` (`host:902-918`): `injected | notApplicable | unavailable(reason)`.
  - External attach is refused ("attach output not qualified").
  - Managed OBS under `auto` reads `MM_FEED_MANAGED_OBS = False`, which means `unavailable` → poster hold. The Q6 gate-record commit flips it before Q7.
- `OBED_LIVE_MM_FEED=off|auto`, plus a constructor flag `off|auto|on`.
  - `on` exists for qualification only. It injects in managed OBS regardless of the constant, so the Q6 feed arm can run. It is still refused for external attach.
- **CEF dev-loop step** (before WS-F starts, owner's OBS go): run `glfeed/instrument.js`'s `direct` arm on Alpha 9→10 inside managed OBS through the existing `mmo-cef` harness, unrecorded.
  - A fail moves to OQ-B10 early, and Q6's feed arm is not built.
- `output.continuity.mmFeed {mode, reason, version, sha256}`, and per-entry `posterHold` lines (slides, movie, reason) next to `notCarried`.

**What the owner sees**
- **Feed on** (headless or visible Chrome; managed OBS once Q6 passes): the movie keeps playing inside Keynote's own move, with Keynote's easing. Tags and the divider stay on top, and the 0.61 tag boxes tint the live video. At settle it continues in its layer with the labels above, with no time jump.
  - There is a small midtone brightness step at departure and at settle. Chromium draws a native `<video>` through a tone curve that `texImage2D` does not get (up to +11/255 in the midtones; gl-replay-managed gates-r1 finding 1, the same residual as G2).
- **Poster hold** (external attach, feed off, or a stand-down): Keynote's move plays with labels on top, over the export's baked still (the clip's frame 0, open item 2, unless the feed had already run). At settle the video resumes from the frame it showed when the move began. There is no restart, and the movie's clock is held for the move's 1.5 s.

### 2.2 (2) N carries per boundary, authored stacking
- **Fed carries are unlimited per boundary.** The player draws them in slot order, so video-on-video overlap (the owner's sliver) renders as authored **in the move**. The settled re-home keeps that order once the slide settles.
- **Overlay-ridden (unflagged) bridges keep the one-per-boundary guard** (post-C `lc:1836-1837` as fixed by `87ab7240`, now counting only unflagged bridges). Checked on post-C `lc` (scratch `critic-r2/r10.py`): with the lift and this counting, Alpha_DSK 5→6, 6→7 and 7→8 all carry, and R10 still applies and passes. No deck qualifies two overlay rides at once, so B does not lift it.
- **Crossing rule (replaces rev 2's `zOrder`).** Two carries at one boundary may intersect in flight unless they are separated along a common axis, on the same side, at both ends (exact for linear edges under a shared progress; separation margin `_OVERLAP_MIN_PX`).
  - If they can cross and the destination settles into DOM → **both** become `under_artwork` (fed or poster-held; reason "crosses `<asset>`").
  - Otherwise the lower one (earlier destination slot) is refused `overlap`.
  - Alpha 7→8 is separated (930|930 → 763|764) and both carries are already under artwork. D7s exercises the crossing branch.
- **Rejected:** a sliver tolerance. It is not needed, and the rev 2 fallback is withdrawn.

### 2.3 Alpha_DSK specifics (unchanged from rev 2 §2.3)
- Fixture: `output/fixtures/sermon/alpha-dsk/`.
- End of show: no change (OQ-B4).
- Skipped slide: no code change; record the ordinal mapping in the gate record.
- Audio: disabled.
- Rev 2's carry-cover sibling fix is dropped: no two overlay bridges ever share a boundary now. Carry-cover skips fed entries.

## 3. Schema, shas, oracle
- **Schema 2 gains two additive keys:** `underArtwork: true` and `feed` (present only when bound). `zOrder` is gone. G2 ignores extra keys.
- **Byte-identical runtime plans:**
  - **P2, p2-loop and D1–D6 stay byte-identical.** Their plan-sha tests must pass unedited; that is B's regression oracle after S3.
    - P2's 1→2 destination is click-driven.
    - D1–D6 have no artwork overlap.
    - D3's pin+bridge pair is x-separated (pin x 100–900, bridge x 1020→1100). It is the only D-deck boundary with two carries, so the crossing rule changes nothing there.
  - These plans inject no module and run no new core branch. The plan sha hashes the runtime JSON only (post-C `lc:672-675`, `:831`), so the core version and sha bumps do not touch it.
- **Plans that change:** the Minimal Alpha_DSK family (the `clip-10-1000001` pin becomes `underArtwork` under OQ-B2).
- **Tests and corpus that change on purpose:**
  - Rev 2 §3 list.
  - S3's negative-corpus `overlap` example, if it used a settling destination (re-point it at a click-driven one).
  - The `87ab7240` test (overlay bridges still counted; fed ones not).

## 4. Work streams (Opus MEDIUM, disjoint files, one message; then Codex GPT-6 Astra (high) on the combined diff)
**Frozen contract before launch:**
- `underArtwork`;
- `feed` shape;
- `feed_draws` / `artwork_above` shapes;
- seam `feed` v1 (with `claim`);
- `MM_FEED_MANAGED_OBS` and the `on` constructor mode;
- `__OBED_MM_FEED__` fields;
- variant names `overlay-ride`, `settle-on-stage`, `no-pause` (core) and `from-only` (feed);
- probe tamper `--feed-tamper ordinal`.

| WS | Files (exclusive) | Work | Minimal tests |
|---|---|---|---|
| D | `lc`, `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py`, `tests/fixtures/live_continuity/**` (trimmed Alpha p3–p8 JSON; S3 corpus edits) | settle-into-DOM lift, crossing rule, guard counting, `feed` binding for the served variant, probe facts | (1) the Alpha fixture derives the expected entries and `feed` (draws and regular ordinals/sizes equal the experiment's: 5/9/12 draws; 7/12/17 regular uploads); (2) parametrised overlap: settling → `underArtwork`, click-driven / extra event → `overlap`, R11 unchanged; (3) crossing → both flagged / lower refused |
| R | `js`, `tests/test_live_continuity_js.py`, `scripts/continuity_core_variants.py` (+ test), re-pins in `tests/test_live_gl_replay_js.py`, `scripts/detach_experiment.py`, `tests/test_detach_experiment.py` | hidden ride, poster hold pause/resume and keep-warm exemption, settle re-home, seam, versions, 3 variants | Node: (1) a fed bridge never paints during the move and lands in the poster layer, with no `src` on the stub; (1b) a held plain-bridge overlay → `underArtwork` lands in the layer; (2) poster hold: paused at departure **including stash's play-then-remount order**, not re-played by keep-warm or `tryRemount`, resumes at the paused time; (3) stand-down mid-move → pause; (4) claimed → keeps playing, unclaimed with a `feed` key → poster hold; (5) overlay bridge → `underArtwork` pin hands off hidden |
| F | **new** `src/obed_edom/live_mm_feed_js.py`, **new** `tests/test_live_mm_feed_js.py`, **new** `scripts/mm_feed_variants.py` | the module (§2.1), warm-up, telemetry, `from-only` | Node with a fake GL: binding accept/refuse (ordinal, size, unit, `mixFactor` present/absent per `to`), claim at idle, identity re-key, state restored, two fed leaves in one frame, from-only leaf, `getContext` chain with G2 |
| H | `host`, `tests/test_live_host.py` (incl. its core-sha re-pin) | `_resolve_mm_feed`, env/flag, output fields, `posterHold` reporting | (1) attach → `unavailable` + poster hold, even with `on`; (2) injected only with a `feed` key; (3) managed OBS: `auto` → `unavailable` until the constant flips, `on` → injected |
| G | `probe`, `tests/test_live_continuity_probe.py`, `scripts/run_gates.sh`, **new** `scripts/mm_feed_instrument.py` (probe-only in-frame GL reader, from `glfeed/instrument.js`), `scripts/managed_obs_qualify.py` + its test | verdicts and arms (§5.2), registrations | scorer units for each new verdict (pass/fail/inconclusive); registrations as data |
| P | `README.md`, `.agents/skills/obed-edom/SKILL.md` | "What is carried" (feed, poster hold, N carries); contract keys; module table | — |

Full suites on 3.12 (`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`), and the 3.10 floor for the probe/paint/run_gates files, locally.

## 5. Re-qualification

### 5.1 What reopens, precisely
- **Core bytes change, so §4's rule reopens Q2–Q6.** P2, p2-loop and D1–D6 run none of the new branches and inject no module. Their verdict tables must **equal S3's**, which is a regression check, not new qualification.
- **The new module is qualified only where it is injected:** D7, D7s and Alpha_DSK in Q3, the new Q6 feed arm, and Q7.
- **G2 bytes are unchanged.** Q4 reruns only because the core bytes changed. G2 decks have no `feed` key, so their seam object is unchanged.

### 5.2 Decks
- D7 and D7s keep rev 2's geometry and draw order (A, B, TA solid green, TB white 61 %, DV), and every movie starts After Transition.
- Fed moves let the binary counter be decoded from GL pixels, which makes `feedLive` exact on D7 and D7s.

| Deck | Expected plan | Proves |
|---|---|---|
| **D7** (S1→S2 both shrink, S2→S3 grow back, S3→S4 hold) | @2 and @4: bridge A+B, `underArtwork` + `feed`; @6: pin A+B, `underArtwork` + `feed` (to = null if no crossfade) | the feed in the move, labels on top, two fed carries per boundary, fed pins, the settle re-home chain |
| **D7s** (no DV; S2 B at 955 → 5 px over A) | @2/@4: bridge A+B, both flagged (artwork and crossing) | the owner's sliver drawn as authored in the move and once settled |
| **Alpha_DSK** | @6 overlay bridge (untitled), @8 restart, @10/@12 fed bridge, @14 two fed bridges | the goal |

### 5.3 Gates and verdicts
**New verdicts (WS-G):**
- **`feedLive`** (per fed carry, read in frame at progress 0.25/0.5/0.75, single run):
  - The patch lies inside the fed leaf's projected quad (MVP from the draw) and is **not covered by any later draw's quad** (grow 2 px).
  - The reference is the decoder drawn into a canvas at the leaf texture's size **in the same task**, sampled over the patch's UV footprint.
  - D7/D7s: the decoded counter must equal the reference's counter ±1.
  - Alpha: green when dV ≤ dP/2, where dP is the export poster over the same footprint. INCONCLUSIVE when dP is below a floor.
    - Register the floor by re-scoring `run2-cmp/direct`: all 9 reads must score green or inconclusive.
    - The rev 3 centre-patch rule scores 6→8 at 0.5 as tP 0.556 (dV 13.1, dP 10.5) on a working feed. 9→10 wa0121 at 0.75 reads a label box over the centre (dV 13.1).
  - Plus a max inter-feed gap under the paint-coverage rule (slower side's cadence), which catches the 357 ms stall.
- **`noRiderAboveCanvas`:** on every rAF of a fed or poster-held move, no carried decoder composites while it intersects the GL canvas (`opacityProduct > 0.02`, visible). The player hides the source layers during the move, so any compositing decoder is above the canvas.
- **`labelsOverFeed`:** for each label-box draw over a fed leaf, computed in frame from a single run.
  - Read under = `readPixels` just before the label draw, and final = after the frame's last draw.
  - Use the box's pixels inside its quad (grow −3) that are not covered by later quads (grow 2).
  - k = the least-squares slope of final on under. It must be within ±0.02 of 1−opacity. INCONCLUSIVE when the spread of under is below 24.
  - The rev 3 cross-arm k (`analyze.py:97-123`) needs a paired off-arm frame at identical geometry, which exists only under the virtual clock.
  - Draw 7 is included (limit 6). The uncovered k measured 0.388–0.390 against an expected 0.388.
- **`posterHold`:** for a poster-held carry, the clock is still for the move, resumes within 1 frame of the pause point, and does not go back to 0. It replaces the carry verdict's stall rule for that entry only.
- **`artworkAbove`** (settled, rev 2): unchanged.

| Q | Run | Pass | Red controls (pre-registered, each red only on its verdicts) |
|---|---|---|---|
| Q1 | Suites | green | — |
| Q2 | P2 `run_gates` fast/slow/auto | equal to S3's table | existing |
| Q3 | Host probe ×3 viewports, arms A/B/C, attach, V/Voff/Vgl, Pass G; P2 + D1–D6 (equal to S3) + D7, D7s, Alpha_DSK; plus an MM-opacity-off arm on Alpha | all verdicts; attach arm scored with poster-hold facts | `feed-off` (`--mm-feed off`) → `feedLive` red; the same capture scored as poster hold is green. `from-only` (scored on D7/D7s only) → `feedLive` red at the 0.5 and 0.75 reads, green at 0.25. On Alpha the run1 `from` arm read 0.75 green and 0.5 red. `overlay-ride` → `noRiderAboveCanvas` red only; `labelsOverFeed` stays green, since it reads the GL buffer, which a DOM overlay does not touch. `settle-on-stage` → `artworkAbove` red. `no-pause` under feed-off → `posterHold` red (~1.5 s jump). `--feed-tamper ordinal` → stand-down note, `feedLive` red, `posterHold` green (proves binding fails closed). MM-opacity off → `labelsOverFeed` red (boxes solid). `--strip bridge@14:movie2` → only wa0121 b7to8 red |
| Q4 | G2 seam (Vgl, `--gl-force-fail` ×4) | as S2 | `--gl-force-fail` |
| Q5 | Loop L1 (+ L2 per rule, OQ-B5) | as S2 | as S2 |
| Q6 | Managed OBS arms at 25/30 + **new `feed` arm** (constructor `mm_feed="on"`; Alpha 6→8, 9→10 in CEF) + `feed-off` poster-hold arm (owner's go); a pass flips `MM_FEED_MANAGED_OBS` | M1–M6; feed verdicts green in CEF | OD-2 `--kb` arms; `feed-off` |
| Q7 | Owner: managed OBS Keyer (feed) on D7, D7s, Alpha; external attach (poster hold) on Alpha; D1 spot | labels on top in the move and settled; no visible restart; poster hold as described; the midtone step at departure and settle is acceptable | — |

## 6. Sequencing
- **Order: C (#264) → S3 → B.**
- B starts when S3 merges. WS-F and the probe instrument can be written against this contract earlier, since their files are new.
- B updates S3's corpus only where §3 says.
- B adds no allowlist: D7, D7s and Alpha_DSK join through their plan-sha tests and registrations.

## 7. Owner questions that remain (recommendation first)
1. **OQ-B2: pins under artwork on DOM-settling slides.** **Rec: yes.** They are fed in the move and already re-home. D7 S4 covers them.
2. **OQ-B4: end of show.** **Rec: no change.** Press past the end once at Q7.
3. **OQ-B5: re-qualification scope.** **Rec: full Q2–Q6** per §4, with P2/D1–D6 as equality checks. The cheaper option is Q5 = L1 only.
4. **OQ-B7: D7/D7s authoring.** **Rec:** the S0 generator under your Keynote go, plus your V4 eyeball.
5. **OQ-B8: slivers on click-driven slides** stay refused. **Rec: accept for B.**
6. **OQ-B9 (new): feed every carry on DOM-settling slides,** retiring the overlay ride, its eased interpolation and R10. **Rec: a later stage.** It changes D1–D6 and P2 3→4 behaviour and reopens their oracles.
7. **OQ-B10 (new): if CEF 127 fails the Q6 feed arm,** ship with managed OBS on poster hold (feed in Chrome outputs only) until it is fixed. **Rec: yes.**
8. **OQ-B11 (new): surfacing poster hold.** **Rec:** the host field plus a line under the continuity badge. No new UI.

## 8. Residuals (README)
- Poster hold shows the export's baked still (frame 0) during the move when the feed never ran (external attach).
- A fed move shows a small midtone brightness step at departure and settle (the native `<video>` tone curve, as G2).
- Overlay-ridden carries with no artwork overlapping them on the destination still paint above artwork they cross mid-flight, and follow R10 eased interpolation.
- One overlay bridge per boundary.
- Overlap on click-driven or multi-build destinations stays refused.
- Keynote texture-id defects: the feed binds by geometry, draw index and ordinals, and does not depend on the separate prepare-time repair.
- Probe ordinal labels after a skipped slide.
- Audio is disabled (a suppressed overlay-bridge destination still decodes).
