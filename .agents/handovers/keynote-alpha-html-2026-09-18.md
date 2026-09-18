# Keynote alpha HTML — handover 2026-09-18 (supersedes 2026-09-17)

## Step 1 (ownership & targeting) — DONE 2026-09-18, branch `claude/pr158-handover-findings-4366b9`
Tip `5cfa8ee`. 7 implementation rounds folding 6 adversarial Codex (gpt-5.6-sol) reviews
(`.agents/reviews/step1-ownership-codex-r1..r6.md`); contract + residuals in
`.agents/plans/step1-ownership-contracts.md`. **Not pushed / not on the PR branch
`feat/keynote-alpha-p2-html-mm` — awaiting owner integration decision.** No Keynote since one
offline export (`edef8929`-equivalent rebuild; source deck byte-intact). Runs offline
`--reuse-export --disposable`, main-checkout venv + `PYTHONPATH=<worktree>/src`.

Delivered — ownership is now **deterministic** and the instrument **fail-closed**:
- Feed binds to the ONE decoder the PLAYER itself drew into a target canvas (a
  `CanvasRenderingContext2D.drawImage` wrapper records canvas-ELEMENT→video in a WeakMap; a
  `__obedFeeding` guard keeps our own draws out; records only after the draw succeeds). No
  ready-video / geometric / last-wins fallback. `footprintOwnerDecoderId` is a two-pass,
  order-independent resolver that returns null on a distinct-decoder overlap tie, on zero
  overlap, and on an unknown footprint key (all fail-closed).
- getContext recording is element-stamp ONLY (no id-map probe).
- Texids resolve the 1→2 boundary structurally: the ONE footprint-sized `contents` crossfade
  under an authored `apple:magic-move-*` **transition** (steady-anchoring was wrong — the
  movie's posters `0885→A223` are transition-only, never slide-1/2 steady; that mis-diagnosis
  cost round 2). `movieTexids` = `{decoderKey, outgoing:[from], incoming:[to]}`, both-sided or null.
- `feedEngagedAt1to2` fail-closed gate folded into `continueThroughMagicMove1to2`: passes ONLY
  with both-sided texids + `motionAcrossFlip.ok` + one stable non-null decoderId + 2d context +
  a player-authored incoming-slot draw on that decoder within `[num(hash2), SLIDE3_MIN_HASH)`.
  Never passes by absence.

Verified (offline, both wait profiles): texids resolve `movie1 0885/A223`; `feedEngagedAt1to2`
RED on `motionAcrossFlipOk/stableDecoder/contextType2d/incomingFeedDraw`; **Finding 1 correctly
OPEN**; Findings 2 & 3 green. 92 unit tests pass (`tests/test_p2_adversarial.py` +
`tests/test_html_alpha_probe.py`). **2→3 restart is a capture-timing FLAKE** (~2–3/3 either
profile, alternating; restart logic untouched) — worth stabilising but not a regression.

Residuals deferred to Step 2 (documented in the contract): the `#6` cut-vs-restart window
classification; JS-level single-feeder enforcement (gate is fail-closed against it); a repeated
poster pair at genuinely distinct boundaries; a footprint non-movie raster contents-swap under MM.

**Step 2 (next):** engage the feed at the real cut — the mo-prepaint fires at `#4/#6` and the
rVFC feed draws 0 into incoming; intercept the poster-WRITE synchronously so the bound decoder's
current frame lands on the correct newborn INCOMING canvas at `#1→#2`. That is what flips
`feedEngagedAt1to2` (and Finding 1) green — honestly, because the gate now demands it.

---


Branch `feat/keynote-alpha-p2-html-mm` (PR #158), tip pushed. Disposable fixture: Minimal
Alpha_DSK, owner-revised z-order. Source deck untouched; P3 stays unwired. **No Keynote needed** —
the on-disk `html-unmodified` export (`edef8929`) reflects the owner's latest deck; all runs are
offline `--reuse-export --disposable`. Re-export only if the owner edits the deck again.

## Status
- ✅ **Finding 2 (stacking):** owner z-order front→back = green square, larger movie (untitled.mov),
  black sentinel, smaller movie (WA0125). Gate proves black is OCCLUDED by the larger movie
  (behind), green translucent IN FRONT, over a NEUTRAL grayscale movie so `greenish` can't be faked.
  Green translucency proven on slide 1 (`greenTranslucentPre`, partial alpha ~75). Both wait profiles.
- ✅ **Finding 3 (restart 2→3):** untitled.mov restarts on a genuinely fresh decoder; `newElId ==
  restartDecoderId`, mandatory target-decoder rVFC, boundary-guard + retire tied to the earning
  decoder; no manual pool clear. Both profiles.
- ⛔ **Finding 1 (motion through the 1→2 Magic Move cut): OPEN.** Do NOT report closed.

## Finding 1 — the open bug (symptom / expected / evidence)
- **Symptom:** the COMPOSITED movie freezes ~1 frame (~33 ms) at the exact canvas-swap. The DECODER
  never stalls (rVFC mediaTime monotonic through the cut). It is a paint-ordering/re-lock artifact.
- **Why the current "close" is invalid (Codex round 5, all verified):**
  1. The MutationObserver pre-paint fires at scenes **#4/#6, not the gated #1→#2** (mis-targeted
     texids) — `mo-prepaint-draw` sceneHashes are `#4`×11, `#6`×7, none at `#1→#2`.
  2. ~5–10 Hz screenshots can't reliably see a 33 ms freeze (can fall between captures);
     `freezeRunAtCut=0` is coarse-capture MISSING it. `max_freeze_run=2` also permits freezes.
  3. The flat luminance index patch is FORGEABLE by the MM crossfade — an opacity blend of two
     frozen posters yields smooth intermediate values read as "progress" though no decoder frame
     advanced. (Also the mod anomaly test reads `200→10` as +66 forward.)
  4. Feeding + continuity aren't bound to ONE target decoder (`pooledDecoderCandidate` picks any
     ready movie1 / falls back; every rVFC feed draws into every id-matched canvas; continuity takes
     max-of-same-key clock).
  5. `getContext('2d')` is NOT a side-effect-free WebGL test (creates the 2D context, breaks a later
     WebGL request). Texid extraction over-matches any same-sized `contents` animation on any slide.
