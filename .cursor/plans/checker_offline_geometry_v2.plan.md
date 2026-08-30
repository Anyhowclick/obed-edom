---
name: Checker offline geometry v2 (drop the bulk pass)
overview: "v2 of the checker speedup (v1 shipped e86aaca: offline IWA + O(slides) bulk-geometry, ~3.25x). GOAL: compute autosize TEXT geometry OFFLINE (AppKit NSAttributedString shaping) so the 61s bulk Keynote pass can be dropped -> cold inspect ~= offline(0.8s)+export(32s) ~= 33s, ~9x. PEER-SCOPED + MEASURED (Keynote-free, 2026-08-29). Read the v1 plan (.cursor/plans/checker_offline_inspect.plan.md) + SKILL 'Reading a .key offline (IWA)' first. SEQUENCED to de-risk: build+calibrate the shaper (step 1, Keynote-free, low-regret) BEFORE committing to the group work."
todos:
  - id: shaper
    content: "STEP 1. Mode-aware offline text composer using AppKit NSAttributedString (installed; CoreText pyobjc is NOT — no new dep). Discriminator = TSD.GeometryArchive.flags (empirically: 0x1=fixed-width, 0x2=fixed-height; the current frame.h==0 test conflates flags 0 and 1). Per mode: flags=3 -> frame exact; flags=1 (fixed-W+auto-H, the DOMINANT case, ~91-97% of overflow-eligible boxes) -> w=naturalSize.w (EXACT offline), h=shaper.height(text, w=nw-2*inset), y=TOP (fix: current _autosize_rect wrongly uses y-h/2 for flags=1); flags=0 (auto-W+auto-H center) -> w=shaper.width(text), h=shaper.height, x=anchor-w/2, y=anchor-h/2. Extend iwa_runs.resolve_style to expose paragraph metrics (lineSpacing, paragraphSpacing/spaceBefore, firstLineIndent, tracking). Calibrate 3 constants ONCE: text inset (exteriorTextWrap.margin=12pt), line-height multiplier (per font family), paragraph spacing — raw boundingRect height is already median 0.989 of JXA. ORACLE: the cached JXA v3 GW payload already carries JXA's laid-out w/h (ground truth) -> calibrate + verify Keynote-free; PPTX only needed for DSK (no cache). Pending."
    status: pending
  - id: regroup
    content: "STEP 2. Recompute group frames as the child-UNION over the now-SHAPED text children (+ exact images). Measured residual with STALE text children (upper bound): GW 14/21 groups, Full 46/410 diverge >2px — but images 2/188 (GW) / 6/1548 (Full) and movies 0 are already offline-exact (residual = masked-rotated -> flag). The group residual IS the text residual one level up, so it should collapse once text is shaped. Re-measure after step 1. Pending."
    status: pending
  - id: group-source
    content: "STEP 3 (DATA-DRIVEN, decide after step 2). If the group residual collapses -> drop the Keynote geometry pass ENTIRELY (~9x). If not -> keep a SLIM group-only bulk pass (one kind, O(slides), still ~5-6x). Images/movies go fully offline now (tiny masked-rotated residual -> guard+fallback). Pending."
    status: pending
  - id: guard-version
    content: "Keep v1's granular fallback; add a `font-missing` guard (NSFont.fontWithName_ != nil — else metrics are a substitute font's, FALL BACK; TOP accuracy risk). PPTX content-hash-keyed steady-state fallback (autosize extent = pure fn of text+styles+width+fonts -> re-run only on hash change -> ~zero Keynote steady state), OR v1's scoped-JXA per-slide fallback (simpler). Bump INSPECT_VERSION 4->5. Pending."
    status: pending
  - id: verify
    content: "me + 1 peer verify: overflow-flag AND bounds-flag A/B vs JXA = 0 divergence (GW + DSK); per-box W/H parity <=2px on flags{1,3}, width vs oracle on flags=0; deck_slide_digests identical; end-to-end checker run == full-JXA. Pending."
    status: pending
isProject: false
---

# Checker offline geometry v2 — drop the bulk pass

Full peer draft + analysis probes: session scratchpad `checker_offline_geometry_v2.plan.md`
(+ `survey2.py`/`analyze2.py`/`ytest.py`/`calib.py`). This is the reviewed, sequenced version.

## What step-1 scoping established (the problem is smaller than v1 assumed)

