---
name: Checker offline geometry v2 (drop the bulk pass)
overview: "v2 of the checker speedup (v1 shipped e86aaca: offline IWA + O(slides) bulk-geometry, ~3.25x). GOAL: compute autosize TEXT geometry OFFLINE (AppKit NSAttributedString shaping) so the 61s bulk Keynote pass can be dropped -> cold inspect ~= offline(0.8s)+export(32s) ~= 33s, ~9x. PEER-SCOPED + MEASURED (Keynote-free, 2026-08-29). Read the v1 plan (.agents/plans/checker_offline_inspect.plan.md) + SKILL 'Reading a .key offline (IWA)' first. SEQUENCED to de-risk: build+calibrate the shaper (step 1, Keynote-free, low-regret) BEFORE committing to the group work."
todos:
  - id: shaper
    content: "STEP 1 + generalization gaps DONE (inert; not wired). Mode composer on TSD.GeometryArchive.flags (0x1=fixed-W, 0x2=fixed-H); flags=3 frame-exact, flags=1 w=naturalSize+shaped-H+y=TOP, flags=0 shape-both. Height model is SIZE-AWARE: shaped_h = layout*m + b*size per family (AzoSans (1.013,0.455), ArgentCF (1.013,0.294)); the old absolute VERTICAL_PAD=32 was 0.455*70 (a proportional pad frozen at size 70) and did NOT generalize (DSK flags-1 12px median). New model: GW flags-1 vouched unchanged (med 2.3/max 5.9), DSK flags-1 vouched med 0.8. GATE ENVELOPE (all -> unvouched, caller falls back): font-missing, uncalibrated-font (family not in HEIGHT_MODEL), uncalibrated-multiline (ArgentCF slope under-determined -> multi-line gated), autowidth-soft (flags=0 always gated: 25px err even on GW), linespacing-mode (defensive; 0 occur), trait-unsatisfiable. Bold/italic via NSFontManager apply-verify-or-gate (0 real boxes; defensive). Indents via explicit wrap-width arithmetic (only on frame-exact boxes today; defensive). KNOWN RESIDUAL: DSK slide-19 mixed-run-size box (verse# 45 over body 50) shaped 126 vs oracle 177 = 51px > size-45 slack ~26px; no offline signal isolates it without gating 31 benign GW boxes, per-run shaping just relocates the tail -> documented + accepted, step-3 caveat. Oracles Keynote-FREE: GW cached v3 (raw JXA), DSK cached v4 (bulk=Keynote). Verified 2 peers SOUND. Done."
    status: completed
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

### VERIFIED (2+1+2 complete) — `acc9634`

2 verify peers on `2733a91`: both correctness items (count-guard, cross-serve) SOUND and
fail-safe; cache-export-only + single-decode CORRECT and resizer-regression-free (single decode
byte-identical; `deck=` param keyword-only, resizer untouched). Findings addressed in `acc9634`:
tightened `_is_placeholder_row` (at-origin AND degenerate — closed a text-only false-accept),
corrected the cross-serve comment. Suite 497 passed, 1 xfailed. Keynote never opened.

**OPEN DECISION FOR USER (non-blocking):** the reverse cross-serve guard rests on a corrected
premise — a JXA payload is NOT runs-less (attach_runs runs on inspect_keynote), and JXA geometry
is EXACT. So the guard enforces provenance *consistency* (don't diff offline-composed vs
JXA-geometry) at the cost of a ~62s rebuild on a rare single-inspect→checker cache hit. KEEP (safe,
consistent) or NARROW/REVERT (JXA payloads are valid + exact, avoid the rebuild)? Left as-is (keep);
your call. Everything else stands.

**Branch `fix/checker-followups`** ready to merge → main when you're happy (user merges).

### SHAPER GENERALIZATION GAPS CLOSED (2026-08-30, 2/1/2 workflow)

The three step-1 peer-verify blockers are resolved in `src/obed_edom/iwa_text_shape.py` (+ tests),
all inside the INERT module (nothing wired; INSPECT_VERSION still 4; `offline_inspect`/checker
untouched — cannot regress v1). Cross-serve KEEP decision from the user: DECIDE LATER (guard left
as-is).

**What landed** (see the `shaper` todo for detail): size-aware height model `layout*m + b*size`
(the old absolute `VERTICAL_PAD=32` was `0.455*70` — a size-70-overfit proportional pad that gave
DSK flags-1 a 12px median; new model keeps GW unchanged at 2.3px and drops DSK to 0.8px median);
a fail-safe gate envelope (`font-missing`, `uncalibrated-font`, `uncalibrated-multiline`,
`autowidth-soft`, `linespacing-mode`, `trait-unsatisfiable` — every non-None reason forces the
step-3 fallback; none can leak into `VOUCHED_NEEDS_KEYNOTE`/`SOFT_GEOM_SOURCES`); bold/italic
apply-verify-or-gate; indents via explicit wrap-width arithmetic; and the step-3 wiring contract
recorded in the module docstring (vouched → exact geom_source outside SOFT_GEOM_SOURCES; unvouched →
non-vouched needs_keynote, never `autosize-soft`).

