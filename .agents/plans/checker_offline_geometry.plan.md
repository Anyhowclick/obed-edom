---
name: Checker offline geometry — deferred levers & dead-ends
overview: >-
  Single source of truth for the Sermon Checker's offline read. The FOUNDATION IS SHIPPED
  (in git, not to redo): the checker reads a deck offline (IWA addressing + style + exact
  shape/line geometry) and splices a slim O(slides) bulk Keynote pass for the soft classes
  (group/image/movie/text), ~3.25x cold, accuracy-identical, with item-level fallback. The
  Keynote PROBES are now DONE too (see "Probe results"): e2e-run-parity passed, and the
  hash-probes decided the incremental edit-loop design (byte keys dead → decoded +
  style-RESOLVED fingerprint). This file keeps only what is OPEN — the deferred levers with
  their blockers and the measured dead-ends. Two independent tracks remain: (A) the
  EDIT-LOOP project (slide-fingerprint SHIPPED → l5-bulk-cache → incremental-previews) —
  the ONLY thing that speeds a small-edit reload (cold reads already got
  their ~3.25x); (B) slim-bulk (shaper-wiring → slim-bulk, folding in l2b-group-frame) to
  cut the cold bulk tier. See "Next up". Read the SKILL "Reading a .key offline (IWA)"
  first. iwa_geometry is resizer-SHARED — changes land behind the gold-deck gate
  (tests/test_offline_inspect.py).
