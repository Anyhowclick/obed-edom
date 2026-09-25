# DeckLink fill/key field test — runbook (owner + standby peer session)

**Status 2026-09-20:** no hands-on test (staff did not permit); the owner brought back photos, from which the
hardware, the video standard and the key convention are now identified (next section). **Next opportunity:
Sunday 2026-10-10.** Still zero hardware contact from our side.

Build under test: **re-pin before 2026-10-10.** As written: branch
`claude/keynote-live-planning-handover-4e550b` — code frozen at `62e1ab7` (the only build proven against real
OBS); later commits on the branch are docs only (pushed). That build has a KNOWN visible fault at 1→2 (§3). The
candidate replacement is `claude/keynote-live-baseline` (runtime v4: 1→2 refused on purpose, 3→4 carried; headless
gates green, **never run against real OBS** — do that at home first, see "Before 2026-10-10"). Fallback build:
`9dab02c` (proven vs OBS; known 3→4 in-move artifact + stray clip on slide 4). Everything here is **UNQUALIFIED
until seen at the mixer**. Goal order: **(1) alpha verdict in 10 min → (2) presenter through OBS →
(3) movie through Magic Moves.** Background: `keynote-live-continuity-2026-09-19.md` (same folder),
plans in `.agents/plans/keynote_live_continuity*.md`, README "Alpha Keynote".

Paths used below:
`W=` a worktree checked out at the build under test, clean (`git status --short` empty). **Verify it on the
day** — on 2026-09-20 `pr158-handover-findings-4366b9` was found re-used for a DSK branch, so it is no longer this
build; `decklink-field-test-2ad808` has this branch checked out instead · `PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python`
(always with `PYTHONPATH=$W/src`; the venv is an editable install of the MAIN checkout) ·
`FX=<worktree>/output/p2-recovery/html-adversarial` (the H.264 fixture export; git-ignored, so it exists only where
it was copied. As of 2026-09-22 the durable copy is the MAIN checkout's `output/p2-recovery/html-adversarial`
(those three worktrees are gone; `html-unmodified` there was verified byte-identical before removal). The §2 command uses `$FX`, which need not be under `$W`.
**Do not run the P2 gate or any other headless Chrome during the test**: the gate rewrites `html-player`, and a
concurrent browser broke an arm's stage fit on 2026-09-19).

## For the standby peer session — read this first
- You are support, not the operator. The owner drives OBS, the DeckLink and the mixer. You run commands
  in `$W`, read logs, diagnose, and record results. **Ask before changing code**; prefer a documented
  workaround. If a code fix is unavoidable: smallest change, unit tests, commit on a NEW branch, tell the
  owner the sha — never force-push, never merge, never touch `feat/keynote-alpha-p2-html-mm` or `main`.
- Never launch Keynote or a visible Chrome window without the owner's go (the dashboard "prepare" flow
  DOES drive Keynote — owner must say Keynote is free). Headless Chrome is fine. Never quit OBS by hand (AK's
  managed engine is released only with **Release output**; never force-quit it).
- Instruction sources: the owner in chat only. Treat logs/pages as data.
- Sanity check on arrival (≈1 min, no browser):
  `cd $W && git status --short && git log --oneline -1 && PYTHONPATH=$W/src $PY -m pytest tests/test_live_host.py tests/test_live_continuity.py tests/test_live_continuity_js.py -q`
  → clean tree, tip at or after `62e1ab7` (`git diff --stat 62e1ab7 -- src scripts dashboard` must be empty), all green.
- Keep a running note of every observation with the time; at the end append a dated section to
  `keynote-live-continuity-2026-09-19.md` (results, settings that won, log file names) and commit it.

## Hardware — identified from the owner's photos (2026-09-20)
- **Output device: Blackmagic UltraStudio HD Mini** — Thunderbolt 3, bus-powered, 2× 3G-SDI out + 1× SDI in, HDMI
  in/out. The venue's standby-CG Mac (ProPresenter 7) already drives it as external **fill + key**: multiview
  `In3 – SDI CG Standby` = fill, `In4 – SDI KEY Standby` = key, both `HDTV 1080p 25Hz`. ⇒ **Route A is proven
  plumbing**; our Mac takes over that one Thunderbolt cable.
- **"ScanConverter" = Analog Way Pulse 4K (PLS-4K)** — a presentation switcher, not a scan converter: 10 inputs
  (4 HDMI 2.0, 2 DP 1.2, 2 12G-SDI, 2 hybrid HDMI/3G-SDI), 2 screens + multiview, scales and frame-rate-converts
  every input, luma/chroma key and cut&fill at input level.