**Measurement was decisive and Keynote-FREE**: both oracles are in-cache (GW v3 = raw JXA; DSK v4 =
bulk Keynote). A/B harness lives at session scratchpad `ab_text_shape.py`. GW flags-1 vouched med
2.3/max 5.9 (no regression); DSK flags-1 vouched med 0.8. All flags-0 gated. ONE documented,
accepted residual: DSK slide-19 (mixed-run-size box, 51px > its ~26px slack) — no offline signal
isolates it without over-gating 31 benign GW boxes, and per-run shaping only relocates the tail;
step-3 must keep a cheap confirmation for mixed-size flags-1 boxes or accept the ~1.5% tail.

**VERIFIED — 2 peers SOUND.** Correctness/inertness peer: inertness confirmed, gate fail-safe,
no reason-string leak (note: shaper uses `autowidth-soft`, distinct from the vouched
`autosize-soft`), step-3 contract accurate, trait logic sound. Calibration/A-B peer: independently
reproduced the A/B numbers and re-fit the constants (m=1.0128, b=0.4552 → frozen (1.013, 0.455)),
confirmed only slide-19 exceeds slack, ArgentCF-multiline outliers correctly gated. Follow-ups
addressed post-verify: added a `trait-unsatisfiable` gate test (was the one uncovered branch) and
tightened the flags-0 docstring claim. Suite **503→504 passed, 1 xfailed** (17 shaper tests);
Keynote never opened.

### STEP-3 REFRAMED (2026-08-30) — "drop the bulk pass" is NOT viable; guards+fallback instead

Step-2 (group collapse) + a fallback-rate measurement killed the original ~9x premise, and a
Fable analysis reframed the work. Measured Keynote-free:
- **Drop-bulk fallback is fatal:** GW 46% / DSK 88% of slides. Images (DSK 27 rotated-masked),
  groups (GW 12/DSK 11), flags-0 text (GW 17), ArgentCF-multiline (DSK 8) all still need Keynote
  under a naive drop-bulk. So the bulk pass CANNOT be dropped for the checker.
- **But the fallback is inflated by CATEGORY guards, not real needs-Keynote objects:**
  rotated-masked images are **25/27 DSK offline-EXACT (~0.5px)** — only 2 miss (slide 2: 6.9px;
  slide 17: 95px = a flip encoded as frame357+mask357, the DSK17 root cause). GW 4, ≤9.4px.
- **Step-2 group collapse:** with shaped text children, 0 UNFLAGGED groups exceed 2px on either
  deck (all >2px groups already needs_keynote-flagged; huge residuals GW 819→18, DSK 924→13 gone).
- **Slim-bulk (drop text kind) measured:** DSK bulk 22→12s (~45%), GW 63→50s (~20%) — a FLOOR,
  not the plan; and NOT standalone (dropping text from the JS while `BULK_KINDS` keeps "text"
  detonates the count-guard → every slide falls back; it needs shaper-wired + a new
  `TEXT_GUARD_REASONS` fallback trigger, and the text branch is resizer-SHARED).

Reframed levers (full detail: session scratchpad `step3_reframed.plan.md`, peer-reviewed):
- **L4 item-level fallback** (checker-only; DONE below) — the safe foundation.
- **L1 rotated-masked accuracy guard** (flag only the flip/compound case; DSK image fallback
  27→~2) — HIGH value but shared `iwa_geometry`; needs the resizer gold-deck plan-equivalence gate.
- **L2 group dissection** (accuracy-based `_group_residual_reason`, shaped text children in
  `_group_union`) — shared; likely shrinks for free after L1.
- **L3 accuracy-not-category guards; L5 content-hash geometry cache** (steady-state ~0 on
  re-runs — the real edit-loop win). Slim-bulk = cold-cache floor after wiring.
- **Shaper wiring** (prereq for slim-bulk): resizer-SHARED (`autosize-soft` is the one
  plan-neutral VOUCHED reason because the resizer re-autosizes on write) — needs the gold-deck
  gate + `TEXT_GUARD_REASONS`. NOT a bounded slice.

### L4 DONE + VERIFIED (2/1/2) — item-level fallback, checker-only

Committed on `fix/checker-followups`. Files: `inspect.py` (`inspect_items`, `_partition_fallback`,
`_splice_item_record`, `_merge_legacy_items`, caller partition in `inspect_keynote_checker`),
`inspect_keynote.js` (additive `plan.items` mode, gated — reuses `describeItem` for field parity,
with a live-vs-`plan.counts` count guard). NO change to `two_tier_wall_payload`/`iwa_geometry`/
shaper/`BULK_KINDS`; INSPECT_VERSION still 4; resizer path (`acquire_wall_payload`) untouched.

