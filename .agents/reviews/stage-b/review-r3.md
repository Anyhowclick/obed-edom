# Stage B review r3 — Opus 5.5 high, commit 51ee3be2

Round 3 → fold all severities (owner folds mediums and lows through r5). Scope: `git diff 9bf912b6 51ee3be2`.
Reviewer confirmed: targeted suites green (129 probe/contract/decks feed+hold+instrument+pin). I also re-ran the new
Node end-to-end test with its verdicts printed, and checked a fully fed move through `verdict_records` (results below).
Frozen-block additions (writable page API, per-draw `decoderFor`, `src.objectId` keys, install order) are in the plan
at lines 206–207 and are consistent with the instrument.

## r2 findings
| r2 | Status | Evidence |
|---|---|---|
| MA artworkAbove vacuous | **closed** | `mm_feed_instrument.py:336-344`: read only after the move's frames close; a probe-only `pointer-events:auto` style around the hit test; `indexOf(v)`; absent → null → None. Unit in the Node test (`a` red, `b` green, `c` None). Residual: Low 3. |
| MB poster window | **closed** | `:483-499` resume = first play after the last frame; pause = last pause with no play between; clock still across move rows. `score_poster_hold :696-747`; test `test_poster_pairing_uses_the_move_anchored_hold_pause`. Residual: Medium 3. |
| MC self-report inputs | **partially** | Own spies replace telemetry (`:194-202` uploads, `:322-327` seam claim/stand-down, `:72` departures). The gap limit is now a constant (`:13,:610`), and install-before-navigation is in place (`probe:1841-1858,4422,4574`). But the new derivations carry Majors 1–3, and the managed-OBS path never installs the instrument (Medium 1). |
| Med 1 dSep | closed (`:245-246,:588-594`; margins as Python constants `:15-17,:682`) |
| Med 2 late finalize | closed (`:279-282`; contract `late` `contract:733-734`) |
| Med 3 arm-wide contract | **partially**: `kind:null`, `mode:"unavailable"` (+reason), and serial-null media filtering are done (`:350`, `contract:815-817`). The new `departures` stream reintroduces the problem: Major 3. |
| Med 4 label aggregation | closed (`:638-652`, test) |
| Med 5 partial census | closed (`:471-480`, `:619-620`, `:633-634`) |
| Med 6 hold window | closed (`:516-525`) |
| Med 7 missing → red | closed (`:602-606`, `:667-670`) |
| Med 8 pre-feed stand-down | closed for `posterHold` (`:738-743`); `holdFrame` now scores red, against a registered `None` (Low 1) |
| Med 9 instrument cost | closed (small reusable canvas, ring windowed, planned-ordinal poster, p95 reported), but the source-rect crop introduces Major 4 |
| Med 10 untested JS | **partially**: the Node test runs `INSTRUMENT_JS`, but its fakes mask Majors 1, 2 and 4, and it asserts only `is not None` (Medium 2) |
| Med 11 frozen gaps | closed in the plan; one gap remains (Medium 4) |
| Low 1 tamper target | **partially**: `--feed-tamper-scene` added, but `run_gates.sh` names scene 8, and a non-matching scene is a silent no-op (Medium 5) |
| Low 2 variant sha | closed (`probe:1734-1759`); residual in Low 4 |
| Lows 3–12 | closed (`scene()` hash only `:31-33`; prefers `current+1` `:106`; dropped callback → None `:728-729`; overflow `:67,:663,:694`; floor detail `:557-558`; no `getError`; draw-table `layerSize` `:224`; dead code gone; visits `:406-415`; M3 test; pin test moved) |

## Blocker
None.

## Major
1. **(new class: unit mismatch in the instrument)** `mm_feed_instrument.py:195-201`. A feed upload (video source)
   overwrites the texture's recorded `size` with the video's intrinsic size, keeping only the ordinal. The frozen install
   order means every fed draw now snapshots the texture after the module's upload. So `bound` (`:434-437`, which needs
   `size == feed.from.size`) is false whenever the movie's intrinsic size differs from the leaf (Alpha leaves are
   714×402 etc.). The effects:
   - every `feedLive` and `holdFrame` is None ("bound textures were unavailable");
   - `feed_interval` is None, so no GL-interval exemption;
   - continuous and one-shot arms alike.

   The Node test's 100×100 fake video hides this.
   Fix: on a video upload, keep `ordinal` and `size` from the texture's regular upload and add
   `uploadedSize: [w, h]` and `video: true`. Take `leafSize` for captures from the regular size. Add a test case whose
   video is 160×90 against a 100×100 leaf.
