# Stage B review r2 — Opus 5.5 high, commit 9bf912b6

Round 2 → fold all severities. Scope: the r1 fold (`git diff 26ab2213 9bf912b6`); WS-F/WS-P absence not reported.
Reviewer confirmed: targeted suites green (92 probe/contract/decks feed+hold+pin, 125 js/variants/host/lc feed+stand-down
+crossing); `INSTRUMENT_JS` parses; core sha `6c687c47…` matches `js_sha256()` with no stale mirror of `49574c94…`; the
full repaired fixture derives fed bridges @10/@12/@14 (draws 3/4/2+4, layer size == `feed.from.size` on every fed leaf)
and pins `c9e54655…`; census exclusions are consistent. Coordinator decision checked: `ALPHA_POSTER_FLOOR = 2.5` carries
its provisional rationale at the constant (residual in Low 6 / Medium 1, not re-litigated).

## r1 findings
| r1 | Status | Evidence |
|---|---|---|
| B1 in-frame reads | **partially** | Reads now exist (same-task reference `mm_feed_instrument.py:228`, counter/Alpha `:270-280`, patchInside/covered `:165-169,:253-258`, rVFC ring `:77-82`, hold matching `:259-269`). But no test executes `INSTRUMENT_JS`; the new report-shaped test (`tests/test_live_continuity_probe.py:11768`) is hand-built and feeds non-frozen telemetry (`maxInterFeedGapLimitMs`), masking Major C. See Medium 10. |
| M1 per-move scoping | **partially** | rows/riders/labels/artwork carry `entryId`+`serial`+`atScene` and are filtered per move (`:386-424,:495-499`). Media is scoped by `atScene` but not by the move's time window → Major B. Repeated visits (loops/go-back) make `len(moves) != 1` → every visit None (Low 10). |
| M2 frame finishing | **closed** for the main path (in-task finalize at `draw === drawCount` `:235`, report sorted `:337`, pre-finish on new context `:182`); the fallback path introduces Medium 2. |
| M3 fact lookup | **closed** | `probe:1626-1634` keys `feed_draws[atScene]` and `artwork_above[toPlayer]` filtered by `dstObjectId` (matches `lc:2205,2217`). No regression test (Low 11). |
| M4 one binding source | **closed** | Probe tampers `_continuity_plan_script` (`probe:1694-1712`), test `:11836`; host passes no runtime to the builder (`host:1115`). |
| Med 1 held+1 | **closed** | `score_poster_hold` uses media-time step ± half frame, tolerance < half frame (`:642-654`); tests updated. Edge in Low 4. |
| Med 2 feed-off order | **closed** (behaviour) | Mode checked before reads (`:512-517`); residual dependence on self-reported mode tracked in Major C. |
| Med 3 stand-down before departure | **closed** | `js:2305` drops the claim and records only; departure then pauses + `once` (test `test_claim_…[before-departure]`). |
| Med 4 interfaces | **closed** for host/probe (static `variant_script`, keyword builder, no `inspect`), **not** for the instrument (Major C, Medium 11). |
| Med 5 floor provenance | **closed** per coordinator decision (comment at `:8`); see Medium 1 for what Phase 0 must re-bank. |
| Low 1 stand-down key | closed (`js:2295,2304`) |
| Low 2 redundant guard | closed (`js:1162`) |
| Low 3 host fallbacks | closed (`host:1138`, `host:1173-1174`; test asserts `(None, None)` and no version/sha) |
| Low 4 renderer pin | closed (`host:171-173`, `QUALIFIED_SNAP_MAJORS`) |
| Low 5 R11 lift test | closed (`tests/test_live_continuity.py` `r11` param) |
| Low 6 R test 1b | closed (`second_action="bridge"` param) |
| Low 7 take test | closed by narrowing the claim (call order only, renamed) |
| Low 8 Alpha sha pin | closed (`test_repaired_full_alpha_runtime_plan_is_pinned`) |
| Low 9 probe indirection | closed (`feed_host_kwargs`, aliases, no `"armed"` inference) |
| Low 10 crossing vs glReplay | closed (`lc:2112-2127`, crossing decided first) |

## Blocker
None.