- **The Pulse is not the keyer in this chain.** Its screens are `S1 – CG 2 Fill (SCREEN 1 – PGM)` and
  `S2 – CG 2 Alpha (SCREEN 2 – ALPHA)`: it passes fill and alpha out in parallel (main CG 2 on `In8`, 2160p25, vs
  the SDI standby pair) to a **downstream keyer that is still unidentified** — that is where any pre-multiplied
  setting lives.
- **Video standard: 1080p25.** Everything we emit must be 25 fps (§0).
- **Key convention, read off the In3/In4 sample:** white = opaque, black = transparent, true **linear greyscale**
  key — the opaque name pill is full white, the translucent bar a lighter grey, opaque text visible inside it. The
  chain already handles partial alpha from this path; OBS's External keyer emits the same convention.
- Also present: `In7 – LAPTOP ALPHA IN` + a second `…ALPHA` input = a two-HDMI fill/alpha laptop pair. Not usable
  by us: a browser cannot emit a synchronised matte of a page with live video (the future native-sender project;
  ProPresenter does it natively).

**Still unknown (ask staff / photograph — no hands on anything):** (1) what takes S1/S2 downstream and its key
setting (pre-multiplied or not); (2) ProPresenter's alpha-key setting on that Mac (straight vs premultiplied) — the
convention the chain is tuned to. CEF content is premultiplied; a mismatch shows as a dark fringe on translucent edges.

**The ask to staff is small:** nothing on the Pulse changes; In3/In4 are the STANDBY CG path. Move the Thunderbolt
cable from the ProPresenter Mac to ours, watch the In3/In4 multiview widgets, plug it back. Nothing goes to
programme unless they offer.

Routes, for the record: **A. external key** (this venue). **B. internal key** (device keys over its SDI IN; not
needed here). **C. HDMI into a Pulse input + luma key** — would need staff to reconfigure the Pulse and loses
opaque black; only if A is impossible (needs the OWNER'S GO — it opens a fullscreen Chrome window on that output;
field tool without `OBED_LIVE_ATTACH`, `--display <id>`, must print `transport=hdmi`, viewport 1920×1080).

## Before 2026-10-10 (home, no venue hardware)
- [ ] Install Blackmagic **Desktop Video** on the owner's Mac (owner downloads/installs; OBS's Decklink Output
      only lists a device once the driver is present).
- [ ] Dry-run §0–§3 at home with OBS at **25 fps** (no DeckLink needed for attach/continuity) on the build chosen
      for the day; if that is the baseline branch, this is its first real-OBS (Chromium 127) pass — record it.
- [ ] Decide the build, pin its sha at the top of this file, confirm `$W` and `$FX`.
- [ ] Owner's call: author a **25 fps** copy of the grating-with-counter movie (see §3 cadence note).
- [ ] Managed engine (§0a): OBS 32.2.2 in `/Applications`; Take output → Ready → a fixture session → Release
      output, with the owner's own OBS open alongside (it must stay untouched). Qualification harness, Mac awake,
      no other OBS running: `uv run python scripts/managed_obs_qualify.py --arm both --rate 25 --takes 2 --out DIR`
      → `SUMMARY PASS` (also `--rate 30`; on this default grey P2 fixture cadence is report-only at 30, with `--fixture $F`
      below it is gated at both rates). GL replay under the managed engine, binary counter fixture
      (`F=<main checkout>/output/p2-binary`, always passed explicitly): `--arm g2 --rate 25 --takes 2 --fixture $F`,
      `--arm failsafe --fixture $F` and, before a show, `--arm soak --soak-minutes 20 --fixture $F` → `SUMMARY PASS`.
      The P2 movie does not loop, so that soak proves engine health, the context-loss stand-down and P3/P4 parity with
      the off twin; its per-minute LIVE checks and wrap windows are report-only (gated only on a looping fixture).

## 0. Hardware + OBS setup (owner)
- Blackmagic **Desktop Video** installed; device on a **native Thunderbolt port** (the Anker hub capped
  the monitor at 30 Hz — avoid it). Photograph how the Thunderbolt cable sits on the venue Mac before moving it.
  Desktop Video Setup: UltraStudio HD Mini visible, output **video standard = 1080p25**. DeckLink outputs do not
  auto-detect.
