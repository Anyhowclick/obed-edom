# Managed OBS v1 — Alpha Keynote runs its own hidden OBS for fill + key

**Rev 2, DRAFT for owner review** (2026-09-24; owner answers in §14, all resolved). Rev 1 by Opus EXTRA HIGH; critique by Opus HIGH (3 blockers, 9 others; §13),
folded by the coordinator. Nothing is implemented.
Parents: `decklink-field-test-runbook.md` (§0 OBS setup, §3 cadence note), `keynote-live-continuity-2026-09-23-c.md` ("OBS rate +
output cadence"), [`keynote_live_gl_replay_arming.plan.md`](keynote_live_gl_replay_arming.plan.md) (G2 attach qualification OD-2
is out of scope). Spike: main checkout `output/obs-managed-spike/scripts/{seed.py,ws.py}`, `output/obs-rate/{rate.py,decode2.py}`.
Tags: **[M]** measured in the 2026-09-24 spike or read from OBS source · **[C]** read in this repo · **[I]** assumption, each settled
by a Q-item (§8).

**Owner decisions (binding, 2026-09-24):** (1) AK always uses its own isolated OBS config tree; (2) an OBS crash / Safe-Mode prompt
is a dashboard warning, AK never clears OBS's crash marker; (3) OBS is not modified and libobs is not embedded; (4) page render rate
= 2× the output rate, movies ideally at 1× (warn otherwise).

## 1. Scope

**v1 delivers:** operators never see OBS (except the one-time device setup, §6); fill + key through a managed, version-pinned OBS;
an output-rate setting; a dashboard warning when OBS crashed or is blocked.

**In v1.** A new AK output mode **Keyer (fill + key via UltraStudio)**. AK finds the pinned OBS.app, seeds an isolated config tree,
launches it hidden when the operator presses **Take output**, waits for readiness, and quits it cleanly on **Release output** — the
explicit same-Mac handover with ProPresenter (OD-M10, §5). It drives the Browser-source page through `LiveOutputHost`'s existing
attach path on an AK-chosen CDP port. Persisted: output mode, output rate (25 / 30), keyer on/off; the DeckLink device record lives
in the engine's own folder (§6). Warnings W1–W5, W8, W9, W11–W13 (§4).

**Unchanged.** HDMI (Screen) mode; every byte of the continuity, GL-replay and runtime JS; the `_resolve_gl_replay` attach refusal
("attach output not qualified") — GL replay stays off under managed OBS until OD-2, so managed OBS ships with native `<video>`
cadence (8–12 % repeated frames at 2× [M]), not GL replay's 0.5 %. HEVC stays unsupported under attach (`_codec_supported` [C]).
External attach (`OBED_LIVE_ATTACH`, `bridge: "obs-cdp"`) stays exactly as today as the developer fallback, with no UI; removal is a
later cleanup.

**Non-goals.** Modifying OBS; embedding libobs (GPL; the repo is public); any state-changing obs-websocket request in product code
(only `GetVersion`, `GetOutputStatus`; the harness alone may record); clearing `.sentinel/run_*`; automatic force-kill; fractional
rates.

**Deferred to v2 (§12).** Page-rate probe + W6 (sleep/wake drop; v1 relies on the runbook "the show Mac must not sleep"), skipped-
frame history + W7, 50/60 output rates, orphan adoption, "Reset output engine", code-signature check.

## 2. Architecture