## Major
- **MA (new class: vacuous verdict)** `mm_feed_instrument.py:331-332` — `artworkAbove` is true by construction. Every
  core remount sets `pointer-events: none` on the decoder (`js:1199,1433,1680,1770,1818`), so `elementsFromPoint` never
  returns `v`; `findIndex(... node.contains(v) ...)` then matches the first *ancestor* of `v` (`#body` for an on-stage
  decoder), which is always below any authored layer at that point → `vi > 0` → green. The registered
  `settle-on-stage → artworkAbove red` control cannot go red, and on the real path the verdict cannot catch a decoder
  settled above the labels. It is also read at the first visible frame of the dst instance, not after settle.
  Fix: in `settledArtwork`, read only after the move's context has finished (first rAF with no live frame for the entry's
  serial); wrap the hit test in a probe-only, synchronous override — insert `<style>*{pointer-events:auto!important}</style>`,
  call `elementsFromPoint`, remove it in `finally`; set `vi = stack.indexOf(v)` (no containment fallback); `vi < 0` →
  `artworkAbove: null` (scored None); `artworkAbove = stack.slice(0, vi).some(n => !n.contains(v) && rectsOverlap(n, artworkRect))`.
  Add a Node/jsdom-free unit with a fake `elementsFromPoint` covering on-stage (red), in-layer (green), and `v` absent (None).
- **MB (closed class M1, residual: evidence window not anchored to the move)** `mm_feed_instrument.py:453-473` — the
  poster record pairs the *first* `pause` of the move with the *first* `play` after it. The core's departure sequence is
  player teardown pause → stash keep-warm `play()` (`js:978-981`, before the flag is set) → `posterHold` pause → settle
  play (modelled by `test_claim_…[before-departure]`: `plays: 1` then paused). The record is therefore built on the
  departure blip: `settleCurrentTime` is the keep-warm play's clock and `firstAfter` is the next frame after it. Under
  `no-pause` the decoder runs through the move yet `posterHold` scores green (step = 1 frame, clock still); when the player
  only detaches (no JS `pause()`), `no-pause` has no pause row → None. Either way the registered `no-pause → posterHold red`
  cannot go red, and a green `posterHold` waives the carry's stall/advance rules (`probe:3578`, `:2601-2602`). The same
  first-pause choice sets the departure `holdFrame` target (`:488`) one frame early whenever a frame presents between
  keep-warm play and the hold pause (false red).
  Fix: anchor on the move. `first_t/last_t` = first/last frame `t` of `move_frames`; `resume` = first `play` with
  `t > last_t`; `pause` = last `pause` with `t < resume.t` and no `play` between them; departure mode additionally requires
  `pause.t <= first_t` (else red if readable). Clock stillness = every row from the pause onward has a decoder read with
  `paused` true and `currentTime`/`presentedFrames` constant (any missing decoder read → None, any change → red);
  held+1 from that pause's `mediaTime` to the first `videoFrame` after `resume`. `lastPresentedBeforeDeparture` = that
  pause's `presentedFrames`. Test: media `[pause(player), play(keep-warm), pause(hold), play(settle), videoFrame]` scores
  green on the hold pair; the same without `pause(hold)` and with rows showing `currentTime` advancing scores red.