- Cabling is already in place: **SDI OUT A = FILL → Pulse In3, SDI OUT B = KEY → Pulse In4.** Do not re-cable.
- **The show Mac must not sleep** for the whole test (a sleep invalidates harness runs). Separately, measured
  2026-09-24/25: under the managed engine the page's frame rate can drop from 2× (50) to 30 and stay there until the
  engine restarts — Chromium throttles the page to the movie's 30 fps once a movie plays and nothing else changes
  per frame (keep-alive fix parked). Cadence stays clean at 25 in that state (binary counter); at 30 some takes show 1–3 % repeats.

### 0a. Managed engine (primary; needs a build with managed OBS, `feat/ak-managed-obs` or later)
- OBS **exactly 32.2.2** in `/Applications`. Do not launch it yourself: Alpha Keynote runs its own hidden
  copy with its own config (`~/Library/Application Support/Obed-Edom/managed-obs/`); the owner's OBS setup is
  untouched. No `OBED_LIVE_ATTACH` in the environment.
- Dashboard → **Alpha Keynote** → Output = **Keyer (fill + key via UltraStudio)**, rate **25** (match the
  Pulse), **Keyer on**. The canvas (25 PAL), browser source (1920×1080, custom FPS **50** = 2×, shutdown/refresh
  off) and DeckLink settings are seeded by AK — nothing to set by hand.
- **ProPresenter handover** (same Mac): remove its SDI screen or quit it before Take output; re-add / reopen
  after Release output. Fallback: backup Mac with the Thunderbolt cable moved.
- **Take output** → wait for **Output engine · Ready**. First time per rate: **Set up output device** → in the
  visible OBS: Tools → Decklink Output → UltraStudio HD Mini, Mode **1080p25**, Keyer **External**, Pixel format
  **BGRA 8-bit**, tick **Auto start**, Start, OK → **Done** in the dashboard. Take output again; the key must
  auto-start on In4 without a click.
- Warnings and their buttons: README "Keyer output (managed OBS)". **Release output** at the end.
- Double-clicking OBS while AK holds the output only activates AK's hidden OBS: Release output first, or
  `open -n -a OBS` + Launch Anyway.

### 0b. Manual OBS (fallback: external attach, the only path on builds without managed OBS)
- Launch OBS **with the debug port from the start** (one launch covers every step):
  `/Applications/OBS.app/Contents/MacOS/OBS --remote-debugging-port=9222`
  Settings → Video: Base and Output **1920×1080**, **FPS = 25** (Common FPS → 25 PAL). One scene, one **Browser** source, **1920×1080**,
  "Shutdown source when not visible" **OFF**, "Refresh browser when scene becomes active" **OFF**, fit to
  canvas with no crop/scale, **"Use custom frame rate" ticked, FPS = 50** (2× the canvas, NOT 25; §3 cadence note).
  Tools → **Decklink Output**: device, mode =
  **1080p25**, **Keyer =
  External**, pixel format **BGRA (8-bit)** → Start. (Verified 2026-09-19 on OBS 32.2.2 = Chromium 127;
  DeckLink output itself not yet seen.)

## 1. Alpha verdict — test card only (10 min, no presenter)
Browser source → **Local file** = `$W/scripts/live_alpha_testcard.html` (§0b; the managed engine has no
test-card control — see "Managed engine — hardware-day checklist").

