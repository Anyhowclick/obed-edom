# Alpha Keynote live presenter — porting guide

Written 2026-10-19 as obed-edom is retired. The guide is for carrying the live-presenter knowledge into the staff-built tool.

- Line pointers are against `main` @ `5703c2ae` unless a branch is named.
- Contracts in full: `.agents/skills/obed-edom/SKILL.md` §"Live continuity contract", §"Alpha Keynote managed OBS", §"Alpha Keynote live go-to".
- Operator view: README §"Alpha Keynote experiment", §"Movie continuity", §"Keyer output (managed OBS)".
- History of why: `.agents/HALL_OF_WITNESSES.md`.

## 1. What it does, end to end

The presenter plays a Keynote deck live, with real alpha, as fill + key over live video. Keynote does not render; Keynote's own HTML export does.

1. **Prepare (offline, once per deck).**
   - AppleScript drives Keynote to export HTML from a scratch copy of the `.key`.
   - The export is cached, with a manifest.
   - The cached export (never the `.key`) is then repaired, in this order:
     1. texture-id repair ("Stage T");
     2. movie conversion: H.264, or VP9-alpha WebM for ProRes 4444 with alpha.
   - Load-time checks refuse a deck the player cannot run. Requirements: a known player sha, 16:9, manual show mode, no web media, at least one playable slide.
2. **Serve.**
   - A loopback asset server serves the export with Range support, so `<video>` can seek.
   - The player `assets/player/main.js` is replaced by an **in-memory, sha-pinned, byte-patched** copy. The file on disk is never edited.
   - A generated `program.html` wraps the player. It makes the background transparent, hides the player chrome, spoofs fullscreen so the player fits the stage, and injects the continuity scripts.
3. **Render.** There are two engines.
   - **HDMI:** a host-launched Chrome, fullscreen on the output display. The background is black because HDMI carries no alpha.
   - **Keyer:** a hidden, isolated, version-pinned OBS whose browser source (CEF) loads the same page. The host attaches over CDP.
4. **Drive.** The host sends CDP key events (Space to advance; digits + Enter to go to a slide). It reads player state from an injected observation hook, `window.__obedLive.snapshot()`.
5. **Continuity.** An offline plan, derived from the export JSON, says what happens to each movie instance at each slide boundary: `pin`, `bridge`, `restart`, `retire` or `glReplay`. An injected JS core carries the live `<video>` decoder through Magic Moves, so the movie does not restart. The export restarts it by default.
6. **Out.** OBS DeckLink Output, with Keyer = External and BGRA 8-bit, sends fill + key through a Blackmagic UltraStudio to the switcher.

Status:
- **HDMI and managed-OBS paths:** shipped on main.
- **Managed engine:** step 5 qualification PASSED on `76452a91`, except `placement` (finding D2, §5).
- **Venue hardware test:** never run.
- **Stage B** (artwork stays above a moving movie during a Magic Move): unmerged (§5).

## 2. Modules and where the non-obvious logic lives

### 2.1 Prepare

| Pointer | What it solves |
|---|---|
| `html_preview.py:1043` `apply_preview` | The prepare sequence is export → `repair_textures` → re-export **once** on `TextureRepairRefused`, because exports are a lottery (`:1086-1099`) → `convert_movies` → manifest. The cache is invalidated on player sha or repair version change (`:917`, `:923`). |
| `dsk_live.py:556` `LiveBatch` | Keynote automation for the export: a lock, a display poke, an RSS watchdog, a `-1712` retry and a source fingerprint check. |
| `web/live.py:149` `prepared_deck` | Load-time playability rules. Only these block Start; continuity never does. |
| `preview_textures.py:1201` `repair_textures` | Keynote maps some leaves to another object's PDF page. Detection: `_json_hits` `:403` checks sizes, then pixel checks. Donors: D1 text, D1g per-letter glyph twin `:775`, D3 poster, D2 graft of the previous slide's MM `contents.to` page `:824`. Postcondition `:1172`: re-detect must find 0. No verified donor means the prepare fails, naming every slide. |
| `preview_movies.py:328` `convert_movies` | Re-encodes every non-H.264 movie in the cached export under its **original filename**. Copies with identical media data are encoded once. Encodes are verified before `os.replace`. |
| `preview_movies.py:162` `_conversion_target` | Alpha is detected by pix_fmt plus `alphaextract` min < 255. Alpha is allowed only from ProRes with an identity matrix and edits and no audio; everything else refuses. Odd sizes refuse. Alpha is never flattened. |
| `preview_movies.py:198` `_alpha_encode_argv` | `libvpx-vp9 -pix_fmt yuva420p -crf 20 -b:v 0 -row-mt 1 -fps_mode passthrough -f webm`. |
| `preview_movies.py:260`, `:273`, `:291` | Verification decodes with `-c:v libvpx-vp9` **before `-i`**, then checks frame count, duration and alpha PSNR ≥ 48 dB. |
| `live_codec.py` | Pure MP4/MOV box and EBML walkers: codec, fps, timing, geometry; `webm_info` reads `AlphaMode`. No ffprobe on the hot path. |