2. **(new, false red on every working feed)** `:452-458`. `move_uploads` keeps uploads with
   `times[0] <= t <= times[-1]`, where `times` are row `t` = each frame's `clear` time (`:227`). Each frame's upload
   happens after its own clear, so the last frame's upload is always excluded. Then `wanted_frame_ns ⊄ fed_frame_ns`,
   `continuousCoverage` is False, and `feedLive` is **red** ("continuous upload coverage is incomplete"). Reproduced: four
   fully fed frames with uploads at `clear + 3 ms` → `framesFed 3`, `continuousCoverage False`, verdict False. The Node
   test's last frame is deliberately unfed and the hand-built fixture uses `upload.t == frame.t`, so neither catches it.
   Fix: select by frame identity — `move_uploads = [u for u in entry_uploads if u["frameN"] in move_frame_ns]`, where
   `move_frame_ns = {f["n"] for f in move_frames}`; compute gaps from those uploads' `t`. Add a fixture with
   `upload.t = frame.t + 3`.
3. **(closed class Med 3, reintroduced: one shape miss voids the arm)** `:72` with `contract:803`. A `departures` row
   takes `serial` from the media attribution. That is null whenever the hold pause precedes the move's context creation:
   the stash → `scheduleRemount` departure path. `wrap()` patches null serials in `S.media` only (`:184`), never in
   `S.departures`. The contract requires `_id`, so every verdict of the arm is None. `verdict_records` explicitly expects
   this case (`:443`, `serial in (None, serial)`).
   Fix: patch `S.departures` alongside `S.media` in `wrap()` (same `entryId`/`atScene` rule); at `report()`, keep
   unpatched departures and have the contract accept `serial: _id_or_null` for `departures`. Add one Node case where the
   pause precedes `getContext`.
4. **(new: sampling outside the intended footprint)** `capture()` `:141-142`. The 9-argument `drawImage` source rect is
   in the source's intrinsic pixels, but `sx = uv*size - 12` uses the leaf texture size (and the counter strip uses
   `(24+40j)/1920*size[0]`). For a 1920×1080 decoder and a 714×402 leaf, the "0.5" patch samples about UV 0.19. The ring
   is captured before the move with `size = feed.from.size` (`:85`), so the ring vectors and the GL patch at the same UV
   are different regions: `holdMatch` compares unrelated pixels (false red or, by chance, a false green). On D7, the
   counter strip is read at about a third of its position, the reference counter is null, and the read silently falls
   back to `alpha`. The fake 2D context ignores the source rect, which hides this.
   Fix: map UV with the source's intrinsic size —
   `iw = source.videoWidth || source.naturalWidth || source.width`, likewise `ih`. Then `sx = uv[0]*iw - 12*iw/size[0]`
   (keep the footprint in leaf texels), and the strip `x = (24+40j)/1920*iw`, `y = 24/540*ih`. The fake 2D context must
   honour the source rect.

## Medium
1. **(new)** `scripts/managed_obs_qualify.py:527,642-659`. The managed-OBS host is built without
   `install_feed_instrument_before_navigation`, and `drive_and_sample` no longer evaluates `INSTRUMENT_JS` (`probe:1878-1886`).
   So `window.__obedMmFeedProbe.configure` throws and both Q6 arms (`feed`, `feed-off`, `:1965-1966`) crash.
   Fix: call `install_feed_instrument_before_navigation(host, ctx["feedFacts"])` before `host.start()` in `run_session`
   when feed facts are present. In `drive_and_sample`, raise a clear error if the probe object is absent.
2. **(B1/Med 10 residual: the end-to-end test fakes around the reads)**
   `tests/test_live_continuity_probe.py` `test_instrument_js_runs_fake_gl_end_to_end…`. With its verdicts printed, all three
   entries score `feedLive` **False** ("coverage incomplete"). The reads would be red too: `dVideo 101.6 > dPoster/2 100.8`,
   because the fake `readPixels` returns an x-gradient unrelated to the uploaded source. `noRiderAboveCanvas` is False
   (visible fakes). The test asserts only `is not None`. Labels and the late-frame marking are genuinely exercised.
   Fix: make the fake GL return, at each projected UV, the pattern of the last source uploaded to the bound texture.
   Give the video an intrinsic size different from the leaf, honour the 2D source rect, and feed every frame including
   the last. Then assert `feedLive True`, `noRiderAboveCanvas True` (opacity 0), and `labelsOverFeed True` on that run, plus
   `feedLive False` on a poster-only run (no video uploads, mode from a claim). Also cover the `bootstrap` setter path
   (`:303-307`), which no test exercises.
3. **(recurring inverse class: missing evidence scored red)** `score_poster_hold :696-697`. A missing pause row scores
   red whenever the clock is readable, even when every move row shows a paused, constant clock (e.g. the pause row was
   dropped by attribution `:67`).
   Fix: `holdPauseMissing` → red only if `clockStill is False`; otherwise None.
