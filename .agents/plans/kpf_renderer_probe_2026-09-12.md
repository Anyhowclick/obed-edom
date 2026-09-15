# KPF / HTML export feasibility spike - measured 2026-09-12

Read-only. No repo file and no .key deck modified (deck mtimes unchanged; both worktrees clean).
pgrep -x Keynote was empty before the run; Keynote quit at the end.
Artifacts: DSK-html/, GW-html/, keynote.sdef, export_html.sh, rss_dsk.txt, rss_gw.txt, kpf_events.json

## 1. Export - both decks succeeded first try, no `with properties` needed
Command (export_html.sh; inspect.py idiom: close-by-name -> open -> exact-name bind -> export -> close saving no; bundle id com.apple.Keynote, never the app name):
  export theDoc to POSIX file "<scratch>/<stem>-html" as HTML

| metric | DSK | GW |
|---|---|---|
| source deck | 253 MB | 669 MB |
| wall time | 20.3 s | 56.3 s |
| folder size | 95 MB | 637 MB |
| file count | 375 | 426 |
| peak Keynote RSS (1Hz ps) | 0.94 GB | 2.21 GB |
| canvas | 1920x1080 | 7680x1080 |

Export destination under /private/tmp worked (the /private/tmp trap applies to OPENING decks).

FINDING: the HTML export SILENTLY DROPS SKIPPED SLIDES.
| deck | slides | skipped | header.json slideCount |
|---|---|---|---|
| DSK | 43 | 5 (2,4,31,39,41) | 38 |
| GW | 63 | 15 (3,4,6,9,26,27,31,34,40,41,43,47,56,58,62) | 48 |

## 2. Structure - differs from the prior probe's model
index.html (673 B, one <script src="assets/player/main.js">)
assets/header.json[p], assets/thumbnail.jpeg, assets/player/{main.js 2.37MB, pdfjs/}
assets/global/  -> EMPTY
assets/<SLIDE-UUID>/{<UUID>.json[p], thumbnail.jpeg, assets/<UUID>.pdf[p]}

CORRECTION to dsk_generator plan: there is NO global/shared.pdf in a plain `as HTML` export;
each slide carries its OWN PDF. PDF pages = one per texture, matching the JSON asset counts:
| deck | PDF pages | texture assets | video assets |
|---|---|---|---|
| DSK | 117 | 117 | 1 (.mov) |
| GW  | 229 | 229 | 2 (.mp4) |
thumbnail.jpeg present for EVERY slide (38/38, 48/48). Embedded movies exported as SEPARATE
media files; the DSK video is KPF slide 11 = deck slide 13, as reported.
header.json: autoplayTransitionDelay 5, autoplayBuildDelay 2, creator "Apple Keynote 15.3.1",
major/minor 1/2, fonts list (DSK 25, GW 9).

Events carry no top-level type/name - those live on the nested `effects` tree.
| deck | slides | events | build stops |
|---|---|---|---|
| DSK | 38 | 45 | 7 |
| GW  | 48 | 58 | 10 |

Effect name x count (both decks):
| type | name | n |
|---|---|---|
| transition | apple:dissolve | 44 |
| transition | none | 39 |
| transition | apple:magic-move-implied-motion-path | 3 |
| buildIn | apple:dissolve | 6 |
| buildIn | apple:bc-appear | 5 |
| buildIn | apple:movie-start | 3 |
| buildIn | renderMovie | 3 |
| buildIn | com.apple.iWork.Keynote.KLNSparkle | 3 |
| buildIn | apple:fade and move | 3 |
| buildIn | com.apple.iWork.Keynote.LineDraw | 3 |
| buildIn | com.apple.iWork.Keynote.LineDrawForLine | 3 |
| buildIn | apple:appear | 2 |
| buildIn | apple:dissolve character | 2 |
DSK has only `transition: none` (38); all dissolves and Magic Moves are GW's.

## 3. Cross-check vs iwa_builds.deck_builds - agrees
Aligned KPF slideList to the deck's NON-SKIPPED slides (iwa_runs.slide_order gives the flag).
| deck | compared | agree | disagree |
|---|---|---|---|
| DSK | 38 | 38/38 | 0 |
| GW  | 48 | 46/48 | 2 |
Both GW disagreements are the same explained mechanism (KPF emits a LineDrawForLine companion
per LineDraw build):
| deck slide | KPF idx | IWA builds | KPF effects | names |
|---|---|---|---|---|
| 7  | 4  | 4 | 6 | LineDraw x2, LineDrawForLine x2, dissolve x2 |
| 37 | 29 | 2 | 3 | LineDraw x1, LineDrawForLine x1, dissolve x1 |
Counting the pair as one build gives 48/48 and 38/38 - 100% agreement.

