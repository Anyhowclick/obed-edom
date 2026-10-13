# Live continuity, Stage B: carry under artwork via the GL texture feed, N carries per boundary, qualify Alpha_DSK

Status: **rev 3.5, plan critique closed (3 rounds); ready for implementation on the owner's go**
- **Rev 3.2:** owner-approved folds (2026-10-13): all §7 OQs resolved per recommendation; exact-frame poster hold and `holdFrame` gates (OQ-F1–F3); bindings from the served Stage T-repaired JSON at every prepare and a repaired copy of the 7e3c fixture; T #267 merged as `ad6dac98`; B rebases onto main (verified HEAD `6e10ef04`) before implementation, with S3 #266’s merged corpus as oracle; temporary Sol high implementers / Opus 5.5 high reviewers through 2026-10-27; Alpha slide 11 corrected to the owner’s 18:19 edit and qualification re-prepared.
- **Critique r1 (rev 3.3):** (1) carry scoring substitutes feed/hold checks only in the evidenced GL interval; (2) optional pre-teardown take exposed with opacity off, owned by WS-R with tests/pins; (3) feed-off scored against an explicit continuous-feed expectation; (4) copy → repair → zero-hit check → trim Alpha input; (5) separate continuous/once eligibility and qualification-only once override; (6) trimmed terminal vs full Alpha 8→9 retire boundary; (7) evidence contract and tests owned by WS-G; (8) explicit overlap tests retain the unflagged-bridge guard; (9) first-feed deadline starts on an eligible decoded draw; (10) HEAD citations corrected with symbols; (11) merged-T status/source and B rebase corrected.
- **Critique r2 (rev 3.4):** (1) one-shot eligibility follows the qualified renderer independently of attach transport; (2) last-fed hold requires usable context and bound textures, otherwise record an unavailable rendering path without claiming exact hold; (3) WS-G adds post-feed stand-down tampering with last-upload `holdFrame` and held+1 `posterHold` gates; (4) hand-back call citation corrected to the `setupTexture` replacement and its symbols at HEAD `916dc583`.
- **Critique r3 (rev 3.5, final plan round):** (1) post-feed stand-down verifies last-upload retention and no-seek resumption from the actual pause point, reports any resumption discontinuity, and keeps departure one-shot held+1 unchanged; (2) WS-H freezes the recorded renderer predicate, checks OBS/CEF before generic Chrome, resolves it before script selection, and tests real fingerprints with `MM_FEED_MANAGED_OBS=False`; (3) `from-only` red expectations apply only to non-null `feed.to`, with single-texture entries green; (4) the coordinator owns D7/D7s generator extensions, fixture artifacts and V4 confirmation before WS-G qualification.
- **Critique r2 (prior revision):** (B1) the seam gains `claim()`: the core cannot otherwise tell a fed entry from a poster hold when the host does not inject the module. (M1) the hidden ride and poster hold live inside `keepThroughBridge`/`keepThroughPin`, and every `play()` site respects the hold. (M2) the binding uses the regular ordinals only, which are the same in both player variants, because limit 5 is explained. `to: null` requires the single-texture program. (M3) limit 6 is explained. `labelsOverFeed` and Alpha `feedLive` are defined in-frame and in a single run, and two red controls are corrected. (M4) the stall fallback is replaced, because the player makes a fresh GL context per transition. (M5) Q6 gets a way to inject the module, plus a CEF dev-loop step. (M6) the tone-curve step is now in "What the owner sees" and the residuals. Post-C `lc` citations are fixed.
- **Order: C #264, S3 #266 and T #267 merged → B rebases onto updated main → implementation.** T #267 merged as `ad6dac98`. The allowlist is gone; B’s oracle is the plan-sha tests plus S3’s merged `tests/test_live_continuity_corpus.py`.
- **OQ-B1 RESOLVED (owner):** the GL texture feed is proven, and B is built around it. The **poster hold** is the fallback whenever the feed is unavailable or stands down. Rev 2's "bridge hold under artwork" is dropped.
- **Owner decisions resolved:** every §7 OQ is approved per recommendation; OQ-B2 = yes, OQ-B6 = yes. Exact-frame OQ-F1–F3 are approved and folded here.
- **Reads:** this worktree at HEAD `6e10ef04` (main merged), Stage T’s plan `.agents/plans/keynote_export_texture_repair_stage_t.plan.md` and prepare path on main (PR #267 retained merge `ad6dac98`), approved `exact_frame_hold.plan.md`, the feed evidence in `…/scratchpad/glfeed/`, and main-checkout `output/evidence/mm-freeze-2026-10-13/`. Parent plan: `keynote_live_continuity_generalisation.plan.md`.
- **Citation prefixes:** `lc` = `src/obed_edom/live_continuity.py` (post-C names), `js` = `src/obed_edom/live_continuity_js.py`, `probe` = `scripts/live_continuity_probe.py`, `host` = `src/obed_edom/live_host.py`.

**Goal (owner, 2026-10-13).** Qualify a real deck: `Alpha_DSK.key` (H.264, an export Stage T accepts; qualification fixture: a repaired copy of `output/fixtures/alpha-dsk-textures/html-unmodified` (`7e3c9301…`, §2.3)) derives with every same-movie Magic Move carried and passes the probe green. Authored artwork stays above the video **during the move and once the slide settles**.

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
- **Alpha_DSK boundaries (player indices).**
  - 3→4 untitled bridge (no artwork, carried today).
  - 5→6 and 6→7 wa0125 bridges, refused `overlap`.
  - 7→8 two bridges (wa0121, wa0125), both refused `overlap`.
  - 8→None, no runtime entry, is **trimmed-fixture-only**. Full Alpha maps ordinal 10 to player 8 and ordinal 11 to player 9: 8→9 expects two `retire ends` entries for wa0121/wa0125; 9→None is terminal. Reconfirm this mapping on the re-prepared export of the owner’s slide-11 edit (§2.3).
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
- **Experiment limits (carried forward):**
  1. It fed a **separate** muted `<video>`, not the carried decoder. **Open → closed by Q3** (D7/D7s `feedLive` on the carried decoder). The contract does not depend on it.
  2. It ran mostly on a virtual clock. **Closed:** the real-clock direct runs (`out/run2-direct-realclock`) show 0 refusals, feed p95 0.4–0.7 ms, rAF max 33 ms and 0 GL errors on all three moves.
  3. It ran only in headless Chrome. **Open → dev-loop step + Q6** (§2.1 Host). CEF evidence in the repo: G2 already runs WebGL with `drawImage(video)` → `texSubImage2D(canvas)` in OBS 32.2.2 / CEF 127 (`.agents/reviews/gl-replay-managed/gates-r1.md`, M1–M6). Direct `texImage2D(HTMLVideoElement)` is unproven there.
  4. One 357 ms stall in 1 of 6 runs (`run2-cmp/direct/6to7`). The first feed itself took 0.1 ms at 26 ms; the next rAF came at 382.6 ms, so the stall is a whole-page gap, not upload time. Under a real clock the whole Keynote move would jump ~21 frames. **Open → dev loop** (§2.1 warm-up).
  5. Upload counts 13/12 and 20/17. **Closed:** every extra upload is a MM-opacity hand-back texture. `__obedHandbackTextures` (`_MM_HANDBACK_METHOD`, `src/obed_edom/live_runtime.py:34-54`, called by the `setupTexture` replacement in `_MM_OPACITY_REPLACEMENTS` at `live_runtime.py:185-188`) runs after `setupTexture`'s loop and `createTexture`s a next-slide texture for each scaled leaf that has no `contents`.
     - 8→9: #13 266×59 for label box d7.
     - 9→10: #18–20 (287×77, 259×58, 189×91) for label boxes d5/d7/d11.
     - These uploads always follow every regular upload. They are also runtime-conditional: the hand-back returns early unless the next slide's texture cache is loaded.
  6. 9→10 label draw 7 at k 0.07–0.34. **Closed:** draw 8 (the label text leaf, whose outgoing texture is the 13×404 divider, a texture-id defect) is drawn over it.
     - On draw 7's pixels not covered by any later quad, k = 0.388–0.390 in both arms at all three reads.
     - On the covered pixels, k tracks draw 8's mixFactor: 0.13 / 0.50 / 0.88 → k 0.054 / 0.193 / 0.338 (scratch `critic-r2/k7.py`).

- **Exact-frame hold evidence.** Main checkout `output/evidence/mm-freeze-2026-10-13/` (`probe.py`, `run1/`, `montage.png`): the last presented WA0125 frame was 5.100 s, but teardown `currentTime` was 5.087 s. The move showed the baked poster, not a late live frame. Never seek to `currentTime` to obtain the hold: it is one frame before the last presented picture. The held frame is the frame on screen at move start, not at keydown (about 110 ms earlier in this run).
- **Stage T export contract.** Fresh Alpha exports collide texture ids differently each time. T repairs at prepare with D1–D4, re-exports once on a texture-repair refusal, then refuses unrepairable slides/objects by name. B reads the served repaired bytes; historical feed measurements above describe the unrepaired experiment.

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
  - Rebuilt at **every prepare from the served (Stage T-repaired) export JSON**, never a pinned binding table. Repair can change texture sizes; read them from that export.
  - Built by walking the boundary transition's leaves in player order (`textureInfoFromEffect`; port `glfeed/spec.py` `_leaves`, one draw per textured leaf, uploads = leaf texture then its `contents` to-texture).
  - The movie leaf is found **by geometry, not texture id**:
    - take the one transition slot that starts at the source movie layer's rect (the `_bridge_slot_chain` rule, HEAD `lc:1555-1586`);
    - that slot's subtree must hold exactly one textured leaf;
    - its centre must match the movie centre within 2 px.
  - **Ordinals are the regular uploads only** (leaf texture, then its `contents` to-texture). They are the same in both player variants, because the hand-back uploads always come after them (limit 5). Nothing models the hand-back.
  - `to` is the leaf's `contents` to-texture.
    - `to: null` (from-only) is allowed only for a leaf whose scale stays 1→1, because `live_runtime`'s hand-back skips `1===sx&&1===sy`.
    - The player then draws that leaf with the single-texture program: `isBlending = !!toTexture` (main.js `prepareAnimationWithContext`), so no `mixFactor` is set.
    - A scaled movie leaf without `contents` is not bound (reason `hand-back leaf`): the hand-back could crossfade it into a next-slide texture.
  - Not uniquely bindable → the entry keeps `underArtwork` with no `feed` (baked-poster hold), recorded per entry with a reason. The exact-frame one-shot requires the same unique binding as the live feed.
- **Probe-only facts** (not in `to_runtime()`): `ContinuityPlan.artwork_above` (rev 2) and `ContinuityPlan.feed_draws` (per fed boundary: draw table with layer sizes, label-box opacities, and the fed leaves' objectIds).

**Feed module (new sibling, WS-F): `src/obed_edom/live_mm_feed_js.py`**
- Like G2: its own `MM_FEED_VERSION = 1` and pinned sha, so its bytes never ride on the continuity sha. Injected by the host only when continuity is on, the runtime plan has a `feed` key, and continuous feeding or the one-shot hold is available. `mm-feed off` disables continuous feeding, not the one-shot; continuity off injects neither.
- **Hooks:** `getContext` for `/^\d+-canvas$/` WebGL contexts (G2's `CANVAS_ID_RE`; chains with G2's wrapper). On that instance it wraps the texture, bind, pixelStore, program, uniform, clear and draw calls.
- **Arming and claim:**
  - When the hash reads `atScene-1` with the player idle on the source slide, resolve `seam.feed.decoderFor(objectId)`, arm the entry (continuous or `once`) before the move’s context is created, and warm up. Call `seam.feed.claim(objectId)` only for continuous feeding; `once` mode must not claim a playing ride.
  - Only a claimed entry is continuously fed. Contexts are wrapped only while one of the module’s entries is armed (continuous or `once`), so a G2 context is never touched.
- **Per frame (continuous mode):**
  - Count uploads and draws.
  - At draw `d`, verify that unit0 (and unit1 when `to` is set) were uploaded in this move with the planned ordinal and size, and that the active unit is 0.
  - Then check the program: with `to` set, `mixFactor` must be set; with `to: null`, the active program must have no `mixFactor`.
  - Then `texImage2D(decoder)` into the planned textures under each texture's own FLIP_Y/PREMULTIPLY state, and restore GL state.
  - The first good feed records texture identity.
  - Any of the following → **stand down** for that entry until the next go-to: a later identity change, two fed leaves sharing a texture object, a `getError` after the frame's last draw, a binding mismatch, no feed by the end of the first frame containing an eligible decoded draw for that entry (decision-14 `readyState < 2` draws retain their exemption), a lost context, or a decoder with no single identity match. Standing down means: stop feeding and call `seam.onStandDown(objectId, reason)`.
  - Last-fed hold applies only while the context and bound textures remain usable. Context loss or loss of the fed bindings is an unavailable rendering path, not a successful exact hold; record that failure and do not claim retained-picture continuity. Pause without re-uploading; never replace it with a newly sampled frame. G2's `standDown` similarly skips poster restoration/replay on context loss (`src/obed_edom/live_gl_replay_js.py:918-929`). No new recovery mechanism is in scope.
  - `readyState < 2` at a draw (e.g. the decision-14 wrap) skips that draw's feed only. The inter-feed gap excuses that frame.
- **One-shot hold (`once` mode, WS-F).** `window.__OBED_MM_FEED__.once(objectId)` requests the upload for an armed, bound poster-held entry from the core’s hidden-ride hold path; repeated calls in the same move do not upload again. At its leaf’s draw in the move’s first frame with draws, run the same ordinal/size/program checks and one `texImage2D(paused decoder)` per planned texture (both when `to` is set), using each texture’s FLIP_Y/PREMULTIPLY state and restoring GL state. Do this once per move, then keep the upload through settle. No Python schema or plan-sha change beyond B’s existing `feed`.
  - Use the paused element’s last presented picture, before any seek; never seek to `currentTime`. Confirm on GPU Chrome. If it yields the `currentTime` frame instead, take `VideoFrame(decoder)` before teardown at the D4 `jumpToScene_partFour` take hook, in the same task as F3’s take, and upload that; release it after use or cancellation. **WS-R exposes the optional pre-teardown continuity take through the existing player integration, including opacity-off operation; add no additional replacement site.** At HEAD, the existing `_MM_OPACITY_REPLACEMENTS` site (`src/obed_edom/live_runtime.py:210-211`) calls private `PB.prototype.__obedFreezeTake`, whose `__obedShape` guard rejects Magic Move (`:57-75`), and `patch_player` omits it with `mm_opacity=False` (`:312-321`). Expose the continuity callback at that existing site independently of that freeze guard and of MM opacity; WS-R owns `live_runtime.py`, its tests and affected digest pins, WS-F consumes the captured frame.
  - A non-unique binding, initially unavailable upload path, first-draw mismatch or CEF Q6 failure keeps the baked poster, with the reason per entry. A mid-move stand-down keeps the last fed upload only while the context and fed bindings remain usable; otherwise record an unavailable rendering path without claiming exact hold. `once` has no inter-feed-gap requirement for its hold verdict after its successful upload; it does not waive an arm’s explicit continuous-feed expectation (§5.3).
  - Dev loop: headless arms plus ≥ 10 real-clock GPU Chrome runs of the exact-frame arms (§5.3), confirming the held frame is the last presented frame at move start.
- **Warm-up (limit 4):**
  - The player creates a **fresh GL context per transition** (one `0-canvas` context per move, at 1542 / 6050 / 10097 ms in `run2-cmp/direct`). So no warm-up inside the player's context can precede the first feed.
  - Warm up while arming by uploading each eligible decoder once into a texture in a **module-owned** WebGL context.
  - Dev loop: ≥ 10 real-clock runs per Alpha move. If any first-feed gap over 2 frames remains, bring its rate and measured hitch to the owner before the contract freezes. There is no in-player fallback.
- **Publishes** `window.__OBED_MM_FEED__`: `once(objectId)`, per-entry mode `continuous|once`, state `armed|fed|held|stoodDown(reason)`, frames fed, max inter-feed gap, p95 ms; record exact hold vs baked fallback vs unavailable rendering path and its reason per entry.

**Core (`js`, WS-R)**
- **Hidden ride.** For an `underArtwork` entry, the branch lives **inside `keepThroughBridge`/`keepThroughPin`**. Every ride start funnels through them: `markTransition` `js:791-796`, `keepAtSlot` `js:1311-1315`, every `tryRemount` retry `js:1633`, and the departure path stash → `scheduleRemount`.
  - The branch is a `hidden` flag on `rideTransition` that sets `opacity: '0'` and keeps its ownership token, so no visible ride can take the decoder over. The decoder stays attached on `#body`, still decoding: the experiment's opacity-0 video delivered every frame.
  - `keepAtSlot` hands off for a next entry with `underArtwork` whether it is a **bridge or a pin**. Otherwise a held overlay keeps `opacity: '1'` every frame (`js:1336-1338`), and `keepThroughPin` refuses `__obedBridged34` (`js:1231`).
  - **Claimed** (`seam.feed.claim` before departure): the decoder keeps playing.
  - **Otherwise poster hold.** At hidden-ride start, `pause()` and set `__obedPosterHeld = true`, then note `poster-hold {elId, t}` and call the module’s `once(objectId)` when available. The paused picture is the frame on screen at move start; never seek. With no binding/module, retain the baked poster and record why. `onStandDown` mid-move pauses and sets the same flag, but does **not** call `once`: keep the last fed upload only while the context and fed bindings remain usable; otherwise record an unavailable rendering path without claiming exact hold.
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
  - `carry()` clears `__obedPosterHeld` before `scheduleRemount('pin-rehome')`, with note `poster-resume {elId, t}`. The re-home’s own `play()` (`tryRemount`, `js:1738-1740`) then resumes from the actual pause point without seeking. Departure one-shots retain the held+1 gate; post-feed stand-down reports any resumption discontinuity relative to the retained upload and does not claim exact held+1 continuity when the pause point has advanced (§5.3). Pins already re-home.
- **Seam.** `window.__OBED_P2_PRESERVE__.feed = {version: 1, decoderFor(objectId), claim(objectId), onStandDown(objectId, reason), note(kind, detail)}`.
  - It is installed for every plan with a `feed` key, whatever the host resolved. The plan sha does not depend on the output.
  - With the module absent, nothing claims, so every flagged entry gets a baked-poster hold with a reason. With `once` available but no continuous claim, the hold path requests the exact-frame upload.
  - G2's seam is unchanged.
- **Versions.** `CONTINUITY_VERSION` 6→7, `__OBED_P2_PRESERVE__.version` 9→10, re-pin `PINNED_CORE_SHA256` and its mirrors.

**Host (`host`, WS-H)**
- `_resolve_mm_feed()` mirrors the result states of `LiveOutputHost._resolve_gl_replay` (`host:1016-1032`), whose attach guard identifies transport, not renderer: `injected | notApplicable | unavailable(reason)`.
  - Resolve one-shot eligibility by the qualified renderer separately from attach transport. Q6 failure disables CEF uploads; qualified attached Chrome retains `once`. External attach continues to refuse continuous feeding ("attach output not qualified"), even with `on`. The probe's `launch_attach_chrome` launches Chrome (`probe:4084-4094`); the D7/Alpha attach arms exercise its qualified one-shot path.
  - **WS-H freezes the renderer predicate using the recorded Chrome and OBS/CEF fingerprints, checking OBS/CEF before generic Chrome, and resolves it before selecting injected scripts. Test the real fingerprints with `MM_FEED_MANAGED_OBS=False`.** Use `Browser.getVersion.userAgent` as well as `product`: the recorded OBS/CEF session has product `Chrome/127.0.6533.120` but `OBS/32.2.2` in its user agent (`browserVersion` record, `output/evidence/s2-dev/live-logs/gate-main-1589d096/20261012T112006Z-85762-38249581806583.jsonl`); the recorded Chrome session has product `Chrome/154.0.8037.59` and `HeadlessChrome/154.0.0.0` without OBS in its user agent (`browserVersion` record, `output/evidence/s2-dev/live-logs/agent-a2b9951732d577563/20261010T124346Z-63389-156857096960208.jsonl`). At HEAD, `LiveOutputHost.start` assembles/serves scripts at `host:1184-1193` before reading the version at `host:1199-1204`; resolve the renderer before selecting the feed script and before navigation.
  - Continuous and one-shot eligibility are resolved separately. With `MM_FEED_MANAGED_OBS = False`, normal CEF sessions (managed OBS and CEF external attach) enable neither path → baked-poster hold. Q6 qualifies both CEF paths; a pass flips the constant before Q7, enabling managed continuous `auto` and the separately eligible CEF one-shot (including CEF external attach). A CEF failure disables both uploads only in CEF and records a baked-poster fallback per entry (OQ-B10); qualified attached Chrome retains `once` regardless of that constant.
- `OBED_LIVE_MM_FEED=off|auto`, plus a constructor flag `off|auto|on`.
  - `on` exists for continuous qualification only. It injects in managed OBS before the constant flips, so the Q6 feed arm can run. Continuous `on` is still refused for external attach. Define a separate constructor-only `mm_feed_qualify_once=False` override, set only by the qualification harness for Q6’s `mm_feed="off"` arm: it enables unqualified `once` with continuous feeding off. No env/dashboard control enables this override; normal CEF sessions enable neither path until Q6 passes. Ordinary `off` retains only the qualified one-shot path; continuity off injects neither path even with either override (OQ-F2).
- **CEF dev-loop step** (before WS-F starts, owner's OBS go): run `glfeed/instrument.js`'s `direct` arm on Alpha 9→10 inside managed OBS through the existing `mmo-cef` harness, unrecorded.
  - A fail applies resolved OQ-B10 early: managed OBS keeps the baked-poster hold; continuous feed remains Chrome-only until fixed. Record the CEF failure, and do not build the Q6 feed arm while it remains unsupported.
- `output.continuity.mmFeed {mode, reason, version, sha256}`, and per-entry `posterHold` lines (slides, movie, exact hold vs baked fallback vs unavailable rendering path, reason) next to `notCarried`. Show one line under the continuity badge (OQ-B11); no new UI surface.

**What the owner sees**
- **Feed on** (headless or visible Chrome; managed OBS once Q6 passes): the movie keeps playing inside Keynote's own move, with Keynote's easing. Tags and the divider stay on top, and the 0.61 tag boxes tint the live video. At settle it continues in its layer with the labels above, with no time jump.
  - There is a small midtone brightness step at departure and at settle. Chromium draws a native `<video>` through a tone curve that `texImage2D` does not get (up to +11/255 in the midtones; gl-replay-managed gates-r1 finding 1, the same residual as G2).
- **Poster hold** (external attach or feed off, with a qualified unique binding): the picture on screen at move start stops, travels inside Keynote’s move with labels above, and resumes from the pause point at settle; the next presented frame is held+1. No restart; the movie’s clock is held for the move’s 1.5 s. A mid-move stand-down keeps the last fed upload only while the context and fed bindings remain usable; it resumes without seeking from the actual pause point. If that point has advanced beyond the retained frame, report the resumption discontinuity and do not claim exact held+1 continuity.
  - Non-unique binding or an initially unavailable/failed upload path (including CEF Q6 failure) keeps the baked poster, with a per-entry reason and one line under the continuity badge. Context loss or loss of the fed bindings is reported as an unavailable rendering path; retained-picture continuity is not claimed.
- **Continuity off:** stock baked still and restart, unchanged (OQ-F2).

### 2.2 (2) N carries per boundary, authored stacking
- **Fed carries are unlimited per boundary.** The player draws them in slot order, so video-on-video overlap (the owner's sliver) renders as authored **in the move**. The settled re-home keeps that order once the slide settles.
- **Overlay-ridden (unflagged) bridges keep the one-per-boundary guard** (HEAD `_magic_move_movies`, `lc:1815-1816`, as fixed by `87ab7240`; B changes the count to exempt only `underArtwork` bridges). Checked on post-C `lc` (scratch `critic-r2/r10.py`): with the lift and this counting, Alpha_DSK 5→6, 6→7 and 7→8 all carry, and R10 still applies and passes. No deck qualifies two overlay rides at once, so B does not lift it.
- **Crossing rule (replaces rev 2's `zOrder`).** Two carries at one boundary may intersect in flight unless they are separated along a common axis, on the same side, at both ends (exact for linear edges under a shared progress; separation margin `_OVERLAP_MIN_PX`).
  - If they can cross and the destination settles into DOM → **both** become `under_artwork` (fed or poster-held; reason "crosses `<asset>`").
  - Otherwise the lower one (earlier destination slot) is refused `overlap`.
  - Alpha 7→8 is separated (930|930 → 763|764) and both carries are already under artwork. D7s exercises the crossing branch.
- **Rejected:** a sliver tolerance. It is not needed, and the rev 2 fallback is withdrawn.

### 2.3 Alpha_DSK specifics
- Deck fixture: `output/fixtures/sermon/alpha-dsk/`. The `7e3c9301…` fixture `output/fixtures/alpha-dsk-textures` is **unrepaired input**. WS-D copies its `html-unmodified`, runs Stage T’s `preview_textures.repair_textures` on the copy using its manifest, verifies zero remaining detector hits, then trims p3–p8 from that repaired copy and captures its binding expectations. Follow `test_alpha_export_round_trip_repairs_every_hit_and_keeps_the_plan` (`tests/test_preview_textures.py:539-553`, `:583-585`); gate qualification uses a re-prepared, T-accepted export of the edited deck.
- Last slide (ordinal 11), owner edit 2026-10-13 18:19: upper clip `.02` dissolves in over 0.5 s, With Build 1 at 8 s; lower `.01` movie-start is After Transition. The earlier “plays correctly” observation was wrong: the upper poster covered the lower clip.
- End of show: no runtime change (OQ-B4). 8→None has no runtime entry only in the trimmed p3–p8 fixture. Full Alpha expects two `retire ends` entries at 8→9 (`_cut_movies`, `lc:1820-1839`); 9→None is terminal. Reconfirm ordinal 10 → player 8 and ordinal 11 → player 9 on the edited export, and press past the end once at Q7.
- Skipped slide: no code change; record the ordinal mapping in the gate record.
- Audio: disabled.
- Rev 2's carry-cover sibling fix is dropped: no two overlay bridges ever share a boundary now. Carry-cover skips fed entries.

## 3. Schema, shas, oracle
- **Schema 2 gains two additive keys:** `underArtwork: true` and `feed` (present only when bound). `zOrder` is gone. G2 ignores extra keys.
- **Byte-identical runtime plans:**
  - **P2, p2-loop and D1–D6 stay byte-identical.** Their plan-sha tests must pass unedited; that and S3’s merged `tests/test_live_continuity_corpus.py` are B’s regression oracle.
    - P2's 1→2 destination is click-driven.
    - D1–D6 have no artwork overlap.
    - D3's pin+bridge pair is x-separated (pin x 100–900, bridge x 1020→1100). It is the only D-deck boundary with two carries, so the crossing rule changes nothing there.
  - These plans inject no module and run no new core branch. The plan sha hashes the runtime JSON only (HEAD `plan_signature`, `lc:655-657`; `ContinuityPlan.to_runtime` construction, `lc:813`), so the core version and sha bumps do not touch it.
- **Plans that change:** the Minimal Alpha_DSK family (the `clip-10-1000001` pin becomes `underArtwork` under OQ-B2).
- **Tests and corpus that change on purpose:**
  - Replace the inherited rev-2 test list with current overlap expectations: DOM-settling artwork overlap → `underArtwork`; click-driven / extra-event overlap stays refused; R11 stays refused. Update the affected Minimal Alpha expectations explicitly.
  - Retain the unflagged-bridge guard in `test_only_unrefused_geometry_changes_count_towards_the_one_per_boundary_limit` (`tests/test_live_continuity.py:438-465`): two clean unflagged bridges still refuse; exempt only `underArtwork` bridges, including the DOM-settling artwork-overlap clone. Refused overlapping bridges still do not count; cover that case with a non-settling destination.
- **S3 corpus stays unchanged:** merged `tests/test_live_continuity_corpus.py` already uses P2’s click-driven destination for `overlap` and asserts `automaticPlay is False`. No re-pointing is needed.

## 4. Work streams (Codex GPT-5.6 Sol high implementers; Opus 5.5 high reviews)
- **Temporary owner roster through 2026-10-27:** one Codex GPT-5.6 Sol at effort high per WS, disjoint files. Opus 5.5 at effort high reviews the combined diff; rounds 1–3 fold all severities, from r4 only major/blocker.

**Frozen contract before launch:**
- `underArtwork`;
- `feed` shape, derived at every prepare from the served repaired JSON, never a pinned table;
- `feed_draws` / `artwork_above` shapes;
- seam `feed` v1 (with `claim` for continuous mode only); module `once(objectId)` and the WS-R hidden-ride call after pause, no re-upload on mid-move stand-down; paused picture / D4-take `VideoFrame` fallback, never seek;
- `MM_FEED_MANAGED_OBS`, separate continuous/once eligibility by qualified renderer independently of attach transport, WS-H’s recorded-fingerprint predicate checking OBS/CEF before generic Chrome and resolved before injected-script selection, continuous qualification `on` and constructor-only `mm_feed_qualify_once` for Q6 with `mm_feed="off"`; normal CEF enables neither until Q6 passes; `mm-feed off` retains qualified `once`, continuity off stays stock; CEF failure disables both upload paths there, per-entry baked fallback reason; qualified attached Chrome retains `once`, external attach always refuses continuous feed;
- `__OBED_MM_FEED__` fields;
- variant names `overlay-ride`, `settle-on-stage`, `no-pause` (core) and `from-only` (feed);
- probe tamper `--feed-tamper ordinal` and `--feed-tamper after-feed` (WS-G); probe-only hold-upload kill switch; `holdFrame` exact frame and departure one-shot `posterHold` held+1 controls/arms; post-feed stand-down verifies retention and no-seek resumption from the actual pause point, reporting any discontinuity (§5.3).

| WS | Files (exclusive) | Work | Minimal tests |
|---|---|---|---|
| D | `lc`, `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py`, `tests/fixtures/live_continuity/**` (copy `output/fixtures/alpha-dsk-textures/html-unmodified` / `7e3c9301…` → Stage T repair → verify zero hits → trim p3–p8; S3 corpus unchanged) | settle-into-DOM lift, crossing rule, guard counting, `feed` binding from the served repaired JSON at every prepare, probe facts | (1) the Alpha fixture derives the expected entries and `feed` (5→6: 5 draws/7 regular uploads; 6→7: 9/12; 7→8: 12/17, counts/ordinals unchanged by repair; sizes re-captured from the repaired JSON); (2) parametrised overlap: settling → `underArtwork`, click-driven / extra event → `overlap`, R11 unchanged; (3) crossing → both flagged / lower refused |
| R | `js`, `tests/test_live_continuity_js.py`, `scripts/continuity_core_variants.py` (+ test), re-pins in `tests/test_live_gl_replay_js.py`, `scripts/detach_experiment.py`, `tests/test_detach_experiment.py`, `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` and affected player digest pins | hidden ride, poster hold pause → `once(objectId)` call → resume and keep-warm exemption, expose optional pre-teardown continuity take at the existing D4 site, independent of the freeze shape guard and available with MM opacity off; no additional replacement site, settle re-home, seam, versions, 3 variants | Node: (1) a fed bridge never paints during the move and lands in the poster layer, with no `src` on the stub; (1b) a held plain-bridge overlay → `underArtwork` lands in the layer; (2) poster hold: paused at departure **including stash's play-then-remount order**, not re-played by keep-warm or `tryRemount`, calls `once` after pause without seeking, resumes from the pause point (held+1 gate); (3) stand-down mid-move → pause with no re-upload; (4) claimed → keeps playing, unclaimed with a `feed` key → poster hold; (5) overlay bridge → `underArtwork` pin hands off hidden; (6) optional take callback runs before Magic Move teardown with MM opacity on/off, captures/releases the fallback frame, and updated player digest pins pass |
| F | **new** `src/obed_edom/live_mm_feed_js.py`, **new** `tests/test_live_mm_feed_js.py`, **new** `scripts/mm_feed_variants.py` | the module (§2.1), one-shot `once` mode, paused-element / `VideoFrame` upload, warm-up, telemetry, `from-only` | Node with a fake GL: binding accept/refuse (ordinal, size, unit, `mixFactor` present/absent per `to`), claim at idle, identity re-key, state restored, two fed leaves in one frame, from-only leaf, `getContext` chain with G2; `once` uploads each bound texture exactly once at the first draw, never claims continuous play, restores state, no later uploads, baked fallback reason |
| H | `host`, `tests/test_live_host.py` (incl. its core-sha re-pin), `dashboard/src/live/{api.ts,LivePresenter.tsx}`, `dashboard/tests-ui/live-presenter.ui.test.tsx` | `_resolve_mm_feed`, renderer predicate resolved before injected-script selection (OBS/CEF before generic Chrome), env/flag, continuous vs one-shot availability, output fields, `posterHold` reporting + one line under continuity badge | (1) attach refuses continuous feed even with `on`, retains qualified `once`; (2) injected only with continuity on + a `feed` key; `mm-feed off` retains qualified `once`; (3) normal CEF has neither path before Q6; continuous `on` injects for qualification; constructor-only `mm_feed_qualify_once=True` with `mm_feed="off"` enables only `once` for Q6, continuity off still injects neither; after Q6 pass ordinary `off`/CEF attach retain qualified `once`; CEF failure disables both CEF paths with per-entry baked reason while qualified attached Chrome retains `once` with the constant false; (4) replay the recorded Chrome and OBS/CEF fingerprints with `MM_FEED_MANAGED_OBS=False`: OBS’s Chrome product plus OBS user agent must disable normal CEF uploads, while attached Chrome retains `once`; assert renderer resolution precedes script selection; badge line |
| G | `probe`, `tests/test_live_continuity_probe.py`, `scripts/live_evidence_contract.py`, `tests/test_live_evidence_contract.py`, `scripts/run_gates.sh`, **new** `scripts/mm_feed_instrument.py` (probe-only in-frame GL reader, from `glfeed/instrument.js`), `scripts/managed_obs_qualify.py` + its test | verdicts and arms (§5.3), carry DOM/GL interval integration, `holdFrame` controls and kill switch, post-feed stand-down arm (`--feed-tamper after-feed`) proving last-upload hold through settle and no-seek resumption from the actual pause point, with any discontinuity reported, explicit continuous-feed expectation for feed-off, registrations; evidence contract for new decoder/frame producers and poster/feed note payloads, updated in the same commit as producer changes | scorer units for each new verdict (pass/fail/inconclusive); hidden carry passes with evidenced GL coverage while pre/post DOM failures remain red; feed-off exact hold green but continuous expectation red; post-feed stand-down scores `holdFrame` green only for the retained last upload and `posterHold` verifies no-seek resumption from the actual pause point and reports a discontinuity without claiming exact held+1 continuity if that point has advanced; departure one-shot held+1 remains required; unavailable context/bindings cannot pass exact hold; contract required-field/generation tests for new producers and notes; registrations as data |
| Coordinator | `output/fixtures/qual-decks/author/gen.py` and generated D7/D7s fixture artifacts under `output/fixtures/qual-decks/` (WS-D retains `tests/fixtures/live_continuity/**`) | extend the S0 generator for D7/D7s artwork and geometry, generate their fixture artifacts, and obtain V4 confirmation before WS-G qualification | verify §5.2 geometry/draw order and the owner’s V4 confirmation |
| P | `README.md`, `.agents/skills/obed-edom/SKILL.md` | "What is carried" (feed, poster hold, N carries); contract keys; module table | — |

Full suites on 3.12 (`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`), and the 3.10 floor for the probe/paint/run_gates files, locally.

## 5. Re-qualification

### 5.1 What reopens, precisely
- **Core bytes change, so §4's rule reopens Q2–Q6.** P2, p2-loop and D1–D6 run none of the new branches and inject no module. Their verdict tables must **equal S3's**, which is a regression check, not new qualification.
- **The new module is qualified only where it is injected:** D7, D7s and Alpha_DSK in Q3, the Q5 exact-hold arms, Q6’s continuous/one-shot arms, and Q7.
- **G2 bytes are unchanged.** Q4 reruns only because the core bytes changed. G2 decks have no `feed` key, so their seam object is unchanged.

### 5.2 Decks
- The coordinator owns extending `output/fixtures/qual-decks/author/gen.py` for D7/D7s artwork and geometry, generating their fixture artifacts, and obtaining V4 confirmation before WS-G qualification. The current S0 generator’s `DECKS` defines only D1–D6 and `deck_script` generates movies plus the template label; add TA/TB/DV as specified below. Authoring remains under the owner’s Keynote go, plus the owner’s V4 eyeball (resolved OQ-B7).
- D7 and D7s keep rev 2's geometry and draw order (A, B, TA solid green, TB white 61 %, DV), and every movie starts After Transition.
- Fed moves let the binary counter be decoded from GL pixels, which makes `feedLive` exact on D7 and D7s.

| Deck | Expected plan | Proves |
|---|---|---|
| **D7** (S1→S2 both shrink, S2→S3 grow back, S3→S4 hold) | @2 and @4: bridge A+B, `underArtwork` + `feed`; @6: pin A+B, `underArtwork` + `feed` (to = null if no crossfade) | the feed in the move, labels on top, two fed carries per boundary, fed pins, the settle re-home chain |
| **D7s** (no DV; S2 B at 955 → 5 px over A) | @2/@4: bridge A+B, both flagged (artwork and crossing) | the owner's sliver drawn as authored in the move and once settled |
| **Alpha_DSK** | @6 overlay bridge (untitled), @8 restart, @10/@12 fed bridge, @14 two fed bridges; full deck: two `retire ends` at player 8→9, terminal 9→None (reconfirm on edited export); 8→None is trimmed-fixture-only | the goal |

### 5.3 Gates and verdicts
**Carry integration (WS-G):** For `underArtwork` carries, replace DOM ownership/paint requirements only during the evidenced GL interval with the applicable feed/hold verdicts; preserve decoder identity and pre/post-move DOM checks. Integrate in `score_continuity` (`probe:2250-2264`, `:2373-2384`), without disabling paint for the whole carry. Missing GL interval evidence cannot exempt DOM checks. WS-G also updates `scripts/live_evidence_contract.py` and its tests for the new decoder/frame producers and poster/feed notes in the same commit as producer changes; `score_verdicts` validates records before scoring (`probe:3843-3845`).

**New verdicts (WS-G):**
- **`feedLive`** (per fed carry, read in frame at progress 0.25/0.5/0.75, single run):
  - The patch lies inside the fed leaf's projected quad (MVP from the draw) and is **not covered by any later draw's quad** (grow 2 px).
  - The reference is the decoder drawn into a canvas at the leaf texture's size **in the same task**, sampled over the patch's UV footprint.
  - D7/D7s: the decoded counter must equal the reference's counter ±1.
  - Alpha: green when dV ≤ dP/2, where dP is the export poster over the same footprint. INCONCLUSIVE when dP is below a floor.
    - Register the floor by re-scoring `run2-cmp/direct`: all 9 reads must score green or inconclusive.
    - The rev 3 centre-patch rule scores 6→8 at 0.5 as tP 0.556 (dV 13.1, dP 10.5) on a working feed. 9→10 wa0121 at 0.75 reads a label box over the centre (dV 13.1).
  - Plus advancing frame evidence and continuous upload coverage, including a max inter-feed gap under the paint-coverage rule (slower side's cadence), which catches the 357 ms stall; retain the decision-14 undecodable-draw exemption. Score the feed-off red arm against an **explicit continuous-feed expectation**, independent of the observed module mode. A paused decoder matching its one-shot GL picture cannot pass that expectation; score its exact hold separately.
- **`noRiderAboveCanvas`:** on every rAF of a fed or poster-held move, no carried decoder composites while it intersects the GL canvas (`opacityProduct > 0.02`, visible). The player hides the source layers during the move, so any compositing decoder is above the canvas.
- **`labelsOverFeed`:** for each label-box draw over a fed leaf, computed in frame from a single run.
  - Read under = `readPixels` just before the label draw, and final = after the frame's last draw.
  - Use the box's pixels inside its quad (grow −3) that are not covered by later quads (grow 2).
  - k = the least-squares slope of final on under. It must be within ±0.02 of 1−opacity. INCONCLUSIVE when the spread of under is below 24.
  - The rev 3 cross-arm k (`analyze.py:97-123`) needs a paired off-arm frame at identical geometry, which exists only under the virtual clock.
  - Draw 7 is included (limit 6). The uncovered k measured 0.388–0.390 against an expected 0.388.
- **`holdFrame`** (per poster-held entry at departure): in-page `readPixels` of the GL canvas at the leaf’s planned/projected rect, at its first draw, p≈0.5 and the last frame before settle. Match each crop against decoded source frames; the index must equal the decoder’s **last rVFC-presented frame before departure**, exact (0 frames tolerance), with a match margin over the next-best frame under the PDF-vs-decode floor. An ambiguous match is INCONCLUSIVE, never green.
  - **Null:** the same capture with `--mm-feed off` plus the probe-only hold-upload kill switch shows the baked frame 0 on the repaired fixture → `holdFrame` red.
  - **Positive:** a continuously fed arm advances → `holdFrame` not applicable, `feedLive` green.
  - **Arms (Q3/Q5/Q7):** repaired Alpha_DSK ordinal 8→9 and 9→10, dwells 2/5/12 s (held picture distinct from the baked poster), plus D7 attach. Headless and ≥ 10 real-clock GPU Chrome dev-loop runs. Re-prepared edited Alpha for owner qualification.
  - **Post-feed stand-down arm (WS-G, Q3):** extend the feed-tamper control with `--feed-tamper after-feed` on repaired Alpha_DSK ordinal 8→9 and 9→10 to force stand-down after evidenced successful feeding, once the decoder has presented a frame beyond the last uploaded frame and before another upload. Keep the context and fed bindings usable. Require the existing `holdFrame` verdict to retain the evidenced last uploaded frame from stand-down through the last draw before settle; no re-upload. For post-feed stand-down, verify last-upload retention and no-seek resumption from the actual pause point. If that point has advanced beyond the retained frame, report the resumption discontinuity and do not claim exact held+1 continuity. Keep the departure one-shot held+1 gate unchanged. Missing successful-feed/advanced-decoder evidence cannot pass this arm.
  - Non-unique binding / CEF Q6 failure is a recorded baked fallback, not a green exact hold. A mid-move stand-down with a usable context and fed bindings is scored against its last fed upload from stand-down onward, not the move-start frame; no re-upload. Context loss or loss of the fed bindings is an unavailable rendering path: record the failure and do not pass `holdFrame` or claim retained-picture continuity.
- **`posterHold`:** for a poster-held carry, the clock is still during the hold, resumes from the pause point without seeking, and does not go back to 0. For a departure one-shot, the first frame presented after settle must be **held+1**, tightened from a ±1-frame resume tolerance. For post-feed stand-down, verify no-seek resumption from the actual pause point; if it has advanced beyond the retained frame, report the resumption discontinuity and do not claim exact held+1 continuity. It replaces the carry verdict’s stall rule for that entry only; mid-move stand-down holds from stand-down onward.
- **`artworkAbove`** (settled, rev 2): unchanged.

| Q | Run | Pass | Red controls (pre-registered, each red only on its verdicts) |
|---|---|---|---|
| Q1 | Suites | green | — |
| Q2 | P2 `run_gates` fast/slow/auto | equal to S3's table | existing |
| Q3 | Host probe ×3 viewports, arms A/B/C, attach, V/Voff/Vgl, Pass G; P2 + D1–D6 (equal to S3) + D7, D7s, Alpha_DSK; plus an MM-opacity-off arm on Alpha | all applicable verdicts, including `holdFrame` + `posterHold` on the exact-frame arms above; attach arm scored with poster-hold facts; baked fallbacks recorded separately | `feed-off` (`--mm-feed off`, explicit continuous-feed expectation independent of observed `once` mode) → `feedLive` red for missing frame advancement/continuous upload coverage; the same capture with the one-shot enabled scores `holdFrame` + `posterHold` green. Hold-upload kill switch → `holdFrame` red; fed positive control → `holdFrame` not applicable, `feedLive` green. Register `from-only` red expectations only for D7/D7s entries with non-null `feed.to`; single-texture entries must remain green. For those crossfading entries, `feedLive` is red at the 0.5 and 0.75 reads, green at 0.25. On Alpha the run1 `from` arm read 0.75 green and 0.5 red. `overlay-ride` → `noRiderAboveCanvas` red only; `labelsOverFeed` stays green, since it reads the GL buffer, which a DOM overlay does not touch. `settle-on-stage` → `artworkAbove` red. `no-pause` under feed-off → `posterHold` red (~1.5 s jump). `--feed-tamper ordinal` → stand-down note, `feedLive` red, `posterHold` green, baked fallback recorded (`holdFrame` cannot pass; proves binding fails closed). `--feed-tamper after-feed` → evidenced successful feed then stand-down with usable context/bindings, `feedLive` red for interrupted continuous coverage, `holdFrame` green for the last uploaded frame through settle; `posterHold` verifies no-seek resumption from the actual pause point and reports the resumption discontinuity when that point has advanced, without claiming exact held+1 continuity. Departure one-shot held+1 is unchanged. MM-opacity off → `labelsOverFeed` red (boxes solid). `--strip bridge@14:movie2` → only wa0121 b7to8 red |
| Q4 | G2 seam (Vgl, `--gl-force-fail` ×4) | as S2 | `--gl-force-fail` |
| Q5 | Full loop scope: L1 + L2 per rule (resolved OQ-B5); include the exact-frame arms above across loop repetitions | as S2; `holdFrame` + `posterHold` green for exact holds | as S2; hold-upload null and advancing-feed positive controls above |
| Q6 | Managed OBS arms at 25/30 + **new `feed` arm** (constructor `mm_feed="on"`; Alpha 6→8, 9→10 in CEF) + `feed-off` one-shot poster-hold arm (constructor `mm_feed="off", mm_feed_qualify_once=True`, qualification-only; owner’s go); a pass flips `MM_FEED_MANAGED_OBS` | M1–M6; feed and exact-hold verdicts green in CEF. Failure applies resolved OQ-B10: both upload paths off there, baked fallback recorded per entry; Chrome feed remains | OD-2 `--kb` arms; `feed-off`; hold-upload null |
| Q7 | Owner: managed OBS Keyer (feed after Q6 pass; recorded baked fallback on CEF failure) on D7, D7s, re-prepared edited Alpha; external attach exact-frame arms above on Alpha + D7; D1 spot; press past end once | labels on top in the move and settled; no visible restart; exact hold stops on the picture showing at move start, travels with the move and resumes at held+1 (`holdFrame` + `posterHold`); recorded baked fallbacks distinguished; the midtone step at departure and settle is acceptable | hold-upload null and advancing-feed positive controls above |

## 6. Sequencing
- **C #264, S3 #266 and T #267 are merged; T’s retained merge is `ad6dac98`. Rebase B onto updated main before implementation (verified HEAD `6e10ef04`).**
- B derives every prepare’s bindings from T’s served repaired JSON; WS-D copies the unrepaired 7e3c `html-unmodified`, runs Stage T repair on the copy, verifies zero remaining hits, then trims and captures binding expectations. Qualification re-prepares the owner’s edited Alpha deck and uses an export T accepts.
- S3’s merged `tests/test_live_continuity_corpus.py` stays unchanged, alongside the unchanged plan-sha tests (§3).
- B adds no allowlist: D7, D7s and Alpha_DSK join through their plan-sha tests and registrations.

## 7. Owner decisions resolved (2026-10-13, all per recommendation)
1. **OQ-B2: pins under artwork on DOM-settling slides — yes.** They are fed in the move and already re-home. D7 S4 covers them.
2. **OQ-B4: end of show — no change.** Press past the end once at Q7.
3. **OQ-B5: re-qualification scope — full Q2–Q6** per §4, with P2/D1–D6 as equality checks and full Q5 scope (L1 + L2 per rule).
4. **OQ-B7: D7/D7s authoring — S0 generator** under the owner’s Keynote go, plus the owner’s V4 eyeball.
5. **OQ-B8: slivers on click-driven slides stay refused — accepted for B.**
6. **OQ-B9: feed every carry on DOM-settling slides — later stage.** Retiring the overlay ride, its eased interpolation and R10 changes D1–D6 and P2 3→4 behaviour and reopens their oracles.
7. **OQ-B10: CEF Q6 feed failure — ship managed OBS on poster hold, feed in Chrome outputs only until fixed.** The exact-frame one-shot also stands down on CEF failure, in CEF only; retain the baked poster there and record the reason per entry. Qualified attached Chrome retains `once`; external attach still refuses continuous feed.
8. **OQ-B11: surfacing poster hold — host field plus one line under the continuity badge.** No new UI surface.
9. **OQ-F1–F3: exact-frame hold folded into B; continuity off stays stock; held frame = frame on screen at move start.** Pause → one-shot upload → resume from the pause point, never seek to `currentTime`; mid-move stand-down keeps the last fed upload only while the context and fed bindings remain usable, otherwise record an unavailable rendering path without claiming exact hold.

## 8. Residuals (README)
- Exact-frame poster hold requires a unique binding and a qualified upload path. Non-unique binding or an initially unavailable/failed path (including CEF Q6 failure) keeps the baked poster, recorded per entry; mid-move stand-down keeps the last fed upload only while the context and fed bindings remain usable. If the actual pause point has advanced beyond that retained frame, report the resumption discontinuity and do not claim exact held+1 continuity; resume without seeking or re-uploading. Context loss or loss of the fed bindings is an unavailable rendering path, not a successful exact hold; record the failure without claiming retained-picture continuity. No new recovery mechanism is in scope. Continuity off stays stock.
- A fed move shows a small midtone brightness step at departure and settle (the native `<video>` tone curve, as G2).
- Overlay-ridden carries with no artwork overlapping them on the destination still paint above artwork they cross mid-flight, and follow R10 eased interpolation.
- One overlay bridge per boundary.
- Overlap on click-driven or multi-build destinations stays refused.
- Keynote texture-id defects vary per export. B binds by geometry, draw index and regular-upload ordinals **and reads sizes from the served repaired JSON at every prepare**. It depends on Stage T for the served bytes: D1–D4 repair, one re-export on refusal, then refusal by slide/object name. The repaired 7e3c copy’s counts are unchanged; old unrepaired sizes are not a binding oracle.
- Probe ordinal labels after a skipped slide.
- Audio is disabled (a suppressed overlay-bridge destination still decodes).