todos:
  - id: slim-bulk
    content: >-
      Drop kinds from the bulk Keynote pass (BULK_KINDS) to cut the ~61s cold bulk tier.
      Measured floor: dropping text → DSK bulk 22→12s (~45%), GW 63→50s (~20%). NOT a
      bounded slice: the text branch is resizer-SHARED, and dropping "text" from the JS
      while BULK_KINDS keeps it detonates the count-guard (every slide falls back). Needs
      (a) the shaper WIRED (see shaper-wiring), (b) a new TEXT_GUARD_REASONS fallback
      trigger, (c) INSPECT_VERSION 4→5, (d) the resizer gold-deck gate green. Dropping
      image/group later folds in L2b's origin-inside-union gate (see l2b-group-frame).
    status: pending
  - id: shaper-wiring
    content: >-
      Wire iwa_text_shape (BUILT + inert + generalization-gaps-closed, nothing calls it;
      INSPECT_VERSION still 4) so autosize TEXT geometry comes from offline AppKit
      NSAttributedString shaping instead of the bulk pass — the prereq for slim-bulk's
      text drop. Resizer-SHARED: `autosize-soft` is the ONE plan-neutral VOUCHED reason
      (the resizer re-autosizes on write), so it can be trusted; every other shaper gate
      reason forces fallback. GATE ENVELOPE (all → unvouched → fallback): font-missing,
      uncalibrated-font, uncalibrated-multiline (ArgentCF slope under-determined),
      autowidth-soft (flags=0 always gated, ~25px err), linespacing-mode, trait-
      unsatisfiable. Height model is SIZE-AWARE (layout*m + b*size per family). KNOWN
      RESIDUAL kept: DSK slide-19 mixed-run-size box (verse# 45 over body 50) shapes 126
      vs oracle 177 = 51px > slack ~26px; no offline signal isolates it without gating 31
      benign GW boxes, and per-run shaping only relocates the tail — slim-bulk must keep a
      cheap confirmation for mixed-size flags-1 boxes OR accept the ~1.5% tail.
    status: pending
  - id: l5-bulk-cache
    content: >-
      NEXT — now unblocked (slide-fingerprint SHIPPED). Consume `slide_fingerprint.
      fingerprint_deck`: gate the whole store on the `global` key (rebuild all on a bump),
      key each cached bulk-geometry row on the per-slide `slides[i]` key, and treat a slide in
      `uncacheable` as always-changed (never cache it). The L5 lever, bounded to the checker's
      BULK TIER (~50-60s/edit → the changed-slide
      fraction; the export floor remains (~0.64s/slide, P3) → incremental-previews; the
      whole-deck deck_digest cache already zeroes the no-edit rerun — L5's value is ONLY the
      partial-edit loop). Rationale unchanged from the original blocker: laid-out
      geometry is NOT a pure fn of slide-local bytes (fonts, master/theme/document
      geometry, Keynote version) — the slide-fingerprint keys operationalize exactly that
      surface. Implementation: a caching WRAPPER passed as bulk_geometry_fn at the
      inspect.py:545 injection point — NEVER inside inspect.bulk_geometry itself
      (resizer-SHARED via acquire_wall_payload, remap_keynote.py:171). The wrapper MUST
      merge cached rows for unchanged slides into a COMPLETE bulk map before the splice:
      _splice_bulk_geometry skips slides absent from the map and every soft item there
      becomes a bulk-missing fallback (offline_inspect.py:621,743) — so pass only changed
      indices to the already-subset-capable bulk read (bulk_geometry.js plan.slides) AND
      splice cached rows for the rest, else the scheme detonates into mass fallback on
      precisely the slides it meant to skip. SAFETY, stated precisely: on a cache hit the
      count-guard is a TAUTOLOGY (a hit means offline counts are unchanged — cached rows
      get compared against the very payload they were validated on); it catches
      cache-scheme addressing bugs, NOT stale values. Staleness protection = key
      completeness + a VERIFY-SAMPLE burn-in (re-read k random cached slides per run,
      compare, alarm on any mismatch → a measured staleness rate before trust). No
      INSPECT_VERSION bump (payload shape and values unchanged); reverse cross-serve
      guard unaffected (reader stays "offline"; separate store). The new store must carry
      a source-path marker so cache-cleanup's protected-paths split still works.
    status: pending
  - id: incremental-previews
    content: >-
      Beat the whole-deck export floor (~0.64s/slide, P3) for the partial-edit loop — now
      gated only on slide-fingerprint (P2+P3 done; same project as l5-bulk-cache, shares its
      hash hazard). P2 CONFIRMED the skipped-flag route excludes skipped slides, so it is a
      viable subset-export mechanism. Keynote `export … as slide images` is whole-doc (no
      range param). Per-slide preview
      cache keyed by the slide fingerprint — its WIDER pixel surface is already covered:
      Data CRCs capture image bytes, the slide iwa captures effects/colour, the global
      key captures theme/master backgrounds. Export only missed slides via
      subset_keynote OR P2's skipped-flag route — a subset deck's filenames renumber
      sequentially over kept slides in kept order, so map-back to original numbers is
      deterministic. RENDER-DIVERGENCE hazards of a subset deck: slide-number
      placeholders (position-dependent digits; offline detection is a TO-BUILD —
      iwa_runs strips the attachment char untyped, and masters can carry the field),
      auto date/time fields (also stale in today's whole-deck preview cache), and the
      subset copy being re-SAVED by Keynote (render parity of the laundered copy vs the
      original is assumed — verify on gold decks). The doc-bind bug (opt-higher-blast
      item 1) is WORST-CASE here — give every scratch deck a unique basename per run.
      MERGE contract: rename cached+fresh PNGs to ONE uniform prefix carrying original
      document numbers, exactly slideCount files (folder_digests orders by filename sort;
      mapping parses the last stem integer; the hardened hit needs have == slideCount).
      Verify: pixel-compare incremental vs full export on the gold decks + DSK.
    status: pending
  - id: l2b-group-frame
    content: >-
      Zero-size-shape group-residual accuracy (after L2a, the dominant group-residual
      branch: MAP 47, FULL 93). SEPARABLE and does NOT need the shaper (these groups have 0
      text/autosize children). For the has-real-child half (MAP 27, FULL 70): VOUCH iff
      every zero-connector child origin lies inside the real-children union — a clean wide-
      margin separator (vouched ≤0.5px / flagged ≥136px; 0 false-vouch, 0 over-flag;
      vouches 43 over-flagged groups). The no-real-child half (MAP 20, FULL 23) ships the
      raw group frame (bimodal 0/~82px stale, NO offline signal) → genuinely UNBOUNDED. But
      group ∈ BULK_KINDS → the bulk splice overwrites group geometry → ZERO present value
      (no fallback today); only serves slim-bulk's image/group drop. Its gate is
      correlational, not a rigorous error bound like L1/L2a. → Fold into the slim-bulk plan
      and validate against the gold decks there; do NOT ship standalone.
    status: pending
  - id: opt-higher-blast
    content: >-
      Higher-blast-radius optimisations (own pass, careful — they touch ALL exports): (1)
      export_applescript (inspect.py:44) uses the disproven doc-bind (no close-by-name) →
      could silently export the WRONG deck's bytes; every checker export goes through it.
      (2) fold the preview export into the bulk_geometry Keynote session (a cold diff opens
      Keynote ~4×) → ~8s/diff. (3) r-count-guard "(a)" extension: per-slide shape/line
      counts in bulk_geometry.js. (4) SHIPPED BUG (found by P2): the hardened cache hit needs
      have == slideCount PNGs, but `export … skipped slides:false` writes only
      slideCount − skipped, so ANY deck with a skipped slide re-exports on every warm hit —
      fix by comparing against slideCount − skipped, or export `skipped slides:true`. OPTIONAL:
      calibration widening (OhnoBlazeface/CodecPro — perf only, no accuracy change).
    status: pending
  - id: cache-cleanup
    content: >-
      Parked (own plan→peer→implement→verify). .cache/inspect + .cache/previews are keyed
      by deck digest only — no marker separating throwaway user checker decks from gold/dev
      decks (Map, Full, Base_CG_Assets, Sermon_PK); every payload stores its source `path`,
      so the split is recoverable. Proposed: a protected-paths allowlist (gold/dev dirs) +
      a History-tab cache manager (name/path/slides/size/last-used per cached deck, gold/dev
      rows protected, one-click clear-all-non-protected). _purge_artifacts deliberately
      never touches .cache/ (warm cache ~hour to rebuild).
    status: pending
  - id: cross-serve-decision
    content: >-
      OPEN DECISION (user's call, non-blocking). The reverse cross-serve guard rejects a
      cached non-offline (JXA-geometry) payload on a single-inspect→checker cache hit and
      rebuilds (~62s). The premise it rests on is corrected — a JXA payload is NOT runs-
      less (attach_runs runs on inspect_keynote) and JXA geometry is exact — so the guard
      enforces provenance CONSISTENCY (don't diff offline-composed vs JXA geometry) at the
      cost of that rebuild. KEEP (safe, consistent) or NARROW/REVERT (JXA payloads valid +
      exact, avoid the rebuild)? Currently left as KEEP.
    status: pending
isProject: false
---

# Checker offline geometry — deferred levers & dead-ends

Single source of truth for the checker's offline-geometry read. The build history (v1
cold-inspect, the four low-risk follow-ups, L4 item-level fallback, L1, L2a) is shipped
and lives in git; the Keynote probes (hash-probes, e2e-run-parity) are done (see "Probe
results"); this file keeps only what is still open, and the measured dead-ends so they are
not chased again. **Read the SKILL "Reading a `.key` offline (IWA)" first.**

## Next up (ordered)

Two independent tracks. Each lever follows the 2+1+2 loop (peer-reviewed plan → sub-agent
implements → independent verify).

- **Track A — edit-loop (faster small-edit reloads; NO cold-read gain).** The payoff the
  user cares about, now unblocked by the probes.
  1. **`slide-fingerprint`** — SHIPPED (`src/obed_edom/slide_fingerprint.py`, INERT). See
     "Shipped foundation".
  2. **`l5-bulk-cache`** — START HERE. Cache bulk-geometry rows per unchanged slide, keyed
     by the fingerprint (wrapper at the `bulk_geometry_fn` injection point).
  3. **`incremental-previews`** — export only changed slides (P2 confirmed the skipped-flag
     route excludes); merge with cached PNGs.
- **Track B — cold bulk slimming (independent).**
  4. **`shaper-wiring`** — wire the inert `iwa_text_shape` (prereq for the text drop).
  5. **`slim-bulk`** — drop kinds from `BULK_KINDS`; folds in `l2b-group-frame`.
- **Standalone.** **`opt-higher-blast`** now has a quick win: the P2 skipped-slide
  re-export bug. **`cache-cleanup`** (parked) and **`cross-serve-decision`** (user's call).

## Shipped foundation (context, not to redo)

- **Two-tier read.** `offline_wall_payload` (IWA addressing via `derive_kind_index`,
  per-run style, exact shape/line/plain-frame geometry) + `two_tier_wall_payload` splicing
  a slim O(slides) bulk Keynote read of `position`/`size` over the soft classes
  (`BULK_KINDS = group/image/movie/text`). ~3.25x cold, accuracy-identical, checker-scoped
  (other `inspect_keynote` callers untouched). `INSPECT_VERSION = 4`.
- **Guards + fallback.** Count-guard (`iwa_kindindex.reconcile_counts`) + `reader`
  provenance; L4 item-level fallback re-reads only the tripping items, whole-slide
  `_merge_legacy_slides` on a count-mismatch/kindIndex<0 slide (the DSK17 net). Content
  guards (`font-size-unresolved`, `filename-dirty`) survive the splice; geometry guards are
  cleared once the bulk read confirms the item.
- **Accuracy guards (iwa_geometry, resizer-SHARED, behind the gold-deck gate).**
  **L1** — masked images vouched via displacement-gated snap-to-90 (error ≤ displacement +
  ~0.5px; DSK rotated-masked 27→2). **L2a** — the same snap in the group union
  (`_leaf_bbox`) + a displacement-gated masked-child residual (group-residual MAP 53→47,
  FULL 100→94). Both proven plan-neutral for the resizer (soft classes are bulk-overwritten)
  and locked by `test_l2a_cleared_masked_child_groups_are_write_safe` incl. role-parity.
- **The shaper.** `iwa_text_shape` is BUILT, calibrated, generalization-gaps-closed — and
  INERT (nothing calls it). It is the prerequisite for slim-bulk's text drop (see the
  `shaper-wiring` todo).
- **The slide fingerprint.** `src/obed_edom/slide_fingerprint.py` `fingerprint_deck(key_path,
  *, deck=None, font_env=None) -> {"global": hex, "slides": [hex|None], "uncacheable":
  {i: reason}}`. INERT (nothing consumes it) — the save-churn-immune content key `l5-bulk-cache`
  / `incremental-previews` build on. Per-slide key = id-normalized BFS closure of the slide's
  decoded graph (numeric refs → positional tokens so a save's renumber washes out), folding
  every DIRECTLY-referenced style archive (~20 reached types, not just char/para) + image bytes
  as `data:CRC:size` (central directory, media never read) + document position/skip. Global key
  = id-masked non-slide files (masters + `Document.iwa` stay in) minus a justified exclusion
  set + font-env + OS build; Keynote version rides `baseline._app_tag`. **The one design fact
  a consumer must know:** `TSS.StylesheetArchive` is a HARD closure boundary — it is a
  `canCullStyles` name→id catalog Keynote recompacts on EVERY save, so folding it churned 42/42
  DSK keys per no-op save; bounding it out gives 0/42 with zero style-coverage loss (applied
  styles are reached by direct ref). Uncacheable (a MISS, never stale) on undecodable-slide /
  cross-slide-ref / dangling-ref. Built + independently verified via the 2+1+2 loop; the
  acceptance contract is proven end-to-end on the real DSK deck (no-op save → 0 keys move,
  global identical; edit slide k → only key k moves) plus 28 unit tests (incl. churn-immunity
  under an order-scrambling id bijection). CRC-32 is non-cryptographic (accident detection for
  a personal workflow, stated as such). The Phase-0 measurement corrected two literal-P1 points:
  (a) "resolve char+para props" was incomplete (slides reach ~20 style types) → fold the whole
  id-normalized closure instead; (b) global "byte-concat of non-slide entries" churns every save
  → NORMALIZE (id-mask) those files, don't byte-hash.

## Probe results — measured 2026-08-31 (peer-verified)

Scratch probes (no product code) that settle `hash-probes` + `e2e-run-parity`. The
edit-loop levers give **no cold-read gain** (the ~3.25x two-tier read already did that);
their only value is a faster reload after a *small edit to an already-seen deck*.

- **P1 save-churn → byte-level keys are DEAD; use the decoded, style-RESOLVED graph.** On
  scratch copies of the DSK deck: a **no-op open+save** changes the CRC of `Index/Document.iwa`
  AND `Index/DocumentStylesheet.iwa` (plus `CalculationEngine`, `DocumentMetadata`, `Metadata`,
  a `TemplateSlide`, one `Slide-*.iwa`; `ViewState` renumbers). Decoding the two globals: the
  no-op churn of `Document.iwa` (the slide tree — order/skip) is **2 id-like scalars, 0
  structural** (cheap to normalize), but `DocumentStylesheet.iwa` genuinely **compacts its style
  table 526→512** and renumbers archives on every save. So the global stylesheet cannot be
  byte- or position-hashed; the safe design folds each slide's *resolved* referenced-style
  properties into that slide's key (the `iwa_runs` super.parent resolver already does this)
  rather than hashing the churning global table. Confirms `slide-fingerprint`'s style-RESOLVED
  branch is REQUIRED, not optional.
- **P2 skipped-flag export → the SKILL is wrong here, and there is a shipped bug.**
  `export … as slide images with properties {skipped slides:false}` **EXCLUDES** skipped
  slides (35 PNGs, contiguously renumbered 001–035, on a 42-slide deck with 7 skipped). So the
  subset-export mechanism for `incremental-previews` works. It also means today's hardened cache
  hit (`have == slideCount`, inspect.py) **can never be satisfied by a deck that has a skipped
  slide** — such a deck re-exports (~its export cost) on EVERY warm run. Worth fixing in
  `opt-higher-blast`: count against `slideCount − skipped`, or export `skipped slides:true`.
- **P3 subset timing → floor corrected; subset is directionally worth it, not "3x".** The
  whole-deck export floor is **~0.64 s/slide (~100 s for the 155-slide Full deck), NOT the
  ~32 s cited elsewhere** (that figure was a smaller deck). APFS `ditto` of the 6.8 GB deck is
  **~4 s** (copy-on-write clone — the copy is nearly free, correcting the "copy is expensive"
  assumption). Both subset routes land ~31–33 s keeping 2 of 155, but the honest comparison is
  **Route A** (subset-copy: ~4 s ditto + ~29 s open/delete/save) — Route B's timer starts after
  the deck open and is dominated by an O(N) 153-slide skip-marking loop, so its number is not
  comparable. Takeaway: exporting only the changed slides beats a whole-deck export on large
  decks, capped by the O(N) per-slide skip/delete overhead.
- **e2e-run-parity → offline+bulk is end-to-end sound (one benign divergence).** GW(LW)+DSK,
  offline+bulk vs full-JXA, same previews reused for both diffs: pairing IDENTICAL (47), markup
  IDENTICAL, flags 43/44 identical. The lone difference — LW slide 21, `photo.rotated` (offline,
  composed 354°) vs `photo.differs` (JXA), same slide/severity — is the documented masked/flipped
  angle-composition edge (an L1 residual), benign. The strict byte-identical harness gate reports
  FAIL on that single flag; the operator sees the same slide flagged either way.

## Dead-ends — measured, keep so they aren't chased again

- **"Drop the bulk pass entirely" (~9x) is FATAL.** Naive drop-bulk falls back on GW 46% /
  DSK 88% of slides (rotated-masked images, groups, flags-0 text, ArgentCF-multiline all
  still need Keynote). The bulk pass cannot be dropped for the checker — only SLIMMED
  (drop specific kinds once their offline read is vouched). This killed the v2 premise.
- **Category guards cried wolf.** The images/groups the old guards flagged were mostly
  offline-exact; the fix was accuracy-based flags (L1/L2a), not dropping the bulk pass.
  A conservative guard is not a hard limit — measure the residual before trusting a flag.
- **Offline WRITE of a whole deck corrupts it.** `keynote-parser` decode→re-encode→rezip is
  byte-lossy (a 232 MB deck opens as a valid-zip/corrupt-content file); only a SURGICAL
  single-slide rewrite (copy every other IWA verbatim) is viable, and even that needs
  per-deck openability testing (un-built spike). So generate's superscript GUI pass stays.
- **PPTX-export geometry route** (complementary: nails autosize WIDTH in one ~77s export)
  is unneeded while the two-tier bulk read works; keep it only as the fallback if the bulk
  read is ever dropped for autosize width.

## Notes for whoever picks up a lever

- **Re-run `scripts/e2e_run_parity.py` after any read-path change** (slim-bulk, l5-bulk-cache,
  incremental-previews) to confirm no operator-visible finding (pairing/flags/markup) moved.
  It runs the checker offline+bulk vs full-JXA on the Sermon_PK pair; the known-good baseline
  (one benign slide-21 photo divergence) is in its docstring — a different/extra diff is the
  regression signal.
- Anything touching `iwa_geometry` is **resizer-SHARED** → it must keep the gold-deck gate
  (`_assert_two_tier_gate_green` MAP+FULL) green and add a cleared-accuracy test in the L1/
  L2a mould (vouched ⇒ within 2px AND same pin/map role as JXA).
- Non-trivial changes follow the 2+1+2 loop: peer-reviewed plan → a **sub-agent** implements
  (NOT the planner — the author can't neutrally verify their own code) → independent peers
  verify. Doc/measurement-only work (like this consolidation) is exempt.
