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
- **Alpha Keynote** — drop or choose a Keynote, prepare it (movies are converted to H.264 and mis-mapped export textures are repaired), then present using a slide grid and current still preview. Supports silent screen output and managed DeckLink fill/key output.
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

In **Alpha Keynote**, drop a `.key` file from Finder or **Choose on this Mac**.
**Qualify Keynote** prepares a cached HTML
export from a scratch copy, converting every movie that is not H.264 (see
**Codec report**). A prepared deck from **Sermon Checker → Build Preview** can
also be selected. A deck that cannot play (unrecognised player, not 16:9, not
manual mode, unsupported media such as a web video, no playable slides) shows the
reason and cannot start. Any other deck can start; the prepare panel shows whether
movie continuity is on (and which moves are not carried) or off for this deck,
with the reason. Continuity never blocks start.
The server checks the export again when starting.

Prepared decks are saved snapshots; later Keynote edits do not update them. Alpha
Keynote checks freshness when prepared decks load, are selected, and are qualified.
A yellow warning and **Prepare again** button appear when the source changed; a
neutral note appears when the original Keynote is missing or unreadable. These are
warnings only, not continuous monitoring, and do not block starting the saved deck.

Choose the output under **Output settings**, then **Start output session**.
For UltraStudio, **Enable Keyer** sends fill/key for overlaying slides on live
video. **Take output** turns into **Release output** once the engine is running.
Starting creates one output session and shows it once
the deck has loaded; **Hide output** / **Show output** toggles it. The 16:9 picture fits inside
the display without stretching. HDMI hiding produces black and leaves playback
running. Click a thumbnail or type an original slide number and press Enter to
restart that slide at its initial state. The right chevron, right arrow, Space,
Enter, or Page Down advances the next build or slide. The left chevron, left arrow,
or Page Up restarts the previous playable slide; reverse-build is unavailable.
Presenter clickers that send Page Up/Down work as-is. Skipped slides are disabled.
Build Preview and live output
both draw Magic Move objects at Keynote's opacity; `OBED_LIVE_MM_OPACITY=off`
turns this off for both.

Switching tabs or closing the presenter does not stop output. **Stop session**
ends it. Keep the dashboard server running; restarting the server does not restore
a movie position. The Current picture and grid thumbnails are still previews;
the chevrons sit directly below Current. Motion preview, video pause/play, and loop
overrides are deferred. Presenter
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
  (a deck-wide refusal below, an unreadable export, the stage isn't the authored
  size, the stage scale is non-uniform, or the runtime failed to install); the raw
  export plays untouched.
- `qualified` — the runtime installed and confirmed itself from the page. When
  qualified, `output.continuity` also carries `scale` (the uniform factor applied
  to the authored stage, e.g. `1.3333`).

**What is carried.** Policy: every Magic Move where the same movie continues is
carried, whether or not its geometry changes. Continuity follows each movie
instance through the deck, so a movie can be carried across several Magic Moves in
a row. Keynote's "Play across slides" is not in the export, so the carry is
inferred from the Magic Move alone. Each instance is identified by its object ID
only, and a `<video>` belongs to a movie only when its file name matches the
movie's asset exactly (without query or trim suffix, case-insensitive).

- **Magic Move, same geometry:** the live decoder is pinned in place.
- **Magic Move, moving or resizing:** the live decoder moves with the transition.
  The motion follows the export's EaseInEaseOut timing over the transition.
- **Dissolve or no transition:** the movie restarts, as the export plays it.
- **Movie ends:** a carried movie with no instance on the next slide is handed back
  to the player.
- **Repeated movies:** when a slide shows the same movie more than once, each
  source instance is identified from its transition slot and paired with the
  destination draw object at that slot's recorded endpoint. There is no distance
  fallback.
- **Fades:** a validated outgoing fade ends rather than carrying, and an incoming
  fade does not prove a correspondence.
- **Loops:** a carried pair must agree on Repeat → Loop. A carried decoder keeps
  its source slide's loop setting. Repeat → Back and Forth is not yet measured,
  so that movie is declined (`R11`).

**Declined cuts.** A qualified session can still decline one cut for one movie
instance. That instance plays as the export plays it (it restarts or freezes
there), and the rest of the deck stays continuous. Each declined cut appears once
per instance on `output.continuity.notCarried`, with its slides, movie, the
instance's `objectId`, a refusal `code` and a `reason`, and under the presenter's
continuity badge. The codes:

