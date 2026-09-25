# Live continuity — accept looping movies (`movie.loopMode`)

Status: **rev 2, APPROVED by the owner 2026-09-24 — OQ-1..4 all (a)** ("church decks mostly don't loop videos, but this will help expand the scope"). Rev 1 by the Opus planner; rev 2 is the adversarial critique pass
(§9 lists what changed). Read-only against `bd9ae9f4` (origin/main, #227). Parents:
`keynote_live_continuity.plan.md` (derivation + allowlist), `keynote_live_gl_replay_arming.plan.md` §2/§11 (glReplay rules
1–5), OD-2 plan `keynote_live_gl_replay_managed_obs.plan.md` (unpushed branch `claude/od-2-gl-replay-managed-obs-5bd03f`,
6 commits over main; §4 "Soak fixture", OQ-3a splice). Style: `~/.AGENTS.md`.

**Progress (2026-09-24):** WS-A/WS-B implemented (`1fb55c59`); gate commit `21944ddb` allowlists the p2-loop shas; Codex r1 folded (`229e409b`); L2 harness fixes (`96eb6d68`: armed 1→2 recorder window grounded in the take; wrap-row owner excuse for the loop seek's readyState 1). Gates: L4 == `bd9ae9f4`; L1 PASS; L2 3to4 6/6 carried, 1to2 every offset carried in ≥1 valid take, 6/16 1to2 takes INVALID (≈200 ms decoder gap ~300 ms after the press when the loop is about to wrap; below `MAX_STALL_S`) = OQ-4(a) residual. Codex r2 folded (`cc270631`), r3 clean on spec. Full suites at `cc270631`: pytest 7543 passed / 88 skipped / 1 xfailed, `test:ui` 305/305, `test:maps` pass. Gate record `.agents/reviews/continuity-loopmode/gates-r1.md`. Open: WS-C + L5 after OD-2 merges, HALL entry, PR.

## 0. Verified facts (offline; each re-verified in rev 2)

| # | Fact | Evidence |
|---|---|---|
| F1 | Keynote Repeat → Loop exports **exactly one key**, `movie.loopMode: "looping"`, on the `renderMovie` build node (`events[0].effects[0].effects[0]`, inside `apple:movie-start`), in both `<uuid>.json` and `<uuid>.jsonp` (`local_slide({"name","json"})`, payload `json` == `.json`). Absent otherwise. The movie files are **not** re-encoded: same size (19 562 437 B); they differ only in ~30 bytes of `moov` timestamps, exactly as two slides of one export differ from each other. | semantic diff `output/p2-soak-loop/html-unmodified` vs `output/gl-decks/Minimal Alpha_DSK/html`: only that key on 2 slides, plus accessibility-order noise on 5BA2/A709; `cmp -l` of the S4 movie |
| F2 | Loop is on slides **4 and 5** (`7A851F4D` / `C75DC221`, player indices 3 / 4 of **9**), not 1–2. Slides 1–2 (`08C861A1`/`0C652BEB`, the P2 1→2 glReplay movie) do not loop. S4→S5: Magic Move, `pin`, no overlap, S5 movie starts on click (`automaticPlay` false). | slideList + walk of every slide JSON |
| F3 | The loop export is the 9-slide gl-decks deck, not the P2 shape. Slides 1–3 are byte-identical to the gl-decks export; its S3→S4 is `apple:dissolve` (P2: Magic Move bridge). P2's 4-slide export (header mtime 2026-09-19) predates the 2026-09-22 18:15 save of `Minimal Alpha_DSK.key` (sha `e17ff140…`, which `p2-recovery/fingerprints-before.json` records only because fingerprints are taken at gate time with `--reuse-export`). No copy of today's source reproduces the P2 shape. | JSON shas, transition names, mtimes |
| F4 | Even with the key accepted, the loop export derives whole-deck `Unsupported`: `ambiguous 'untitled.mov' ownership at player index 7 -> 8: 2 instance(s) before, 2 after, 4 geometry-equal pair(s)` (same as gl-decks). OD-2's precheck (b) and `allow_soak_plan` therefore cannot pass on `output/p2-soak-loop`, independent of this work. | `derive_plan` with `loopMode` allowed (scratch) |
| F5 | Accepting the key leaves both P2 shas byte-identical: off `bafe26ca…`, on `6a0596da…`. A P2 export with `looping` spliced on every `untitled.mov` node and **no annex** derives the **same two shas** — it would auto-qualify unmeasured (drives §2.4). With the §2.4 annex, the committed fixture and the real P2 export spliced the §4 way both derive off `3dc67558 53692a17 8696a354 95c19296 62005a81 73f93260 7855876b fc299c5d`, on `2ba6fbed 8fc959c8 04e53d2f 21712945 230eac6d cbf90d52 2fe3a6a6 88bef924` (spaces added; indicative, the implementation pins its own and must match). | scratch derivations (rev 2 re-ran all four) |
| F6 | G2 `stats().loopMode` (`live_gl_replay_js.py:162,224`, set :1114/:1133) is the tick driver (`'rvfc'`/`'raf'`), not the movie's loop. OD-2's precheck sample field `loopMode` records the driver; its `slide1Videos` read does record `video.loop` (report-only). | code read |

## 1. Player behaviour (`main.js` sha `e9b2fad4…`, identical in P2 and loop exports)

- **Video.** One call site, `animateEffect` for `renderMovie`: `o = UC.movieCache[objectID+"-video"]`;
  `"loopMode" in C && (C.loopMode === "looping" || C.loopMode === "loopBackAndForth") && o.setLoop(true)`, then volume,
  `startMovie()`. `xB.setLoop(A){this.element&&(this.element.loop=A)}` ⇒ native `HTMLVideoElement.loop` on the element whose
  DOM `id` is `movieId` = `objectID+"-video"`. No own seek: the browser's loop restarts the file (`ended` stays false, no
  `ended` event; `currentTime`/rVFC `mediaTime` drop to ~0). The player listens to none of that; `loop` is never set back
  to `false`. `handleMovieDidEnd` sets `isEnded` only when `!loop`; `isEnded` is never read.
- **`loopBackAndForth`** = the same plain `loop = true` (no ping-pong). Never seen in an export.
- **Audio-only.** `renderAudioOnlyEffect` sets `audioElement.loop = true` (same two literals, same schema path).
  `renderWebVideo` and the header soundtrack (`loopSlideshow`, `soundtrack`) are unrelated.
- **Cache / reuse.** `movieCache` is keyed per movie **object**; `resetMediaCache()` runs when the slide index changes,
  on `goBack…` and `jumpToSlide`. Each slide's instance has its own objectID, so the player never carries an element — or
  its `loop` — across slides. **Only our runtime does** (pool / facade / bridge / glReplay), and it keeps the `loop` of the
  decoder's **source** element. The destination's `setLoop(true)` (run only when the destination's movie-start build
  fires — P2 slide 2: its **third click**) lands on a facade (`bindFacade` forwards `loop`, `live_continuity_js.py:1521`),
  a suppressed element (bridge) or the player's unused element (glReplay armed). So no-loop → loop is repaired late and
  only on a facaded pin; loop → no-loop is never repaired. Nothing is fixable without new core JS ⇒ **refuse any
  difference** (§2.2).
- **Which decoder is carried.** The core pools per asset key and reuses FIFO (`plan_signature` docstring: "picks
  same-asset instances in DOM order"); only glReplay picks by rect (`glCarried`, :596). On a slide with two instances of
  one asset (P2 slide 1: `6BB39942` carried, `CBACAF27` not), the carried decoder may be either. ⇒ The loop check covers
  **every instance of the continuing asset on both slides**, not just the resolved pair.
- **Derivation walk.** `_find_movie_nodes` (`live_continuity.py:984`) = every dict with `movie` + `baseLayer` under
  `events`. `_movie_rect` → `_check_movie_encoding` → `_walk_movie_subtree` (:1048) refuses any key outside
  `_MOVIE_SUBTREE_KEYS` (:36; `movie` set :40) — today's refusal (`possible mask: <movie node>.movie.loopMode`).
  `loopMode` matches no `_MASKING_NAME_FRAGMENTS`.

## 2. Derivation (`src/obed_edom/live_continuity.py`)

1. **Vocabulary.** Add `"loopMode"` to `_MOVIE_SUBTREE_KEYS["movie"]`. `_MovieInstance` (:1219) gains
   `loop: bool = False`. `_slide_movie_instances` (:1224) reads it through a new `_loops(movie, slide_name) -> bool`: key
   absent ⇒ `False`; `"looping"` ⇒ `True`; anything else (`"loopBackAndForth"`, other strings, non-strings, `null`) ⇒
   `_Refuse(f"movie on slide {slide_name} has an unmeasured loopMode {value!r} (only 'looping' is qualified)")` ⇒
   whole-deck `Unsupported` — the same class as every other unmeasured-vocabulary refusal.
2. **Loop difference ⇒ boundary refusal (retire), flag-independent.** In `derive_plan`'s Magic Move branch, right after
   `_resolve_continuation` succeeds: if `{i.loop for i in out_found + in_found}` has two values, set
   `loop_refusal = f"'{asset}' does not loop on every instance at {boundary_desc}; a carried decoder keeps its source's loop setting"`.
   Then `refusal = loop_refusal or <overlap refusal>`; when `loop_refusal` is set, **skip `_gl_replay_attempt`** and, only
   when `gl_replay` is on, set `gl_replay_reason=loop_refusal` (so a flag-on record says why). Everything downstream is
   existing machinery: a refused `pin` becomes today's single `retire` (the raw player's own element — loop-correct), a
   second retire / a retire after a cut / a refused `bridge` make `to_runtime` return `Unsupported` exactly as an overlap
   refusal does, and the reason reaches `refusals` → the host's `notCarried` list. Not checked on `restart` boundaries
   (dissolve / none: fresh element each side) nor the final boundary.
3. **glReplay rules 1–5 (arming §11) unchanged.** A loop-refused boundary never reaches them; a looping pair that agrees
   arms like any other, and its new sha (§2.4) keeps it out until the gates pass.
4. **Signature annex.** `ContinuityPlan` gains `loop_instances: dict[int, dict[str, list[dict[str, float]]]] = {}`
   (last field, default, same shape and rect order as `slide_instances`, looping instances only). **Not** in `as_dict`
   (nothing reads it there; the probe reads `video.loop` from the page). `to_runtime()` appends, **only when non-empty**,
   `"loops": [{"scene": scene_index_by_player[p], "asset": key, "rect": _rect_ints(rect)}, …]` sorted by
   `(scene, asset, x, y, w, h)`, before the `plan_signature` check (:874). Docstring gains one sentence.
   *Why a runtime key and not a signature-only input:* the allowlist contract is "the runtime you install is one P2
   measured" (`plan_signature` docstring); keeping `plan_signature(to_runtime()) ∈ QUALIFIED_PLAN_SHA256` true for every
   qualified deck keeps that invariant, the existing assertions (`test_live_continuity.py:651,1615,2743`,
   `test_p2_adversarial.py:3444`), and the gate record's runtime self-describing. Cost: a few bytes that JS ignores. The
   core reads only `movies`/`boundaries`/`transparentBackground` (`live_continuity_js.py:371,1202,1595`); G2 reads
   `boundaries`/`movies` (`live_gl_replay_js.py:104–141`); `validate_gl_replay_entry`/`gl_replay_script` read the
   glReplay entry + `movies`; nothing rejects unknown top-level keys. *Why per instance and not a deck boolean:* §1
   "Which decoder is carried" — a deck that loops a different subset of instances than `p2-loop` is unmeasured and must
   get a different sha. Non-loop decks: runtime and both P2 shas byte-identical (F5).
5. **Allowlist.** Append (never replace) the two `p2-loop` shas in the **gate commit**, which is what the gate worktree
   pins, so L1/L2/L5 install on product code; removed again if any gate fails. Until that commit, WS-A's test asserts the
   two pinned shas (captured with `plan_signature` patched to record) and `Unsupported("…not yet qualified…")`; the gate
   commit flips it to `∈ QUALIFIED_PLAN_SHA256`. `EXPECTED_PLAN_SHA256` (`tests/test_live_continuity.py:386`) and
   `GL_REPLAY_RUNTIME_PLAN_SHA256` (:2658) unchanged.
6. **Versions.** `CONTINUITY_VERSION` 5, `GL_REPLAY_VERSION` 1: the PR shows an empty
   `git diff origin/main -- src/obed_edom/live_continuity_js.py src/obed_edom/live_gl_replay_js.py`; `PINNED_CORE_SHA256`
   (`tests/test_live_continuity_js.py:38`) and `PINNED_JS_SHA256` (`tests/test_live_gl_replay_js.py:140`) not re-pinned.

## 3. Runtime at a wrap — every check that can see `ended` or a backward clock

| Where | Check | Under loop | Change |
|---|---|---|---|
| G2 `tickOnce` :1082 | `videoEnded = video.ended` | always false | none |
| G2 `rafStep` :1127–1135 | idle = paused ∥ videoEnded; watchdog `LOOP_WATCHDOG_TICKS=2` | a rVFC gap during the loop seek ⇒ rAF tick without upload, no stand-down | none |
| G2 `perLiveUpload` :1096 | `readyState < 2` ⇒ skip | skip one upload | none |
| G2 `perClearUpload` :474 (per `clear` while recording the transition, i.e. ARM) | `assertOr('videoNotReady', readyState ≥ 2)` ⇒ stand-down | **wrap during the recorded transition may stand down** ⇒ retire fallback (fail-closed) | measure (L2), OQ-4 |
| G2 `sampleOnce` :609 | records `vt`, `mediaTime` | report only | none |
| G2 guards :1065 | canvas / frame length / context / GL error | independent of media time | none |
| core `glCarried` :587 | excludes `v.ended` | never ended | none |
| core `releaseArmed` :676 | `ended` ⇒ retire | never | none |
| core `stash` :752 | pool only if `readyState ≥ 2 ∥ currentTime > 0.05` | **detach exactly at the wrap may skip pooling** ⇒ player's fresh element (raw restart) / glReplay `notPooled`→retire | measure (L2), OQ-4 |
| core keep-warm / remount / facade swap :794,1121,1353,1440,1492,1565,1656 | `paused && !ended` ⇒ `play()` | never paused by end | none |
| core pin/motion/slot rAF loops :867,943,1005,1034,1333 | stop on `ended` | keep running (correct) | none |
| core event listeners | only `hashchange`, `error`, `unhandledrejection` (:847,1232,1240) — no media events | — | none |
| host `live_host.py:1210` `_video_snapshot` | logs `currentTime` | report | none |
| p2_verdict `carriedClock1to2` :1196, `rvfcMonotonic` :2042/2108, `_presented_time_advances` :2189; html_alpha_probe `score_index_progression` :1429, `_backward_reset` :2395 | strict monotonic | would false-fail on a wrap | none: P2-fixture-only (the P2 script takes no `--fixture`; the host probe imports none of them) |
| probe `score_continuity` :1162 (`MAX_DROP_S` 0.05, stall run, window advance) | strict | would false-fail on a wrap | wrap-aware, opt-in (WS-B) |
| probe visible passes (`score_inpage_liveness` :2066, liveness masks) | sample-callback times monotonic; `mediaTime` report-only | unaffected | none |
| OD-2 `obs_cadence_decode.phase_stats` | `wrapSteps` vs `backwardSteps` (`loop_frames`) | already wrap-aware | reuse |

No product JS change is expected. A wrap race found by L2 is a finding, not a silent fix (OQ-4).

## 4. Fixtures

- **`output/p2-loop` (gates; OQ-1).** New `scripts/loop_fixture.py` (one command, no subcommands) builds it in the **main
  checkout** `/Users/anyhowclick/Desktop/work/obed-edom/output/p2-loop` from
  `/Users/anyhowclick/Desktop/work/obed-edom/output/p2-recovery/html-adversarial` (read-only; source file shas asserted
  equal before/after). Copies `html-player/` and `html-unmodified/` (71 MB + 126 MB) and `asset-replace.json` (the 30 fps,
  46.0333 s counter movie ⇒ period 1381 frames); `html-disposable`, `pdf-strip.json`, `fingerprints-*.json` are not
  copied (no gate reads them; the probe and OD-2's `make_export` read only `html-player` + `html-unmodified/index.html`,
  OD-2's `loop_representation` reads `html-unmodified` JSON). Splices `"loopMode": "looping"` into the `movie` object of
  every `renderMovie` node whose objectID is in a fixed list — `6BB39942`, `CBACAF27` (slide 1), `F9AFED1B` (slide 2),
  `98D59E27` (slide 3), `E4728E7D` (slide 4); `2FE5195A` (WA0125) untouched — in **both** `.json` and `.jsonp` of **both**
  trees, as a **textual** insertion — Keynote's files do not round-trip through `json.dumps` (it writes `\/`) — of
  `,"loopMode":"looping"` before the closing `}` of the k-th flat `"movie":{…}` object (k = the node's position in
  document order = parse order), which is where the owner export has it; every other byte unchanged. Writes `loop-splice.json` {source shas,
  objectIDs, per-file pre/post sha}. Asserts: each touched file's semantic diff is exactly the added key (F1's shape),
  `.jsonp` payload == `.json`, and a fresh derivation reproduces F5's two annexed shas. Refuses to overwrite an existing
  `p2-loop` unless `--force`.
- **Owner export `output/p2-soak-loop`** (read-only): authenticity only — F1 proof, the committed unit fixture, a
  REAL-gated parity test. Not a gate fixture (F4).
- **Committed:** `tests/fixtures/live_continuity/minimal_alpha_dsk_loop/assets/` = `header.json` (slideList S4, S5) +
  `7A851F4D…json`, `C75DC221…json` copied **verbatim** from the owner export's `html-unmodified` (Keynote's own bytes; no
  sanitizing needed beyond what `minimal_alpha_dsk/` did — match it). Mixed / unknown / `loopBackAndForth` / non-string
  variants are single-key edits made in `tmp_path` by the existing `_mutate_slide` helper. The P2-loop unit case splices
  the committed P2 fixture (`tests/fixtures/live_continuity/assets/`) in `tmp_path` with the same objectID list.