- **MC (contract vs frozen WS-F)** `mm_feed_instrument.py:411-416,445-447,462,482-494` — verdict inputs come from module
  self-report, contrary to the frozen block ("WS-G's instrument derives every verdict input … never from module
  self-report"), and two of them are not in the frozen `entries` fields: `maxInterFeedGapLimitMs` and `lastUploadedFrame`.
  Against a module built to the frozen spec: `feedLive` with a continuous expectation is always None at `:561-562` (limit
  unreadable), so `feed-on` / `from-only-single` / the fed positive control can never be green; `standDown`
  `holdFrame`/`posterHold` are always None (`advancedDecoder` false, target None), so the registered `after-feed`
  (holdFrame/posterHold green) and `ordinal` (posterHold green) expectations are unreachable; `continuousCoverage`,
  `successfulFeed`, `reuploadAfterStandDown` and the record `mode` itself are telemetry. Root cause: the instrument is
  evaluated after page load (`probe:1836`), so its `getContext` wrapper is outermost and never sees the module's uploads.
  Fix: (1) install `INSTRUMENT_JS` before page scripts (CDP `Page.addScriptToEvaluateOnNewDocument` before
  `LiveOutputHost.start` navigates) so its wrapper is innermost and the module's saved GL entry points are the
  instrument's spies; freeze this order in the plan's WS-F block. (2) In `texImage2D`, classify a source that is an
  `HTMLVideoElement`/`VideoFrame` as a feed upload `{t, frameN, texture, presentedFrames, mediaTime}`; count regular
  ordinals over non-video sources only (keeps `bound` matching D's ordinals). (3) Derive per entry from those rows:
  `framesFed`, `maxInterFeedGapMs` over the move's frames, `lastUploadedFrame` (`presentedFrames` of the last video upload
  into the planned texture), `reuploadAfterStandDown` (any video upload after the stand-down time). (4) Take the gap limit
  from a Python constant under the paint-coverage rule, never from evidence. (5) Derive the record mode from the core
  seam, not the module: spy `__OBED_P2_PRESERVE__.feed.claim` (true → continuous) and `.onStandDown` (→ standDown with
  `t`), and the core's hidden-ride hold (→ departure). Keep module telemetry only as `module` diagnostics. Replace the
  hand-built fixture's `maxInterFeedGapLimitMs` accordingly.

## Medium
1. **(new class: separation measured on the outcome)** `mm_feed_instrument.py:247-250,277-278` — the Alpha patch is
   chosen by maximum `dPoster = d(final GL, poster)` and the floor is applied to that same quantity (`:540`). When the
   feed is broken the GL shows the poster, `dPoster ≈ 0` everywhere, and the read is "ambiguous" → None instead of red;
   `holdMatch` reuses that outcome-selected patch, so the kill-switch null can fall under its margin → None, not red.
   Fix: compute `dSep = d(reference, poster)` (GL-independent) per safe UV; choose the UV with the largest `dSep`; record
   `dSep`; the floor applies to `dSep` ("the poster/live separation"); keep green iff `dVideo <= dPoster/2`. Phase 0
   re-banks the floor on `dSep`. Also move `requiredMargin` (6.0 / 1.0, `:262,:268`) to Python constants applied by
   `score_hold_frame`, not trusted from evidence (provisional, cited like `ALPHA_POSTER_FLOOR`).
2. **(new, edge of M2 fix)** `:182,:209,:240,:285,:322` — `finishFrame` calls `finalizePixels` when the frame never
   reached `drawCount` (new context, next `clear`, rider tick, context loss). Those reads run in a later task against a
   presented (cleared) drawing buffer: Alpha reads of zeros go red, label `after` of zeros gives slope 0 (red), and
   `holdMatch` picks the darkest candidate (rare false green when the target is darkest). Fix: pixel reads only in the
   last-draw task; `finishFrame` on an unfinalized frame sets each row `feedRead {patchInside:false,
   coveredByLaterDraw:false, kind:null, late:true}`, `holdMatch: null`, drops `F.under`; contract allows `kind: null`.
3. **(new class: one shape miss voids the arm)** `contract:720,797,770` — (a) the unreadable branch (`:273`) emits
   `feedRead` without `kind` → `mmFeed.feedRead.kind:missing`; (b) `verdict_records` sets `mode: None` when module
   telemetry is absent/unreadable (`:414-416`) → `feedVerdict.mode`; (c) a media row attributed by candidates whose move
   never creates a context keeps `serial: null` → `_id`. Any one makes `score_verdicts` return None for every verdict of
   the arm, P2/restart/retire included (`probe:4168-4170`). Fix: (a) as Medium 2; (b) record `mode: "unavailable"` with a
   reason (contract-accepted) and score that entry None in `score_under_artwork`; (c) drop unpatched rows at `report()`.
4. **(closed class, recurring: aggregation masks reds)** `score_labels_over_feed :585-589` returns None at the first
   unreadable or low-spread row, so a later red row (MM-opacity-off) is hidden; a box fully covered by later quads in one
   frame (`slope: null`, `:175`) voids the verdict. Fix: per row classify readable-ok / readable-red / inconclusive
   (slope null or spread < 24); False if any readable-red; None if no readable row or any inconclusive; True otherwise.
5. **(recurring class: partial census counted green)** `score_no_rider_above_canvas :569-577` and
   `score_labels_over_feed` score whatever rows exist; a frame where `decoderRead` returned null (e.g. after the
   after-feed tamper nulls `decoderFor`) or a label draw whose quad was missing simply has no row. Fix: in
   `verdict_records`, count the move's frames and require one readable rider row per entry per frame (and one label row
   per label draw whose quad overlaps the fed quad, per frame); any gap → record `coverage: false` → None.
6. **(recurring class)** `verdict_records :436-440` — hold reads are first/middle/last of the rows that *have* a
   `holdMatch`, not of the move's frames, so an unreadable first draw silently promotes a later frame to "first"; and the
   window ignores stand-down, so the after-feed arm's "first" read is a live-fed frame ≠ last upload (false red against
   the registered green). Fix: window = move frames (departure) or frames with `t >= standDown.t` (standDown); take the
   first, middle and last frame of that window; a missing `holdMatch` on any of the three → None.