- `R1`: Magic Move transition correspondence is missing, contradictory or
  ambiguous. The affected asset is declined rather than paired by distance.
- `R2`: the carried instance itself builds out or in (including a destination hidden
  at its first event), or either slide has a build that names no object, so the export
  cannot prove that it belongs to some other object.
- `R4`: the pair disagrees on Repeat → Loop.
- `R7`: the movie is a web video or an image movie.
- `R8`: the pair is trimmed differently.
- `R9`: the movie is not fully opaque on either side (a carried decoder is drawn
  at opacity 1, so a fade would turn solid).
- `R10`: a movie that moves across the transition does not ease in and out over
  the whole transition, or has no positive duration (the carried movie can only
  follow that timing).
- `R11`: an export shape that has not been measured; the `reason` names the exact
  check. A movie layer that does not read as an unmasked, unrotated, unanimated
  rectangle declines that movie at the Magic Moves into and out of its slide (the
  unmeasured instance is listed by its `objectId` but has no plan entry and plays
  as the export plays it); an unreadable destination draw order declines that
  carry; and a carry into a slide whose outgoing transition is not Magic Move,
  Dissolve or none is declined, so nothing is held into that transition and
  that slide restarts its movie where it might have carried. An unrecognised
  Magic Move variant also declines the affected asset because its transition
  record has not been measured.
- `R12`: more than one otherwise admissible movie changes geometry at the same
  cut. Every moving instance at that cut is declined; independent pinned movies
  and continuity at other cuts remain eligible.
- `overlap`: artwork above the carried movie on the destination slide (GL replay
  may still carry it; see below).

Deck-wide refusals make the whole deck `unsupported`, with the code at the start
of the `reason`: `R3` (a transition is not on the slide's last build), `R5` (an
object ID repeats across slides) and `R6` (the carried instances do not chain from
slide to slide). A slide with more than one transition, an unreadable header,
slide list or slide JSON, a movie without an asset ID or object ID, or a plan
that fails its own integrity checks also makes the deck `unsupported`, as do the
host's checks: the stage gate, a runtime that fails to install, a movie codec
this output cannot play, and `OBED_LIVE_CONTINUITY=off` (reported as `off`). The
deck still plays.

**Not carried (named residuals).**

- `R-res-1`: a "Play across slides" movie at a Dissolve or no-transition cut
  continues in Keynote but restarts here.
- `R-res-2`: a second copy of the carried movie entering at a Magic Move shares
  the carried clock in Keynote but plays from 0 here.
- `R-res-3`: a Magic Move out of a movie with "Play across slides" off restarts
  midway in Keynote. Here it is carried. Validation flags it as an authoring error.

**Coverage.** Every deck whose plan derives gets continuity. Only the gate
decks (P2, p2-loop and D1–D6) have been measured end to end; any other deck
shape is installed on derivation alone, trusting the refusals above.
`tests/test_live_continuity_corpus.py` holds one synthetic export per refusal
code and proves each still fires. `output.continuity.planSha256` is the runtime
plan's signature: equal to a gate deck's means the same plan the gates measured.

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
boundaries, with continuity on, `OBED_LIVE_CONTINUITY=off` and red arms that strip
one plan entry or swap in a faulty core, plus one attach-mode run. It scores one
verdict per planned (cut, movie instance) from the plan itself: decoder identity,
playback-clock continuity and landing rect at each cut, and no stray movie on any
settled slide. An instance declined with `R11` is left out of the plan's instance
lists, so the stray check would flag it; no gate deck has one.