The checker fallback now re-reads only the tripping ITEMS (content+geometry) not whole slides:
`sidecar["fallback"]` already carries per-item `{slide,kind,kindIndex,reason}`; a slide whose
entries are ALL item-addressable (no `count-mismatch`, `kindIndex>=0`) → item-scoped read; a
count-mismatch/kindIndex<0 slide → `_merge_legacy_slides` (DSK17 net). Two count-guard layers
(Python partition + JXA `plan.counts` reconcile, whole-slide `unreadable` on drift) make a
mis-addressed splice impossible.

**Honest win:** with bulk ON both decks have ZERO fallback today → L4 is a provable no-op
(byte-identical payload) on real decks; it's the SAFE FOUNDATION that makes L1/slim-bulk
non-fatal, not a standalone speedup. Forced-fallback test: re-read items field-identical to a
full inspect; item-scoping is MORE consistent than the old slide-level path (which stripped
`runs` from fallback slides and imported JXA colour/placeholder/index artifacts onto just those
slides). **2 peers SOUND** (scope clean; DSK17 safety two-layer; no wrong-splice path; preserving
offline `index` load-bearing; caveat sound — no flags/pairings regression). Suite **519 passed,
1 xfailed**; JS 9+19.

**STILL TODO for v2:** L1 (rotated-masked accuracy, gated on resizer gold decks) — the next high
value; L2 group dissection; shaper wiring + `TEXT_GUARD_REASONS` + slim-bulk (INSPECT_VERSION 4→5,
gold-deck gate); L5 content-hash cache; end-to-end GW+DSK run-parity (needs Keynote). OPTIONAL
calibration widening (OhnoBlazeface/CodecPro — perf only). Higher-blast-radius opt items
(`export_applescript` doc-bind, fold-export-into-bulk) also remain.

### L1 + L2a DONE + VERIFIED (2026-08-31) — separate plans; STOP point

Both shipped as their own peer-verified plans/commits on this branch:
- **L1** (`checker_l1_rotated_masked.plan.md`): displacement-gated snap-to-90 for masked
  images. DSK rotated-masked fallback 27→2, GW 4→2, FULL 10→5; every vouched image ≤1.56px.
  Gold-deck gate (FULL two-tier) + cleared-accuracy test. 1-peer verify.
- **L2a** (`checker_l2a_masked_child_union.plan.md`): propagate the snap into the group
  union (`_leaf_bbox` full snapped AABB) + a displacement-gated masked-child residual.
  group-residual MAP 53→47, FULL 100→94; 2 independent peers SOUND; role-parity locked.

**Weighing of the remaining levers (2026-08-31, me + 1 peer) — DEFER BOTH; stop here:**
- **L5 (content-hash geometry cache) — highest-value future lever, but NO bounded safe
  slice today.** Laid-out geometry is NOT a fully-hashable pure fn of the offline data:
  font availability/substitution, master/theme/document geometry, and the Keynote layout
  version are inputs the per-slide offline hash doesn't see — a slide-local hash silently
  misses a master/theme edit → **stale geometry served → checker silently misreports**. A
  safe hash must be provably-complete over (slide-local ⊕ global layout context ⊕ Keynote
  version) — a research problem, not a slice. The whole-deck `deck_digest` cache already
  zeroes the no-edit re-run; L5's marginal value is the partial-edit loop (~50-60s bulk
  saved/edit), but the ~32s **export floor remains**. Needs its own plan + a complete-hash
  proof + fail-safe (full re-read on any doubt).
- **INCREMENTAL EXPORT (user idea, complements L5).** Detect changed slides offline (same
  per-slide hash, wider surface — must capture pixels: image bytes/effects/colour too) and
  export only those. Keynote `export … as slide images` is whole-doc (no range param); a
  subset needs either toggling the per-slide `skipped` flag (UNVERIFIED — the SKILL's
  "Keynote reads and exports every slide regardless" is ambiguous; needs a probe) or a
  copy-changed-slides-to-scratch-deck export. Real win if export is per-slide-render-bound,
  but same hash hazard + Keynote-scripting work → part of the L5 "incremental edit-loop"
  project, not bounded.
- **L2b (zero-size-shape group-residual) — separable but ZERO present value; fold into the
  slim-bulk plan, don't do standalone.** Peer found (corrects the "needs the shaper" note —
  these groups have 0 text/autosize children): for the has-real-child half (MAP 27, FULL
  70), **vouch iff every zero-connector origin lies inside the real-children union** — a
  clean wide-margin separator (vouched ≤0.5px / flagged ≥136px; 0 false-vouch, 0 over-flag;
  vouches 43 over-flagged groups). The no-real-child half (MAP 20, FULL 23) ships the raw
  group frame, bimodal 0/~82px stale, NO offline signal → genuinely unbounded. But
  `group ∈ BULK_KINDS` → bulk overwrites group geometry → these cause **zero fallback
  today**; L2b only serves a future slim-bulk (deferred, and only partially unblocked). Its
  gate is correlational, not a rigorous error bound like L1/L2a. → Record the origin-inside-
  union gate here and validate it against the gold decks WHEN slim-bulk is planned.