### 2.2 Player patch: `live_runtime.py`

- `SUPPORTED_PLAYERS` `:11` maps each stock `main.js` sha to its three pinned outputs: patch on, patch off, preview. Two stock players are known.
  - `_pinned` `:442`: any byte drift fails closed with `LiveRuntimeUnsupported`.
  - `_apply_replacements` `:452`: every anchor must occur exactly once, before and after replacement.
- `patch_player` `:406` is the live path: the observation hook plus `_MM_OPACITY_REPLACEMENTS` `:228`.
  - The hook (`:323-399`) wraps `changeState`/`setCurrentSceneIndexTo` and exposes `__obedLive.snapshot()`.
  - The snapshot carries ready/busy, scene count and the auto-play run.
- `patch_rendering` `:434` is the Build Preview path. It has no hook and no freeze.
- "R-numbers" are positions in `_MM_OPACITY_REPLACEMENTS`. The source does not name them; the names come from `tests/test_live_runtime.py:300-311`.

| Patch | Effect |
|---|---|
| R1–R4, R13 | MM leaves draw at Keynote's authored chain opacity. The export draws them opaque during the move. Admitted fades keep the ramp × ancestor product. |
| R5 | `handleAnimateEffectDidBegin` runs synchronously, so the swapped DOM node hides in the same task as the first GL draw. This removes a one-frame double image. |
| R6–R7 | Hand-back geometry. A scaled MM leaf settles 2–3 px off the slide-2 DOM and snaps at build 1. The patch cross-fades it to the matched next-slide texture. |
| R8 | Preloads the destination slide only when the next event is a Magic Move. |
| R9–R10 | True Dissolve cross-fade (`isolation:isolate` + `plus-lighter`). A `none` cut becomes a clean swap with no double slide. |
| R11–R12 | Movie **freeze**: at `jumpToScene_partFour`, admitted outgoing `<video>`s are snapshotted to canvases that fade with the slide. Without it they jump to the baked opening frame. The freeze runs only with the host grant `window.__obedPlacement` (§2.3) and passes strict geometry, colour (bt709) and paint gates (`:84-172`). |
| R14–R19 | Line Draw. The export bakes it as an opacity fade; the patch re-reveals the texture along `shapePath` with fail-closed admission. |

### 2.3 Host: `live_host.py`