- **`geometry.flags` is the autosize discriminator** (3-way, clean on GW's 99 boxes): flags=3
  fixed both (frame exact), flags=1 fixed-W+auto-H (**dominant**; width EXACT offline, only
  height missing), flags=0 auto-W+auto-H (width stale on 11/32). v1's `frame.h==0` conflates
  flags 0 and 1.
- **"Shuffled" was a myth** — plain stale (the box's own pre-relayout width; no join bug).
  True width-shaping ("B1") is only ~11 boxes on GW, ~2 on DSK.
- **~91-97% of overflow-eligible boxes are fixed-width+auto-height** — the EASY case (wrap at a
  known width -> height). So v2 is mostly a B2 (height) problem, not the B1 "wall" v1 feared.
- **AppKit `NSAttributedString` shapes it** (installed; no new dependency; custom fonts resolve),
  raw height median 0.989 of JXA before a 3-constant calibration.
- **Non-text geometry residual** (measured, pure-offline): images/movies offline-EXACT (GW
  2/188, Full 6/1548 — masked-rotated tail); groups diverge but only because their text children
  are stale — expected to collapse once text is shaped (step 2 re-measures).

## Ceiling & risk

~9x (306s -> ~33s) IF the group residual collapses; else ~5-6x with a slim group-only bulk.
Step 1 is Keynote-free and low-regret (calibrate against the cached JXA oracle). **Top risk:
font substitution** — a machine missing the deck's fonts silently mis-shapes; the `NSFont`
guard + fallback is load-bearing. The floor is the preview export (user-facing PNGs need Keynote).

## KNOWN BUG — FIXED (fd79e88)

DSK slide 17 rendered out of order (between 12 and 13) on a real run. ROOT CAUSE: slide 17's
lower-third photo is FLIPPED vs its LW counterpart; the offline read composes a masked image's
angle from frame+mask (357+357 → 354) where JXA reports 0, and `deck_slide_digests` — the
slide-IDENTITY key that decides PAIRING — included image `rotation`, so the flip churned slide
17's digest and floated it out of sequence. FIX: dropped `rotation` from the digest — orientation
must not drive pairing/order; a flip-vs-LW discrepancy is caught by the paired-image COMPARISON,
not the ordering key. Offline masked-image angle left as v1 composed it (signal preserved for the
comparison). Regression test: `test_deck_slide_digests_ignore_image_rotation`.

## Step-1 peer-verify (62b39eb) — VERDICT: correct, safe, INERT; not yet generalization-safe

Nothing calls `iwa_text_shape` (checker/resizer still use `bulk_geometry`; `resolve_para_style`/
`tracking` additive) → cannot regress v1. Mode composer correct (0x1=W/0x2=H); flags=1 y=TOP anchor
fix real & large (50–178px); AppKit lazy-imported; font-missing guard gates; 35 tests pass. **CLOSE
BEFORE STEP-3 WIRING** (should-fix, GENERALIZATION — none affect GW): (1) shaper IGNORES resolved
paragraph metrics — inter-para spacing (only one absolute `VERTICAL_PAD`), `lineSpacing.mode` (always
applied as relative multiple), indents → multi-para/non-GW drift; (2) an installed-but-UNCALIBRATED
font/size is silently vouched (`DEFAULT_LINE_CORRECTION`/absolute `VERTICAL_PAD`, `reason=None`) — gate
or widen calibration before DSK; (3) bold/italic traits not applied (relies on fontName weight) — a
bold run inheriting a `-Regular` name shapes too narrow. Nits: flags==2 short-circuits to a stale
frame width, vouched; para-level `tracking` dropped; flags==7 (0x4) undocumented (non-text). **Caveat:
NO test asserts a shaped value vs a JXA oracle — the ~2px/6px accuracy is self-reported; real JXA A/B
(step-1 verify item) still PENDING.** Next: close (1)(2)(3) + JXA A/B, then step 2.

## Checker items to pull from `resizer_optimizations.plan.md`

Independent of the v2 shaper track; land the correctness/cheap ones regardless of whether v2 drops
the bulk pass. Full detail + coordination in that plan.

- **`r-count-guard` (correctness — HIGH; do first).** `_splice_bulk_geometry` overwrites items by
  `kindIndex` with NO offline-vs-Keynote count check; a dropped/added mid-list BULK_KIND item silently
  hands every later item the previous object's frame. The DSK17 bug was this class (a dropped
  placeholder — harmless to ordering only after rotation left the digest; a mid-list IMAGE drop would
  silently mis-splice geometry with no catch). The guard `iwa_kindindex.reconcile_counts` is BUILT but
  wired into nothing. Wire it into `two_tier_wall_payload`/`_splice_bulk_geometry`: per (slide,kind)
  compare bulk-rows vs offline count (text tolerates keynote−derived ∈ [0,2] trailing placeholders —
  verify tail rows are placeholder-shaped), image/movie/group exact; on mismatch mark unspliced AND
  force the slide into `fallback_slides` even with zero soft items.
- **`r-cache-hit-export-only` (~62s checker win).** Cached JSON present + PNGs evicted → the checker
  does a full offline+bulk re-read (~62s) when only the ~32s export is needed. ~10-line fix in
  `inspect_keynote_checker`'s cache block (inspect.py ~379). HARDEN the hit to require
  `len(preview_pngs) == slideCount` (Session-14 partial-state lesson).
- **`r-misc-cleanups` (cheap, checker-touching):** (3) `_build_checker_offline` decodes the deck TWICE
  (`two_tier`→`_load_deck` then `attach_runs`→`_load_deck`) — single decode saves ~0.4–1s; (2) fold
  the preview export into the bulk_geometry session (a cold diff opens Keynote 4×) → ~8s/diff; (5)
  `export_applescript` (inspect.py:44) uses the disproven doc-bind (no close-by-name) → could silently
  export the WRONG deck's bytes; every checker export goes through it; (4) checker-written v4 payloads
  land in the SHARED digest cache served to resize-propose/single-inspect — A/B one cross-serve + add
  a `reader` provenance field.
- **`r-nested-bulk-probe` / `r-bulk-counts-plan`** would cut the 61s bulk tier (~94s→~45-55s) — but v2
  aims to DROP the checker's bulk pass, so likely MOOT for the checker (durable for the resizer remap
  read + write verifier). Revisit only if step-3 keeps a slim group-only bulk.