7. **(recurring class, inverse: missing evidence scored red)** `score_feed_live :552-556` — no finite
   `presentedFrames` (decoder unresolved, rVFC not yet fired) → `advancing` False → red. `score_hold_frame :606-607` —
   `reuploadAfterStandDown` None → `is not False` → red. Fix: fewer than two finite `presentedFrames` → None; red only on
   ≥ 2 equal readings across the interval. `reuploadAfterStandDown is True` → red, `None` → None.
8. **(edge)** `score_poster_hold :657-659` with `verdict_records :463` — a stand-down before any successful feed
   (the `ordinal` control) is `standDown` mode and needs `lastUploadedFrame`, so the registered `ordinal → posterHold
   green` is unreachable even after Major C. Fix: when `successfulFeed` is false, score the stand-down hold like a
   departure hold from the stand-down pause (clock still, no seek, held+1 at resume); keep the discontinuity branch only
   for post-feed stand-down.
9. **(new, unmeasured — instrument perturbs what it measures)** `:77-82,:131-134,:203,:228` — every rVFC of every armed
   decoder for the whole run does a full leaf-size `drawImage`+`getImageData` into a new `willReadFrequently` canvas; every
   fed draw does another; every non-video upload (backgrounds included) is captured at full size in the move's first
   frame. This can inflate the inter-feed gap / first-feed hitch and drop rVFC callbacks (held+1 false reds).
   Theoretical until measured. Fix: one reusable small canvas per entry; capture only the 9 UV footprints and the counter
   strip via source-rect `drawImage`; ring capture only while the entry's source slide is idle at `atScene-1` or its move
   is live; poster capture only for the planned `from`/`to` ordinals; report p95 callback cost; Phase 0 compares the gap
   with the instrument on/off.
10. **(B1 residual)** No test runs `INSTRUMENT_JS`; every scorer test is synthetic. Fix: one Node test with a minimal fake
   WebGL context (recorded uniforms, `readPixels` returning a known pattern), fake video with rVFC and `drawImage`
   source, and fake seam: install → configure → clear/uploads/draws × `drawCount` → `report()` → `contract.mm_feed_report`
   clean → `verdict_records` → `feedLive`/`labelsOverFeed` non-None, plus one frame finished without its last draw is
   marked unreadable (Medium 2).
11. **(item 3 gaps — add to the frozen WS-F block)** (a) `window.__OBED_MM_FEED__` must be a plain writable object
   (the kill switch replaces `once`, `:299`; `Object.freeze` would make `configure` throw in strict mode); (b) the module
   resolves `seam.feed.decoderFor(objectId)` at every fed draw (the after-feed tamper replaces it, `:312`; a cached
   decoder makes the control a no-op and `feedLive` green); (c) `entries` is keyed by `src.objectId` (instrument `:411`,
   core `once(boundary.src.objectId)` `js:1170`); (d) the install order of Major C.

## Low
1. `--feed-tamper after-feed` tampers the first fed entry seen (`:305`) and `ordinal` the first fed boundary
   (`probe:1702-1705`); Q3 needs 8→9 and 9→10. Add `--feed-tamper-scene N` and filter on `atScene`.
2. `injected_feed_variant` (`probe:1717-1739`) patches the module attribute and the host still reports the shipped
   module sha for a variant run; once the host imports statically the patch is a no-op. Mirror `injected_core_variant`:
   patch the host's binding and report the variant sha.
3. `scene()` (`:26-29`) reads `snap.scene`, which `__obedLive.snapshot()` does not expose (`sceneId`,
   `live_runtime.py:278`); it always falls to the hash. Use the hash only (core `currentHashNum` semantics). Edge:
   `resolveAtScene` prefers `current` over `current+1`, so a post-arrival GL build context on a fed destination would be
   attributed to the move (two contexts → None); prefer `current+1` when the hash reads `atScene-1`.
4. (edge) held+1 (`:651-654`): a dropped rVFC callback after resume (`presentedFrames` +2, `mediaTime` +2 frames) reads
   as a skip → false red; when the `presentedFrames` delta exceeds 1, score None.
5. Media buffer silently truncates at 20000 rows (`:63`); a dropped `seeking` row reads `seeked: False`. Record an
   overflow count in `report()` and score poster/hold None when it is non-zero.