New `src/obed_edom/managed_obs.py` (`ManagedObs`) and `src/obed_edom/obs_websocket.py` (minimal sync v5 client ported from the
spike's `ws.py`; handshake and auth fixed by the spike [M]). One `ManagedObs` per dashboard process, owned by `web/live.py`'s
`live_router` (process lifetime).

**Frozen Python API** (S5 is written against it): `ManagedObs(home: Path, *, launcher=…, clock=…)`; `.state() -> dict` (the §5
JSON); `.ensure_started(rate: int, keyer: str) -> None` (idempotent; returns immediately, work runs on the engine thread);
`.restart(rate, keyer)`; `.quit()`; `.check()`; `.show()`; `.setup_device_begin(rate)` / `.setup_device_done()`;
`.cdp_endpoint -> str | None`; `.target_id -> str | None`; `.device() -> dict | None`.

**Home.** `~/Library/Application Support/Obed-Edom/managed-obs/` is AK's `HOME`; OBS reads `<home>/Library/Application
Support/obs-studio/` [M]. Not the repo's `.cache` (the repo lives under `~/Desktop`; a tree there blocked OBS in `fopen` on a TCC
prompt [M]). The user's `~/Library/Application Support/obs-studio` is never read or written (owner decision 1).

**Discovery.** `/Applications/OBS.app/Contents/Info.plist`: `CFBundleIdentifier == com.obsproject.obs-studio`,
`CFBundleShortVersionString == PINNED_OBS ("32.2.2")` as the first check; obs-websocket `GetVersion.obsVersion` after launch is
authoritative and logged. `LastVersion = (major<<24)|(minor<<16)|patch` (32.2.2 ⇒ 537001986, matches the spike [M]).

**Seeding.** `seed.py` ported to pure `render_tree(cfg) -> {relpath: bytes}` + `write_tree`, called **only while AK's OBS is not
running** (OBS writes config back on quit [I]). AK rewrites before every launch: `global.ini`, `user.ini`,
`basic/profiles/AK/basic.ini` (no recording keys in product), `basic/scenes/AK.json` (Browser source url `about:blank#obed-ak`,
`fps_custom` true, rate per §3, no audio capture sources), `plugin_config/obs-websocket/config.json` (a new random password each
launch), and `plugin_config/decklink-output-ui/decklinkOutputProps.json` (only when a device is recorded, §6). Logs, CEF cache,
`plugin_manager` and `.sentinel` are OBS's; AK never touches them.

**Launch.** `NSWorkspace.openApplicationAtURL_configuration_completionHandler_` with the full bundle URL and a configuration of
`arguments = [--multi, --disable-updater, --disable-missing-files-check, --minimize-to-tray, --remote-debugging-port=<cdp>]`,
`environment = {CFFIXED_USER_HOME: <home>, HOME: <home>}`, `createsNewApplicationInstance = true`, `hides = true`. It returns the
`NSRunningApplication` ⇒ pid and launch date directly. **Q-I** must show this isolates the tree exactly like the spike's
`open -n --env …` [M]; if it does not, fall back to `open -n --env` + a before/after snapshot of running OBS apps. Never exec the
binary directly (hung in CoreAudio [M]). `--multi` always: it only suppresses the "already running" dialog [M]. CDP and websocket
ports: pick free ports by binding `127.0.0.1:0` and releasing; the fresh password plus the unique page prove they are ours.
New dependency: `pyobjc-framework-Cocoa` (darwin) in `pyproject.toml` (S1 owns it; AppKit is today only a transitive dependency of
`pyobjc-framework-Vision` [C `pyproject.toml:26`]).

**Lock.** The first engine action takes `fcntl.flock` on `<home>/ak-engine.lock` and holds it **for the dashboard process's
lifetime** (not only while OBS runs), so another dashboard cannot slip in between a quit and a relaunch. A second holder ⇒ W13.
`<home>/ak-engine.json` (`{pid, launchDate, cdpPort, wsPort}`) is written before seeding.

**Readiness** (all within 20 s; measured ~2 s [M]; W3b if a macOS permission or other dialog holds it): (a) process alive; (b) CDP `/json/list` has exactly one page whose URL contains
`#obed-ak` — record its CDP **target id**; (c) obs-websocket Identify ok and `GetVersion.obsVersion == PINNED_OBS`; (d) the newest
log in `<tree>/logs/` (mtime ≥ launch) has no `[Safe Mode] Safe mode launch selected` [M, source] (defensive: under `--multi` OBS
never prompts, Q-E). Outcomes: `ready` · `blocked:safeMode` · `blocked:timeout` · `exited`.