**GL replay**: keeps a movie live across a click-driven Magic Move whose
destination draws artwork above it, by replaying the player's own WebGL frame
with the live movie as the texture. It is on by default under **Keyer output** and off
for screen output and the developer OBS attach path. `OBED_LIVE_GL_REPLAY=off`
turns it off everywhere; `auto` turns it on for screen output. Any other value
refuses to start. GL replay carries at most one eligible cut per deck; later
eligible cuts keep their `overlap` refusal.
`output.continuity.glReplay.mode` reports `off`, `injected`, `notApplicable` or
`unavailable`; the developer attach path reports `unavailable` ("attach output
not qualified") when asked for `auto`, and `notCarried` still lists that
boundary while GL replay is injected. Chromium draws a native `<video>` with a
midtone tone curve that the replayed frames do not get, so real footage can
shift in brightness (up to about 4 % in the midtones) where GL replay takes over
and where the slide's first build hands the movie back; timing stays continuous. Qualify it with
`scripts/live_continuity_probe.py --gl-replay auto`,
`scripts/p2_recovery_html_adversarial.py --gl-replay auto` and, under Keyer
output, `scripts/managed_obs_qualify.py --arm g2|failsafe|soak`.

**Magic Move opacity**: Keynote's exported player draws a translucent object
opaque during a Magic Move. Live output serves the player with an in-memory
patch (pinned to the supported player version) that draws each object at its
authored opacity from the first frame of the move; an object that fades, hides,
or carries several or nested animations keeps the player's own look. It is on by default for every output,
independent of continuity and GL replay. `OBED_LIVE_MM_OPACITY=off` serves the
unpatched player; `auto` keeps it on; any other value refuses to start.
`off` also restores the export's own Dissolve, cut and movie behaviour: the incoming
slide pops in under a Dissolve over fill-less textures, a cut shows both slides at
once, and a playing movie jumps back to the opening frame baked into the outgoing slide
(on, the cross-fade and clean cut apply on every output, raw export and Build Preview included).
On, the movie instead freezes on its current frame and fades with the slide on a qualified output:
- **HDMI/headless output:** when the host launched that Chrome itself, it is Chrome 154 or 155 with GPU compositing, the scale
  factor is 1, 1.5 or 2 and the stage is unscaled (`grant: snap`, granted from the browser's own report).
- **Keyer output (managed OBS):** after the host calibrates OBS's browser source. It loads a probe page in a hidden Studio
  Mode preview scene (`AK-Calibrate`, never on program), proves the capture is fresh, measures which rule OBS's renderer
  uses, then removes everything it added and restores Studio Mode and preview. A pass grants `frac` (OBS 32.2.2 / CEF 127
  draws the movie at its unsnapped position; the freeze redraws partly covered edge pixels from the movie and is refused
  when an edge pixel's centre falls outside it) for 15 s, renewed while the connection, page, OBS launch, browser and scale
  factor stay the same; DPR 1 and an integer stage origin only. Calibration runs when the output first connects and after a
  reload or reconnect; the presenter's **Recalibrate output** retries it. A calibration that disturbs the program stops
  automatic calibration until OBS restarts.
Everywhere else the movie keeps that jump: before calibration or after it fails, on scaled stages (an output not 1920 CSS
px wide), and in raw export and Build Preview, which carry the cross-fade and cut but no freeze code at all. On GPU
compositing the freeze shows a mid-tone step (identity tone, a known limit; Q5 open pending the W5 probe;
`keynote_live_dissolve_crossfade.plan.md` §3.3, §12; `keynote_live_cef_placement.plan.md`).
`output.mmOpacity` reports `mode` (`on`/`off`) and the served player's `sha256`;
`output.placement` reports `state` (`invalid`/`probing`/`valid`), `grant` (`snap`, `frac` or null), `method`
(`knowledge` for HDMI, `probe` for Keyer), lease fields, `automaticProbesDisabled` and `reason`. HDMI reasons are
`granted`, `attached`, `unqualified-version`, `software-compositing`, `version-unavailable`, `revoked-fingerprint`;
Keyer reasons include `calibrating`, `waiting-for-transition`, `probe-failed`, `program-disturbed`, `isolation-failed`,
`cleanup-failed`, `leaseLapsed`. `channel-compromised` keeps the output hidden and refuses `show` on either.
Build Preview serves the same drawing patch, without the live observation hook. Qualify it with
`scripts/mm_opacity_probe.py`, `scripts/p2_recovery_html_adversarial.py --mm-opacity auto|off`
and, under Keyer output, `scripts/managed_obs_qualify.py --arm mmo|mmo-cef`.

**Magic Move hand-back geometry**: when a Magic Move object changes size and
Keynote exported no picture crossfade for it, the exported player ends the move
2–3 px smaller and off-centre. The slide then draws the object at its authored
place, so it snaps at the next click. The same patch (and the same switch:
`OBED_LIVE_MM_OPACITY=off` serves the stock player bytes) crossfades such an object
to the next slide's picture during the move, so the move ends exactly where the
slide draws it. Build Preview gets it too. The middle of the move shows a blend of
the two pictures. The fix only engages when the next slide has already rendered
at the start of the move. A queued double click is one case where it has not;
that move looks as it does without the fix. With the patch on, GL replay on the
P2 fixture reports `opacityUnproven` `[{4, "size"}]` (patch off: `[]`). Its
`frameLen` depends on frame timing, so the probes only report it; the OBS
harness's expected value is first measured in the owner's OBS session. Qualify
it with `scripts/mm_handback_probe.py` plus the Magic Move opacity harnesses
above.

### Codec report

Preparing a deck converts every movie its slides reference that is not H.264 to
H.264 (libx264 crf 14, preset fast, yuv420p; audio AAC 192k), in place in the
cached export, with the same file names. Only the export's movie copies are
converted; the `.key` is never touched. Copies with the same media data, timing and
geometry are encoded once. Each output is checked against its source (codec, coded size,
timescale, rotation matrix, presented duration and, where the source has no
trimming edit list, frame count) before it replaces the copy; a failed check
fails the prepare and removes the incomplete export.
`manifest.movieConversion` records the encoder and each converted file; the
prepare panel lists the converted movies with their source codecs. A cached
export is reused only while every movie it references is H.264, so an older
cache with ProRes or HEVC movies is exported again once.

The prepare fails, naming every such movie, when a movie has real transparency
(H.264 has none), is HEVC whose transparency cannot be checked, has an odd width
or height, or has unreadable timing. Replace it with an opaque movie (or one with
even dimensions) and prepare again.

Preparing a deck also repairs Keynote's HTML-export texture mis-mapping: Keynote
sometimes points a label, tag box or movie poster at another object's image (for
example a label drawn as a stretched video poster). Before movies are converted,
each such object is re-pointed to its correct image in the same slide, or that
image is copied in from the previous slide's Magic Move, and the copy is checked
(size, OCR or pixels) before it is written. Only the cached export changes; the
`.key` is never touched. `manifest.textureRepair` records every repaired object
(slide, rule, old and new texture, donor) and every rewritten PDF, and is written
even when nothing needed repair. When an object has no verified replacement the
prepare fails, naming each slide and object (for example `slide 10 (287×77
image)`); re-export the deck. A cached export without a current
`manifest.textureRepair` is exported again once.

Every session still probes each movie the export references (reading its box
tree directly, no ffprobe) and reports it on `output.codecs`;
`output.codecWarnings` flags any that may not play in the current output. HEVC
(`hvc1`/`hev1`) is only attempted in headful launch mode — never headless launch,
never the OBS attach output — and a deck's continuity plan reports `unsupported`
if a movie it needs is not playable this way. A deck prepared in the dashboard
has only H.264 movies, so this only applies to exports that bypass the prepare
(for example the probe's gate fixtures).

Residuals:

- H.264 High 10 or 4:2:2 is not converted, and Chrome cannot decode it.
- HDR HEVC (PQ/HLG) becomes 8-bit SDR without tone mapping.
- Encoding runs at about realtime at 3840×1080, so long clips add minutes to a
  prepare.
- Conversion is one more generation at crf 14 (visually transparent); audio is
  re-encoded (live output is muted anyway).
- Two concurrent prepares of the same deck can make each other fail (fail
  closed).
- Re-preparing a deck while a live session serves its cache can re-export it
  underneath the session; an older non-H.264 cache always re-exports on its
  first re-prepare.

### Keyer output (managed OBS)

**Output = Keyer (fill + key via UltraStudio)** sends the show as fill + key
through a Blackmagic UltraStudio. Alpha Keynote runs its own hidden OBS 32.2.2
with its own configuration under
`~/Library/Application Support/Obed-Edom/managed-obs/`; your own OBS setup is
never read or changed. The DeckLink path is still untested on the venue hardware.

**Needs:** OBS **32.2.2** at `/Applications/OBS.app` (exactly this version; any
other version is refused) and Blackmagic **Desktop Video**.

1. In **Alpha Keynote** → **Output settings**, set **Output** to **Keyer (fill
   + key via UltraStudio)**, set **Output rate** to match the standard the Pulse
   shows (25 or 30 fps), and leave **Enable Keyer** ticked (untick for fill only). The page
   renders at 2× the rate automatically. The display picker is hidden in this
   mode.
2. **Take output** starts the engine; wait for **Output engine · Ready**.
   **Start output session** stays disabled until then.
3. First time per rate only: **Set up output device** opens OBS visibly. Follow
   the on-screen steps (Tools → Decklink Output → UltraStudio HD Mini, Mode
   1080p25 or 1080p30, Keyer External, BGRA 8-bit, Auto start, Start, OK), then
   press **Done**. This is the only time OBS is shown.
4. **Release output** after the show quits the engine and frees the
   UltraStudio. Switching Output back to **Screen (HDMI)** or closing the
   dashboard also releases it.

Output rate, keyer, device setup, Take/Release and Restart are refused with
"Stop the show first." while a session is loaded. The one exception is
**Restart output engine** after a dead-output warning, which stops the session
first.

| Warning | What to do |
|---|---|
| Output engine not installed. Install OBS 32.2.2 into Applications, then press Check again. | Install 32.2.2, **Check again** |
| Output engine is OBS {found}; Alpha Keynote needs OBS 32.2.2. Install 32.2.2, then press Check again. | Install 32.2.2, **Check again** |
| OBS closed unexpectedly last time. It has been restarted; check the output before going live. | Check the Pulse multiview before going live |
| OBS is waiting for an answer or a permission. Press Show OBS, answer it, then press Check again. | **Show OBS**, answer, **Check again** |
| OBS started in Safe Mode, so Alpha Keynote cannot watch it. Press Restart output engine and choose Normal Mode when OBS asks. | **Restart output engine** |
| OBS stopped unexpectedly — nothing is going to the keyer. Press Restart output engine. OBS may then ask a question (see Show OBS). | **Restart output engine** (allowed mid-show) |
| OBS lost the Alpha Keynote page — nothing is going to the keyer. Press Restart output engine. | **Restart output engine** (allowed mid-show) |
| Alpha Keynote cannot reach OBS. Press Restart output engine. | **Restart output engine** (allowed mid-show) |
| The output engine hit an internal error. Press Restart output engine. | **Restart output engine** (allowed mid-show) |
| No output device set for {rate} fps — the keyer receives nothing. With the UltraStudio connected, press Set up output device (one time). | **Set up output device** |
| Alpha Keynote cannot open the UltraStudio. If ProPresenter is running, remove its SDI screen in Screen Configuration or quit ProPresenter; otherwise check the Thunderbolt cable and Desktop Video. Then press Release output and Take output again. | See ProPresenter below; **Release output**, **Take output** |
| OBS is not responding to Quit. Press Show OBS and quit it from the OBS menu, then press Check again. | **Show OBS**, OBS → Quit |
| The output engine is being used by another dashboard window (pid {pid}). Close that dashboard first. | Close the other dashboard, **Check again** |

A movie whose frame rate differs from the output rate is listed under "Some
movies do not match the output rate" and judders slightly. Export movies at the
output rate.

**ProPresenter on the same Mac.** Only one app can drive the UltraStudio, and
ProPresenter's SDI screens are always on. Before **Take output**, remove its SDI
screen in Screen Configuration or quit ProPresenter; after **Release output**,
re-add the screen or reopen ProPresenter. Fallback: run Alpha Keynote on the
backup Mac and move the UltraStudio's Thunderbolt cable to it.

**During a show:**

- The Mac must not sleep. After a sleep the page renders at the wrong rate
  until the engine is restarted, and nothing warns about it.
- Double-clicking OBS while Alpha Keynote holds the output just activates
  Alpha Keynote's hidden OBS. Press **Release output** first, or open your own
  OBS from Terminal with `open -n -a OBS` and choose **Launch Anyway**.
- If the dashboard dies mid-show, OBS keeps keying the last picture. Relaunch
  the dashboard: it quits the old engine. Then press **Take output** again.
- A movie carried through a click-driven Magic Move keeps playing on the next
  slide (GL replay); its midtones may shift slightly in brightness when GL replay
  takes over and at that slide's first build. To fall back to a frozen poster,
  start the dashboard with `OBED_LIVE_GL_REPLAY=off`.
- A translucent object stays translucent through a Magic Move, as in Keynote,
  and an object that grows or shrinks in a Magic Move does not snap at the next
  click. To fall back to the exported player's look (opaque during the move, and
  the snap), start the dashboard with `OBED_LIVE_MM_OPACITY=off`.

**Qualification** (developer, launches OBS on this Mac; no other OBS may be running):
`uv run python scripts/managed_obs_qualify.py --arm both --rate 25 --takes 2 --out DIR`, and for GL replay
`--arm g2 --rate 25 --takes 2 --fixture output/fixtures/p2-binary --out DIR` (the binary-counter copy of the P2 fixture,
built by `scripts/binary_counter_movie.py --build-fixture`). Gate fixtures live in the main checkout's
`output/fixtures/<name>`; scripts resolve them from any worktree via `obed_edom.fixture_paths.fixture()`, so there is
nothing to symlink.

### DeckLink fill/key via OBS (developer fallback, UNQUALIFIED)

Operators use **Keyer output** above. This external-attach path, driven by
environment variables with no dashboard controls, is kept for development.

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