## 4. Fidelity - the main.js name grep is a MISLEADING proxy
Raw name grep scores 4/13. That number is wrong: main.js only string-names its ~48
SHADER-backed effects (apple:3D-cube, apple:action-*, KLN*, BLT*, BUK*, magic-move-...).
Everything else is replayed generically from explicit CA keyframes baked into the slide JSON.
Measured properly (baked `animations` present OR named in main.js):
| type | name | n | baked keyframes | in main.js | renderable |
|---|---|---|---|---|---|
| transition | apple:dissolve | 44 | 44 | no | yes |
| transition | none | 39 | 39 | yes | yes |
| transition | apple:magic-move-implied-motion-path | 3 | 3 | yes | yes |
| buildIn | apple:dissolve | 6 | 6 | no | yes |
| buildIn | apple:bc-appear | 5 | 5 | no | yes |
| buildIn | apple:movie-start | 3 | 3 | no | yes |
| buildIn | renderMovie | 3 | 0 | yes | yes |
| buildIn | KLNSparkle | 3 | 3 | yes | yes |
| buildIn | apple:fade and move | 3 | 3 | no | yes |
| buildIn | LineDraw | 3 | 3 | no | yes |
| buildIn | LineDrawForLine | 3 | 3 | no | yes |
| buildIn | apple:appear | 2 | 2 | no | yes |
| buildIn | apple:dissolve character | 2 | 2 | no | yes |
SUPPORTED 119/119 effect instances; 0 not found.
CORRECTION 2: Magic Move is NOT a bare declaration here - its effects carry real keyframes
(the earlier `animations: []` observation does not reproduce on these decks).

## 5. Player in the dashboard - works, embeds cleanly, drives by hash
Served DSK-html/ with `python -m http.server 8791` (not 8765); opened in the Browser pane.
- Renders correctly; stepped ~18 slides matching the deck. Canvas 1920x1080.
- ZERO player console errors.
- Clicks advance slides and fire builds (apple:appear on slide 3, KLNSparkle slide verified).
- NO public JS API: main.js is a minified IIFE, the show controller is module-scoped.
  jumpToSlide( / advanceToNextBuild( / goBackToPreviousBuild( exist (9/7/5 hits) but are NOT
  on window (only local_header, local_slide, local_pdf, requestAnimFrame are).
  Synthetic MouseEvent dispatch does NOT advance it.
- BUT the player publishes and accepts location.hash as the slide index: it writes #<n> on
  every advance, and setting the hash on an embedded frame is honoured and retained.
  Usable JS-free control channel + real key/click events for per-build stepping.
- SAME-ORIGIN IFRAME EMBED WORKS. No frame-busting (top.location, window.top, parent.location,
  frameElement, X-Frame: all 0 hits). index.html references only assets/player/main.js relative.
  Only network hosts in main.js are youtube.com/embed + player.vimeo.com (web-video
  placeholders) and w3.org namespaces. Parent could read the child document and canvases.
- ENV CAVEAT (known): with the Browser pane HIDDEN, rAF is frozen (1 frame / 800 ms) although
  document.hidden === false, so the player wedges after one queued advance. Overriding
  window.requestAnimFrame (which main.js itself assigns) with a setTimeout(...,16) shim fully
  unfreezes it (31 pumped frames / 500 ms) and clicks then advance normally. Does not arise in
  a visible pane or headless Chromium. Intra-build frame smoothness could NOT be sampled
  (shader builds draw to a context getImageData could not read), so "builds animate smoothly"
  is verified qualitatively, not frame-by-frame.

## 6. Text extractability - real text, not outlines
pypdf extract_text() on per-slide PDFs returns genuine Unicode incl. verse numbers, reference
labels and CJK runs.
| deck | first 8 slides: pages | pages with extractable text |
|---|---|---|
| DSK | 22 | 19/22 (86%) |
| GW  | 46 | 23/46 (50%) |
Samples: "1 In the beginning God created the heavens and the earth.", "Genesis 1",
"MATTHEW 18|19 |Again, truly I tell you that ...". Text-free pages are pure-image textures.
(pypdf warns fontTools is absent for CFF Type1 encoding; extraction still succeeded.)
BETTER THAN THE PDF: every slide JSON carries an `accessibility` array of
{text, targetRectangle{x,y,width,height}} - 180 items across DSK, 418 across GW - i.e.
per-object text WITH layout rectangles from Keynote's own render, no PDF parsing, no OCR.

## Recommendation
(a), scoped - build the dashboard build-preview on KPF, and treat text as a bonus, not yet as
an OCR replacement. The numbers are good on every axis that matters: the export is cheap and
reliable (20 s / 56 s, one AppleScript call, no options tuning, no new Python dependency), the
build inventory it reports matches the repo's own offline deck_builds reader 100% once the
LineDraw/LineDrawForLine pairing is accounted for, and every one of the 119 effect instances on
these two real decks is renderable - either as baked CA keyframes or as a shader main.js names,
Magic Move included. Apple's player drops into the dashboard as a same-origin iframe with no
frame-busting, no absolute paths, no console errors and a working location.hash slide-address
channel, so a build-preview pane is a few hours of glue rather than a port. The honest costs are
three: the export SILENTLY OMITS SKIPPED SLIDES (5 of 43, 15 of 63 here), so every KPF index
must be mapped through the deck's skip list or {skipped slides:true} must be proven; the GW
export is 637 MB for a 669 MB deck, fine on demand and unattractive as a cached artefact; and
there is no public JS API, so per-build stepping must be driven by synthesised key/click events
(synthetic MouseEvents do not work) plus the hash. Stage PNGs stay the shipping route exactly as
framed - KPF's value is the thing PNGs cannot give: the motion between stages, in the dashboard,
for free. The accessibility text-plus-rectangle arrays are the sleeper finding and deserve a
separate spike against the checker's OCR ground truth before anyone claims they replace it.