**Liveness (v1, every 2 s on the engine thread):** pid alive — gone without AK asking ⇒ `exited` + W5; CDP target **id** still
listed (never matched by URL: during a show the page is on the asset server's URL [C `live_host.py:1051`]). No stats history, no
page-rate probe in v1.

**Host integration.** Keyer start calls `make_host(..., attach_endpoint=engine.cdp_endpoint, attach_match=<target id>,
bridge="obs-managed", output_rate=rate)`. S4 extends `_pick_target` to accept a target id match (`item["id"] == match`), because
after a failed stop the page URL is not `#obed-ak` and attach needs exactly one match [C `live_host.py:556-560`]. Everything
downstream is the existing attach path [C]; stop returns the page to `about:blank#obed-ak` (`_blank_url` keeps an `about:blank*`
URL [C]). When no session is loaded, **Check again** navigates the target id back to `about:blank#obed-ak`. New kwargs are passed
only in Keyer mode, so today's fake `host_factory(export_root, slides, *, display_id, continuity)` keeps working.

**Quit.** `NSRunningApplication.terminate()` on our pid only (a Cmd-Q to that process [I, Q-B]); never the spike's
`tell application id … to quit`, which may hit a user OBS. Wait 10 s; still alive ⇒ `stuck` + W12. **Never an automatic SIGKILL**
(a force-kill causes the Safe-Mode prompt on the next launch [M]). Quit on dashboard shutdown (after the router stops the session),
on a switch to Screen mode, and on restart.

**Orphans (v1).** At startup, a live pid recorded in `ak-engine.json` with a matching launch date is always quit cleanly and
relaunched — never adopted.

**Unclean exits (owner decision 2, Q-E).** `--multi` turns OBS's own crash check off (no prompt can appear or steal focus), so AK
tracks it: `ak-engine.json.cleanExit` is false from launch until AK's own quit completes; finding it false at the next launch ⇒ W3.
AK never reads, writes or deletes OBS's `.sentinel` (a test asserts it is byte-identical).

## 3. Output standard

**`settings.json` keys** (S2 adds them to `DEFAULTS` with explicit `_clamp` branches — `_clamp` rebuilds from `DEFAULTS` and drops
unknown keys [C `settings.py:28`]; the generic PUT then keeps them because it loads, patches and saves [C `app.py:263-281`]):
`akOutputMode` (`"screen"` | `"keyer"`, default `"screen"`), `akOutputRate` (25 | 30, default 25), `akKeyer` (`"external"` |
`"off"`, default `"external"`). `settings.json` is per worktree (repo `.cache`); the per-user device record is not in it (§6).

| Output (= what the Pulse shows) | Canvas `FPSCommon` | Browser-source fps | DeckLink mode | Evidence |
|---|---|---|---|---|
| 25 | `25 PAL` | 50 (2×) | 1080p25 | [M] |
| 30 | `30` | 60 (2×) | 1080p30 | [I] — Q-H measures it before 30 ships |

**50/60 deferred:** obs-browser's fps property is limited to 1–60 and CEF's windowless frame rate to 60 [M, source], so 2× is
impossible at 50/60 (owner decision 4); they need their own measurement (v2).

**Changing rate, keyer or device** requires an OBS restart (OBS reads the canvas rate and the DeckLink settings only at start [M];
`SetVideoSettings` is refused while video is active [M]) and is refused while a session is loaded (§5). Nothing changes live.

## 4. Warnings (exact operator wording)

`block` disables **Start output session** in Keyer mode. Buttons: **Show OBS** (activate our pid), **Restart output engine**,
**Check again**, **Set up output device**.

| id | Trigger | Sev | Text | Action |
|---|---|---|---|---|
| W1 obsMissing | no bundle at `/Applications/OBS.app` | block | "Output engine not installed. Install OBS 32.2.2 into Applications, then press Check again." | Check again |
| W2 obsVersion | plist or `GetVersion` ≠ pin | block | "Output engine is OBS {found}; Alpha Keynote needs OBS 32.2.2. Install 32.2.2, then press Check again." | Check again |
| W3 obsUncleanExit | `ak-engine.json` says the previous engine did not end with AK's own quit (`cleanExit` false; OBS's own crash check is off under `--multi`, Q-E) | warn | "OBS closed unexpectedly last time. It has been restarted; check the output before going live." | — |
| W3b obsWaiting | not ready by 20 s, process alive, no crash line | block | "OBS is waiting for an answer or a permission. Press Show OBS, answer it, then press Check again." | Show OBS · Check again |
| W4 obsSafeMode | Safe-Mode line in the log, or CDP up with the websocket down | block | "OBS started in Safe Mode, so Alpha Keynote cannot watch it. Press Restart output engine and choose Normal Mode when OBS asks." | Restart |
| W5 obsExited | process gone without AK asking | block (live: red banner) | "OBS stopped unexpectedly — nothing is going to the keyer. Press Restart output engine. OBS may then ask a question (see Show OBS)." | Restart |
| W8 movieRate | a deck movie's fps outside ±0.2 % of the output rate (Keyer mode only) | warn | "{asset} is {f} fps but the output is {r} fps, so it will judder slightly. Re-export it at {r} fps for smooth motion." | — |
| W9 noDevice | no device record for this rate | warn | "No output device set for {r} fps — the keyer receives nothing. With the UltraStudio connected, press Set up output device (one time)." | Set up |
| W11 deviceInactive | device recorded and `GetOutputStatus.outputActive` false 5 s after ready (DeckLink output is exclusive to one app: `EnableVideoOutput` ⇒ `E_ACCESSDENIED` while another holds it [M, Blackmagic SDK]) | block | "Alpha Keynote cannot open the UltraStudio. If ProPresenter is running, remove its SDI screen in Screen Configuration or quit ProPresenter; otherwise check the Thunderbolt cable and Desktop Video. Then press Release output and Take output again." | Release · Take |
| W12 stuck | no quit within 10 s | block | "OBS is not responding to Quit. Press Show OBS and quit it from the OBS menu, then press Check again." | Show OBS |
| W13 ownedElsewhere | engine lock held by another process | block | "The output engine is being used by another dashboard window (pid {p}). Close that dashboard first." | Check again |