6. Record `alphaFloor` and `provisional: true` in the `feedLive` detail so a gate table run on 2.5 is identifiable until
   Phase 0 re-banks it (on `dSep`, Medium 1).
7. `finishFrame` calls `gl.getError()` (`:286`), which clears the flags the module's stand-down check reads; ordering-
   dependent, theoretical. Drop it, or read only inside the last-draw task after the inner draw returns.
8. Projection uses `feed.from.size` as the layer size (`:227`); equal on all Alpha fed leaves, unverified for D7. Use the
   draw table's `layerSize` for projection and the texture size for texel offsets. The off-centre UV↔layer (flip)
   mapping is unvalidated (the experiment read the centre only): Phase 0 must decode the D7 counter on the positive
   control before any Alpha off-centre read is trusted.
9. Dead code: unused `fake` in `counterFromGl` (`:160`), trivial `programMatrixForRow` (`:252`), `S.holds` never written.
10. Repeated visits (Q5 loops, go-back) give several contexts per `(atScene, entry)` → `serial None` → None for every
    visit (`:386-391`). Emit one record per visit and combine.
11. M3 has no regression test: one `ground_truth_facts` case where `feed_draws` has two scenes and `artwork_above` rows
    for two objectIds at one player.
12. `tests/test_live_continuity_decks.py:13` imports the 9000-line probe for one constant; move the pin test to
    `tests/test_live_continuity_probe.py`.

## Scorer inventory — how missing/ambiguous input scores (after this fold)
| Scorer | Missing / unreadable | Ambiguous | Partial coverage | Problem |
|---|---|---|---|---|
| `score_feed_live` | record/mode/reads/progress set/usable/bound/gap → None | Alpha below floor → None unless another read red | 3 reads only (by design) | mode/coverage/gap from telemetry (MC); missing `presentedFrames` → **red** (M7); floor on outcome (M1) |
| `score_no_rider_above_canvas` | no rows / unreadable row → None | — | **green on subset** (M5) | — |
| `score_labels_over_feed` | no rows → None; **first** unreadable row voids all (M4) | low spread → None, **masks later red** (M4) | **green on subset** (M5) | late-finalized frames give false red (M2) |
| `score_hold_frame` | target/reads/phases/match → None | margin < required → None | reads chosen among readable rows, unwindowed (M6) | `reuploadAfterStandDown` None → **red** (M7); target from first pause (MB); margin from evidence (M1) |
| `score_poster_hold` | any clock/frame field → None; standDown needs `lastUploadedFrame` (M8) | tolerance ≥ half frame → None | window = first pause/first play (**false green**, MB) | dropped rVFC → red (L4); truncated media → `seeked` False (L5) |
| `score_artwork_above` | no rows / unreadable → None | — | rows only where facts intersect | **true by construction** (MA) |
| `verdict_records` (normaliser) | telemetry absent → `mode None` → arm-wide contract None (M3) | — | — | self-report inputs (MC) |

## Frozen WS-F interface consumption
| Consumer | Frozen item | Status |
|---|---|---|
| Host builder | `mm_feed_script(*, continuous, once)`; missing module → `{mode: unavailable, reason}` | consistent (`host:1115`, `:1170-1178`, test) |
| Host info | `MM_FEED_VERSION`, `js_sha256()` | consistent; variant runs report the shipped sha (L2) |
| Probe variants | `variant_script(name, script)` | consistent (`probe:123-126,1728`); patch target will break on static import (L2) |
| Probe tamper | ordinal patches `_continuity_plan_script` | consistent; instrument `runtimeFeed` reads the same served plan |
| Instrument entries | `{mode,state,reason,hold,framesFed,maxInterFeedGapMs,p95Ms}`, informational only | **inconsistent**: reads `maxInterFeedGapLimitMs`, `lastUploadedFrame`, uses telemetry as verdict input (MC) |
| Instrument hooks | kill switch replaces `once`; after-feed replaces `seam.feed.decoderFor` | rely on unfrozen module behaviour (M11) |
| Core take hook | `take(controller, scene)` from `jumpToScene_partFour` | consistent (`live_runtime.py:58`, guarded) |
| Core seam | `feed {version, decoderFor, claim, onStandDown, note}`; `once(src.objectId) -> boolean` | consistent (`js:2276-2310`, `:1166-1171`) |

Verdict: not ready — three majors (vacuous `artworkAbove`, poster window on the departure blip, self-reported and unfrozen
telemetry as verdict inputs) leave registered controls unable to go red/green. Counts: blocker 0, major 3, medium 11, low 12.