4. **(item 3 gap)** `armSeam` (`:322-327`) wraps `feed.claim`/`feed.onStandDown` on the seam object at the first rAF. A
   module that caches `const claim = seam.feed.claim` at load bypasses the spy. That means no claim rows, mode
   `unavailable`, and every continuous verdict None.
   Fix: add to the frozen WS-F block: "the module calls `__OBED_P2_PRESERVE__.feed.claim`/`.onStandDown` by property lookup
   at call time, never caching them".
5. **(silent no-op control)** `scripts/run_gates.sh:118`. `ordinal --feed-tamper-scene 8` names the full Alpha plan's
   `@8` restart: the fed scenes are 10/12/14 (`alpha_dsk_repaired_full`). `tampered_feed_ordinal(8)` patches nothing and
   raises nothing (`probe:1701-1712`), and the JS after-feed loop waits forever on a non-matching scene (`:308-320`). The
   control runs untampered.
   Fix:
   - correct the scenes to fed boundaries for the plan's ordinals;
   - raise in `tampered_feed_ordinal` when no boundary was patched;
   - record `tamper.applied` in the report and score the arm None when it is false.

## Low
1. Registration `ordinal → holdFrame: None` (`probe:355`), but a pre-feed stand-down now scores `holdFrame` red: target
   is the stand-down pause frame and the GL shows the baked poster. Register `False` (it "cannot pass" either way).
2. Visits: `claims` carry no serial and unpatched `departures` match every visit (`:441-443`), so a claim in visit 1 sets
   visit 2 to `continuous`. The visits wrapper returns no `interval`/`posterHold`, so `score_carry` applies DOM checks
   through every visit's GL interval (`probe:3577-3582`), which is a false red.
   Fix: stamp `serial` on claims and stand-downs from the decoder's current move. Have the wrapper return per-visit
   intervals for `score_continuity`, or score multi-visit carries None until it accepts several intervals.
3. `artworkAbove` (`:344`) counts any node above `v` that overlaps the fact rect. With pointer-events forced on, a
   transparent full-stage overlay now counts as artwork.
   Fix: require the node's rect to match the fact rect within 2 px (the artwork element itself, or an ancestor whose rect
   matches).
4. The variant `js_sha256()` (`probe:1747-1750`) is the sha of the `<script>` tag, not the JS bytes (not comparable to
   the shipped sha). It also raises when `_mm_feed_info` runs on a path that never built the script (notApplicable or
   unavailable renderer), which crashes `start()`.
   Fix: hash the JS body and return the shipped sha until a script is built.
5. `MAX_INTER_FEED_GAP_MS = 50.0` (`:13`) has no provenance comment. Cite the paint-coverage rule it encodes, or mark it
   provisional like the floors.
6. `install_feed_instrument_before_navigation` monkeypatches the private `_install_placement_channel`
   (`probe:1851-1858`). Prefer a host constructor hook (`pre_navigation_scripts=`) so the ordering survives host
   refactors.

## Scorer inventory — how missing/ambiguous input scores (after this fold)
| Scorer | Missing / unreadable | Ambiguous | Partial coverage | Problem |
|---|---|---|---|---|
| `score_feed_live` | mode None/unavailable, reads, bound, < 2 presented → None | dSep < floor → None | 3 reads by design | coverage window drops the last frame → **red on working feeds** (Major 2); bound false on real videos → None (Major 1) |
| `score_no_rider_above_canvas` | coverage false / unreadable → None | — | coverage enforced | — |
| `score_labels_over_feed` | coverage false → None | low spread / null slope → None unless a readable red | coverage enforced | — |
| `score_hold_frame` | bound, target, reads, margin, overflow, re-upload census → None | margin < constant → None | fixed first/middle/last of window | ring/patch regions differ (Major 4); pre-feed stand-down red vs registered None (L1) |
| `score_poster_hold` | fields, overflow, dropped callback → None | tolerance → None | clock across all move rows | missing pause → **red** when clock readable (Medium 3) |
| `score_artwork_above` | absent `v` / no rows → None | — | rows only where facts intersect | any overlapping node counts (L3) |
| `verdict_records` | mode unavailable → per-entry None | — | visits per context | null-serial departures → **arm-wide None** (Major 3); visit mode leakage (L2) |

Verdict: not ready. The fold closes the r2 classes, but it introduces four instrument defects: video size overwrites the
binding, coverage drops the last frame, null-serial departures void the arm, and captures crop in the wrong coordinate
space. Together they keep every positive feed/hold arm from going green on real decks. The end-to-end test's fakes hide
all of them except Major 3, which none of its runs reaches.
Counts: blocker 0, major 4, medium 5, low 6.
