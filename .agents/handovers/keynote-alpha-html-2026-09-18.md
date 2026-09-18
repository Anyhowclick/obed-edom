# Keynote alpha HTML — handover 2026-09-18 (supersedes 2026-09-17)

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
