---
name: Checker offline geometry — deferred levers & dead-ends
overview: >-
  Consolidated plan for the Sermon Checker's offline-geometry read (supersedes the v1
  cold-inspect plan, the v2 "drop the bulk pass" plan, and the L1/L2a plans — all
  shipped). The FOUNDATION IS DONE: the checker reads a deck offline (IWA addressing +
  style + exact shape/line geometry) and splices a slim O(slides) bulk Keynote pass for
  the three soft classes (group/image/movie/text), ~3.25x cold, accuracy-identical, with
  item-level fallback. This file keeps ONLY what is still open: the deferred levers
  (each with its known blocker) and the measured dead-ends, so they are not re-derived.
  Read the SKILL "Reading a .key offline (IWA)" first. iwa_geometry is resizer-SHARED —
  any change to it lands behind the gold-deck gate (tests/test_offline_inspect.py).
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
  - id: hash-probes
    content: >-
      BOUNDED PROBES (scratch scripts, no product code; needs Keynote free — batch with
      e2e-run-parity) gating the incremental edit-loop project (slide-fingerprint →
      l5-bulk-cache → incremental-previews). P1 SAVE-CHURN (decisive): on a scratch copy
      of a gold deck, edit ONE slide in Keynote + save, plus a no-op open/save, and diff
      the FULL zip central directory (all members STORED, per-entry CRC-32+size, ~ms to
      read). Named suspects are the GLOBAL files, not the slide files: Document.iwa holds
      the slide tree (order/skip — verified) and DocumentStylesheet.iwa holds the
      document-wide style table a one-slide text edit can rewrite; if either churns on
      every save, byte-level keys are worth zero even with clean Slide-*.iwa behaviour.
      Outcomes: (a) only the edited slide file + noise (Metadata/*, preview*.jpg,
      ViewState*) churn → byte-level fingerprints; (b) churn/id-renumbering → hash the
      decoded per-slide graph instead — id-normalized, or style-RESOLVED if the
      stylesheet renumbers (decode measured 1.5s Map / 3.5s Full; inherits _load_deck's
      silent skip of undecodable IWAs → such slides are uncacheable). P2 SKIPPED-FLAG
      EXPORT probe on a scratch copy: settles the SKILL's ambiguous "exports every slide
      regardless" — and NOTE it validates an assumption today's code ALREADY makes: the
      hardened cache hit requires have == slideCount PNGs under `skipped slides:false`
      (inspect.py:614-621), so if skipped slides are excluded, a deck with skipped slides
      re-exports ~32s on EVERY warm hit today. P3 TIMING: subset_keynote keep-2-of-155
      (ditto + open + ~150 per-slide deletes + save) vs the ~32s whole-deck export floor.
      subset_keynote.py/js EXIST but are UNEXERCISED (no caller, no test, dormant since
      1524ab6) — a primitive, not a shipped path.
    status: pending
  - id: slide-fingerprint
    content: >-
      INERT per-slide fingerprint module (P1 decides byte-level vs decoded-graph
      representation; nothing consumes it → zero risk). Supersedes L5's "provably-
      complete hash" demand with a CONSERVATIVE PARTITION: hash EVERYTHING, split
      slide-local vs global, so over-inclusion costs only cache misses, never staleness.
      Per-slide key = H(the slide's Index/Slide iwa entry ⊕ referenced Data/* entries'
      central-directory CRC+size ⊕ the slide's DOCUMENT POSITION — position closes the
      duplicate-slides / slide-number-field hazard for free, since reorders already
      invalidate the global hash via Document.iwa). Global key = H(ordered canonical
      concatenation — NOT xor — of every non-slide entry minus a TINY per-file-justified
      noise exclusion list ⊕ font-env fingerprint ⊕ OS build); Keynote app version rides
      the existing .k cache tag (baseline.py:89). The exclusion list is THE one staleness
      door: anything doubtful stays hashed (a miss, never a stale serve). Partition
      gotchas (measured): bare Index/Slide.iwa IS a real slide's file on Full (id
      17558158) — key slide files off slide_order ids, never a Slide-<digits> glob;
      ViewState is id-suffixed. REACHABILITY VALIDATOR via _load_deck's id_to_file: walk
      each slide's reachable graph, assert every ref lands in the slide's own file or a
      global file (measured: ZERO cross-slide refs on both gold decks; 0.2s/1.9s on the
      decode the checker already shares); numeric refs only (string `identifier`s are
      style names), classify Data-id numerics, dangling id (Map has one: 1344) or an
      undecodable slide file → slide UNCACHEABLE; assert id uniqueness. Font fingerprint:
      _ns_font/font_missing give only missing/trait booleans — add the resolved font's
      file URL + mtime/size (CTFontDescriptor) and enumerate names referenced from
      masters too. CRC-32 is non-cryptographic — accident detection for a personal
      workflow, stated as such. Ships with tests against P1's scratch decks (edit slide
      k → only key k changes; touch the theme → global key changes).
    status: pending
  - id: l5-bulk-cache
    content: >-
      The L5 lever, bounded to the checker's BULK TIER (~50-60s/edit → the changed-slide
      fraction; the ~32s export floor remains → incremental-previews; the whole-deck
      deck_digest cache already zeroes the no-edit rerun — L5's value is ONLY the
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
      Beat the ~32s export floor for the partial-edit loop (gated on P2+P3 +
      slide-fingerprint; same project as l5-bulk-cache and shares its hash hazard).
      Keynote `export … as slide images` is whole-doc (no range param). Per-slide preview
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
  - id: e2e-run-parity
    content: >-
      OUTSTANDING VERIFY GATE (needs Keynote free): run the real checker on GW + DSK via
      the offline+bulk path vs a full-JXA run and diff pairings/flags/markup end-to-end.
      Geometry A/B is proven (overflow-flag 63/63 on GW, 0 fallback); this is the last
      whole-pipeline confirmation the v1 plan left open.
    status: pending
  - id: opt-higher-blast
    content: >-
      Higher-blast-radius optimisations (own pass, careful — they touch ALL exports): (1)
      export_applescript (inspect.py:44) uses the disproven doc-bind (no close-by-name) →
      could silently export the WRONG deck's bytes; every checker export goes through it.
      (2) fold the preview export into the bulk_geometry Keynote session (a cold diff opens
      Keynote ~4×) → ~8s/diff. (3) r-count-guard "(a)" extension: per-slide shape/line
      counts in bulk_geometry.js. OPTIONAL: calibration widening (OhnoBlazeface/CodecPro —
      perf only, no accuracy change).
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
and lives in git; this file keeps only what is still open, and the measured dead-ends so
they are not chased again. **Read the SKILL "Reading a `.key` offline (IWA)" first.**

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

- Anything touching `iwa_geometry` is **resizer-SHARED** → it must keep the gold-deck gate
  (`_assert_two_tier_gate_green` MAP+FULL) green and add a cleared-accuracy test in the L1/
  L2a mould (vouched ⇒ within 2px AND same pin/map role as JXA).
- Non-trivial changes follow the 2+1+2 loop: peer-reviewed plan → a **sub-agent** implements
  (NOT the planner — the author can't neutrally verify their own code) → independent peers
  verify. Doc/measurement-only work (like this consolidation) is exempt.