| Pointer | What it solves |
|---|---|
| `:458` `_AssetServer`, `:616` `_program_html` | Loopback server with Range support, and the program page. The page does a `webkitIsFullScreen` spoof so the player fits the stage. In alpha mode it sets a transparent `html/body/#body`, keeps `#body` at opacity 0 until `show()`, and runs a MutationObserver that re-applies this. HDMI mode uses a black cover. |
| `:665` `ChromeCdp` | One socket, one lock, a deadline per call. It routes events while waiting and tracks each frame's execution-context `uniqueId`, so grants bind to the program document. |
| `:899` `key` | **No `nativeVirtualKeyCode`.** On macOS it goes through AppKit key equivalents and stalls the browser UI thread. |
| `:928` `_blank_attached_target` | In attach mode, stop navigates the CEF page to `about:blank` so the last frame never stays on air. |
| `:1188` `LiveOutputHost` | `start()` `:1468` order: validate export → codec gate → continuity → patch → serve → `Browser.getVersion` → install placement channel → goto → continuity stage gate → settled. |
| `:77` `QUALIFIED_SNAP_MAJORS = (154, 155)` | The freeze is granted only on qualified Chrome majors. |
| `:132` `placement_init_script`, `:1754` `_sync_knowledge_placement` | Private, context-bound grant channel. HDMI grants `snap` only for a host-launched Chrome on a qualified major with GPU compositing on. A round-trip mismatch is `channel-compromised`: the output is hidden and `show` is refused. |
| `:2116` `_measure_probe` + `placement_probe.py:189` `classify_probe` | Managed OBS cannot use "knowledge". A pinned probe clip is shown in a hidden Studio-Mode preview and captured with `GetSourceScreenshot`. Freshness is a nonce decoded from the PNG. The classifier yields `snap`/`frac` or nothing; a grant is a renewable 15 s lease. |
| `:2615` `observe` | Raises if `sceneCount` ≠ the authored count, which detects the player silently falling back from the build renderer. |
| `:2821` `_repair_goto_autoplay` | After a go-to, a slide that starts with an automatic-play run is given one advance, or its movies sit idle. |
| `:2806` `_await_click_target` | In click mode, waits for the slide-number overlay to close; otherwise the click is eaten hiding it. |
| `:224` `movie_codec_refusal` | VP9 plays (headful Chrome, managed OBS) but is refused for continuity. |

### 2.4 Continuity

- **Plan, offline: `live_continuity.py`.**
  - `derive_plan` `:2159`.
  - Pairing `_pair_instances` `:1696` works by transition slot and recorded endpoint. There is **no distance fallback**.
  - Refusals: `_carry_refusal` `:1963`, `_overlap_refusal` `:1234`, `_bridge_timing_refusal` `:1827`, chain invariant `_chain_refusal` `:948`.
  - Whole-deck refusal: `Unsupported` `:853`. The deck still plays, with continuity off.
  - Geometry comes only from the authored layer tree.
- **Core, in page: `live_continuity_js.py`** (`CONTINUITY_VERSION` 6 `:97`; the docstring `:1-95` is the best spec).
  - `patchSrcAccessor` `:2017` hooks `src`. The player sets `id = objectID + "-video"` before `src`, and the hook re-identifies instances and swallows clears of pooled decoders.
  - `rideTransition` `:1149` moves a bridged decoder on **Keynote's own GL clock**: EaseInEaseOut, stamped by a `requestAnimFrame` setter hook, falling back after 50 ms.
  - `findMovieCanvas` `:1445` is the own-layer anchor rule.
  - `isCompositing` `:1354`.
  - A 200 ms keep-warm interval re-plays paused pooled decoders.
- **GL replay: `live_gl_replay_js.py`.**
  - After a click-driven Magic Move, the settled GL frame is replayed with the carried decoder's live pixels.
  - `wrapContexts` `:285` records the player's WebGL calls.
  - `uploadVideo` `:342` on main stages through a 2D canvas and calls `texSubImage2D`. Stage B's feed (§5) uses `texImage2D(video)` directly: 0.3–0.7 ms, against 6–10 ms for 2D staging.
  - `standDown` `:872` and context-loss handling are fail-safes.

### 2.5 Managed OBS / DeckLink: `managed_obs.py`

| Pointer | What it solves |
|---|---|
| `:39` `PINNED_OBS = "32.2.2"` | Exact version pin. The plist is checked first; the authoritative check is websocket `GetVersion`. |
| `:153` `render_tree` | Pre-seeds `global.ini` (dialog suppression), `user.ini`, `basic.ini`, the scene collection, and a websocket config with a random per-launch password. A fresh home without these files hits a startup modal. |
| `:117`, `:49` `RATES` | One locked browser source at `about:blank#obed-ak`, rendered at **2× the output rate** (25→50, 30→60), with `shutdown: False`. |
| `:144` `_decklink_props` | Device hash, mode per rate, keyer External, auto start, pixel format. It is written only when a device is recorded. |
| `:1929` `_launch` | Launches through NSWorkspace with `CFFIXED_USER_HOME` + `HOME` = the managed home, as a new hidden instance. Args: `--multi --disable-updater --disable-missing-files-check --remote-debugging-port`. Never exec the binary directly (it hangs in CoreAudio/TCC). |
| `:2010` `_await_ready`, `:2060` `_liveness` | Readiness: the pid is ours (`ps -E` env marker), there is exactly one `#obed-ak` CDP target (matched by **id**, never URL), the version matches, and the log shows no Safe Mode. A DeckLink output inactive twice means a device conflict, usually ProPresenter. |
| `:1835` `_quit` | `terminate()` with a 10 s wait, else `stuck`. Never SIGKILL. |
| `:533` `STEP0_NULL_ALLOWLIST`, `:568` `check_persistence` | Calibration must leave no residue in OBS's saved config (§5 D2). |