## 5. Gates (every gating check has a known-bad that must FAIL and a control that must read 0)

| ID | Where / how | PASS | KB (must FAIL) | CvC (must read 0) |
|---|---|---|---|---|
| L0 unit | `uv run pytest` | a) S4→S5 both loop ⇒ pin, no refusal, runtime has `loops` (2 entries); b) S5 loop removed ⇒ refusal with the §2.2 text, flag on ⇒ `glReplay` false with that reason; mixed on the P2 3→4 **bridge** ⇒ `to_runtime` `Unsupported("a refusal the runtime cannot retire: …")`; P2 slide-1 `CBACAF27` only differs ⇒ 1→2 refused (the all-instances rule); c) `"bogus"`, `True`, `None`, `"loopBackAndForth"` ⇒ §2.1 reason; d) P2 fixture ⇒ runtime == pinned literal, shas `bafe26ca…`/`6a0596da…`; P2-loop ⇒ P2 runtime + `loops`, the two pinned shas (§2.5); real core+G2 sandbox (`_REAL_MODULE_AFTER_CORE` pattern, `test_live_gl_replay_js.py:3256`) installs with the P2-loop runtime (core `ready`, G2 not `planUnreadable`); `validate_gl_replay_entry` accepts it; e) REAL-gated parity: committed fixture vs `output/p2-soak-loop` S4–S5 slice (`as_dict` + runtime equal) and the owner deck whole ⇒ the F4 reason | L0-a's derivation run at `bd9ae9f4` ⇒ `possible mask … movie.loopMode` (recorded once in the gate record) | (d) byte-identity; P2 `build_continuity_plan` == derived (existing test) |
| L1 host, standard | `live_continuity_probe.py --fixture <main>/output/p2-loop/html-player --original-index <main>/output/p2-loop/html-unmodified/index.html`, 2560×1440, 1600×1000, 1920×1080, arms A/B/C + V/Voff + attach, then `--gl-replay auto` | `qualified`, glReplay `injected`, every existing verdict True; no wrap inside any scoring window (a sampled looping element's `currentTime` drop > period/2 there ⇒ **INVALID**, retake) | same command at `bd9ae9f4` ⇒ SystemExit "fixture does not derive a continuity plan: … movie.loopMode" | two takes at 1920×1080 ⇒ identical verdict sets |
| L2 wrap during carry | probe `--force-wrap {1to2,3to4}:<offset_ms>`, 1920×1080, `--gl-replay auto`; offsets −200, 0, +375, +750, +1125, +1700 ms from the advance press (transition 1.5 s) | **safe** outcome in every take: either the carry holds (verdict True under the wrap-aware scorer with **exactly one** wrap in window; 1→2 `armSeen`, LIVE after settle, no stand-down; 3→4 `continue3to4` True) **or** a listed fail-closed fallback — G2 stand-down `videoNotReady`, zone `retired` reason `notPooled`, or the raw player's own restart with no preserved element painting — each counted and reported for OQ-4. Anything else (frozen carried frame, other stand-down reason, JS error, wrong element) FAILs | P2 (non-loop) fixture, same pre-seek ⇒ the movie ends in window ⇒ "exactly one wrap / keeps advancing" FAILs; scorer unit: a mid-period drop FAILs, and a real wrap FAILs with `loop_period_s=None` | wrap-aware scorer re-scoring L4's three `bd9ae9f4` host artifacts (`host-<V>.json`) ⇒ verdict dicts byte-identical to the legacy scorer |
| L4 P2 regression | `scripts/run_gates.sh <gate-wt> <out>` at the PR commit and at `bd9ae9f4`, same session | identical: core JS sha, host verdicts, P2 fast/slow 14/14, `--disable-bridge34` red only on `continueThroughMovingMagicMove3to4` | (built into run_gates: disable-bridge34) | PR vs main diff of verdict sets = ∅ |
| L5 managed OBS (after OD-2 merges) | `managed_obs_qualify.py --arm soak --precheck --fixture <main>/output/p2-loop`, then `--arm soak --fixture <main>/output/p2-loop` (M6) | precheck (a)(b)(c) PASS on **product** code (no splice), (a) `video.loop` true on slide 1 **and** on the carried element after hand-back, enforced; M6 per OD-2 §5 with its `enforced=looping` checks on | main ⇒ (b) FAIL; `--kb frozen` soak FAILs (existing); `is_wrap` KB (existing decoder test) | off twin P3/P4 (existing) |

L5 is the G2-LIVE-across-wraps gate (precheck (c): ≥ 2 wraps, LIVE, no stand-down, `videoEnded` false, uploads rising;
M6: 20 min, wrap-window recordings decoded wrap-aware, frozen KB). Rev 1's headless 100 s hold (L3) duplicated it and is
cut; the mixed-deck host run (L6) re-proved an offline refusal and is cut (L0-b covers it).

**Forcing a wrap honestly (L2).** On the settled source slide the harness selects the source instance's `<video>` by DOM
id `<objectID>-video` (the player sets `id = movieId`; missing or duplicate ⇒ INVALID), sets
`currentTime = duration − lead`, waits for `seeked` + ≥ 10 rVFC frames, and presses advance at the computed instant, at
least 1.5 s after the seek. A harness-only rVFC recorder on that element logs `{now, mediaTime, presentedFrames}` (pooled
decoders keep firing rVFC — arming §10). The take is **INVALID** unless the recorded wrap (first `mediaTime` drop >
period/2) lies within ±100 ms of the intended offset. The scorer's window start is clipped to `max(grounded start,
seeked_t + 1.0 s)` (the grounded start of `score_continuity` is the first settled source sample, which would otherwise
contain the seek); both are in the artifact. The wrap itself is the browser's loop; no clock is faked. Period = the
element's `duration`, asserted equal to the node's `endTime − startTime` within one frame. If the tracked (carried)
element is not the seeked one, "exactly one wrap" fails — an honest FAIL, not INVALID.

**Wrap-aware scorer (WS-B).** `score_continuity(…, loop_period_s=None)`: with a period `P`, a step `a → b` with
`b < a` is a wrap iff `a ≥ P − tol` and `b ≤ tol`, `tol = 2/fps + (t_b − t_a)`; the clock is unwrapped (`b + P`) for
`max_drop`, stall and advance, and `wraps` is counted. Every other drop still counts to `maxDropS`. `None` ⇒ today's
behaviour byte-for-byte. Standard arms pass `None` and INVALIDate on any drop > P/2 of a sampled element whose
`loop` is true.

Rules: one headless Chrome at a time (run_gates is serial); gate worktree fresh and pinned to the gate commit;
`output/p2-recovery/`, `output/p2-soak-loop/` and every `.key` untouched (builder asserts source shas before/after); no
Keynote.

## 6. Work streams, sequence, review

**Sequence (OQ-2):** land **after OD-2's PR merges**, not stacked. WS-A and WS-B start now on main (disjoint from OD-2's
files); WS-C starts after OD-2 merges. OD-2 need not wait: per F4 its precheck cannot pass on `p2-soak-loop`, so its M6
takes its documented P2-fixture fallback with the Q3 caveat; this PR re-runs M6 on `p2-loop` (L5) and deletes the splice.

| WS | Files (disjoint) | Work |
|---|---|---|
| A | `src/obed_edom/live_continuity.py`, `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py`, `tests/test_live_gl_replay_js.py` (one sandbox test), `tests/fixtures/live_continuity/minimal_alpha_dsk_loop/` | §2.1–2.5; L0 a–e |
| B | `scripts/loop_fixture.py` (new), `tests/test_loop_fixture.py` (new), `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py` | §4 builder; probe samples gain `loop`, `duration`, `ended`; the wrap-aware scorer; standard-arm INVALID rule; `--force-wrap` with the recorder and window clip; L2's report of fallback events |
| C (after OD-2 merges) | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | delete `allow_soak_plan` and the `allow` plumbing (the fixture must qualify on product code; clear SystemExit if not); `SOAK_FIXTURE = output/p2-loop`; precheck (a) `video.loop` enforced and also read on the carried element after hand-back (not `stats.loopMode`, F6); delete `--build-fixture`/`build_fixture` if OQ-1 = (a) |
| Docs (coordinator, last) | `README.md` "Movie continuity", this plan's status, HALL entry | one paragraph: looping movies carry when every instance on both sides of a Magic Move loops; a difference declines that cut (listed in `notCarried`); `loopBackAndForth` makes the deck `unsupported` |

Implementers: 2 × Opus MEDIUM now (A, B), 1 later (C, may be B's). Then gates L1, L2, L4, L5 (coordinator, gate
worktree) → **Codex (gpt-5.6-sol) review** → fold → full local suites on the final commit:
`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps` (from `dashboard/`, bundled Node on
PATH) → one PR (never merged without the owner).

**Codex brief.** (1) Can any carry reach the runtime with differing loop settings among the asset's instances on either
side (every Magic Move pair, both flag states, multi-instance pins, glReplay)? (2) Is non-loop output byte-identical
everywhere — runtime, `as_dict`, P2 injected plan, both shas, JS module shas? (3) Does any value other than `"looping"`
pass, including via the generic walk? (4) Is the annex complete (every looping instance) and deterministic? (5) Can the
wrap-aware scorer turn a real restart / mid-period jump into a pass, and does every standard arm INVALIDate rather than
pass on an unplanned wrap? (6) Is the forced wrap honest (window clipped past the seek, wrap verified by the recorder)?
(7) Are the fixture splices exactly F1's shape, and are the read-only sources provably untouched? (8) Is every gating
threshold traceable, and does each gate have its KB?

## 7. Open questions for the owner (recommendation first)

- **OQ-1 Fixture.** Your loop copy put Loop on slides **4 and 5** (a pin with nothing above it, so G2 never arms there),
  and today's deck can no longer reproduce the P2 shape (F2–F4). (a) **Qualify on `p2-loop`: a copy of the P2 export with
  exactly the key Keynote writes spliced in (F1: one JSON key, media untouched), keeping your export as the authenticity
  reference** · (b) you re-author a deck in P2's shape with Loop on slides 1–4 (needs a Keynote export with your go).
- **OQ-2 Order.** (a) **After OD-2 merges; OD-2's soak uses its P2 fallback now** · (b) stack on the OD-2 branch.
- **OQ-3 Expectation.** Real church decks stay `unsupported` until the allowlist is retired (generalisation brief); this
  makes looping a non-blocker and qualifies one looping shape. (a) **Proceed** · (b) defer until the generalisation work.
- **OQ-4 A wrap at the exact carry instant** (§3: stash readiness :752, G2 `videoNotReady` :474) can fall back to the
  player's restart / the poster-then-retire path. (a) **Ship with it as a measured, reported residual if L2 shows it; fix
  in a follow-up** · (b) fix in this PR (core/G2 byte change, version bump, full P2 + OD-2 re-qualification).

Decided by existing convention (not asked): `loopBackAndForth` and any other value refuse (unmeasured vocabulary ⇒
`unsupported`); a loop difference declines that cut like an overlap does (README "Movie continuity"); looping decks get
their own allowlist entry (the allowlist admits only measured runtimes).

## 8. Risks

(1) Wrap races (OQ-4) are timing-dependent; L2 samples six offsets, not every frame. (2) `startTime`/`endTime` trims: the
export pre-trims files (`-0.0000-46.0333`), so the loop wraps to the trimmed start; a non-zero `startTime` is unmeasured
and not validated today (unchanged). (3) Audio-only looping movies stay refused upstream (unmeasured). (4) The splice is
evidence for the JSON representation only; if Keynote wrote something else for a looping movie in the P2 shape (e.g. in
the Magic Move effect), `p2-loop` would not show it — F1 found no such change on the S4→S5 Magic Move.

## 9. Rev 2 — what changed (critique)

1. **Mixed loop ⇒ boundary refusal, not whole deck** (rev-1 OQ-3 dropped). Derivation already splits "cannot tell which
   element is carried" (ambiguity ⇒ whole deck) from "can tell, but carrying looks wrong" (overlap ⇒ per-boundary refusal
   ⇒ retire, escalating to `Unsupported` via `to_runtime` when it cannot retire). A loop difference is the second kind;
   the retire zone hands the movie to the raw player, whose element has the destination's own loop. Moved out of
   `_resolve_continuation` into `derive_plan`, with glReplay skipped.
2. **Loop check covers every instance of the asset on both slides**, not just the resolved pair: the core reuses pooled
   decoders FIFO by asset, so the carried one may be a non-continuing instance (P2 slide 1 has two).
3. **`_MovieInstance.loop: bool`** instead of `loop_mode: str | None` — only one value is accepted, so a bool is enough.
4. **Annex kept as a runtime key, justified** against a signature-only input (invariant + existing assertions) and a deck
   boolean (subset ambiguity); `loopInstances` dropped from `as_dict` (no reader). Annexed shas computed offline (F5).
5. **L3 and L6 cut**, with `--hold-live-s`, the wrap-time `debugForceFail` switch and `p2-loop-mixed`: L5 is strictly
   stronger for G2 LIVE across wraps and runs anyway; L6 re-proved an offline refusal. **WS-D folded into WS-A** (one
   sandbox test).
6. **L2 PASS made consistent with OQ-4(a)**: rev 1 required "LIVE, no stand-down" while calling `videoNotReady` /
   `notPooled` report-only, so any race hit would have failed the gate. PASS is now "carry holds or a listed fail-closed
   fallback".
7. **Forced wrap: rev 1 claimed the seek sits ≥ 1 s before the scored window — false**: `score_continuity` grounds the
   window at the first *settled source* sample (:1197–1213), which is where the seek happens. The window is now clipped
   past the seek, press ≥ 1.5 s after it; selection by DOM id `<objectID>-video` confirmed in `main.js`.
8. **Scorer tolerance specified** (rev 1's wording was ambiguous); L2 CvC names its inputs (L4's main-side host
   artifacts); L1 KB is a SystemExit, not an `unsupported` verdict; L1 CvC is two takes (rev 1 pointed at L4).
9. **Fixture spec tightened**: absolute main-checkout paths, explicit objectID list, only the files gates read, a
   textual splice at Keynote's own key position (a `json.dumps` rewrite would change every `\/`), annexed-sha
   self-check; F1 extended (media not re-encoded). `fingerprints`/`pdf-strip` consistency is moot: no gate reads them.
10. **Line fixes**: `xB.setLoop` has an element guard; G2 :474 is `perClearUpload` (upload per `clear` while recording),
    not an "ARM upload"; host snapshot is :1210 (was :1205); html_alpha_probe :1453 is a docstring — the function is
    `score_index_progression` :1429; sandbox pattern :3256 (was :3250); OD-2 branch is 6 commits, unpushed. Added the
    facts that the destination's `setLoop` runs only at its movie-start build (P2 slide 2: third click) and that the
    core has no media-event listeners.
11. **§2.5** says how the pre-gate test asserts the new shas and when it flips. **OQs** trimmed to four real owner calls;
    the three with a repo convention are stated as decided.

## 10. WS-C detail (read from OD-2 at `0620603e` + its uncommitted tree, re-read at pushed `56b5904b`, 2026-09-25)

OD-2 is adding a **binary counter** (`scripts/binary_counter_movie.py`, fixture `output/p2-binary` with `fixture.json`
`{"counter": "binary", "base": "p2-recovery/html-adversarial", …}`): Chromium's native `<video>` applies a midtone curve
that G2's `texImage2D` path does not, so the grey counter reads frames apart between native and G2 — a wrap at the
hand-back would decode wrong. The binary decoder is wrap-aware (`is_wrap(..., mod=None)`, 12 bits > 1381 frames). Owner
2026-09-25: the looping soak fixture gets the binary counter. Re-verify every name below on the merged OD-2.

1. **Fixture.** `output/p2-loop` is rebuilt with `scripts/loop_fixture.py --force --source <main>/output/p2-binary` (one
   fixture for L1, L2 and L5; the grey-counter build is superseded). The builder also copies `fixture.json`, adding
   `"loop": {"objectIds": […], "planSha256": {off, on}}` (the `loop-splice.json` record). The JSON splice is unchanged, so the
   plan shas stay `3dc67558…` / `2ba6fbed…` (the builder's self-check proves it); only the movies differ.
2. **Harness `p2_family()`.** Today any manifest with `base == FIXTURE_BASE` counts as "qualified as is and not looping".
   Change: P2 family = that base **and** no `loop` key. Looping = `loop` present; drop the `ctx["fixture"] != FIXTURE`
   inference in `sessions_for`.
3. **Drop the splice.** Delete `allow_soak_plan` and the `allow` plumbing (`make_export`/`fixture_facts`/`run_session`/
   `sessions_for`): the product allowlist (`21944ddb`) qualifies `p2-loop`; a fixture that does not qualify is a clear
   `SystemExit`, never an in-process patch. Delete `build_fixture`/`--build-fixture` (OQ-1(a)).
4. **`SOAK_FIXTURE = output/p2-loop`**; `SOAK_LOOP_FRAMES` 1381 unchanged (asserted against the binary movie's
   `fixture.json` `frames`).
5. **Pre-check (a) enforced:** `video.loop` true on every slide-1 `untitled.mov` (`slide1Videos`), and on the carried element
   after hand-back (read `.loop` on the handed-back element, not G2 `stats.loopMode` — F6). `loop_representation`: the
   differing JSONs equal the `loop-splice.json` file list and every loop key is `loopMode="looping"` — enforced.
6. **Soak.** Re-read at OD-2 `56b5904b`: `--soak-minutes` defaults to 5 ("20 before a show or on a looping fixture");
   windows fire only `if minute in SOAK_WINDOW_MINUTES (2, 8) and minute < lose_at` with `lose_at = max(2, minutes // 2)`,
   so a 5-minute soak records **no** wrap window. L5 therefore runs `--soak-minutes 20` (windows at 2 and 8), unless OD-2
   makes the schedule scale with the length. With a real looping fixture, `soak_gates`' `enforced=looping` checks and `kb_verdict`'s `fixtureLooping`
   become live (Opus r1 #8 on OD-2 stops being vacuous). Wrap windows decoded with `counter="binary"` + `loop_frames=1381`.
7. **L1/L2 re-run on the rebuilt fixture** (headless, ≈ 25 min; clock-based, expected unchanged) so every gate reads one
   fixture; record in `gates-r2.md`.
8. **Tests:** `tests/test_managed_obs_qualify.py` — splice gone (no `mock.patch` of `QUALIFIED_PLAN_SHA256`), `p2_family`
   false for a manifest with `loop`, pre-check (a) KBs (a slide-1 element with `loop` false ⇒ FAIL; an extra differing JSON ⇒
   FAIL). `tests/test_loop_fixture.py` — manifest copied with `loop`, binary source accepted.

Owner-gated: L5 launches managed OBS (per-session OK). Files: `scripts/managed_obs_qualify.py`, its tests,
`scripts/loop_fixture.py`, `tests/test_loop_fixture.py` — one implementer.