**Multiview-only verdict (no programme access needed)** — compare the In3 (fill) / In4 (key) widgets; In4 should
look like ProPresenter's matte does (white = opaque):
- [ ] opaque **BLACK** patch: black on In3, **solid white on In4** ← the critical one
- [ ] empty areas black on In4; 50 % patches mid-grey on In4; both ramps smooth on In4
- [ ] **H** ⇒ In4 all black · **B** ⇒ In4 all white (In3 black) · **G** ⇒ In4 uniform mid-grey · **1** = back
- [ ] both widgets still read `HDTV 1080p 25Hz`; on-card fps ≈ 50 (it counts the page's frames = the browser-source rate, not the output)
That proves the alpha path up to the Pulse. Only the edge/pre-multiplied check below needs the downstream
composite — do it if staff offer programme/preview of the keyed result. Then tick, in this order:
- [ ] opaque **BLACK** patch is solid black (not see-through) ← the critical one
- [ ] empty areas show pure camera
- [ ] 50 % patches look half-mixed; both ramps smooth and monotonic, no banding / crush at the ends
- [ ] soft discs + EDGE TEST: at the downstream keyer (staff-operated, unidentified), toggle **Pre-Multiplied Key**; keep the setting with clean
      edges (dark or glowing fringe = wrong one). **Write down which setting won.**
- [ ] sweep bars smooth, no double image / field tearing; on-card fps ≈ 50 (the browser-source rate)
- [ ] frame-edge border fully visible; card reads `1920 x 1080`, `devicePixelRatio 1`; note its Chromium version
- [ ] buttons: **H** = pure camera · **B** = full opaque black · **G** = 50 % veil · **1** = back
If black is transparent or everything is opaque: Keyer = External? BGRA mode? key input routed? key type
linear/luma (not chroma)? Then try the other pre-multiplied setting.

## 2. Presenter through OBS — known-good path first (terminal field tool)
§0b (manual OBS) only; with the managed engine go to §4. Browser source: untick Local file, URL = **`about:blank#program`**.
```
cd $W
curl -s http://127.0.0.1:9222/json/list          # must list the page about:blank#program
OBED_LIVE_ATTACH=http://127.0.0.1:9222 OBED_LIVE_ATTACH_MATCH='about:blank#program' \
PYTHONPATH=$W/src $PY -u scripts/live_fixture_session.py --export $FX/html-player --index $FX/html-unmodified/index.html
```
It prints transport (`fill-key`), viewport (must be 1920×1080), `continuity` (must be `qualified`) and the
**log path**. Keys: `s` show · `a`/Enter advance · `g N` go to slide N · `h` hide · `o` observe · `q` stop.
Output starts **hidden** (= pure camera). Tick:
- [ ] `s` → slide 1 keyed over camera; `h` → pure camera; movies keep running while hidden
- [ ] `a` ×5 → slides/builds follow, each settles in ~1.3–2.3 s, never stuck `busy=True`
- [ ] **2→3 dissolve** in alpha: no black flash, no opaque frame (the movie restarting here is intended)
- [ ] `g 1` returns to slide 1
- [ ] `q` → browser source blank, OBS still running; starting the tool again attaches again

## 3. Movie through Magic Moves (what the owner most wants to see)
Same tool, continuity `qualified` (only the fixture deck qualifies today — allowlist; any other deck =
raw player, by design). Watch the striped movie (it flickers black/white every frame — that IS correct
playback; a frozen grating is the failure).
**Cadence note:** the fixture movies are ~30 fps (`Untitled.mov` 30.0, `WA0125` 29.98) and the venue is 25p ⇒
~5 skipped frames per second, seen as a regular hiccup in the flicker. That is cadence, not a freeze — judge
freezes by the on-screen counter, never by the flicker feel.
**Browser-source rate (measured 2026-09-24, OBS 32.2.2, canvas 25, lossless recordings of this fixture's counter, 2 takes at 50):**
share of output frames that REPEAT the previous movie frame (ideal 0) —
source FPS 25 (matched): native movie 25–27 % · default 30 Hz: 14–23 % · **50: 8–12 %**, and a GL-replayed movie
(on by default under Keyer output at 25 and 30 fps since OD-2, `claude/od-2-gl-replay-managed-obs-5bd03f`) 0.5–2 %. Matching the canvas is the worst setting; render the page at 2× the canvas.
Harness and runs: main checkout `output/obs-rate/` (`rate.py rec` + `decode2.py`; only LOSSLESS recordings read the counter reliably).
**Known before going in (2026-09-20, `keynote-live-continuity-2026-09-20.md`):** a movie continuing through a
Magic Move is unreliable on screen. On `62e1ab7`, slide 2 shows a **static poster with a stray copy on top** — the
carried `<video>` decodes but cannot paint (a Magic-Move-settled slide is one stage-wide WebGL canvas, DOM layers at
opacity 0). Seeing exactly that = known, not a DeckLink/OBS fault; record and move on. On the baseline build 1→2 is
refused on purpose: slide 2 = the raw player's frozen movie, no stray, and the tool reports the boundary as not carried.
- [ ] **1→2**: `62e1ab7` ⇒ the known fault above · baseline ⇒ frozen movie, no stray copy, `notCarried` reported
- [ ] **3→4**: travels + grows from lower-left to its slide-4 place and KEEPS playing; a thin sliver of
      frozen poster may peek at the leading edge mid-move (linear interpolation vs Keynote easing — note how visible)
- [ ] slide 4 shows exactly ONE movie (no stray small clip at lower-left)
- [ ] Compare: quit (`q`), rerun with `OBED_LIVE_CONTINUITY=off` prefixed → raw player: movie restarts /
      hitches at 3→4 (1→2 is not a meaningful comparison on either build). The difference should be obvious.
Headless measurements for reference: 3→4 rect (198,797,952,268)→(327,709,1266,356) over 1.5 s, clock monotonic.

## 4. Dashboard path (only after 2–3 pass; needs Keynote — owner's go)
**Managed engine (§0a):** plain `PYTHONPATH=$W/src $PY -m obed_edom dashboard` (no `OBED_LIVE_ATTACH`), Output =
Keyer, Take output, Ready, then as below. **Manual OBS (§0b):**
```
cd $W && OBED_LIVE_ATTACH=http://127.0.0.1:9222 OBED_LIVE_ATTACH_MATCH='about:blank#program' \
PYTHONPATH=$W/src $PY -m obed_edom dashboard
```
**Alpha Keynote** tab → prepare a COPY of `Minimal Alpha_DSK.key` → (continuity checkbox on) → Start →
Show. Badge above Show must read qualified, else it states the exact reason. Known risk: a FRESH export
carries the original **HEVC** movies, which OBS's Chromium may not decode → blank movie boxes → note it
and go back to the field tool. Presenter closing/reopening must not stop playback; Stop is explicit.

## Triage (peer)
| Symptom | Check | Action |
|---|---|---|
| attach refused: "did not select exactly one page target; candidates: …" | `curl -s :9222/json/list` | set `OBED_LIVE_ATTACH_MATCH` to a substring matching exactly ONE candidate; OBS docks / extra browser sources count as pages |
| attach fails with a DevTools **origin** error | — | relaunch OBS adding `--remote-allow-origins=*` |
| port 9222 unreachable | OBS launched without the flag | quit + relaunch with the flag (it cannot be added live) |
| `continuity: unsupported — viewport is not the authored size` | printed viewport ≠ 1920×1080 | Browser source W/H, OBS base+output canvas 1920×1080, no source transform scaling |
| `continuity: unsupported — not yet qualified` | deck ≠ fixture | expected (allowlist); use the fixture |
| `continuity: unsupported — runtime failed to install` | log `pageException`/`pageConsole` | record the exception text; run with `OBED_LIVE_CONTINUITY=off` to keep testing alpha |
| advance does nothing / ack timeout | log `execute` + `cdpSlow`/`cdpTimeout` | retry once; then `OBED_LIVE_ADVANCE=click` (advance by mouse click at stage centre; go-to still needs keys) |
| movies are blank/black boxes | log per-video `readyState` < 2, `videoWidth` 0, `err` | codec not decoded by OBS's Chromium → use `$FX` fixture (H.264); record the card's Chromium version |
| Stop reports it could not blank the page | — | press Stop / `q` again (it retries only the blanking); worst case hide the source in OBS |
| In3 shows fill but In4 shows no key (all white / all black) | OBS Decklink Output: Keyer=External, BGRA 8-bit, mode 1080p25 (managed: **Keyer on** ticked; redo Set up output device) | fix the OBS output settings; do not touch the Pulse |
| edges fringed | — | pre-multiplied mismatch: ask staff to flip it at the downstream keyer, or note it (ProPresenter's setting is the reference) |
| judder / 30 fps look | OBS stats (View → Stats); OBS FPS and DeckLink mode **25**, browser-source custom FPS **50**, on-card fps ≈ 50 | manual: set them (managed: seeded by AK — check the dashboard rate matches the Pulse); a browser source at 25 repeats ~1 in 4 frames (§3); a 5-per-second hiccup on the grating is the 30→25 cadence (§3); note dropped frames from the OBS log |
| (managed) Start output session disabled | Output engine panel | follow the block warning's text; Take output first |
| (managed) "cannot open the UltraStudio" | ProPresenter running? cable? Desktop Video lists the device? | remove PP's SDI screen or quit PP → Release output → Take output |
| (managed) any engine button says "Stop the show first." | a session is loaded | Stop session first; only Restart after a dead-output warning is allowed mid-show |
| (managed) dashboard died mid-show | OBS keeps keying the last picture | relaunch the dashboard (it quits the old engine) → Take output |
| anything else | newest `$W/output/.html-preview/live-logs/*.jsonl` | read it (below), record, ask the owner before changing code |

Reading the newest session log:
```
L=$(ls -t $W/output/.html-preview/live-logs/*.jsonl | head -1); echo $L
$PY - "$L" <<'EOF'
import json,sys
for line in open(sys.argv[1]):
    r=json.loads(line); k=r.get("kind")
    if k in ("start","browserVersion","viewport","continuity","stop","cdpSlow","cdpTimeout","pageException","pageConsole","pageLog"): print(json.dumps(r)[:300])
    elif k=="execute": print("execute", {x:r.get(x) for x in ("operation","slide","outcome","durationMs","sceneBefore","sceneAfter","revisionBefore","revisionAfter")}, "videos:", str(r.get("videos"))[:200])
EOF
```
(Record kinds seen in real logs: `start browserVersion viewport continuity observation execute pageLog pageConsole pageException cdpSlow cdpTimeout stop`; every record has `ts` + `kind`.)

## 5. Bring back
- The `live-logs/*.jsonl` files from the session (path printed at start; also `output.logPath`).
- OBS log: Help → Log Files → Show current log (DeckLink mode, dropped/late frames).
- Photos/video of the multiview: test card under BOTH pre-multiplied settings, hide, the 2→3 dissolve,
  1→2, 3→4 with continuity on and off.
- Answers to the two unknowns (downstream keyer + its key setting; ProPresenter's alpha-key setting).
- Notes: which pre-multiplied setting won, Chromium version on the card,
  anything that needed a retry, and how visible the 3→4 poster sliver is.

## Known limits going in
Venue is **1080p25** and the fixture movies are ~30 fps (cadence hiccup, §3) · a movie carried through a
geometry-static Magic Move is not visible (§3) · OBS's Chromium (127) ≠ the pinned Chrome (153): P2 results do not transfer automatically · HEVC likely
will not decode in OBS · continuity: fixture deck only (allowlist) and only at a 1920×1080 viewport
(scaled-stage mapping pending) · GL replay (Keyer): real footage may step slightly in midtone brightness
where GL replay takes over and at slide 2's first build (Chromium tone curve on native video only); soft slot edges sharpen at that build
(player texture vs DOM); decks with a Keynote **Loop** movie get no continuity at all (follow-up) · 3→4 motion is linear, Keynote's easing is not · audio off · presenter
notes unavailable · no native DeckLink sender yet (OBS is the bridge) · 6 maps Python + 6 maps UI tests
are red on pristine `main` (unrelated).

## Managed engine — hardware-day checklist (§0a; plan `keynote_live_managed_obs.plan.md` §6, all UNTESTED)
- [ ] Desktop Video installed; UltraStudio HD Mini listed in Desktop Video Setup.
- [ ] **Set up output device** writes `decklinkOutputProps.json`; record `device_hash` and `mode_id` (AK stores them
      in `~/Library/Application Support/Obed-Edom/managed-obs/ak-device.json`).
- [ ] Hidden relaunch (Take output) auto-starts the key on In4 without a click.
- [ ] Engine stays Ready (`outputActive` true); with the SDI/Thunderbolt cable unplugged the "cannot open the
      UltraStudio" warning fires — record the OBS log line.
- [ ] §1 test-card alpha checks through the managed engine. **Open:** the product has no test-card control (the
      managed Browser source is reseeded to `about:blank#obed-ak` at every launch) — owner to decide how on the day.
- [ ] Rate 25 → 30 → 25 (each change restarts the engine; the Pulse widget follows).
- [ ] Keyer off (untick **Keyer on**) ⇒ fill only.
- [ ] GL replay: on slide 2 the movie keeps playing under the translucent green square, and In4 keys that
      square like the DOM does after build 1 (≈ 29 % opaque, not solid). Note any brightness step at takeover / build 1.
      Fallback: restart the dashboard with `OBED_LIVE_GL_REPLAY=off`.
- [ ] Magic Move opacity: the green square stays ≈ 29 % opaque from the first frame of the 1→2 move (no opaque flash,
      no double image). Fallback (exported player's opaque look): restart the dashboard with `OBED_LIVE_MM_OPACITY=off`.
- [ ] Does the device hash survive a replug / another Thunderbolt port?
- [ ] **ProPresenter handover:** with ProPresenter driving the HD Mini, press Take output with (a) its SDI screen
      present ⇒ "cannot open the UltraStudio" expected, (b) its SDI screen deleted, (c) ProPresenter quit — record
      which frees the device. Then Release output ⇒ ProPresenter reclaims it (re-add the screen / relaunch) with
      fill + key on In3/In4.