## 3. Hard-won gotchas

### Keynote export

- **A transition is stored on the OUTGOING slide.** Slide N's transition is the N→N+1 move.
- **HTML export is nondeterministic.** The same deck gives different trees and different texture-id collision victims on each export.
  - "Doesn't reproduce" means re-export several times.
  - Test any repair against several fresh exports.
- **Texture-id collisions.**
  - Ids are reused across slides; a zoom's right page exists only as the previous slide's MM `contents.to`.
  - Ids are recycled onto per-letter base glyphs.
  - The victim's page is never exported.
  - Never bind a decoder or label to a texture id. Bind by draw index, upload ordinals and geometry.
  - Eye checks must use the **repaired** export.
- **Play-across-slides restarts.** The export restarts a "Play across slides" movie whenever a Magic Move changes its geometry. This is an Apple bug, filed. "Play across slides" is not in the export at all; carries are inferred from the Magic Move.
- **Degraded builds.** The export degrades some builds; Line Draw ships as an opacity fade. Check the exported effect and the authored transition before designing a fix.
- **Player input.**
  - The player ignores keys unless `document.hasFocus()`.
  - It **queues** key presses it cannot honour and replays them later. A "drift" was a queued keystroke.
  - Its SPA hash establishes only on the first navigation, so use a fresh browser per run.