**Two lists.** W1–W5, W9 and W11–W13 are the engine's `warnings` (§5 JSON). **W8 is a session warning:** `live_codec.movie_fps(path) ->
float | None` reads `mdhd` (timescale) and `stts` in the video `trak` the codec parser already walks [C], within the same box budget,
never raising; `codec_report` entries gain `"fps": float | None`; `LiveOutputHost(output_rate=…)` puts W8 strings in
`output["rateWarnings"]` beside `codecWarnings` [C]. Unreadable fps ⇒ no warning ("fps unknown"). S6 shows both lists.

## 5. API, locking and dashboard

**Routes in `web/live.py`** (same `_same_origin` dependency [C]): `GET /api/live/engine`;
`POST /api/live/engine/{start|restart|check|show|quit|setupDevice|setupDone}`; `GET|PUT /api/live/output-settings`.
**Locking (blocker fix).** Keyer start and every engine action check state and initiate their change under `web/live.py`'s existing
`lock`. **Restart, quit, setupDevice and output-settings PUT return 409 "Stop the show first." unless the session is `stopped`**
(after W5 the route stops the dead session first). The quit/relaunch runs on the engine thread; no route waits for it while holding
`lock` (the thumbnail route shares it [C `web/live.py:153`]). Keyer start returns 409 with the first block text unless
`engine.state == "ready"`. Shutdown order: the router stops the session, then quits the engine.
**Engine lifetime = explicit handover (OD-M10).** The engine runs only while AK holds the UltraStudio: **Take output**
(`POST /api/live/engine/start`) launches it; **Release output** (`POST /api/live/engine/quit`, refused while a session is loaded)
quits it cleanly so ProPresenter can drive the device again; dashboard exit and a switch to Screen mode also release. Nothing starts
the engine implicitly (no lazy start on tab mount), so AK never holds the device or sends a transparent key while idle.

**State JSON (`GET /api/live/engine`):** `{state: "unavailable"|"stopped"|"starting"|"ready"|"blocked"|"stuck"|"quitting", reason?,
obs: {path, version, pinned}, rate: {output, canvas, source}, device: {name, set}, keyer, warnings: [{id, severity:
"block"|"warn"|"info", text, action?}]}`. The websocket password never appears in API JSON, logs or URLs (tested).

**Dashboard.** `LivePresenter.tsx` gains an Output selector ("Screen (HDMI)" / "Keyer (fill + key via UltraStudio)"). Keyer mode
shows the rate (25 / 30, labelled "Match the standard the Pulse shows"), keyer on/off, the device name, and a new `OutputEngine.tsx`
panel (engine state, **Take output / Release output**, warnings, action buttons; polls every 2 s; Start output session is disabled
until the output is taken and ready); `rateWarnings` shows beside `codecWarnings`. The Display picker is
hidden in Keyer mode. The lede "DeckLink fill + key is not qualified" [C] stays until the hardware day passes. `api.ts` gains the
engine and output-settings types and methods, `bridge?`, `rateWarnings?`. Note [C]: `live_session.start` writes `transport: "hdmi"`
into the loading snapshot until the first observation; Keyer mode must not flash "hdmi" — fixed in S5 with a test.

## 6. DeckLink device, keyer and mode (hardware day; UNTESTED)

Keys of `decklinkOutputProps.json`: `device_hash`, `device_name`, `mode_id`, `mode_name`, `keyer` (0 off / 1 External / 2 Internal),
`auto_start`, `pixel_format`, `color_space`, `color_range`, `buffering`, `force_sdr`, `allow_10_bit`. `auto_start` starts it on
FINISHED_LOADING; websocket control of it is unsafe — write the file before launch [M]. Device hash and mode ids cannot be known
without hardware [M].

**Recommended (OD-M3): one-time "Set up output device".** (1) AK quits the engine and relaunches it **visible** on the AK tree.
(2) The dashboard shows: "In OBS: Tools → Decklink Output → pick UltraStudio HD Mini, Mode 1080p{r}, Keyer External, Pixel format
BGRA 8-bit, tick Auto start, press Start, then OK. Then press Done here." (3) On **Done** AK quits OBS cleanly, reads the file OBS
wrote and stores `{deviceHash, deviceName, modeIds: {"{r}": …}, pixelFormat}` in **`<home>/ak-device.json`** (per user, owned by
S1 — not settings.json, which is per worktree). (4) Repeat per rate only when `modeIds` lacks that rate. This is the only time OBS
is visible.

**AK writes at every launch:** `keyer` = 1 if `akKeyer == "external"` else 0; `auto_start` = true; `mode_id` = `modeIds[rate]`
(missing ⇒ W9); `pixel_format` = stored. **Only one app can own the device** [I]: if ProPresenter or a user OBS holds it,
`outputActive` stays false ⇒ W11; the log text is recorded on the hardware day.

**Hardware-day checklist** (appended to `decklink-field-test-runbook.md`): Desktop Video installed, device listed · setup flow writes
the file; record `device_hash`/`mode_id` · hidden relaunch auto-starts the key on In4 without a click · `outputActive` true; W11
fires with the cable unplugged (record the log line) · runbook §1 test-card alpha checks through the managed engine · rate 25 → 30
→ 25 (restart; the Pulse widget follows) · keyer off ⇒ fill only · does the device hash survive a replug / another port? ·
**ProPresenter handover:** with ProPresenter driving the HD Mini, press Take output with (a) its SDI screen present ⇒ W11 expected,
(b) its SDI screen deleted, (c) ProPresenter quit — record which frees the device; then Release output ⇒ ProPresenter reclaims it
(re-add the screen / relaunch) with fill + key on In3/In4.

## 7. Security — obs-websocket listens on every interface [M, source: no bind-address option]

**Recommended (OD-M5): websocket on, a new random password every launch** (`secrets.token_urlsafe(32)`), a random high port, AK
connects to 127.0.0.1 only, product sends read-only requests only (`GetVersion`, `GetOutputStatus`). The password file's
permissions are not relied on (OBS may rewrite it); a fresh password per launch is the protection. Residual exposure: the LAN sees
OBS's version in the Hello message and reaches obs-websocket's parser while AK runs. The alternative, websocket off, loses the
version check and W11 (the only confirmation that the key is actually running). CDP binds loopback [I] with no auth, as today.

## 8. Qualification before product code (Q0; scratch under `output/obs-managed-spike/`)

- **Q-A** A user OBS (default tree) and AK's OBS (`--multi`) run together: no dialog, trees isolated, both CEF instances and ports up.
- **Q-B** `terminate()` by pid quits only AK's instance (user OBS running), no new `run_*`, next launch prompt-free.
- **Q-E** Force-kill, then hidden launch: is the Safe-Mode dialog visible; does **Show OBS** bring it forward? Confirm the log lines
  on the 32.2.2 tag (the critique read them on OBS master).
- **Q-H** Lossless cadence at canvas 30 / source 60 (fills §3's 30 row).
- **Q-I** `NSWorkspace` launch with `environment` isolates the tree like `open -n --env` and returns the right pid.
Resolved from source (critique): the 60-fps cap (was Q-C); no websocket bind address (was Q-D). Deferred with W6: the page-rate probe
(Q-F) and sleep/wake recovery (Q-G).

### Q0 results (2026-09-24, OBS 32.2.2, this Mac; evidence main checkout `output/obs-managed-spike/`)

- **Q-I PASS.** `NSWorkspace.openApplicationAtURL…` with `arguments`, `environment` (`CFFIXED_USER_HOME`, `HOME`),
  `createsNewApplicationInstance`, `hides` returns the `NSRunningApplication` (pid == `pgrep`), args intact, tree isolated (user
  config untouched). The `open -n --env` + snapshot fallback is not needed.
- **Q-E — design change.** Without `--multi`, a crash puts OBS's Safe/Normal prompt **on screen with keyboard focus even though OBS
  was launched hidden** (the owner's spacebar, typed into another app, answered it; default button = Normal). **With `--multi`, OBS
  has no crash detection at all** (32.2.2 source: multi-instance mode default-constructs `CrashHandler`, so `hasUncleanShutdown()`
  is always false) and starts normally after a force-kill [M]. ⇒ AK always passes `--multi`, the prompt can never appear or steal
  focus, and **AK detects an unclean exit itself** (owner decision 2 kept): `ak-engine.json` gains `cleanExit` (false at launch,
  true only after AK's own quit completes); a launch that finds it false shows W3. `.sentinel` is ignored entirely (W10 dropped);
  W4 (Safe Mode) stays only as a defensive log check.
- **Q-A PASS with a finding.** With AK's hidden OBS running, the user's normal OBS (`open -n`, own config) shows "OBS is already
  running! … Launch Anyway / Cancel"; **Launch Anyway** runs both side by side, each tree untouched by the other. A plain
  `open -a OBS` (a normal double-click) does **not** start the user's OBS: macOS activates AK's hidden tray instance, so it looks
  like nothing happened. ⇒ runbook note: "while Alpha Keynote holds the output, press Release output first — or open your own OBS
  from Terminal with `open -n -a OBS` and choose Launch Anyway".
- **Q-B PASS.** `NSRunningApplication.terminate()` by pid quits only AK's instance; the user's OBS keeps running; the user's config
  is unchanged except OBS's own saved window geometry.
- **Q-H PASS (canvas 30, lossless, 3 takes interleaved).** Page 60 (2×): G2 LIVE 2.1 % / 1.3 % repeated frames, native 12–13 %;
  page 30 (matched): G2 0.9 %, native 13–17 %; paused 100 %; OBS 0 skipped frames. At 30 the page rate barely matters (movie, page
  and canvas share one clock); the 2× rule is kept for simplicity (harmless: page 60.4, 0 skipped). **30 ships with 25.**

## 9. Tests

**Unit, no OBS** (`tests/test_managed_obs.py`, `tests/test_obs_websocket.py`): tree goldens **pinned to the spike's `seed.py` output
at rate 25** (ignoring UUIDs, password, port, page URL) — not self-generated; `LastVersion` formula; `FPSCommon` / source fps per
§3; DeckLink file only when a device is recorded; keyer 0/1; launch configuration via a fake launcher; readiness matrix against a fake
CDP HTTP server (`/json/list`), a fake obs-websocket (`websockets.sync.server`: Hello with auth, Identify, `GetVersion`,
`GetOutputStatus`) and log fixtures ⇒ ready / safeMode / timeout / exited / wrong version; `cleanExit` false on the previous run ⇒ W3; liveness by target id (a URL
change mid-show stays ready); W5 on a vanished pid; quit timeout ⇒ `stuck`, never kill; orphan always quit-and-relaunch; second lock
holder ⇒ W13; **`.sentinel` byte-identical before/after every flow**; seeding refused while the pid is alive; the password never
appears in `state()` or logs.
**Other unit:** `tests/test_settings.py` (AK keys and clamps; generic-PUT round-trip keeps them); `tests/test_live_codec.py`
(`movie_fps` on synthetic `mdhd`/`stts`, timescale 30000/1001, missing `stts`, truncated box); `tests/test_live_continuity.py`
(`codec_report.fps`); `tests/test_live_host.py` (target-id attach match; `bridge="obs-managed"` in `output`; `rateWarnings`
wording/tolerance; GL-replay attach refusal unchanged); `tests/test_live_api.py` (Keyer start needs `ready`; restart/quit/setup/PUT
refused unless stopped; W5 route stops the dead session; **shutdown stops the session before quitting the engine**; the loading
snapshot never says "hdmi"; the existing fake `host_factory` at `test_live_api.py:238` still passes as the Screen-mode guard);
`dashboard/tests-ui/live-output-engine.ui.test.tsx` (each warning's text and button; Start disabled on a block; rate selector
disabled while live).

**Live harness** (`scripts/managed_obs_qualify.py` using the product `ManagedObs`; `scripts/obs_cadence_decode.py` ports
`decode2.py`): launch with a harness-only profile override (lossless `hybrid_mov` into scratch [M: "Small" H.264 fails the controls])
→ websocket `StartRecord` → `rate.py`'s `rec` phases on the P2 fixture through `LiveOutputHost` attached to the engine →
`StopRecord` → decode → assert → `runs/*.json`. Arms at canvas 25: **2×** (source 50): native repeat ≤ 0.15 (measured 0.08–0.12),
decodable ≥ 0.9; **null** (paused phase): repeat ≥ 0.95 (measured 1.00); **positive control** (source 25): native repeat ≥ 0.18
(measured 0.25–0.27) and above the 2× arm's. Plus a lifecycle arm (ready time, clean quit, marker diff) and an attended arm (Q-B, Q-E
with the owner). The show Mac must be kept awake for every live run (a sleep invalidated a spike run [M]).
**Full local suites for the PR** (no CI): `uv run pytest tests/ -n auto --dist loadfile`; `cd dashboard && npm install && npm run
build`, `npm run test:maps`, `npm run test:ui`; harness 2 takes per arm.

## 10. Work split (file-disjoint; Opus MEDIUM implementers)

| # | Files | Work |
|---|---|---|
| Q0 | scratch only | Q-A, Q-B, Q-E, Q-H, Q-I — all block S1 except Q-H (blocks offering 30) |
| S1 | `src/obed_edom/managed_obs.py`, `src/obed_edom/obs_websocket.py`, `pyproject.toml` (+ `uv.lock`), `tests/test_managed_obs.py`, `tests/test_obs_websocket.py` | discovery, render/write tree, launch, lock, readiness, liveness, quit, orphans, device record, warnings |
| S2 | `src/obed_edom/settings.py`, `tests/test_settings.py` | three AK keys + clamps |
| S3 | `src/obed_edom/live_codec.py`, `src/obed_edom/live_continuity.py` (`codec_report` only), `tests/test_live_codec.py`, `tests/test_live_continuity.py` | `movie_fps`, `fps` field |
| S4 | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | target-id match in `_pick_target`; `bridge` / `output_rate` kwargs; `rateWarnings` |
| S5 | `src/obed_edom/web/live.py`, `src/obed_edom/live_session.py` (loading transport only), `tests/test_live_api.py`, `tests/test_live_session.py` | engine singleton, locking, routes, shutdown order, Keyer start wiring |
| S6 | `dashboard/src/live/{LivePresenter.tsx,api.ts,live.css,OutputEngine.tsx}`, `dashboard/tests-ui/live-presenter.ui.test.tsx`, `dashboard/tests-ui/live-output-engine.ui.test.tsx` | UI against the §5 JSON with a fake client |
| S7 | `scripts/managed_obs_qualify.py`, `scripts/obs_cadence_decode.py` | harness |
| D | `README.md` (Alpha Keynote), `.agents/handovers/decklink-field-test-runbook.md`, `.agents/skills/obed-edom/SKILL.md` | docs after green (incl. "show Mac must not sleep"; "if the dashboard dies mid-show, relaunch it — it quits the old engine") |

Order: Q0 → (S1 ∥ S2 ∥ S3 ∥ S6; §2 API and §5 JSON frozen here) → S4 (after S3) → S5 (after S1, S2, S4) → S7 → harness → D →
Codex review → **one integration PR**. **Codex brief:** (1) can any path delete or rewrite `.sentinel`, or send SIGKILL? (2) can
seeding run while OBS is alive? (3) can quit/show target a process AK did not launch? (4) does any product websocket request change
state? (5) is the password ever in logs, API JSON or a URL? (6) is Screen mode byte-identical? (7) is `_resolve_gl_replay`'s attach
gate untouched? (8) can any engine action run while a session is loaded?

## 11. Risks

1. Seeds are tied to OBS 32.2.2's file formats; updating OBS trips W2 on purpose (OD-M4).
2. OBS may rewrite AK-owned files on quit — harmless: AK reseeds before every launch and reads the device file after a quit.
3. Isolation rests on CoreFoundation's `CFFIXED_USER_HOME`, an undocumented override a macOS update could break; readiness catches it,
   and the harness checks the user tree's mtime is unchanged.
4. No sleep/wake detection in v1: after a sleep the page ran at 30 until relaunch [M]; the runbook requires the show Mac to stay awake.
5. Native `<video>` cadence (8–12 %) stays on air until OD-2 lifts the GL-replay attach gate.
6. The DeckLink path has had zero hardware contact; §6 is entirely on-the-day.
7. The one-time setup shows OBS to an operator (OD-M3).
8. If the dashboard dies mid-show, OBS keeps keying the last slide on air until the dashboard is relaunched (it quits the old engine).
9. ProPresenter cannot share the UltraStudio: its SDI screens are always on (Renewed Vision KB) and DeckLink output is exclusive to
   one app. Worst case the operator quits ProPresenter before **Take output** and reopens it after **Release output** (owner-accepted);
   whether deleting ProPresenter's SDI screen frees the device without quitting is a hardware-day item (§6).

## 12. v2 (deferred)

Page-rate probe + W6 (Q-F, Q-G), `GetStats` skipped-frame history + W7, 50/60 output rates with their own measurement, orphan
adoption, "Reset output engine", OBS.app code-signature check, removal of external attach.

## 13. Critique log (Opus HIGH, 2026-09-24) — all folded into rev 2

Blockers: engine actions could restart OBS under a live show (§5 locking) · the page was matched by URL, which changes mid-show
(target id, §2) · a pyobjc dependency owned by no stream (S1 owns `pyproject.toml`). Majors: `_clamp` drops unknown keys (§3) ·
device record belongs to the per-user engine folder, not per-worktree settings (§6) · NSWorkspace launch returns the pid, removing
the snapshot/`lsof` logic (§2, Q-I) · self-generated goldens would pass a broken seed (§9). Minors: lock held for the process
lifetime; orphans never adopted; W3 split into crash vs waiting; password permissions not relied on; W8 is a session warning;
`--disable-shutdown-check` does not exist; Q-C/Q-D settled from source.

## 13b. Codex GPT-5.6 Sol review log (implementation, 2026-09-24)

- **r1** (3 blockers, 6 majors, 2 minors) — all accepted and fixed: synchronous pending state; env-marker ownership
  (`CFFIXED_USER_HOME=<home>` read via `ps -Eww`) + recorded pid/date; cancellable, terminal shutdown; `cleanExit` only after
  AK's own confirmed quit; bounded fail-closed liveness (`obsPageLost`, new `obsUnreachable`); W2 recovery on Check; Take output
  refused while a show is loaded; setup state polled; Screen output byte-identical (fps opt-in; loading snapshot key order).
- **r2** (3 blockers, 4 majors, 1 minor) — all fixed except R2-6 partially by owner-simplicity decision: tri-state identity
  (unknown ⇒ new block `obsIdentityUnknown`, no launch, no tree write, no terminate); terminate/show act on the same verified
  `NSRunningApplication` (re-checked immediately before); NO per-launch nonce (only AK sets `CFFIXED_USER_HOME` to its home);
  coalescing `apply_settings` (never launches because Keyer was selected); Check + page reset as one job.
- **r3** — converged: no new-class blocker/major. Fixed: W3 latch across the startup orphan-recovery path (must-fix); output
  settings refused during device setup; route-fake fidelity. **Deferred residuals (edge cases in closed classes):** (1) no
  launch-pending record for a dashboard crash in the milliseconds between seeding and the OS launch (the next start's orphan scan
  finds the process by its env marker once it exists); (2) `close()` followed by `shutdown()` quits without re-taking the flock —
  not a product path (product teardown calls `shutdown()` only).
- Live harness (product engine, real OBS 32.2.2, lossless, 25 fps): 4/4 takes PASS after r1 and after r2 — 2× native repeats
  9–13 %, positive control 23–30 %, paused 100 %, clean quit via identity, user OBS config unchanged, `.sentinel` untouched.

## 14. Owner decisions on the open items (2026-09-24)

- **OD-M1 — 30 fps ships with 25**, after Q-H measures canvas 30 / source 60 (the owner will test it).
- **OD-M3 — one-time visible-OBS device setup: accepted.**
- **OD-M4 — pin the latest stable OBS, exactly.** Today that is 32.2.2 (GitHub releases, 2026-08-14; the installed version). The pin
  moves only by a deliberate change after the qualification harness passes on the new release.
- **OD-M5 — websocket on, strong password entropy:** `secrets.token_urlsafe(32)` = 256 bits from the OS CSPRNG, a new password every
  launch, never logged or returned by the API (tested).
- **OD-M10 — RESOLVED (2026-09-24): explicit Take / Release output (§5).** History — ProPresenter 7 can switch its output on and off. When ProPresenter's output is off,
  AK takes over the UltraStudio; when ProPresenter's output is on, AK stands down. The owner sees this as the only clash.
  Pending: are AK and ProPresenter on the SAME Mac? If they are on different Macs, the Thunderbolt cable decides ownership and AK needs
  no coordination; if they share one Mac, research first: (1) whether ProPresenter 7's network API reports its SDI output state;
  (2) whether ProPresenter releases the DeckLink device while its output is off; (3) AK stands down by quitting its OBS (the DeckLink
  output cannot be stopped safely over the websocket, §6) and takes over by relaunching with auto-start.

  Research (Renewed Vision KB + Blackmagic SDK): ProPresenter's SDI screens are always on (the Audience/Stage toggles and the API's
  `PUT /v1/status/audience_screens` do not affect SDI); clearing layers only changes content; DeckLink output is exclusive per device
  (`E_ACCESSDENIED` for a second app until `DisableVideoOutput`); PP 7's API (7.9+, default port 50001, no auth) can read screen
  toggles but cannot identify the SDI screen or release the device. Owner: same Mac first (explicit handover; worst case quit
  ProPresenter before Take output, reopen after Release — acceptable); fallback = the venue's backup Mac with the UltraStudio cable
  moved. A ProPresenter-status hint via its API is out of v1.

Resolved without the owner (critique, from facts): 50/60 deferred (60-fps cap); W8 Keyer-only, warn-only; W6 deferred; external
attach kept unchanged; no code-signature check in v1.