- **Established facts:** the player is a webpack bundle; `UC` is closure-local and **unreachable**
  from injected scripts (empirically confirmed) — the `UC.getTextureObject` source-wrap lead is OUT.
  Each authored object is its own 2D `<canvas>` under `#stage`; the MM slot builds an invisible `to`
  (opacity 0) + visible `from` canvas. Evidence: `output/p2-recovery/html-adversarial/report.json`
  (findings, preserveEvents), `runs/primary/*.png`, commits 015df77..0f21d1e.

## Interim capability statement (framing B — use THIS, do not claim closure)
> Decoder continuity and live composition before/after the cut are established. A compositor
> transient remains; current capture cannot establish its absence or reliably bound its duration.

Note: "sub-frame" understates it — 33 ms is ~1 source frame @30fps / ~2 refreshes @60Hz. Conversely,
repeated composited frame IDs are NORMAL for a 30fps movie on a 60Hz display, so `max_freeze_run=0`
is NOT a sound universal definition. Right framing: **prove correct frame DELIVERY, then measure
additional presentation delay** — not a raw freeze count.

## Next round — bounded plan (owner/Astra directive 2026-09-18)
Do B now (above). Pursue a BOUNDED version of A as the next experiment, in this order:
1. **Ownership & targeting first (necessary regardless of capture tech):** bind the authored movie
   object and its outgoing/incoming texture ids to ONE exact decoder. Remove ready-video fallbacks
   and max-of-same-key clocks. Passively RECORD the context type returned by the player's own
   `getContext` calls (instrument context creation) instead of probing with `getContext('2d')`.
2. **Prove the repair engages at the failing cut:** require events showing the correct newborn
   canvas receiving THAT decoder's current frame during `#1→#2`. If the MutationObserver still misses
   that lifecycle, trace the actual poster-WRITE operation; an inject-only, narrowly-scoped
   interception of that write could replace its pixels synchronously (preserving the player's drawing
   state + crop). Candidate to test — does NOT need `UC`.
3. **Qualify the instrument before trusting a positive result:** deliberately inject a
   one-presentation-frame poster FLASH and a one-frame STALE hold at several cut phases — the
   instrument MUST catch them. Then compare feed-off vs feed-on. Prefer a controlled
   `HeadlessExperimental.beginFrame` sequence first IF the exact browser supports BeginFrameControl
   (verify; a clean controlled result must be re-checked under normal playback that altered
   scheduling didn't eliminate the race), then ordinary playback WITH explicit capture-loss
   accounting.

**Capture caveats (do not assume):** `Page.startScreencast` does NOT guarantee every presented frame
(Chromium skips when too many frames await ack; `everyNthFrame=1` doesn't fix it) → unobserved
intervals must INVALIDATE a zero-freeze verdict. A barcode is "non-blendable" only if DEMONSTRATED:
test frozen-endpoint blends across opacity values and reject ambiguous decodes; a checksum alone
doesn't prove freshness.

**Acceptance metric must distinguish:** (a) wrong content / a poster appearing; (b) an OLD movie
frame persisting after a newer one should have shown (allow a declared pipeline latency); (c)
legitimate crossfade contributions from outgoing+incoming surfaces; (d) UNOBSERVED intervals
(remain unknown, not "pass").

**Defer** a large capture-system rebuild until it demonstrably detects the exact one-frame defect
(via step 3's injected controls). Keep the round focused on eliminating the gap, not manufacturing a
reassuring score.

## Consults on file
Fable-1 (grounded leads), Opus peer (pressure-test + honest-gate reframing), Fable-blind (proposed
UC source-wrap — disproven), Fable-critique (aliasing stimulus + false-zero counter + crop/readyState
guards). Codex gpt-5.6-sol rounds 1–5 (20 defects; all folded except the open Finding-1 items).

## Do not
- Claim Finding 1 closed. Touch Keynote / owner source decks. Wire P3. Trust a green you can't trace
  to the fix engaging at `#1→#2`.