- **Never time off the player's hash.** It never fires `hashchange` and shows the NEXT scene while idle.
- **Never edit `main.js` on disk.** It is a dependency and breaks on Keynote updates. Use sha-pinned in-memory patches. Any patch change re-pins `SUPPORTED_PLAYERS`, the `REAL_*_SHA256` test pins and `scripts/detach_experiment.py`.
- **Slide numbers.** Owner slide numbers need not match export ordinals; "8→9" was export 7→8. Pin the move by what is on screen before measuring.
- **The MM GL canvas lingers** about 300 ms after its last draw (the swap is on a `setTimeout`). A GL-fed carry must cover that.
- **Magic Move partners.** When anything changes what is hidden or deleted, check MM partners on the adjacent slides. Off-canvas partners were once silently deleted (#224).

### Keynote automation

- `osascript … tell application "Keynote"` **launches** Keynote; it is not a probe. Check `pgrep -x Keynote` first.
- `save doc in P` saves a copy and leaves the document bound to the source.
- Files written by a sandboxed or agent shell carry `com.apple.quarantine`, and Keynote then fails with "Operation not permitted".
- Keynote cannot open files under hidden paths such as `.claude/`.
- A "hang" at 0 % CPU is a modal dialog, for example the theme chooser.

### Chrome / CEF / CDP

- **Chrome auto-update silently breaks the freeze.** Chrome 155 arrived on 2026-10-15; every Dissolve jumped to frame 0 because the major was unqualified.
  - When the freeze "stops working", check `Google Chrome --version` first.
  - Then re-qualify with `scripts/chrome_requal.py --chrome <binary> --out <dir>`: about 9 min, exit 0/1/2. Add the printed tuple to `live_host.py:77`.
  - Port the *mechanism*: a version allowlist plus a one-command re-qualification. A hard-coded list on its own is not enough.
- Never send `nativeVirtualKeyCode` on macOS.
- CEF drops CDP keys right after load. Wait for input readiness before the first go-to.
- **Keepalive.** A CDP client that idles without reading dies on "keepalive ping timeout", because the websockets queue fills. Drain or poll while idle.
- **Tone curve.** Chromium draws native `<video>` with a midtone tone curve that `drawImage`/`texImage2D` do not get (≤ +11/255). Brightness can therefore step at GL takeover and at hand-back.
  - Grey-coded test counters misread across the two paths.
  - Qualify with a binary-counter movie (`scripts/binary_counter_movie.py`).
- **Reading the current frame.** `drawImage(video)`/`VideoFrame` read the compositor's *current* frame. Identify drawn frames by `VideoFrame` timestamp, not the rVFC expected time.
- **DPR.** CDP DPR emulation smooths canvases. Use a real `--force-device-scale-factor`.
- **Frame rate.** After sleep/wake, page rAF reads 30 until relaunch, and nothing warns. The show Mac must not sleep.
- **rVFC.** An rVFC armed after `seeked` races on fast machines. Arm it before the seek.
- **PDF rasterising.** PDF textures rasterise differently on Chrome 155 and CEF 127. Calibrate every pixel bar on every engine.
- **Detached video.** A detached `<video>`'s rect is the literal viewport (0,0).

### OBS

- `HOME` alone does not isolate OBS. Set `CFFIXED_USER_HOME` too.
- obs-websocket binds all interfaces by default. Configure it for loopback.
- **Browser source.** OBS hides a browser source unless it is showing; off-program you get an empty or stale frame. Keep "Shutdown source when not visible" and "Refresh when active" OFF.
- **Screenshots.** `GetSourceScreenshot` trails the page by about 200 ms and is premultiplied.
- **2× browser source.** Matching page fps to canvas fps judders 6–13 %.
- **Config residue.** Installing Desktop Video makes OBS add `/modules/decklink_captions` on first save (finding D2).
- **Pacing.** The Mac sleeps on battery with the lid closed despite `caffeinate`. Battery and Low Power Mode also throttle capture.

### Movies

- **Decoding alpha.** Decode VP9 alpha with `-c:v libvpx-vp9` **before** `-i`. ffmpeg's native vp9 decoder silently drops alpha.
- **Range requests.** A server without Range support cannot seek media. `SimpleHTTPRequestHandler` fails this.
- **Colour range.** `getImageData` is full-range RGB, while the movie is tv-range. Never range-check decoded RGB.
- **Positive controls.** A fully transparent first frame is a weak positive control. Score a frame that has both alpha classes.
- **Masks and trims.** Keynote movies cannot be masked; crops come only from screen dimensions. Differently trimmed copies behave as skip/fast-forward, so a restart is correct.

### Measuring

These are the lessons that cost the most time.

- **Look at pixels.** A green gate that never looked at pixels let an invisible movie into a field build. Check the ancestor-opacity product and `checkVisibility`, never the element alone. Look at mid-move pixels too; a linear overlay passed every gate against Keynote's eased GL poster.
- **Fail closed.** Integrity failure gives INCONCLUSIVE; PASS/FAIL is given only for a valid stimulus. Every check needs a known-bad that fails and a null that reads 0. Never score a page-computed sub-verdict; keep raw evidence and re-derive.
- **Seams come in pairs.** The hand-back flash pairs with the departure hide. When you fix one end, check the other.
- **Observer cost.** Per-frame `drawImage` + `getImageData` can itself cause jitter. Judge cost per GL frame; a whole-capture p95 is diluted by idle frames.
- **Unspaced bursts.** CDP screenshot bursts misread a WebGL-only repaint as dead, because the surface updates lazily, about every 290 ms. In-page `readPixels` is the validated liveness oracle.

## 4. Owner decisions that govern

Do not re-propose these:

- **Product rules**
  - Continuity never blocks Start. Any deck that derives continuity installs it.
  - Refusals are scoped per move. Never relax a refusal to qualify a deck.
  - `overlap` (z-order) is a valid refusal.
  - Never plan mask support.
  - R8 (restart on differing trim) is correct.
- **Playback mechanics**
  - Exact-frame MM hold: never seek a hold to `currentTime`; at teardown it is one frame behind the presented frame.
  - The movie anchor is the own-layer rule (`findMovieCanvas`). "Prefer visible" lost the decoder.
  - Bind the GL feed from the served, Stage-T-repaired JSON on every prepare, never from a pinned table.
- **Movies and codecs**
  - Convert movies silently.
  - VP9 crf 20.
  - An unqualified output warns and never blocks.
  - No Chrome version gate for alpha movies.
- **Out of scope:** movie audio (program audio comes from the live feed); 50/60 output, which is deferred.
- **P3 (pre-rendered transparent export)** is parked as a ProPresenter fallback. If restarted, render offline through the patched HTML player, not native Keynote.
- **Wanted, not built:** decks that are not 16:9, not in manual show mode, or have web media should **still load if possible**. The planned fixes are a pillarbox, a prepare-time `showMode` rewrite, and a web-media warning instead of a block.

## 5. Unfinished work

### Stage B

Branches:
- `origin/claude/stage-b-c4c5` @ `6639d4f0`: code and instruments.
- `origin/claude/stage-b-arch` @ `fa8dabdc`: same `src/`, plus the docs and the final folds plan.

Both are unmerged and 13 commits behind main.

**Goal.** Qualify the real `Alpha_DSK.key` so every same-movie Magic Move is carried with authored artwork staying **above** the video, during the move and after it settles. Plan: `keynote_live_continuity_stage_b.plan.md`.

**Mechanism.** The live `<video>` is fed into Keynote's own MM texture at the movie leaf's draw, with `texImage2D(video)`. Keynote then draws the live movie with its own easing, and the labels stay on top. The movie re-homes into the DOM at settle.
- Fallback = **poster hold**: pause at move start, upload the exact on-screen frame once, then resume at held+1 with no seek.
- Hand-back keeps the GL canvas live through Keynote's roughly 300 ms linger.

New code (c4c5 line numbers):

| Pointer | What it is |
|---|---|
| `live_mm_feed_js.py` (new) | The feed module. `arm` `:248`; `texImage2D(decoder)` `:221`; `standDown` `:195`. Any `getError` stands every feed down (`:475-486`). |
| `live_continuity.py` `_feed_binding` `:2014` | Binds by geometry, draw index and upload ordinals, never texture id. |
| `live_continuity.py` `_settles_into_dom` `:1295` | Lifts `overlap` to `underArtwork` for destinations that settle into the DOM. |
| `live_continuity.py` `_crossing_carries` `:2258` | N carries per boundary. |
| `live_continuity_js.py` (`CONTINUITY_VERSION` 7) | `posterHold` `:1292`; `rideTransition(…, hidden)` `:1377`; `lingerFeed` `:895`. |
| `live_host.py` | `MM_FEED_ENV` `:75`; `MM_FEED_MANAGED_OBS = False` `:83` (CEF not yet qualified; managed OBS ships on poster hold if CEF fails). |

**Where it stopped (2026-10-17).** The pre-5a gate round on `6639d4f0` was `failed=77` by design: every arm is INVALID until the owner freezes the Q2 cadence statistic. The defects fall into three groups:

1. **Instrument cost.** Clean-null `frame.total` p95 is 9.9–10.8 ms against an 8 ms gate. The cause is the instrument's own per-GL-frame `readPixels`/`sample` work, not the product.
2. **Missing GL intervals.** Three Alpha red arms report "GL intervals were not supplied", because `gl_intervals_for` is all-or-nothing.
3. **Nine scorer MISMATCHes:**
   - unseparated holds on moving footage;
   - an ordinal-scorer defect;
   - a no-pause expectation that is too broad;
   - two load flakes.

The fixes are specified in `keynote_live_continuity_stage_b_pre5a_folds.plan.md` r4 (F1–F6, on arch) and were never implemented. The resume point is `.agents/handovers/stage-b-c2-integration-2026-10-17.md` → "Resume here — IMPLEMENTERS".

**Still owed after that:**
- the pixel round;
- owner gate 5a: Q1 host rows, the Q2 cadence statistic, OBS rate matching, departure pixel classification;
- Q7 attempt 4 (owner eye);
- Q2–Q6, including CEF qualification of the feed.

**Porting advice.**
- Treat Stage B as a **design**, not code to lift. The mechanism (feed into Keynote's texture, poster-hold fallback, linger cover, binding by ordinals) is the valuable part.
- The instrument stack (`gate_checks.py`, `paint_instrument.py`, `mm_feed_instrument.py`, `live_run_validity.py`, about 10k lines) never reached a passing round.
- `PRE_DRAW_GRACE_MS` = 320 ms has a thin margin (D7 measured 306.5 ms).

### Other open items on main

- **D2:** the first Keyer calibration gives `persistence-failed`; a Recalibrate fixes it. The fix branch `origin/claude/placement-decklink-captions-allowlist` (`e775fd88`) is **unmerged**. It still needs full suites, then a rerun of `--arm placement`.
- **D1 (attach path only, not the show path):** at 2→3, the outgoing slide's coloured squares grey out. Unexplained.
- **Venue hardware day, never run** (`.agents/handovers/decklink-field-test-runbook.md`):
  - alpha verdict at the mixer and the premultiplied key setting;
  - device setup, rate switching, keyer off;
  - GL replay and MM opacity on the device;
  - placement with a configured device;
  - VP9-alpha movie on fill/key;
  - ProPresenter handover.
- **Refusal rules:**
  - "still load" for non-16:9, non-manual and web-media decks (§4);
  - lifting R12 (needs a two-bridge gate deck);
  - R4 loop and R9 opacity runtime fixes.
- **Dissolve follow-ups** (`keynote-live-dissolve-crossfade-followups.md`):
  - a stale freeze grant after an unobserved GPU fallback;
  - W5 tone calibration;
  - scaled stages still jump;
  - a bridged decoder painting over an outgoing Dissolve.
- **F2 other transitions/builds:** increment 1 (Twist, Flop, Iris, Revolve, Sparkle, Anvil) is planned, and its eye step is pending.
- **Unverified lead:** the player ignores clicks whose target is a `<video>`, so in attach mode a playing movie over the stage centre may swallow `click_stage()` advances.
- **Native sender (no OBS):** researched only. See memory `native-decklink-sender` and `.agents/plans/keynote_live_alternatives_research.md`. The best route is CEF OSR + a DeckLink SDK helper, prototyped on `macadam` (Apache-2.0). FreeShow is GPL, so take ideas only.

## 6. Suggested porting order

Each step is usable on its own. Stop wherever the staff tool's needs are met.

1. **Export + serve + drive (HDMI, no patches).**
   - Get the AppleScript export, a Range-capable loopback server, the `program.html` wrapper, and CDP Space/digit+Enter driving.
   - Add the load-time checks.
   - Carry over the CDP rules: no `nativeVirtualKeyCode`, focus before keys, drain while idle.
2. **Observation hook + sha pinning.** Port `_ANCHOR`/`_INSTALL` and the exactly-once replacement machinery, so there is a ready/busy state to wait on and a hard refusal on unknown players.
3. **Movie conversion.**
   - H.264, plus ProRes-alpha → VP9-alpha WebM, with the libvpx-before-`-i` verification.
   - This alone gives alpha movies on fill/key.
4. **Texture repair (Stage T).**
   - Needed for real decks. Without it, labels and posters show the wrong image.
   - Port it with the re-export-once retry and the postcondition.
   - It is large (`preview_textures.py`, about 1.3k lines). D2 (MM image graft) and D1g (glyphs) are the cases real decks hit.
5. **Managed OBS → DeckLink.**
   - Isolated home, pre-seeded config, exact version pin, readiness by CDP target id, 2× browser source, never SIGKILL.
   - Then do the venue test before going further.
6. **Rendering-fidelity patches.** In value order:
   1. R10 dissolve/cut;
   2. R1–R5 MM opacity;
   3. R6–R8 hand-back;
   4. R11–R12 freeze, with the Chrome-major allowlist + re-qualification script, and the placement probe for CEF;
   5. Line Draw.
7. **Movie continuity.**
   1. pin and restart;
   2. bridge on Keynote's GL clock;
   3. GL replay.
   - Port the refusal codes and the negative corpus with them (`tests/test_live_continuity_corpus.py`). Continuity must fail closed per move, never deck-wide by surprise.
8. **Stage B (artwork above a moving movie).** Only if the owner still wants it. Start from the plan and the pre-5a folds, and budget for the instrument problem first.

**Test fixtures:**
- `Minimal Alpha_DSK.key`, `F2.key` and the F2 HTML export are in main `output/source-decks/` (#299).
- The binary-counter fixture is under main `output/fixtures/p2-binary`.
- The real deck `Alpha_DSK.key` is at `~/Desktop/Convert wall to 16x9 CGs/`.
- These are local and git-ignored. Copy them out before the checkout is trashed.
