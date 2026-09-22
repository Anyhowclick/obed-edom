# Obed-Edom

Obed-Edom is a local Mac dashboard for preparing church presentation media. It can turn a Word outline into LED-wall (LW) and lower-third (DSK) Keynote decks, check finished material, resize wall slides for CG, and create map or watercolour assets.

Your outlines and decks are processed on this Mac. Keynote is required.

## Start the dashboard

1. Double-click **`Start Dashboard.command`**.
2. Wait for the browser to open at [http://127.0.0.1:8765/](http://127.0.0.1:8765/). The first launch may take a few minutes while the app sets itself up.
3. Leave the Terminal window open while you work.

If macOS blocks the launcher, Control-click it and choose **Open**.

## What you can do

- **Sermon Base Generator** — create LW and DSK decks, an operator-cued Word outline, previews, and a review PDF.
- **Sermon Checker** — check an outline, one deck, or an LW/DSK pair for cue, wording, layout, photo, and house-style issues. Checks do not alter the source files.
- **Alpha Keynote** — experimental presenter for a prepared 16:9 Keynote HTML export, with current/upcoming stills, slide-number navigation, and a separate silent display output. Native HTML alpha and movie continuity are not qualified; DeckLink fill/key is not available yet.
- **CG Resizer** — turn a finalised wide-wall deck into a 16:9 CG deck and review any framing choices.
- **DSK Generator** — turn a full-wall (FW) deck into a lower-thirds (DSK) deck; the DSK template is optional for image/video decks (the wall deck's own transparent layout, then the reference deck, are tried first), required for reformatted text verses; chosen once and remembered on this Mac, shared with Sermon Base Generator.
- **Maps** — build and export map slides for LW, DSK, and CG.
- **Watercolour** — turn photos into pencil-and-wash artwork and add them to maps.
- **History** — reopen recent results stored in the `output` folder.

## Generate sermon decks

1. Open **Sermon Base Generator**.
2. Add an LW template, a DSK template, or both. The dashboard remembers them on this Mac.
3. Drop in one or more `.docx` sermon or offering outlines.
4. Let the job finish before using Keynote for something else.
5. Review the slide previews and any flags, then open the generated decks and `review.pdf`.

Each run is saved under `output/<outline name>/`. Depending on the templates supplied, it includes:

- LW and DSK `.key` decks
- an `<outline name>_CUED.docx` show-call outline
- `review.pdf` and slide previews

## Outline cues

Put cues in square brackets in the Word outline to tell the generator what to build.

| Cue | Use it for |
|---|---|
| `[TITLE]` | Sermon title |
| `[VERSE]` | Scripture passage |
| `[VERSE-CONTINUED]` | A passage that resumes after commentary |
| `[POINT]` / `[NUM-POINT]` | Unnumbered or numbered sermon point |
| `[VERSE-AFTER-POINT]` | A verse paired with the point immediately before it |
| `[FILLER-QR]` / `[GIVING-OPTIONS]` | Offering slides |

The generator writes one operator cue for every generated slide into the `_CUED.docx` file. Notes such as `[Pray]` or `[Instructions]` remain stage directions and do not create slides.

## Alpha Keynote experiment

Prepare a deck using **Sermon Checker → Build Preview**, then select that prepared
deck and a detected display in **Alpha Keynote**. Starting creates one hidden
output session; **Show output** makes it visible. The 16:9 picture fits inside
the display without stretching. HDMI hiding produces black and leaves playback
running. Type an original slide number and press Enter to restart that slide at
its initial state. Skipped slides are unavailable.

Switching tabs or closing the presenter does not stop output. **Stop session**
ends it. Keep the dashboard server running; restarting the server does not restore
a movie position. Current/upcoming pictures are still previews, and presenter
notes are unavailable in the current HTML preparation path. Audio is disabled.
Only the recognised Keynote player version and manual presentation mode are
accepted. This experiment does not enable the separate DSK animation-file exporter.

### Movie continuity (experimental)

When a deck plays the same movie across a Magic Move or continues it into a
following slide, the exported player can lose that continuity (restarting the
movie from a fresh decoder, or breaking authored "Play across slides"). The host
derives a per-deck continuity plan from the export and injects a small runtime
that carries the live decoder through those cuts, instead of letting the export's
own transitions reset it.

Every session reports its continuity `mode` (also on `output.continuity`, next to
the runtime's version and sha256):

- `off` — disabled for this session (see below); nothing continuity-related is
  injected, and the served page is identical to a session with continuity never
  built.
- `unsupported` — the plan could not be derived or installed, with a `reason`
  (rotated/animated movie geometry, more than one movie changing across one cut,
  an unreadable export, the stage isn't the authored size, the stage scale is
  non-uniform, or the runtime failed to install); the raw export plays untouched.
- `qualified` — the runtime installed and confirmed itself from the page. When
  qualified, `output.continuity` also carries `scale` (the uniform factor applied
  to the authored stage, e.g. `1.3333`).

A qualified session can still decline individual cuts: when the destination slide
draws artwork above the carried movie, that boundary retires the movie (it
restarts or freezes there) while the rest of the deck stays continuous. Declined
cuts appear on `output.continuity.notCarried` and under the presenter's
continuity badge, one line per cut. A movie whose layers do not read as an
unmasked rectangle — an unreadable layer shape, or a possible mask — makes the
whole deck `unsupported` instead.

Set `OBED_LIVE_CONTINUITY=off` before starting the dashboard server to disable it
outright.

**Scaled stage**: footprints are derived in authored-canvas pixels and mapped
through the player's own `#stage` scale each frame, so continuity qualifies
whenever the stage is the authored size under a uniform scale — a 2560x1440
display, or a non-16:9 display where the stage is letterboxed — not only an
exact 1:1 match. It still reports `unsupported` when the stage isn't the
authored size or its scale is non-uniform. The OBS Browser Source (below) stays
fixed at 1920x1080.

**Qualification**: `scripts/live_continuity_probe.py` drives `LiveOutputHost`
itself (not a bare page) through a known fixture's Magic Move and dissolve
boundaries, in three arms — continuity on, `OBED_LIVE_CONTINUITY=off`, and
continuity on with the bridging boundary disabled — plus one attach-mode run, and
scores decoder identity + playback-clock continuity at each cut.

### Codec report

Every session probes each movie the export references (reading its box tree
directly, no ffprobe) and reports it on `output.codecs`; `output.codecWarnings`
flags any that may not play in the current output. HEVC (`hvc1`/`hev1`) is only
attempted in headful launch mode — never headless launch, never the OBS attach
output — and a deck's continuity plan reports `unsupported` if a movie it needs
is not playable this way. The original movie file is never transcoded.

### DeckLink fill/key via OBS (experimental, UNQUALIFIED)

Instead of driving its own Chrome window, the host can attach to a page already
open inside OBS's Browser Source (an offscreen CEF browser) and hand it to OBS's
DeckLink Output with an External keyer, giving real alpha over HDMI/SDI fill+key.

**This path is unqualified.** OBS bundles a different Chromium build than the one
P2 pins; nothing from P2's fixture acceptance (movie continuity, Magic Move
timing, alpha compositing) transfers to it. HEVC sources are unlikely to decode
in CEF. Treat any deck run this way as unverified until it has been watched
end-to-end on the real switcher.

**Launch OBS** with a remote-debugging port so the host can attach to it:

```
/Applications/OBS.app/Contents/MacOS/OBS --remote-debugging-port=9222
```

If the attach fails with a DevTools origin error, also pass
`--remote-allow-origins=*` (Chromium 111+ rejects a DevTools socket connection
whose Origin header does not match unless this is set; our client sends no
Origin header, so most builds will not need it, but CEF's behaviour is
unverified without hardware).

**Browser Source settings**: 1920x1080, any URL (the host navigates it to the
program page once attached, so a blank page is fine), enable "Use custom
frame rate" only if you need one, "Custom CSS" left default (the host forces
a transparent background itself), **"Shutdown source when not visible" OFF**,
**"Refresh browser when scene becomes active" OFF** (either would drop the
navigated page), and control audio through the deck instead of OBS ("Control
audio via OBS" OFF — audio is disabled in this experiment regardless).

**Tools → Decklink Output**: Keyer = **External**, and a BGRA/8-bit pixel
format matching your switcher's key input.

**Environment variables**, set before starting the dashboard server:

- `OBED_LIVE_ATTACH` — the OBS CDP endpoint, e.g. `http://127.0.0.1:9222`.
  When set, `POST /api/live` skips display selection entirely (no display is
  spawned or resized) and drives the existing OBS browser-source page instead.
- `OBED_LIVE_ATTACH_MATCH` — optional substring to disambiguate the target
  page when OBS has more than one Browser Source open; without it, exactly
  one open page is required.
- `OBED_LIVE_ADVANCE=click` — use a CDP mouse press/release at the player stage
  centre for Advance if OBS does not accept Space. The default is `key`; the
  choice is captured and logged when the session starts. Go-to still uses
  digits and Enter, and refuses with a clear error if the player does not
  acknowledge those keys before the command timeout.

In this mode the reported output transport is `fill-key` with `alpha: true`.
**Hide is transparent, not black**: the program page keeps its background
transparent and hides by fading the player to zero opacity in place, so movies
keep decoding and transitions keep running while hidden — unlike HDMI hide,
which is an opaque black overlay because that transport has no alpha channel.
`stop()` in this mode only releases what the host owns (it navigates the OBS
page to `about:blank` and closes its own CDP connection); it never terminates
OBS or the browser source itself.

**Session log**: every host start writes one JSONL file to
`<preview cache>/.html-preview/live-logs/<UTC timestamp>-<pid>.jsonl`
(the exact path is also returned as `output.logPath`). It records the start
configuration, browser version, measured viewport, every command with its
outcome and timing, every observed state change, slow or timed-out CDP calls,
page console errors/warnings, and a per-command snapshot of any `<video>`
elements — useful for diagnosing a bad run after the fact without OBS open.

### Local security posture

In launch mode the host picks a free port by binding `127.0.0.1:0`, closes that
socket, and passes the number to Chrome (`--remote-debugging-port` with
`--remote-debugging-address=127.0.0.1`); in the gap another local process could
claim it, and the host only checks that something serves a usable page target
there within 15s — it fails closed (`Chrome CDP did not start.`) if nothing does,
but does not prove the responder is the Chrome it launched. CDP and the asset
server (also loopback, on a random port) are unauthenticated, so while a session
runs any local process or user can list targets, drive the output, or read the
prepared deck. Attach mode takes its endpoint from `OBED_LIVE_ATTACH`, requiring
`http`, a loopback host, and no userinfo, path, query or fragment, and requires
the target websocket to be `ws` on a loopback host at the same port — loopback,
not identity. Run this on a single-user operator machine, not a shared host.

## Important checks

- The first time you generate or resize a deck, macOS may ask for Accessibility access. Allow the launcher app—usually Terminal—in **System Settings → Privacy & Security → Accessibility**, then restart the dashboard.
- Keynote jobs run one at a time. Do not close Keynote or the Terminal window while a job is running.
- Always read the flags and review PDF, then check the LW and DSK decks separately before show day.
- Source outlines and Keynote files are not overwritten. Generated work goes to `output` unless another destination is chosen.

## If something does not open

- Visit [http://127.0.0.1:8765/](http://127.0.0.1:8765/) manually if the browser does not appear.
- If a job reports a permission problem, grant Accessibility access and restart the dashboard.
- Find completed work in **History** or the `output` folder.
- To restart, close the dashboard's Terminal window and double-click **`Start Dashboard.command`** again.