### Second peer fact-check (all 4 claims hold) + additions

All four claims above CONFIRMED against HEAD, except nested-bulk/bulk-counts is PARTIAL not
moot — it still speeds TODAY's checker (full 61s bulk runs until v2 ships), and if step-3 keeps
a slim group-only bulk the nested read still trims it (smaller win). Additions the first pass
under-weighted:

- **REVERSE cross-serve is a CHECKER CORRECTNESS BUG — raise `r-misc-cleanups`(4) to HIGH.** Item
  (4) as written only covers checker→propose. The dangerous direction is JXA→checker: the JXA path
  emits NO `runs[]` (`inspect_keynote.js:71`), but the checker reads runs (`validate.py:466,711`,
  `diff_keynotes.py:931`). If a sermon deck is single-inspected (app.py:1266 caches a runs-less JXA
  payload under the digest) then diffed, the checker's cache-hit (inspect.py:380/388) returns that
  payload with NO `attach_runs` → highlight/small-caps/style diffs SILENTLY under-report. Fix: the
  provenance (`reader`) field, and the checker cache-read must REJECT/ignore a non-offline (runs-less)
  payload and rebuild. Higher priority than the propose-side A/B.
- **`r-digest-sidecar` — modest checker win.** `inspect_keynote_checker` SHA-256-hashes the whole
  deck every inspect (inspect.py:375), twice per diff; a byte-current mtime/size sidecar
  (`baseline._cached_file_digest` pattern) skips re-hashing an unchanged deck on repeat diffs — ~a few
  seconds/deck (sermon decks ~0.5–0.7GB), Keynote-free, low risk.
- **`r-misc-cleanups`(6): dead `_slide_index_by_number`** (offline_inspect.py:556-562, zero refs) is
  in the checker's module — fold the delete into the r-count-guard edit.
- **NOT checker-applicable (peer-confirmed):** `r-readback-nocache-fix` (checker sets previewDir to the
  dir it exported into — no bug), `w-skipped-slide-options`(1) (deck_slide_digests fingerprints ALL
  slides incl. skipped — the DSK17 surface, so keep full bulk for the checker), `w-tmp-path-fix`,
  `w-statfinalize-parity-audit`, `r-propose-*`, `r-acquire-cache-read`, `r-readback-two-tier` (resizer
  apply/write paths the checker never traverses).

## Execution status (branch `fix/checker-followups`, off merged main)

**DONE + committed `2733a91` (497 passed, 1 xfailed; Keynote never opened):** the four low-risk
checker follow-ups — r-count-guard (reconcile offline-vs-bulk counts in `_splice_bulk_geometry`,
placeholder-tail check, force fallback on mismatch even with zero soft items), reverse cross-serve
(`reader` provenance field; checker rejects a cached non-offline/runs-less payload and rebuilds),
r-cache-hit-export-only (export-only path + `len(preview_pngs)==slideCount` hardening), and
r-misc-cleanups (3) single IWA decode + (6) dead-code delete. New tests in `tests/test_inspect_checker.py`
+ count-guard tests in `tests/test_offline_inspect.py`.

**IN FLIGHT:** 2 verify peers on `2733a91` (2+1+2 workflow). If they surface a should-fix, address on
this branch and re-commit.

**STILL TODO (deferred / not started):**
- Higher-blast-radius opt items (own pass): r-misc-cleanups (5) `export_applescript` doc-bind (no
  close-by-name → could export wrong bytes; touches ALL exports), (2) fold-export into the bulk session,
  and the r-count-guard "(a)" extension (per-slide shape/line counts in `bulk_geometry.js`).
- **End-to-end GW+DSK run-parity** (needs Keynote free): run the real checker via the new path vs a
  full-JXA run, diff pairings/flags/markup. This is the outstanding v1 "verify todo" gate.
- v2 step-3 wiring blockers (from the step-1 peer-verify): close the shaper's paragraph-metric /
  uncalibrated-font / bold-italic generalization gaps + the JXA A/B before wiring.
- Merge `fix/checker-followups` → main when the verify peers are green (user merges).
