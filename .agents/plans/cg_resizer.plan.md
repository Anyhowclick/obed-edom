---
name: CG resizer — optimizations (read + write tracks), bug backlog, features
overview: "Single active plan for the CG resizer. As of 2026-09-07, R2 validated-readback has passed ranged and four-deck whole-deck parity, so R2b propose caching is unblocked. R0.1–R0.3 are code-complete and independently approved; the remaining R0 work is the misc cleanup slice, followed by the pack-list residuals. The restored full-report inputs enabled a fresh whole-deck W1 `offline_write_ab.py` bank on 2026-09-07. The gate completed RED: the surgical write's own consistency/live verification passed at 0.00px, but A/B stat-finalize parity and 12 slides' identity geometry failed. Both reusable decks and run records are banked for Keynote-free diagnosis; W1 remains opt-in/default OFF and W2 stays gated on W1. The old single-slide `write_gate_ab.py` Map bank remains absent but was superseded by this whole-deck gate. Read `.agents/skills/obed-edom/SKILL.md` first. Measure first, never run Keynote concurrently, use copies for live probes, and obtain the owner's explicit hands-off acknowledgement for long Keynote runs. No PRs unless asked."
todos:
  - id: output-bugs-batch1
    content: "DONE 2026-09-03 — code-complete AND live-verified (2/1/2: sonnet+opus planners, fresh sonnet implementer, sonnet+opus reviewers, two live Map remaps). Commits: 90aaa4e F nits; 171fc65 E backdrop y=0; e689c23 A badge_raise_report + obedRaiseItem plate→globe→text on every remapped slide (three gates relaxed); 56a735c C card stroke restore-to-source (ONE Index/DocumentStylesheet.iwa patch, unconditional, guarded out<src and out≤src·canvas_scale·1.1, pairing by (colour,pattern)); caee7a0 B1/D1 caption-bearing groups (≥3-char leaf text, checked in classify_item only) are `other` not `pin`; 95c722b review nits; f9261b7 + 8e5d3b2 A2 geometry-guarded badge raise (the first live run showed the image-index raise hitting the MAP on reuse slide 6 — index drifted by one — so plate/globe rows carry the planned CG frame, `<kind> idx` is accepted only within 3px, else one bulk read per property scans for the unique match, else skip+report; title stays on the content search). LIVE RESULT (output/batch1-verify.key, previews output/previews/batch1-verify/): verify_batch1.py PASS — badge above the map on slides 1–7, backdrop y=0, stroke 18316959 = 3.0 after pass 2's save, 0 caption overflow; verify_slide9.py PASS — 66/66 text groups at 0.483×, frontmost, unions within 1.3% of plan (live runs at f9261b7; 8e5d3b2 is error-path accounting only, osacompile-checked); score_resize identical before/after (cached payloads carry no child text, so it does not exercise B1 — the gold side of the scorer still classifies without child text, a known asymmetry). The '+' marks were Keynote's editor-only clip badge (exports show none). Residual nits from review (not blocking): scorer gold-side classification asymmetry; `result['cardStroke']` has three shapes; PIN origin guard is looser with 32 fewer pins."
    status: completed
  - id: card-template-size-reflow
    content: "DONE 2026-09-03 — BATCH 2 code-complete AND live-verified (2/1/2: sonnet+opus planners, fresh sonnet implementer, sonnet+opus reviewers, one live Map remap). Commits: 0ad68b0 iwa attach_group_captions + shape_padding; 0cdcd2b template card size + job-scoped caption step-down + grid re-pitch/reflow; 753acef score_resize attachers + card lane. What shipped vs the accepted item: cards = wall groups with ONE caption leaf (≥2 words, non-numeric) + aspect within 2% of the template card group (slide 12, 120.37×100) take the template rect; caption = template swatch 10pt Amplitude-Bold stepped down whole points while the AppKit-measured line exceeds box − 2·inset (inset = the shape's own padding, 4.0pt — NOT iwa_text_shape.TEXT_INSET), floor 8; the size travels JOB-SCOPED (child_resize captionPt → obedStatJob leafPt) because 38/44 slide-4 captions also occur as roster-list leaves, so the global exact-text size_map was unsafe; the pitch is TEMPLATE-derived from the 3-card L the owner added to slide 12 (gutters 7/7 → pitch 127/107 from payload ints), wall-derived + stroke+7 floor only for a single-card template; grid = 6 columns right-aligned beside the map, origin descending below stat blocks while the grid still fits (slide 4 y0=176, slide 5 y0=392), reading order kept; slide 5 (27 cards, 7→6 cols) included. LIVE (output/batch2-verify.key, previews output/previews/batch2-verify/): 71 cards matched, exactly the 5 predicted 9pt step-downs, 0 off-canvas cards, off-frame 29 → 2 (slides 7/8 pre-existing), 4 + 6 cards overlap stat blocks (reported; owner accepted — gold hand-reshaped those), clearance 4.0/4.0pt (below the batch-1 ≥7pt guideline; template-authoritative, reported), verify_batch1 + verify_slide9 PASS, pass-2 counts identical to batch 1. Gold agreement 70/71 (Bian Lan 9 vs gold 8, accepted). First live attempt crashed on a variable shadowing `source` in a say() line — no offline gate reaches remap_keynote's say path; the live run is that gate."
    status: completed
  - id: w-offline-write-stabilise
    content: "TRANCHE 1 (W1). SHIPPED ec20f4b/a8b27ac/5577e27 (OBED_OFFLINE_WRITE off|on|verify, default OFF = byte-identical production; deck-level patcher, streaming in-place rewrite, reconcile_counts refuse gate, AS fallback, read-back verify, scripts/offline_write_ab.py). The 'pass-2 0.48× group shrink' was an ORACLE ARTIFACT (banked specs_slide9.json + A_prime predate 8a8ef7a); the offline write itself is correct and survives pass 2. 2026-09-04 evening: GOLD BASELINE A/B KIT built and run — `remap` on main 869a28f vs this branch f083a67, PRODUCTION DEFAULT PATH (offline write OFF) — NO regression: geometry 0.00px on all 19 Gold slides, styles identical; the only diff between runs is Keynote's own drawablesZOrder scrambling (see w-zorder-patch). So the branch is safe to sit on at default OFF. Separately, opt-in mode (`on`) has a SEVERE REGRESSION, now root-caused: the IWA patcher writes correct frames but leaves Keynote's render-derived fields stale — shape pathsource naturalSize for non-bezier sources (`_find_bezier` only knows bezierPathSource), masked images (originalSize + mask naturalSize never written, displacement parked in the mask), text naturalSize never written, group children inheriting all of it. Content renders ÷4 inside otherwise-correct frames: 587 stale objects on the 12 offline Gold slides, 0 on the AppleScript ones. `verify_offline_frames` is structurally blind to this (compares the bytes it just wrote; skips masked/groups/text) — this also explains badgeUnresolved (10 Gold / 84 Full: stale-naturalSize plates + globes with a 467px anchor drift); the badge probe is correct and must stay as-is. So 'Map deck gate GREEN' in the tranche-1 handover was luck of object classes, not a clean gate. FIX SCOPE (2/1/2 planning, feature branch, in progress): universal path-natural writer (scalar corner constant, editable-bezier nodes rescaled per production); hard-miss on any unwritable field → AppleScript fallback for that object; masked media REFUSE for now; groups refuse on any unwritable descendant; text width naturalSize written (height stays informational); a spec-independent consistency audit (naturalSize==size, mask naturalSize==mask size, originalSize==size, mask offset within frame, 2% tol) that fails the run. TO CLEAR: (1) SUPERSEDED — see below, the whole-deck gate replaced the single-slide re-bank plan; (2) re-run offline_write_ab.py with a HEALTHY A (Accessibility granted; gate must hard-fail on an unhealthy A: pass-2 done/skipped counts, dedup counts), plan-as-oracle for exact classes, identity matching, group children bucketed separately, groups compared as a SET; (3) default-flip bar = gate GREEN on both gold decks with real patches AND one end-to-end `on` run placement-identical to a scripted run, now including the consistency audit. FLIP STAYS ON HOLD. The Full-deck A/B bank under output/offline-write-ab-full/ was deleted with output/ (owner); on 2026-09-07 the owner restored Full_Report_Card_Wall.key and the Full_Report_Card_CG.key reference, while Base_CG_Assets.key remains available, so a fresh ~1h-plus whole-deck bank is runnable. Design points that stand: deleteHides stays in pass 1 and the patcher bridges kindIndex (never both); reuse slides stay fully in Keynote; the JXA attrs pass stays in pass 1; mapReadback assertion moves to the verify. Payoff: replaces the ~100ms/command AS geometry phase (~100–155s Map, multi-minute Full) with seconds. UPDATE 2026-09-04 (fe44f6b) — the gate was hardened and earned its keep: 49cbc7e whole-deck gate (Accessibility pre-flight, clean-pass-2 bars, identity matching by drawable id — output ids == source ids on every non-reuse slide — plan-as-oracle for the exact classes via _spec_box, run records with digests, --mode on|verify, --no-validate); 36e2d81 REAL patcher defect found by the gate and fixed (iwa_write._text_fields wrote size_h onto an autosize text box whose stored h==0.0 is the sentinel; B's slide-8 text became a fixed 43pt frame); 6ac80d8 every bucket gates at doubled per-side budgets (measured Map: line 0.95 group 1.43 child:image 1.83); 3ca6385 refuses open Keynote docs + closes own stray decks; 08d2e2b --pass2-bar parity; 94df47f bulk-tier errors loud+durable (bulkErrors rides the cache) + gate quits Keynote between runs. MAP DECK GREEN in verify AND on modes (output/offline-write-ab-v2, -on; identity 100%, plan oracle B exact 0.00px, A ≤0.49 = AppleScript integer rounding). FULL DECK NOT GREEN, undebugged (output/offline-write-ab-full, A_unflagged + B_flagged banked with run records): offline-write verify FAIL image Δ2687px (n=174) line Δ88 shape Δ11 (keyed by bridged saved kindIndex — Full has hides mid-collection, so possibly mis-pairing); pass-2 badgeUnresolved 0→84 A vs B (badge raise scans the PLANNED frame — independent off-plan evidence); 30 specs on 26 slides missed the patch (AppleScript fallback ran); gate crashed at write_run_record(B) on int fallbackSpecs keys so the id-based compare never ran. Timing win is real: pass 1 20:12 (A) vs 10:40 (B) on 154 slides. NEXT: fix the round-trip, run the compare Keynote-free with --reuse-a --reuse-b --pass2-bar parity, then debug from the per-slide lines (bridge, masked/group scaling, the 30 misses, badge plates); missedSpecs with a healthy fallback should likely be WARN. DEFAULT FLIP still ON HOLD: patch at output/offline-write-ab-full/piece2-default-flip.patch, apply only on Full GREEN. The old plan's item (1) re-bank of the single-slide write_gate_ab kit was dropped by decision (the whole-deck gate supersedes it; stale sidecars are now refused by commit stamp)."
    status: pending
  - id: r-nested-bulk-probe
    content: "TRANCHE 1 (R1) — DONE 2026-09-04, PROBE ANSWER = NO. `scripts/probe_nested_bulk.py` (d4663ed, 99b2e09; 74 tests) ran live on an APFS clone of the GW deck (2 locked objects + 1 empty text box added, 15 skipped slides, zero-item slide 1, 2 movies) and on a Map clone. Correctness criteria 1-4 PASS on both: outer length == slide count with skipped slides in position, values identical to bulk_geometry.js for 4 kinds × 3 props, 113 (GW) / 12 (Map) empty collections returned `[]` in position, text placeholder tails within slack. Failure semantics (6): a per-element failure inside `<x> of every text item of every slide` is SUBSTITUTED (`missing value` in position, all 63 per-slide lengths preserved, 127/226 elements) — never a silent partial; an invalid property (`object text of every movie`) raises for the WHOLE event (-1728); `count of characters of object text of every … of every slide` collapses to ONE integer; `properties of every image` fails outright (-10000). Speed (5) FAILS: GW nested 48.8s vs bulk 66.9s warm (1.37×), Map nested 50.1s vs bulk 36.3s (0.73× — SLOWER); JXA `doc.slides.textItems.position()` 46s and omits kinds. Per-read seconds show the cost is PER OBJECT-PROPERTY inside Keynote (GW images ≈70ms/prop/object, Map images ≈33ms, text ≈9ms), not per Apple Event — the overhead-dominated hypothesis is refuted, so `r-bulk-counts-plan` (skip empty-collection events) would save only a few seconds too; both are closed. Findings + raw sidecars: output/nested-bulk-probe/findings-*.json. The bulk tier stays as is; the read-side minutes now come only from R2 (fewer reads), not faster reads."
    status: completed
  - id: r-readback-two-tier
    content: "TRANCHE 2 (R2) — CODE-COMPLETE 2026-09-07 on branch fix/resizer-backlog-r2 (b50d22b + fix
      round 7bb0f52), 2/1/2 (planners sonnet+opus AGREE-WITH-AMENDMENTS AM-1..14; fresh sonnet
      implemented; reviewers sonnet APPROVE, opus REQUEST-CHANGES → fix round → re-verified CLEARED;
      all docs under output/handover-2026-09-07/). The validated-resize readback now goes through a new
      _readback_payload ladder (remap_keynote.py): offline-write verify mode forces LEGACY (AM-2 — so
      verify_live_frames never self-confirms offline-composed shape/line frames; _splice_bulk_geometry
      only overwrites BULK_KINDS) → OBED_OFFLINE_READ=off kill switch → package-dir dest → legacy
      (range threaded) → inspect_keynote_checker(use_cache=False literal, slide_range threaded) with
      fail-safe to ONE legacy read on any plain exception. inspect_keynote_checker gained slide_range
      (ranged never caches even with use_cache=True; result subsetted to the legacy JXA shape AFTER
      attach_runs + the legacy merges; slideCount stays full-deck); LegacyInspectFailed sentinel is
      raised ONLY when an actual legacy inspect_keynote call failed — a merge-step failure escapes
      plain and falls back (b50d22b's arm-C re-labeling crashed a validated resize with zero legacy
      runs; the opus review caught it, fixed in 7bb0f52 with mutant-killing tests). Caveats: (c)(f)
      closed in code; (b) CLOSED 2026-09-07 in the owner-acked hands-off window — ranged A/B on the
      r2-round Gold _CG deck, slides 2 and 12 (results + script:
      output/handover-2026-09-07/ranged-ab/): scalars, returned-slide shape and validate flags
      identical, NO cache write on either side, and the ONLY census difference is 2 trailing
      zero-rect empty placeholder text items legacy reports and the two-tier read omits (the
      documented reconcile [0,2] placeholder-tail class; 246/246 real items exact-equal on the
      86-name roster slide, runs+colors included); (a) CLOSED 2026-09-07 in a monitored owner-acked
      hands-off window — the whole-deck field-parity A/B passed on APFS copies of all three checklist
      Gold banks (main, reuse-builds2, preadd) plus the newer r2-round output. Every deck: childCount
      hard gate 0, scalars/slides exact, zero blocking item differences after the specified rounding,
      zero kindIndex divergence, exact validate flags, matching 19-PNG basename sets/export state,
      and exactly 38 benign legacy-only zero-rect placeholders (2 per slide). Timings legacy→two-tier:
      main 130.7→52.5s, reuse-builds2 134.7→55.6s, preadd 136.7→54.6s, r2-round
      139.3→54.7s. Evidence and comparator:
      output/handover-2026-09-07/full-ab/. The first pre-Accessibility attempt timed out -1712 and
      was closed without saving; memory monitoring stayed recoverable, and the successful serial runs
      ended with Keynote clean. The R2 parity work does not gate W1. For W1, the old single-slide
      `scripts/write_gate_ab.py` Map bank remains absent but is superseded by the whole-deck
      `scripts/offline_write_ab.py` gate. The owner restored `Full_Report_Card_Wall.key` and the
      `Full_Report_Card_CG.key` reference on 2026-09-07; with the existing `Base_CG_Assets.key`
      template, a fresh full-deck A/B bank is now runnable. Accepted residual: a deck
      where inspect_items marks EVERY slide unreadable promotes arm C to a whole-deck merge, and a
      failure there runs a ranged + a whole-deck legacy pair (fails safe; b50d22b crashed instead).
      Gold-deck readback payoff is now measured at 2.4–2.6×; the old 756s→~290s report-class figure
      remains a projection until a report deck is available. Next: r-propose-two-tier is unblocked."
    status: completed
  - id: r-propose-two-tier
    content: "TRANCHE 2 (R2b), after r-readback-two-tier's FULL-DECK field-parity A/B exists. The resize PROPOSE source read is still full JXA (_run_resize_propose → inspect_keynote in web/app.py, not acquire_wall_payload): a new deck's first propose pays the full legacy read although apply reads two-tier. Same consumer audit plus deck_slide_digests parity (pairings/framings key on digests of ALL slides), propose_framings/planner parity, and cache the two-tier propose payload under the digest so propose→apply→re-propose reuse it (cross-serve is then deliberate — verify once). The old 12.6→~3 min figure is a projection, not a measured result. Risk MEDIUM (fingerprint churn; worst case a one-time pairing re-align)."
    status: pending
  - id: w-zorder-patch
    content: "TRANCHE 2 (W2). Offline drawablesZOrder+ownedDrawables reorder (patch BOTH identically) at the W1 hook, LAST per slide, replacing pass 2's GUI Bring-to-Front raises (obedRaiseSlide + the badge raise) and the resizer's Accessibility dependency. PROBE LIVE PASS 99771bf (2026-09-02): Keynote 15.3.1 honours a patched order on open, a re-save keeps it, the render changes; permute within the target ids' slots (a fresh deck carries 3 placeholder drawables). Correctness is already handled by the index-guarded descending raise (23de0d2) — this is purely the optimisation: ~0.55s/raise × N GUI clicks + Accessibility + run-to-run group-index churn. 2026-09-04 evidence this is now COSTING content, not just speed: the gold-baseline A/B kit (w-offline-write-stabilise) ran the identical `remap` twice (main vs branch, same default path) and got two different renders purely from Keynote's own drawablesZOrder scrambling on save/open — banner text hidden on Gold slides 3/4/5/8/9 in one run, 'Global Missions' clipped to 'Glob' on slides 11-17 in the other. Same deck, same code, different z-order outcome each Keynote pass. Raises the priority of this item independent of the read-speed payoff. Must run after pass 2's font sizing (or recompute stat indices), and the read-back compares reordered kinds AS A SET. Gated on W1 stable. Risk MEDIUM. 2026-09-05, offline z-order reads of the banked gold decks: the pass-2 GUI raise arranged 0 of 227 reported objects on the `main` run (all 19 slides byte-identical to the source order) and 91 on the `branch-verify2` run, with identical 'front=' counters. frontRaised counts System-Events clicks, not arrangements. W2 also removes an unverifiable counter."
    status: pending
  - id: r-cache-quick-wins
    content: "R0 leftovers, Keynote-free except for explicit measurement/live parity gates: (1) r-propose-from-cache — CODE-COMPLETE + KEYNOTE-FREE VERIFIED 2026-09-07 under 1/1/1; complete digest-current jxa/offline caches now serve ranged proposals without a wall JXA read, while the subset plans and full context preserves digests/decisions/numbering/skips/thumbnails. Review caught and fixed skip-aware navigator overflow plus coercion of malformed numeric cache fields; final independent review APPROVE. LIVE EVIDENCE STILL PENDING: warmed-Gold cached-vs-fresh A/B and scripts/e2e_run_parity.py both open Keynote. (2) r-acquire-cache-read — CODE-COMPLETE + KEYNOTE-FREE VERIFIED 2026-09-07 under 1/1/1; acquire_wall_payload now serves complete digest-current caches (on: jxa/offline, off: jxa), keeps full-deck context for ranged Apply, prevents rejected-cache leakage through legacy fallback, stamps fresh two-tier payloads offline, warns on cached bulkErrors, and keys group-child attachment to the actual reader. Independent review APPROVE. (3) r-digest-sidecar — CODE-COMPLETE + KEYNOTE-FREE VERIFIED 2026-09-07 under 1/1/1; regular-file deck digests now use a strict, path-keyed, atomically written sidecar with device/inode/ctime safety guards while package decks retain the old content walk. Independent review APPROVE. On the 6,771,226,182-byte Full deck, cold hashing took 3.97205s and the warm median was 0.1197ms with identical SHA-256 results; this proves about 3.97s saved per avoided hash, not the old speculative 30–60s whole-cycle claim. Combined gate after R0.1–R0.3: 1,248 Python tests passed, 20 skipped, eight known host-only checks deselected; all pure-JavaScript harnesses passed. (4) r-misc-cleanups remainders: remove the doomed JXA exportImages attempt in inspect_keynote.js after measuring its cost; align export_applescript with close-by-name → open → document 1; fold checker-side export into the bulk_geometry session; stop the legacy cache-hit full re-read when JSON exists but preview PNGs were evicted (~274s observed case)."
    status: pending
  - id: r-reuse-photo-placement
    content: "BUG BACKLOG (B). Reuse is KEPT (measured +39% on contiguous map series). Part (A) DONE in bf0fbe7 on branch fix/reuse-builds-side-panels: no (0,0) yank ever occurs (`ItemTransform.as_dict` always emits x/y; `applySpec` returns before any write when spec.x is null) — the real defect was a spec-less reuse add being silently skipped (not even counted as missed) and riding the paste at its wall coordinate; fixed by giving such adds a canvas-scaled rect and counting them as misses if still absent. Part (B) FRAMING COVER-FALLBACK OFF-FRAME on dense infographic slides (124/125-class, pairQuality=0) still open — reuse-INDEPENDENT (identical off-frame counts on/off); a framing item touching all slides, own workstream. Once W1 removes the AS-geometry bottleneck, dropping reuse becomes cheap — revisit then."
    status: pending
  - id: full-deck-stat-finalize-unresolved
    content: "BUG BACKLOG (B), found 2026-09-04 by the whole-deck offline-write gate on Full_Report_Card_Wall.key (output/offline-write-ab-full/A_unflagged.run.json, gate-full-3.log): the SCRIPTED production pass 2 on the report deck is far from clean — jobs 390 / done 245 / skipped 145 / unresolved 134 / dedupShortfall 6 / sigFallback 108 / badgeFallback 50 / front 482 / one missed GUI raise (-1719). The Map deck is 174 done / 1 skipped / 0 unresolved. So 134 stat groups keep their wall font size and stay buried on the CG report deck, and 6 donor-copy doubles persist. Diagnose with the index-guarded addressing (23de0d2) in mind: which slides, which signatures collide, whether the 145 skips are sig-less jobs, and whether reuse-target index drift (8 reuse slides: removal shortfalls on 123/124/125/128/144) is the driver. Independent of the offline write (A and B agree on every counter). Also: pass 1 and pass 2 both need Keynote UNTOUCHED (clipboard paste + GUI raises); an operator bringing Keynote forward mid-run silently loses a paste (slide 126 on 2026-09-04)."
    status: pending
  - id: stat-group-template-sample
    content: "BUG BACKLOG (B), follow-up from batch 2 (owner accepted the overlap for now). The re-pitched card grids overlap the affine-sized stat blocks (slide 4: date banner + '44 / Total Church Buildings' 109×265; slide 5: '110 / Full-Time Workers') — 4 + 6 cards, reported per card by caption in the say() line. Gold hand-reshaped those blocks (44 block → 509×88 bar above the grid). Fix = a stat-block sample in the template so those groups take a template size/shape (sibling of the constellation cluster affine: role-named group + template anchor). Until then the operator drags them; the grid origin already descends below stat blocks when the rows still fit (slide 5 y0=392)."
    status: pending
  - id: constellation-cluster-affine
    content: "BUG BACKLOG (B) / recipe work, after batch 2. Per-CLUSTER affine with template anchors (section below). Today one uniform fit-to-width (0.48×) leaves the top half empty; gold scales each CHC cluster ~0.82× as a unit and pushes clusters outward to fill the frame. Cluster discovery offline from line incidence; per-object size from the template circle swatches; placement by pairing clusters to template ANCHOR circles at gold positions (angular order around the building); hub lines rewritten by identity; radial frame-fit fallback when anchor count ≠ cluster count. Template needs one anchor circle per cluster + building/people rows/SOT at gold positions. Score offline against gold before any Keynote run."
    status: pending
  - id: builds-follow-source
    content: "DONE 2026-09-06 — round 2 code-complete AND Gold-verified, on branch fix/reuse-builds-side-panels (round 1: 69ede81 A, bf0fbe7 Y, 4d36be8, e7c8e9a F, 4cadd15, 39337d5, 3296ef3; round 2: 7f229d1 docs, 7722439 D1+D2, 501af25 review nits, 4654602 D3+D5+D4, 37dbb90 review-B B1/B2, 80cb442 write-anchor fix). ROUND 1 SHIPPED: offline IWA build/transition patch `restore_source_builds`, run after stat-finalize (unconditional, like the card-stroke restore); reuse-target KEEP set computed as a multiset keyed (effect, animationType, geometry-free target identity), kept builds emitted in source order; the patcher's verify raises on any surplus; transitions copied verbatim in the same SlideArchive rewrite; the dead `stripBuilds`/`buildCount` code (Keynote's sdef has no build class) deleted. Gold build 3296ef3 PASSES part F exactly: reuse slides 12-17 carry 0/9/44/29/1/3 builds (source order), transitions magic-move/dissolve/dissolve/magic-move/dissolve/dissolve, zero surplus deck-wide. ROUND 2 SHIPPED (plan output/handover-2026-09-05/plan/plan2.md + addendum-plan2.md; review output/handover-2026-09-06/review-B/review.md): D1 fixed the `remap_keynote.js deleteRefs` INDEX-SHIFT bug (JXA by-index specifiers renumber on delete) — it now matches everything first, resolves text refs by content (`matchText`) before falling back to geometry, deletes once in one descending-index pass, and measures `removed` from the live collection-count drop; D2 the mutate-with-hidden-target → donor-remove fix in `plan_slide_reuses` removes the resulting surplus (the roster rule stays mandatory as the general rule for other decks, per the owner's intent); D3 REVERTED the round-1 coincident-twin un-hide (restored `if id(item) in coincident_dups:`) — it collided with stat-finalize's index-guarded addressing, and an un-pasted/deleted drawable's build cannot be re-pointed; the 2 lost KLNSparkle builds on slide 13 are reported as a loud `WARNING builds: … lost 2 …KLNSparkle build(s)` shortfall, full-fidelity routes remain a follow-up (plan2.md §4, still open); D5 the OWNER'S ROSTER RULE landed (roster kept ONLY on the church-list slide(s) — Gold 11 plus 12, the magic-move spread — packed into frame; every later slide hides ALL roster items regardless of position; side-panel roster items still follow the per-slide `--keep-side-panels` whitelist); D4 the roster is packed into the visible frame, refined twice after the first Gold build: 37dbb90 sizes packed columns by their widest box (review-B B1, fixing 64/85→85/85 slide-12 containment) and re-gates preview resolution back to conditional (B2, deferred a wider gate change — see `pack-lists-gate-widen`); 80cb442 dropped a `+h/2` write-anchor 'compensation' the initial D4 pack had added — that was a pure write bug compensating for a READ-side artifact (`_autosize_rect` mis-reads a `kFrameAlignTop` autosize box's stored y as centre-anchored when it is already the visual top — see SKILL 'Offline inspect' and `output/handover-2026-09-06/anchor-diagnosis/diagnosis.md`); Keynote's `position` write is always the visual top, so the packer now writes the planner's y straight through, no ±h/2 anywhere. GOLD BUILD `output/gold-baseline/reuse-builds2/` (80cb442) PASSES plan2 §6 exactly: roster kept 11-12, dropped 13 (a wall leftover behind newer content); chain `13←12 (drop 85, add 7)` (plan2's literal 'add 9' was a stale round-1 carryover — the two re-hidden coincident twins account for −2 adds/+2 hidden); stat-finalize 1 skipped, no dedup/unresolved warnings (D3); `Builds follow source: 84 kept … 6 transition(s) restored on 6 reuse slide(s)`; count_deck text 7/86/1/1/1/1/1 groups 0/0/6/50/35/9/8 builds 158/0/7/44/29/1/3 for slides 11-17; geometry parity vs main clean outside 11-12; previews clean (no doubled names on 12); ONE live probe (read-only, single open, close saving no) confirmed slide-11's six columns at their composed visual tops (Global Missions y=67, matching the alignment-aware prediction exactly, not the old centre-anchored model's 97) and slide-12 packed 4 columns all inside frame. OPEN FOLLOW-UPS spun off as their own backlog items: `autosize-rect-alignment-fix` (make `_autosize_rect` alignment-aware — the frame-containment oracle still false-fails the packed columns at y≈−140 until it lands) and `pack-lists-gate-widen` (review-B deviation (2), deferred). OPERATIONAL NOTE: AppleEvent -1712 observed while the source deck is still opening is Keynote's post-open busy-phase retry, not a code bug. Gold bank: output/gold-baseline/reuse-builds2 (round 2, 80cb442; round 1's bank, output/gold-baseline/reuse-builds, was deleted 2026-09-06 by owner decision and is rebuildable from 3296ef3); output/gold-baseline/main is the 6161bcd A/B baseline. Gold builds need the owner's explicit hands-off acknowledgement before launch — never assume it."
    status: completed
  - id: side-panels-positional
    content: "DONE 2026-09-06 — round 2 code-complete AND Gold-verified, own workstream, branch fix/reuse-builds-side-panels (round 1: 69ede81, 4d36be8; round 2 commits as in builds-follow-source: 7f229d1, 7722439, 501af25, 4654602, 37dbb90, 80cb442). ROUND 1 SHIPPED: the list-hide arm deleted (`plan_slide_transforms` no longer hides every role=list item deck-wide via the `loose`/`is_summary_list` gate); `--keep-side-panels` is now positional and per-slide, keying off `is_side_panel_item` (content outside the centre wall band x∈[1920,5760]); CLI `--keep-side-panels [SLIDES]` (bare = every slide, `4,7`/`4-9` = those slides) replaces the deck-wide `--include-lists`; reuse reconcile is role-aware for persisted pairs, including groups, in the add direction (donor hidden + target visible → add the target's own item); a phantom-remove filter drops `remove` refs for donor objects already deleted; the text/line matcher for the mutate/remove partition is kind-aware and ignores height. ROUND 2 SHIPPED (see builds-follow-source for the full D1-D5 detail and the Gold-build acceptance numbers, all of which apply here too since the roster rule is a refinement of this same positional gate): D1 remove-by-content, D2 mutate-with-hidden-target donor-remove, D3 twin re-hide (revert of the round-1 un-hide), D5 roster rule, D4 frame-packing (incl. the write-anchor fix in 80cb442). Plan: output/handover-2026-09-05/plan/plan2.md + addendum-plan2.md; review: output/handover-2026-09-06/review-B/review.md. OPEN FOLLOW-UP: `pack-lists-gate-widen` — `_place_free_text`'s measured-placement gate still only fires on whitelisted slides; review-B's deviation (2) found that widening it naively would move demoted map labels and just-hidden side-panel roster boxes, so it needs the role=='list' filter + pack_lists gate spec'd there, deferred out of round 2 on purpose."
    status: completed
  - id: autosize-rect-alignment-fix
    content: "DONE 2026-09-06 — read-side fix, offline unit tests only (the round-2 output deck was not banked, so no live Keynote step this round). `_autosize_rect` (`src/obed_edom/iwa_geometry.py:187`) assumed an autosize text box's stored y is always the visual CENTRE (`top = y − naturalSize.height/2`), true only for a `kFrameAlignMiddle` box. It now resolves `shapeProperties.verticalAlignment` up the style parent chain (`shape.super.style` → `TSWP.ShapeStyleArchive.shapeProperties`, then `super.super.parent` — the same archive shape as `iwa_text_shape._resolve_shape_padding`) and branches: `kFrameAlignTop` → `y`; `kFrameAlignBottom` → `y − nh`; middle, justify, unknown or absent → `y − nh/2` (behaviour unchanged). Enum `TSWP.ShapeStylePropertiesArchive.VerticalAlignmentType`: Top=0, Middle=1, Bottom=2, Justify=3; keynote-parser's `MessageToDict` emits the NAME, the int is accepted defensively. One caller (`_compose_record`, `iwa_geometry.py:372`); `compose_geometry`/`compose_deck_geometry` signatures unchanged. `iwa_write` is untouched — a stored-h==0.0 autosize box hard-misses to the AppleScript fallback (`iwa_write.py:594`) before `_text_fields` sees it. `compose_geometry` is now the visual truth for every anchor, so the offline frame-containment oracle no longer false-fails the D4-packed slide-11 columns at y≈−140: a 313-tall top-aligned column written at 16.5 composes back to 16.5. Tests pin the live-probed numbers (s11 'CHC Fu Chang' 173.0 stays 173.0, 'CHC Jiang Shou' 796.0; 'Global Missions' 97.5/61 → 67.0; s12 first name 643.0/26 → 630.0) plus the parent-chain hop, the absent-alignment default and the raw enum code. Measured on `output/gold-baseline/main/Gold_Wall_Input_CG.key`: 168 middle / 11 top of 179 autosize boxes, 0 unresolved. NEVER re-add write-side `±h/2` compensation for this (the reverted bug in 80cb442) — see SKILL 'Offline inspect'. Out of scope and deliberately untouched: `iwa_text_shape.compose_text_geometry`'s independent `geometry.flags` anchor model (measured on the same deck, flags and the anchor enum are uncorrelated: (flags=1,Middle)×93, (flags=3,Middle)×73, (flags=1,Top)×11, (flags=0,Middle)×2 — worth its own backlog item), and group-union handling of autosize children (zero-extent, dropped by `_is_real_box`)."
    status: completed
  - id: pack-lists-gate-widen
    content: "DONE 2026-09-07 — dcae6a7 + review fix b6039ef on branch fix/resizer-backlog-r2, reviewed
      by sonnet+opus (output/handover-2026-09-07/review-pack-lists/), both REQUEST-CHANGES on ONE shared
      blocker, fixed in b6039ef. Shipped per review-B deviation (2): `_place_free_text` targets only
      role==list AND erases from the occupancy raster exactly the boxes it moves (one step past the
      review's letter; both reviewers judged it necessary — erasing a demoted label's rendered pixels
      would let packed text land on top of it); both gates widened from `slide_lists` to
      `slide_packs = slide_lists or slide_keeps_centre_roster`; B2's preview resolution restored IN
      SPIRIT not letter — new `preview_wanted_slides()` resolves without the whitelist but decodes only
      whitelist ∪ roster-keep slides (∩ range), keeping flagless full-wall runs off the ~3.9GB decoded
      preview set review-B measured. Opus measured on the banked Full-wall payload: flagless run 0 → 93
      placements, all role=list both sides, overlap 0.0; the naive widen would have moved+erased 120
      hidden boxes; parent even moved 198 non-list boxes on WHITELISTED runs (dropped-roster slide 124)
      — a real pre-existing bug this fixes, so whitelisted runs are deliberately NOT byte-identical to
      parent. The blocker: the operator report line was still gated on the deck-wide keep_side_panels
      bool, silencing exactly the runs this item enables; now `if recipe.get(\"listFontSize\") and
      (keep_side_panels or placements)`. RESIDUALS worth their own items: (1) LATENT GOLD FLIP — Gold
      has no preview cache dir today, so Gold output is unchanged; the first framing review that
      populates it silently switches Gold 11-12 to the measured packer un-Gold-verified — check on the
      next Gold build; (2) bare --keep-side-panels still decodes all 155 previews (3.86GB); only 59
      slides carry list content — cheap tightening; (3) 94/311 list boxes on whitelisted runs get
      neither packer (pre-existing all-or-nothing hole, 0/93 on the widened path)."
    status: completed
  - id: reuse-chain-preadd-duplicate
    content: "DONE 2026-09-06 evening — landed as 08a5130 on feat/reuse-preadd-duplicate (stacked on
      d31fedc alignment-aware _autosize_rect), pushed, owner merging. OPTIMIZATION (W), opened
      2026-09-06 by the owner off the round-2 Gold chain log. The reuse chain pastes a slide's delta
      then deletes it again one slide later: Gold
      `slide 12←11 (drop 6, add 85); slide 13←12 (drop 85, add 7)` — the 85 names pasted onto 12 are
      deleted one AppleEvent at a time off 13's copy, plus deleteRefs' ~86-object text snapshot
      (~430 AppleEvents for nothing). FIX: `applyReuse` duplicates the donor into the next target's
      slot BEFORE pasting its own adds (`duplicate slide to to before slide to+2`, between the remove
      pass and the paste); the consumer then skips its own duplicate — one duplicate per reuse slide
      either way, so `Duplicated 6` is unchanged. Planner gate (all four): donor is the immediately
      previous slide (a parked slide must never be live while `applyTransforms`'s `slides[n-1]`
      addressing runs), every donor-pasted item dies on the target, no pasted GROUP (keeps the
      group-dedup model bit-identical), no donor mutate (mutates land after the paste, so a pre-add
      snapshot would carry stale text). `removeFallback` restores the trimmed refs if the parked base
      failed to materialise. Magic move is unaffected: transitions are restored verbatim offline by
      `restore_source_builds` and Gold's two magic moves carry no identifier reference (they are not
      `transitionSkipped`), the surviving objects on 13 are duplicates of the same slide-12 objects
      with the same z-order, and the 85 never render either way. MEASURED: Gold reuse deletes 91→6;
      on the cached (transform-less) Full-wall payload the adjacent-only gate qualifies 0 links — the
      adjacent intersections are partial (2 and 1 objects) and the gate needs the full subset; the win
      this round is Gold-only (91→6). The Full wall's 197-object delete at slide 125 is an ANCESTOR
      paste (pasted at 123, mutated at 124), which needs the parked variant spun off as
      `reuse-chain-parked-snapshot`. TRUE BATCH DELETES judged NOT worth doing: no sdef bulk-delete,
      D1 already deletes in one descending pass, and after this fix 6 refs remain. Banked plan:
      `output/handover-2026-09-06/plan/preadd-duplicate-plan.md`. TIMED PRODUCTION GOLD BUILD
      `output/gold-baseline/preadd/` (@08a5130, owner-acked window): EXIT=0, single attempt, cold
      Keynote start, 910s wall-clock (epoch stamps in remap.log; ENV.txt notes the banked comparisons
      are NOT like-for-like — reuse-builds2 806s and main 745s were warm-Keynote, round 2 right after
      three -1712 retries; the ~430 saved AppleEvents ≈40s theoretical sit within run variance; future
      timing A/Bs should pair cold-cold or warm-warm). ALL 11 DEFERRED ACCEPTANCE ITEMS PASSED: chain
      `slide 12←11 (drop 6, add 85); slide 13←12 (pre-add, add 7); slide 14←13 (add 45); slide 15←14
      (add 29); slide 16←15 (add 3); slide 17←16 (add 3)`; roster kept 11-12, dropped 13; stat-finalize
      1 skipped, 198 deduped, no dedup/unresolved warnings; both known lost-build WARNINGs only (11: 6
      twist-and-scale, 13: 2 KLNSparkle); `Builds follow source: 84 kept, 936 dropped, 6
      transition(s)`; applied 830 missed 0; no `WARNING reuse slide 13: only removed …` line; recipe
      377 hidden; `count_deck` EXACT (text 7/86/1/1/1/1/1, groups 0/0/6/50/35/9/8, builds
      158/0/7/44/29/1/3 on 11-17). OFFLINE A/B vs `output/gold-baseline/reuse-builds2`: composed
      geometry 0.00px identical on ALL 19 slides (write_gate_ab.slide_units +
      offline_write_ab.compare_units_multiset — ab_geom_diff.py needs Keynote inspect caches that
      don't exist for these decks); builds/transitions multisets identical; 19/19 preview PNGs
      byte-identical — this also closes the plan's magic-move preview-A/B caveat at the render level.
      FIRST TRUSTED USE of the alignment-aware containment oracle (`compose_deck_geometry`) on the
      output deck: slide 11 packed columns 6/6 in frame at composed tops 16/436/640 (no −140
      artifact), slide 12 85/85, slide 13 zero roster items. Gold bank now holds main (6161bcd),
      reuse-builds2 (80cb442) and preadd (08a5130)."
    status: completed
  - id: reuse-chain-parked-snapshot
    content: "OPTIMIZATION (W) backlog, spun off from `reuse-chain-preadd-duplicate`. Let a pre-add
      snapshot serve a NON-adjacent later target: on the Full wall slide 125 deletes 197 names that were
      pasted at 123 and re-texted at 124, so 125 wants 123's pre-add state (cost ≈ +9 pastes for −197
      deletes). Needs the snapshot parked across several `run()` iterations — park it at the END of the
      deck so `applyTransforms`'s `slides[n-1]` addressing stays valid, delete it after its last
      consumer and before `skipOutsideRange`/save — plus a donor search over snapshot states and
      `donor_out`/`group_out` bookkeeping for a base that is not any wall slide. Needs a Full-wall build
      to validate; do not attempt without one."
    status: pending
  - id: map-label-classification-fix
    content: "BUG (fixed), off main, branch fix/map-label-classification, commit cbde0a7. `is_list_item` called any CHC/CHLI/CHEL text a roster list, and the unticked-list gate hid it by default (`loose` is True whenever there are no previews) — 23 single-line map labels on Gold slides 3/4/8/9 were deleted. Fix: `name_columns()`/`name_column_ids()` — a name column is now ≥3 same-left-edge rows (x tol 6, pitch 2.0×h) or a multi-line box; a lone label demotes to role=other before the hide gate (only when `include_lists` is False). Gold hide 491→468, everything else byte-identical; Full-deck sweep: 0 roster rows demoted, 134 labels newly kept across 58 slides. Live-verified (output/gold-baseline/labelfix/): labels land within 1px of the human ideal on slide 9; slide 8's offset is the human's own map shift, not error. `name_columns()` is the reusable primitive for the side-panel item (bug a, see builds-follow-source) — kept separate per owner decision."
    status: completed
  - id: map-label-text-sizing
    content: "DONE 2026-09-07 — e74e5fa on branch fix/resizer-backlog-r2. Root cause MEASURED (not the
      guessed 'sizing gap': diagnosis at output/handover-2026-09-07/label-sizing/diagnosis.md): the
      demoted label correctly matches a template character swatch, but the template palette holds TWO
      white Amplitude-Bold swatches — 40pt (Malaysia tile, slide 3) and 35pt (China tile, slide 4) —
      and `match_character_style`'s colour tie broke on `predicted = wall × 0.5 = 20pt`, so 35 (penalty
      15) always beat 40 (penalty 20). 40 × 0.875 ≈ 35 was coincidence. Only the Malaysia labels
      (slides 3/4) were wrong; slides 8/9 were right by luck (source 35). Fix: unpaired list/other text
      predicts with the affine it rides (`size_ratio=aff.s`, 0.5 with no affine) — translate-only map
      s=1.0 predicts 40 → picks the 40pt swatch; verified offline against the preadd bank's real
      palette. Offline unit + integration tests (integration pins the call site; fails on parent);
      LIVE-CONFIRMED 2026-09-07 on the r2-round Gold build: font census vs preadd differs ONLY
      'CHC Sitiawan' slides 3/4 at 40pt, previews diff only on 003/004, geometry 0.00px. Note the prompt-era assumption 'template has no label
      swatch' was FALSE — both map tiles carry label swatches at exactly the ideal sizes. The missing
      'CHC Kuching' on output 3/4 is the separate map-label-offslide-parked-delete residual."
    status: completed
  - id: map-label-offslide-parked-delete
    content: "BUG BACKLOG (B), residual from map-label-classification-fix (ii), needs its own audit. The off-slide branch (map_remap.py:2350-2354) DELETES parked off-canvas objects (e.g. 'CHC Kuching' parked at wall (4681,1678)) instead of keeping them parked like the human does (parked at (1813,1678) in the ideal). 14 parked objects on the Gold deck, mostly one parked card group."
    status: pending
  - id: card-border-source-ref-floor-fix
    content: "BUG (code fixed and merged), commit 94d2969. `restore_card_stroke_widths` applied the card classifier (white+solid, ≥10 refs) to the OUTPUT side only; the Full wall's stray 3-ref 5pt white style 17682825 (two big images, slides 26/57) shared the colour+pattern key with the real 83-ref card style, tripping a '1 output / 2 source' refusal and leaving the Full deck with no white card borders at all. Fix: `iwa_write.match_card_stroke_styles()` now applies a per-key SOURCE floor `max(2, out_refs // 8)` (output refs run ~3.2× inflated by donor copies at patch time, e.g. 83→269, so a flat floor of 10 would wrongly refuse small decks); refusals dump every candidate, successes note what the floor set aside. Residual: output card refs 10-31 still refuse on the Full wall (floor caps at ≤3) and need a follow-up. No final Full-deck live-verification result was recorded; do not describe it as still running."
    status: pending
  - id: propose-pins-flag
    content: "FEATURE. Surface pins-paired (pairQuality) per template tile in the propose UI so a '0-pin' slide is flagged, not trusted. Image-similarity scores can invert the geometric fit on bespoke slides (Map slide 9: template 4 scored 0.69 but paired 0 → vetoed at remap; template 13 scored 0.06 but paired 34 at the right 0.483 scale)."
    status: pending
  - id: recipe-library
    content: "FEATURE. Recipes as browsable artefacts. Built then reverted: a page needing a borrowed transform usually needs two affines (map + badge). Revisit now badge-affine names groups by role — section below; the cluster affine is a third role."
    status: pending
  - id: stat-drift
    content: "FEATURE. Validation rule slide.stat_drift: a figure that changes between adjacent slides then holds. Ships at warning. Independent; stubbed in validation_rules.yaml."
    status: pending
  - id: outline-editor
    content: "FEATURE. Editable outline view extending OutlineResultView, LibreOffice page-view toggle, in-place surgical writes to the source .docx with timestamped backups. Design below."
    status: pending
  - id: image-cues
    content: "FEATURE. Image cues as an asset slot count + shape per cue. Both capabilities (image place, movie via file-name reassign) probed and present. Taxonomy below."
    status: pending
  - id: iwa-surgical-write-generator
    content: "FEATURE (generator). Use the offline IWA writer (ec20f4b) to set cyan superscript verse numbers offline and retire generate's GUI Copy/Paste-Style pass 2 (Accessibility, silent-fail). Style-table patch = a harder byte class than geometry floats; own spike + per-deck openability test."
    status: pending
isProject: false
---

# CG resizer — optimizations, bug backlog, features

**Read `.agents/skills/obed-edom/SKILL.md` first.** Every durable Keynote/IWA finding —
bundle-id targeting, the verified scripting limits, cache versioning, the template contract,
offline read/write facts — lives there. This plan is the executable delta plus the reasoning
a new agent would otherwise rediscover. Cue palette + DSK generator: their own plan.

## Discipline (applies to every item)

- **Measure first.** Every payoff figure is measured (cited) or marked estimate; never ship on
  an estimate. Say what a change ACTUALLY does (native-res crops, not downscaled previews).
- **Probe before trusting.** Any "Keynote can't do X" is probed in AppleScript first; verify a
  batch-op probe by COUNTING affected objects, never by timing a try-wrapped call. Don't
  inherit "can't" comments (the "JXA cannot scale a group" lore cost a session).
- **1/1/1 workflow** for this continuation, selected by the owner on 2026-09-07: one planner →
  one fresh implementer → one independent reviewer. The implementer does not review their own
  work. Historical 2/1/2 citations below describe completed work and stay unchanged.
- **Never run Keynote concurrently.** One deck warm at a time; agents offline during a live
  read/write. Keynote here is "Keynote Creator Studio.app" = Keynote 15.3.1. Close-by-name →
  open → `document 1`; `with timeout of 3600`. Fast probe: APFS-clone (`cp -c`), mutate, read,
  close saving no. Never `/private/tmp` for `.key` files. Accessibility must be granted or the
  reuse pastes and GUI raises fail silently.
- **After ANY read-path change** re-run `scripts/e2e_run_parity.py` (baseline in its docstring).
- Commits at verified checkpoints, at real wall-clock time (forward-dating to ~10:00 UTC retired
  2026-09-04), never re-date cited SHAs; no PRs unless asked. Housekeeping at every landing:
  todo status here, SKILL, memory.

### Memory safety: what the "16GB rule" actually means

This is not a blanket ban on Keynote work and not a Codex permission. It is a narrow caution born
from one observed failure: a legacy full-JXA inspection of a multi-gigabyte report deck drove
Keynote to roughly 80GB of memory on this 16GB Mac and destabilised the following read. Safe work
already performed on this machine includes offline IWA reads, scoped/ranged Keynote reads, ordinary
Gold remaps, preview exports, and the two-tier bulk reader. Only a **full-deck legacy JXA inspect of
a multi-gigabyte deck** gets the high-memory treatment: explicit owner acknowledgement, a copy of
the banked deck, one clean Keynote process, no concurrent automation, one deck at a time, and active
memory-pressure monitoring. Stop if pressure climbs or Keynote stops responding. A larger-memory
Mac is preferred, not mandatory policy. Historical reviews retain their original stronger wording.

## Current state (2026-09-07, `main` after PR #54)

- R2 validated-resize readback is merged (`b50d22b`, `7bb0f52`). The scoped A/B on Gold slides 2
  and 12 passed for scalars, slide shape, flags, runs and colours; the only census difference was
  the documented pair of trailing zero-rect placeholder text items returned only by legacy JXA.
- The full-deck R2 field-parity A/B passed on copies of the three checklist Gold banks plus the
  newer r2-round output. All hard fields, flags, preview/export state and per-kind order passed;
  only the documented two empty legacy placeholders per slide differed. R2b propose caching is
  now unblocked.
- The restored Full Wall deck and existing Base CG template were used for a fresh whole-deck W1
  `scripts/offline_write_ab.py` run. The restored Full CG deck is a reference output, not the
  `--template` argument. The gate completed RED; its A/B decks and run records are reusable for
  diagnosis without Keynote. See “W1 fresh full-deck gate evidence” below.
- The literal `scripts/write_gate_ab.py` is the older one-slide Map harness. Its bank and Map wall
  input remain absent, but the active plan already superseded it with the whole-deck gate; do not
  mislabel that absence as a W1 input blocker or as a blanket RAM prohibition.
- R0.1–R0.3 are code-complete, independently reviewed and Keynote-free verified. Next R0 item:
  the reviewed-but-not-yet-approved R0.4 misc cleanup slice.
- W2 z-order patch stays gated on W1. Offline write remains opt-in/default OFF.

### R0.1 execution plan — `r-propose-from-cache` (code-complete, reviewed)

- A ranged proposal may reuse a cached wall payload only when the digest-current cache declares
  `reader: jxa` or `reader: offline`, `slideCount` equals the slide array length, and the slides
  cover document positions `1..slideCount` in order. A missing, partial, reader-less, unknown or
  malformed cache keeps the existing single ranged-JXA fallback and document-position warning.
- Treat the cache as two views: a requested-slide subset for recipe/framing planning, and the full
  payload for navigator conversion, saved-decision reuse, wall digests, skipped-slide context and
  preview-to-slide mapping. Never renumber subset slides and never mutate the cached object.
- Extend `propose_framings` with an explicit full-wall context. Planning and returned pages use the
  subset; thumbnail mapping, `wallDigests`, `skippedSlides` and `numberingNote` use the complete
  deck. Page indices remain absolute (`slide number - 1`), so Apply and saved framing decisions do
  not change meaning.
- Deterministic tests cover both accepted readers, skipped-slide range conversion, absolute page
  and decision indices, full digest order, thumbnail mapping, cache immutability, malformed-cache
  fallback and out-of-range rejection. Run the focused dashboard/framing/preview suites, then the
  full Python and JavaScript suites.
- Keynote-free code/tests are the landing gate for this item. The warmed-Gold cached-vs-fresh A/B
  and `scripts/e2e_run_parity.py` both open Keynote; record them as pending live evidence for the
  next explicit hands-off window rather than claiming they ran here.
- Implemented in `web/app.py` and `framing.py`, with focused dashboard/framing regressions. The
  independent review initially rejected skip-aware navigator overflow and permissive numeric
  coercion; both were fixed and the re-review approved. Final local gate: 1,223 canonical Python
  tests passed, 20 skipped, eight host-only compiler/font checks deselected; all pure-JavaScript
  harnesses passed. No Keynote process was opened.

### R0.2 execution plan — `r-acquire-cache-read` (code-complete, reviewed)

- Move R0.1's strict full-payload validator into `inspect.py` for shared use. It continues to
  require a known reader, exact integer `slideCount`, and contiguous integer `number`/`index`
  fields; booleans, strings, floats, partial arrays and unknown readers remain invalid.
- `acquire_wall_payload(mode="on")` accepts complete digest-current `jxa` and `offline` caches;
  `mode="off"` accepts only `jxa`. Return the complete deck even for a ranged Apply because roster
  runs and navigator/skipped context cross slide boundaries; the existing planner/writer already
  limits mutations with `slide_range`.
- A rejected cache must not leak back through a legacy fallback: all legacy calls in that
  acquisition use `use_cache=False` after a rejected hit. With no cache present, retain the current
  cache-populating behavior. Fresh two-tier payloads are stamped `reader: offline`.
- Serve cached offline payloads without their stripped `_offline` sidecar. Preserve `bulkErrors`
  as a loud warning, but do not invent new fallback work from the diagnostic. Log the accepted
  reader and that the source Keynote read was skipped.
- Downstream group-child attachment follows `wall["reader"]`, not the requested mode: attach for
  offline geometry, skip for live JXA geometry, and retain the old mode-based behavior only for
  explicitly injected reader-less payloads used by compatible callers/tests.
- Keynote-free tests cover both readers/modes, malformed and rejected caches, fallback cache
  bypass, two-tier reader stamping, `bulkErrors`, full-deck ranged returns, logging and group-child
  attachment. Run the focused acquisition/readback/offline-write suites, then the canonical Python
  suite and all pure-JavaScript harnesses.
- Implemented in `inspect.py`, `remap_keynote.py`, `web/app.py` and focused regressions. One fresh
  Terra implementer completed the change; the independent reviewer approved with no blockers.
  Final gate: 1,233 canonical Python tests passed, 20 skipped, eight host-only compiler/font checks
  deselected; all eight pure-JavaScript harnesses passed. No Keynote process was opened.

### R0.3 — `r-digest-sidecar` (completed 2026-09-07)

- Keep `deck_digest(path) -> str` and the content-only SHA-256 result unchanged. Only regular-file
  decks use the sidecar; package-directory `.key` decks retain the existing sorted-tree hash and
  never read or write one.
- Store one versioned record per resolved path under `cache_root()/deck_digest/`. The requested
  primary key is resolved path + size + `mtime_ns`; also require device, inode and `ctime_ns` as
  safety guards so same-size copies/overwrites that preserve mtime cannot serve a stale digest.
- Accept only strict integer metadata and a 64-character lowercase SHA-256. Corrupt, stale,
  malformed or wrong-version records are ordinary misses and are atomically replaced after a
  stable fresh hash; cache I/O failures never make digesting fail.
- Stat before and after streaming. Write a sidecar only when the opened file and final path retain
  the same identity throughout; a concurrent deck change returns the freshly computed digest but
  does not cache it. Writes use a same-directory unique temporary file, flush + fsync, mode `0600`
  and `os.replace`; no lock is needed because duplicate cold hashes are safe and records rebuild.
- Tests cover cold/warm behavior, exact SHA-256 parity, ordinary edits, restored-mtime in-place
  rewrites, atomic replacement, copied paths, symlink convergence, package decks, corrupt records,
  mid-hash changes, cache-I/O failures, concurrent writers, permissions and cache-root isolation.
- Keynote-free measurement on the existing 6.8GB regular-file Full deck: one cold hash and at least
  three warm calls, identical digests, warm median under 100ms and at least 20× faster than cold.
  Report the measured cycle saving; do not retain temporary measurement sidecars outside the
  configured cache root.
- Implemented in `baseline.py` with focused coverage in `test_baseline.py` by one fresh Terra
  implementer after one planner; one independent reviewer returned APPROVE. The final focused
  suite passed 26 tests across 20 repeated runs. The combined repository gate passed 1,248 Python
  tests, 20 skipped and eight known host-only checks deselected; all pure-JavaScript harnesses and
  the diff/YAML checks passed.
- Measurement on the 6,771,226,182-byte Full deck used an isolated temporary cache: cold
  3.97205s; warm 0.3818/0.1197/0.1056ms, median 0.1197ms; all four calls returned
  `abf291d12e8e4ef1fff0947fe8036c200cfe4c00b49d8972c2261676a7a2d265`. This proves roughly
  3.97s saved per avoided digest call. Whole-cycle savings remain unmeasured.

### R0.4 execution plan — `r-misc-cleanups` (awaiting owner review)

- Treat the four residuals as one 1/1/1 slice with three ordered checkpoints because the checker
  export fold depends on the repaired document binding. One implementer owns the whole slice and
  one independent reviewer reviews the combined behavior.
- **Checkpoint 0, measure before editing:** on an APFS copy, time `Keynote.export(...)` and
  `doc.export(...)` separately and compare their direct/recursive PNG sets with the established
  AppleScript exporter. Bank a before-change checker run. If either JXA form unexpectedly produces
  the complete preview set on Keynote 15.3.1, stop for owner review instead of deleting it.
- **Checkpoint 1, export correctness and legacy cache-only repair:** align standalone
  `export_applescript` with bundle-id target, exact-name close, open, `document 1` binding,
  name/path verification, one-hour timeout, PNG export and close-without-saving cleanup. Add an
  internal already-open form for the later handoff. Remove the disproven JXA export attempts while
  preserving payload shape. Port the checker's export-only cache-hit behavior to legacy
  `inspect_keynote`: cached JSON returns immediately without previews, returns with a complete
  preview set, or runs only AppleScript export for missing/partial previews; it never performs a
  fresh JXA inspect in that branch. Preserve cache metadata, skipped-slide accounting and stale
  export-error clearing; do not change cache version or reader cross-serving.
- **Checkpoint 2, fold checker export into the bulk session:** keep public `bulk_geometry()` and
  existing callers close-by-default. An explicit checker-only `keepOpen` handoff leaves the deck
  open after geometry, immediately exports it through the verified already-open AppleScript form,
  and always closes it. Export failure remains separate from geometry success, is surfaced once,
  and does not trigger a duplicate standalone attempt. If the production bulk closure is never
  reached, retain standalone export as the fallback. Keep read/export timings non-overlapping and
  guarantee cleanup on JSON/export errors.
- Tests cover generated-script ordering/guards/cleanup, absence of `exportDir` from the legacy JXA
  plan, every legacy cache/preview state including all-skipped, proof that export-only hits never
  call JXA, checker folded/fallback/error paths, timing, unchanged bulk diagnostics, and default
  close behavior for other callers. Run focused suites, the canonical Python suite and all JS
  harnesses.
- Live gates on copies: post-change checker A/B against the banked before run (payload parity after
  metadata removal, preview basename/pixel parity, one deck open instead of two, measured wall-time
  delta); a legacy cached-payload/evicted-preview export-only hit (`_cached:true`, no JXA timing,
  complete previews); the required `scripts/e2e_run_parity.py`; final zero-open-document check and
  original-digest confirmation. Update this plan and the checker plan with measured results; add
  only durable verified handoff/export rules to the skill.

### W1 fresh full-deck gate evidence — RED 2026-09-07

- Ran `scripts/offline_write_ab.py` on the restored `Full_Report_Card_Wall.key` with the existing
  `Base_CG_Assets.key` template, `--mode verify --no-validate --pass2-bar parity`. The restored
  `Full_Report_Card_CG.key` is a reference output and was not mutated or used as the template.
  Accessibility passed after the owner enabled it; the first preflight attempt had aborted before
  opening a deck. Keynote ran serially, quit cleanly between A and B, ended document-clean, and
  memory stayed recoverable (observed 33–56% free).
- Fresh reusable evidence is under `output/handover-2026-09-07/write-gate-full/`: 5.3GB
  `A_unflagged.key` + run record, 5.4GB `B_flagged.key` + run record, and `gate.log`. A ran
  15:54:30–16:34:47 (~40m17s); B ran 16:34:49–17:09:39 (~34m50s). Reuse these banks for the
  next diagnosis; do not pay Keynote again until a fix needs a new live gate.
- The surgical writer's local checks passed strongly: 147 slides patched, no refused slide,
  value-clean, naturalSize/originalSize/mask consistency PASS, and live verify image/movie/shape
  max delta 0.00px. It applied 3,200 specs, but 689 missed specs across 124 slides fell back safely
  to AppleScript; that fallback load is too high for the intended performance payoff.
- The whole gate is RED. Pass 2 diverged materially: A→B done 312→379, skipped 78→11, sized
  323→409, dedupDeleted 57→198, dedupShortfall 141→0, sigFallback 41→108, unresolved 67→0.
  Thus B is locally cleaner, but not equivalent to A. All compared slides retained 100% drawable-id
  population parity; nevertheless the gating identity geometry failed on 12 slides
  (43, 51–54, 56, 106, 113, 119, 131–132, 144), with a maximum 6.12px child-image delta.
  Separate plan-oracle failures also exist on both sides, including large common group residuals,
  so diagnose oracle validity independently from the A/B identity deltas.
- The final log line incorrectly says parity tolerated A's unresolved/dedup shortfall “because
  A==B” after the preceding RED lines prove A!=B. Fix that summary text during diagnosis; it did
  not affect the RED exit status. Offline write remains opt-in/default OFF and W2 remains gated.

## Historical state log

- **Pipeline:** two-tier offline source read (`OBED_OFFLINE_READ` default ON: IWA for
  everything + one bulk Keynote read of group/image/text frames) → pass 1 in Keynote (canvas
  set, layout import/apply, JXA attrs pass, AS geometry with `set properties`, reuse
  duplication, deleteHides, save) → optional offline IWA geometry patch (`OBED_OFFLINE_WRITE`,
  default OFF) → pass 2 stat-finalize (dedup, index-guarded font pass, recorded raises, badge
  raise, export).
- **Owner's contract (2026-09-03):** the template `Base_CG_Assets.key` dictates SIZE (and
  position where appropriate) for matched objects, **including text point sizes**; colour,
  font family/style, run formatting and each slide's builds/animations are always copied from
  the SOURCE (memory `template-size-source-style`, SKILL "Text styling").
- **Just shipped (2026-09-03):** stat-finalize index-guarded addressing (`23de0d2`, the slide-9
  signature collision) and output-bugs batch 1 (`171fc65` … `f9261b7`: backdrop y=0, badge
  plate→globe→text raised on every slide with a geometry-guarded index, card stroke restored to
  source, caption-bearing groups are never pins) — both live-verified on the Map deck.
- **Batch 2 shipped + live-verified (2026-09-03, `0ad68b0`/`0cdcd2b`/`753acef`):** photo cards
  take the template card rect, captions the template swatch with a job-scoped whole-point
  step-down, and each card grid re-pitches to the template's own gutters (3-card L on slide 12)
  and reflows to 6 columns; off-frame 29 → 2 on the Map deck.
- **Next:** tranche 1 → **tranche 2** (the immediate optimization TODO). New follow-up in the bug
  backlog: stat-group template sample (the grid overlaps the date banner / "44" block on slide 4
  and the "110" block on slide 5 because those groups keep their affine size; gold hand-reshaped
  them).
- **2026-09-04 evening (branch `feat/tranche1-offline-write-gate`, plus two off-main fix
  branches):** gold-baseline A/B kit built and run — production default path (main 869a28f vs
  this branch f083a67) shows NO regression (0.00px geometry, identical styles on all 19 Gold
  slides); the sole difference between runs is Keynote's own z-order scrambling, now hard
  evidence for `w-zorder-patch`. W1 opt-in mode has a SEVERE regression, root-caused (stale
  render-derived fields — naturalSize/originalSize/mask geometry — left behind by the IWA
  patcher); fix scope written up in `w-offline-write-stabilise`, 2/1/2 planning under way,
  default flip stays OFF. Two independent bugs found and fixed off main: map-label
  classification (`map-label-classification-fix`, cbde0a7) and the card-border source-ref floor
  (`card-border-source-ref-floor-fix`, 94d2969, live confirmation in progress). Two residual
  backlog items opened from the map-label fix (`map-label-text-sizing`,
  `map-label-offslide-parked-delete`).
- **2026-09-05 (late), branch `fix/reuse-builds-side-panels` off main f8f39e5 (7 commits, pushed,
  no PR yet):** round 1 landed and Gold-built (3296ef3) — offline IWA builds/transitions now
  follow the source (part F PASS exactly; Keynote's sdef has no build class at all), "keep side
  panels" is positional per-slide (`--keep-side-panels [SLIDES]`), reuse-add placement fixed
  (part Y). Round 2 (D1-D4, plan in `output/handover-2026-09-05/plan/plan2.md` +
  `addendum-plan2.md`, plan2.md written, incorporates the roster rule; round 2
  implementation next) plus a late owner clarification: the roster is kept ONLY on the
  church-list slide(s), packed into frame, hidden everywhere else regardless of position.
  Gold builds require the owner's explicit hands-off acknowledgement before launch, always.
- **2026-09-06:** round 2 (D1-D5) shipped and Gold-verified (`output/gold-baseline/reuse-builds2/`,
  commit 80cb442) — see `builds-follow-source` and `side-panels-positional` for the full detail.
  D4's frame-packing needed a second fix after the first Gold build rendered the columns h/2 low:
  the corrected model is that Keynote's AppleScript/JXA `position` (read AND write) is always the
  object's visual top-left; the IWA stored y is the visual top for a `kFrameAlignTop` autosize box
  and the visual centre only for a `kFrameAlignMiddle` one. `_autosize_rect` now resolves that
  anchor up the style parent chain, so `compose_geometry` is the visual truth for every anchor
  (`autosize-rect-alignment-fix`, DONE 2026-09-06, read-side only, offline tests). One follow-up
  from the round is still open: `pack-lists-gate-widen` (review-B deviation (2), deferred with a
  landing condition already met).
- **2026-09-07, branch `fix/resizer-backlog-r2` off main c7c8510 (worktree
  obed-edom-wt-resizer-backlog, 5 commits, not pushed, no PR):** `pack-lists-gate-widen` DONE
  (dcae6a7 + blocker fix b6039ef), `map-label-text-sizing` DONE (e74e5fa, measured two-swatch
  tie-break root cause), R2 `r-readback-two-tier` CODE-COMPLETE (b50d22b + 7bb0f52) — each 2/1/2
  reviewed, suite 1153/78, zero Keynote opened during the code round. All round documents (plans,
  vets, reviews, diagnosis, implementation reports) under `output/handover-2026-09-07/`. The
  owner-acked hands-off Keynote window then ran the same day (10:03-10:25): PRODUCTION GOLD BUILD
  `output/gold-baseline/r2-round/` (880s, EXIT=0, single attempt, warm idle Keynote) — offline A/B
  vs preadd: geometry 0.00px on all 19 slides, font census differs ONLY 'CHC Sitiawan' slides 3/4
  (35→40pt, the label fix, live-confirmed), previews 17/19 byte-identical (DIFF only 003/004), all
  preadd acceptance lines reproduced (roster 11-12/13, the two known build WARNINGs, applied
  830/missed 0); RANGED READBACK A/B closed caveat (b) — see the R2 item. The whole-deck R2
  field-parity A/B subsequently passed on all three checklist Gold banks plus r2-round. Later on
  2026-09-07 the owner restored the Full Wall and Full CG reference decks and a fresh whole-deck
  `offline_write_ab.py` run completed RED with the existing Base CG template. Both A/B decks and
  run records are banked for Keynote-free diagnosis; the superseded one-slide Map
  `write_gate_ab.py` bank remains absent. The
  pack-lists latent Gold flip stays latent: this build ran with no preview cache and geometry is
  byte-stable.

## Order of work

1. **Unblocked now:** finish the R0 misc cleanup slice; R0.1–R0.3 are complete.
2. **Also unblocked by the passed R2 A/B:** R2b `r-propose-two-tier`.
3. **W1 bank rebuilt, RED:** diagnose the reusable full-report A/B bank Keynote-free; only run
   Keynote again after a reviewed fix. W2 remains gated on W1 stabilisation/default-flip.
4. **Then:** remaining bug backlog, constellation cluster affine, and feature backlog.

### Tranche map

| Tranche | Item | Keynote | Status / depends on |
|---|---|---|---|
| W0.1–W0.4 | tmp-path fix, skipped-slide bulk skip, z-order probe, stroke probe | probes only | DONE (2ac04db, 695199d, 99771bf, c4dc5e5) |
| Fixes | output-bugs batch 1 → batch 2 | one live remap each | both DONE + live-verified (batch 2: 0ad68b0, 0cdcd2b, 753acef) |
| Fixes | `map-label-classification-fix` (cbde0a7), `card-border-source-ref-floor-fix` (94d2969) | one live remap each | both merged; map-label live-verified; final Full-deck card-border verification outcome was not recorded |
| **W1** | `w-offline-write-stabilise` | gate on both gold decks | gate hardened + patcher fix; Map GREEN (verify+on); Full NOT GREEN, undebugged; flip on hold (patch banked) |
| **R1** | `r-nested-bulk-probe` | yes | DONE 2026-09-04 — correct+safe but NOT faster (object-bound); closed with `r-bulk-counts-plan` |
| **R2** | `r-readback-two-tier` → `r-propose-two-tier` | output-deck A/B | readback complete; ranged + four whole-deck Gold A/Bs passed; R2b unblocked; write-gate re-run separately blocked by deleted inputs |
| **W2** | `w-zorder-patch` (stroke prod folded into batch 1 C) | yes | W1 stable |
| R0 | `r-cache-quick-wins` | no (A/B on warmed decks) | anytime, Keynote-free |
| B | reuse yank / framing fallback, cluster affine, builds | yes | independent |
| B (branch) | `fix/reuse-builds-side-panels`: `builds-follow-source`, `side-panels-positional`, reuse-add placement (part Y) | two Gold builds (3296ef3, 80cb442) | round 1 + round 2 (D1-D5) both DONE + Gold-verified; `autosize-rect-alignment-fix` DONE 2026-09-06 (read-side, offline); open follow-up `pack-lists-gate-widen` |
| W (branch) | `reuse-chain-preadd-duplicate` (backlog: `reuse-chain-parked-snapshot`) | Gold build `output/gold-baseline/preadd/` (08a5130) | timed Gold build preadd/ 910s cold, all acceptance passed, 0.00px vs reuse-builds2, previews byte-identical |
| drop | `w-hides-offline` (optin chose the deleteHides bridge), skipped-slide option (2), Stage B / batch z-order / batch delete via their original mechanisms | | closed |

R1/R2 touch `inspect.py` / `bulk_geometry.js` / `remap_and_inspect`; W1 edits
`remap_keynote.py` — sequence, don't interleave. The checker's edit-loop cache wraps
`bulk_geometry_fn` at the inspect.py call site and depends on the `plan.slides` subset path:
any nested-bulk rewrite must preserve it.

## Write track — what stands after the reviews

- Dominant cost was the AS geometry phase (~70% of a heavy-slide run, ~100ms/command redraw
  even off-screen, no cross-object bulk write); surgical IWA float patches are the missing bulk
  write. Byte-risk ladder: float patches < list reorder < object removal.
- Proven: object-level patching of ONE stored member (values clean, snappy churn only);
  locality (every slide's drawables in exactly one member, derived from `id_to_file`, never
  from the slide id); Keynote opens patched decks clean and re-saves them first-class; size
  lives in `bezierPathSource.naturalSize` (patch size AND naturalSize; a line's length is
  `naturalSize.width`); write patched bytes IN PLACE (`com.apple.macl`); masked-image size
  writes 108/108 @0.54px; group-child scaling (`s = spec / REPORTED union`, origin = spec +
  (stored − reported)·s, descendants ×s, masks too) with no double-scale on open; NBSP zip
  member names must be preserved raw; a text box is never a line.
- Group move = DELTA on the stored origin (stored ≠ reported on stale-frame groups); soft
  classes (group/text/masked image) seed from a bulk read of the SAVED deck, never from the
  offline composition alone; refuse a slide whose reconcile counts disagree (fail-safe to the
  scoped AS script). Reuse slides stay fully in Keynote.
- Known cosmetic: AS geometry `set properties {width,height}` renders as two origin snaps; gone
  on offline slides.
- **Gold-baseline A/B kit (2026-09-04):** a Keynote-light way to A/B two branches on the
  production default path — one `remap` per branch, then offline IWA reads (~1-3s per 2.5GB
  deck) + preview PNG diffs for geometry/style comparison; Keynote is only needed for the two
  remaps themselves and one preview export of the human ideal. Caught the z-order
  nondeterminism (see w-zorder-patch) that a same-code same-deck re-run would otherwise hide.
  Rule learned the hard way: treat full-deck legacy `inspect_keynote`/`inspect_gold` of these
  multi-gigabyte decks as a monitored high-memory operation, and keep the paste phase of pass 1
  hands-off — a lost-paste run reads "Card-border
  stroke: … (12 refs)" instead of 269.

## Read track — what stands after the reviews

- Bulk-read inspect (227s → 57s, byte-identical) and the two-tier read (Map 51.8s / Full
  283.7s vs ~12.6 min JXA; plan gate GREEN on both decks with live values) are shipped. The
  bulk tier is Apple-Event-overhead-dominated, hence R1.
- Correctness guards that exist: `reconcile_counts` wired into the splice (text slack [0,2]
  trailing-only, placeholder tail check); array-length guards per bulk array; granular per-
  slide/per-class legacy fallback. Only `role="hide"` geometry is write-dead — lines and group
  w/h ARE written; verify "is this field written?" against `remap_keynote.js`.
- Compare output groups as a SET, never by index (Bring-to-Front reorders kindIndex run to
  run); the canvas shrink jitters the map ~8px/run — read pixel diffs against that floor.
- Cache facts: `deck_slide_digests` hashes no geometry; ranged reads never cache; cross-serve
  (checker-written payloads served to propose) is consumer-compatible but carries a `reader`
  provenance guard — keep it.

## Constellation slide — per-cluster affine with template anchors

The constellation (Map slide 9 = 67 groups / 68 lines; Full 134→127) is not one affine. Gold
scales each CHC cluster (hub circle + UPG satellites + church/book icons + white connector
lines) **~0.82× as a unit**, then pushes clusters outward, keeping their angular order around
the building, until the frame is filled; the yellow hub lines re-anchor to the moved CHC
circles. Today's planner applies one uniform fit-to-width (**0.48×**) and leaves the top half
empty. (The earlier "two-knob" reading — scale nodes in place ~0.85 + pull centres toward the
centroid ~0.5 — was the same observation from the other side.)

1. **Cluster discovery, offline, automatic.** Every circle is a group. Membership comes from
   line incidence: a yellow line from the building to a CHC circle marks a cluster root; white
   lines from that CHC circle to UPG circles and icons mark members. Edges match nodes by
   **identity** (recorded incidence), never proximity; a deleted node's edges are dropped.
2. **Size from the template.** The template's sample CHC/UPG circles give the per-object scale
   (~0.82×), applied uniformly within each cluster; circle text follows the pass-2 font rule.
3. **Placement from template anchors.** The template slide carries one plain CHC-sized circle
   per cluster at its gold position (13 on the Map deck) plus the building, the two people
   rows and the SOT mark at gold positions. Pair wall clusters to anchors by angular order
   around the building; translate each cluster so its CHC circle lands on its anchor; rewrite
   hub lines to the new CHC centres.
4. **Fallback** when anchor count ≠ cluster count: keep each cluster's angle from the building
   and scale its radius anisotropically to fill the frame — never overlapping the building,
   never off-frame.

Template needs: the size swatches it already has, plus the anchor circles and bottom-band
objects at gold positions (thirteen circles placed by hand once). Score offline against gold
(predicted cluster centres/sizes) before any Keynote run. Ask first whether the slide's
content changes yearly — that gates how much automation is worth.

## Recipes as browsable artefacts (revisit)

A template slide only helps if something *pairs*; what transfers instead is the **recipe** —
a portable subset of the learned transform. Built and reverted: a page that cannot learn its
own framing is usually a map-and-badge page that wants **two affines, not one** (report card
slide 94: the badge rode the map's affine off-frame). Now `badge-affine` names groups by role:
`portable_recipe` carries `[{role, s, tx, ty}]`, `apply_portable_recipe` resolves each role on
the page in hand; an orphaned role fits to its own footprint (`visible_content_union` over
the orphan subset, keeping position relative to the frame — fit-to-frame centres today, and
the union is measured against the full 7680). Storage: a tracked `recipes/` folder of small
labelled JSON files; plumbing `recipe_overrides: dict[int, dict]` beside `framing_overrides`.

## Outline editor in the dashboard

Editing surface: HTML rendered from the .docx (`load_paragraphs` returns per-run
bold/highlight/superscript/color; `ListNumberResolver` resolves auto-numbering;
`OutlineResultView` renders cue chips at exact offsets via `segments()` — make it editable).
Page view: LibreOffice `soffice --headless --convert-to pdf`, read-only, cached until the next
save, disabled when absent. Writes go to the source .docx in place (scoped reversal of
SKILL's never-overwrite rule; Sermon Checker stays read-only): timestamped backup per save
under `output/.outline-backups/{stem}/`, **surgical edits only** (operation list against
touched paragraphs, as `_apply_ops`/`_make_run` in `annotate.py`). Semantic cues in, operator
cues out (`annotate_outline` converts at generate time). Validate as you type with what the
parser knows.

## Image cues: design for these, build later

An image places from AppleScript with `position` and `width`; a movie is placed by creating
an image and assigning the video to its `file name` (converts the object, keeps geometry) — no
GUI automation, a template needs only a small image placeholder. Taxonomy: centre-panel photo
set, mirrored single set, full-centre media, design-authored collage (not operator-buildable),
grid cases (count + grid spec). So an image cue is a cue plus an **asset slot count and
shape**, with an optional background asset distinct from the content ones.

## Stat drift across adjacent slides

"11 Renovated Church Buildings" on one page, "44" on every page after. Compare text objects
across adjacent slides, matching on position and on wording with digits removed; flag a page
whose number disagrees with the run either side of it. Ships at `warning`.

## Operator / source-deck items (no code fix) and parked notes

- Slide-124: ~130×11px overlap between two right-side groups; slide-125: church list = 46
  opaque groups (source-deck ungroup); a verse's wall-authored hard line breaks (stripping by
  script destroys superscripts and small-caps LORD); sparkle-overlay placement; a caption in
  the "as it will look" preview.
- AppleEvent -1712 seen while the source deck is still opening is Keynote's post-open busy-phase
  retry, not a code bug (observed 2026-09-06 during the reuse-builds2 Gold build) — no fix needed.
- UNCONFIRMED production reports from the 2026-09-01 full Map run (`output/write-gate/A_png`),
  never localised: (b) the yellow "269 churches" text deleted on several slides yet present +
  mis-positioned in the slide-7 PNG; (d) right-side photo z-order wrong on slides 4 & 5 (may be
  subsumed by the badge/z-order work — re-check on the next live run before opening an item).
- Never dedupe images (stacked map layers are coincident on purpose). The first ranged propose
  on a never-read deck cannot translate the range into Keynote's numbering and says so.
  Composite preview text is scaled wall pixels (close, not right). The JXA export has never
  worked (`exportError` carried while `export_slide_images` succeeds). PNG export fidelity
  differs 117px @ ≤2/255 between Keynote versions — keep watching.

## Shipped record (compact)

| Item | Commit(s) | One line |
|---|---|---|
| Keynote 15.x migration, framing confirmation, badge-affine, structural title, off-frame hiding + delete-hides, side-panel whitelist, number-block packing, operator notes, navigator numbering | (git log) | pre-Aug-28 feature work; findings in SKILL |
| AS geometry default, `set properties`, validate=False default, Stage A export fold | 56c104c, d1234e2, 9c32084 | speed banked (slide 8: 9:58 → 4:58) |
| bulk-read inspect | d218350 | 227s → 57s, byte-identical |
| IWA per-run style / grouped text | feat/iwa-per-run-style | offline runs on finalized decks |
| two-tier offline read, default ON | 9ad2ba3 + Session 15 | Map 51.8s / Full 283.7s vs 12.6 min; gate GREEN |
| r-count-guard, r-cache-hit-export-only, r-readback-nocache-fix (f3f19b1), r-reuse-side-content-strip (9f465ba) | — | read-side defects closed |
| w-spike0 (b8c7d68), w-spike1 core (5624eee), iwa_write patcher (5707d4d), write gate + A′ oracle (210b1c6, 233f388), group-child scaling (fe3cd87) | — | write mechanics proven |
| W0: tmp-path (2ac04db), skipped-slide bulk skip (695199d), z-order probe (99771bf), stroke probe (c4dc5e5) | — | Tranche 0 |
| W1 offline write opt-in | ec20f4b, a8b27ac, 5577e27 | default OFF; stabilise = tranche 1 |
| reuse group dedup (292802c), role=other group-child scaling + font pass (8a8ef7a) | — | reuse doubles fixed; group text scales |
| stat-finalize parity audit (7781de8), descending raise (aff1470), index-guarded addressing (23de0d2), nits (90aaa4e) | — | pass-2 addressing correct |
| output-bugs batch 1 (171fc65 … 8e5d3b2) | — | backdrop y=0, badge raise, stroke restore, caption groups never pins |
| output-bugs batch 2 (0ad68b0, 0cdcd2b, 753acef) | — | template card size, job-scoped caption step-down, template-pitch grid reflow |
| reuse round 1: builds/transitions follow source, side-panels positional (69ede81 … 3296ef3) | — | Gold build 3296ef3 PASSES part F exactly |
| reuse round 2: D1 remove-by-content, D2 hidden-target donor-remove, D3 twin revert, D5 roster rule, D4 frame-packing + write-anchor fix | 7722439, 501af25, 4654602, 37dbb90, 80cb442 | Gold build reuse-builds2/ PASSES plan2 §6 exactly |
| `autosize-rect-alignment-fix` | (this change) | `_autosize_rect` resolves `verticalAlignment` up the style parent chain; composed autosize tops are visual truth for every anchor |

## Insights worth keeping

**Placement model**
- One affine per **role**, not per slide (badge, map, cluster); structural title detection
  beats wording; fill-don't-letterbox (`FILL_MAX_CROP_FRACTION=0.47`) was the one code-side
  gold-closeness win — the rest of the gold distance is editorial crop choice.
- The template is a size/position oracle, not a styling oracle. Content that carries text is
  not a pin (proximity classification skipped the font pass on 5 cards and 27 circles).

**Groups and text in Keynote**
- Setting a group's w/h scales its children (AS and JXA) but NOT their font size — the pass-2
  font pass scales child text by the group's affine; stat numbers take the template size.
- Group children are addressable in place via AppleScript; every JXA "limit" (group children,
  line endpoints, per-char styling, z-order read, masters, export) was JXA-only.
- Content-signature addressing collides; address by index verified against content and skip
  rather than guess. Keynote's clipped-text "+" is editor chrome; wrap-off text spills
  horizontally instead. Never re-assert a verse box's text.
- Exact-text lookups leak across groups: 38/44 card captions are also roster-list leaves, so a
  per-leaf size must travel with its job (captionPt → leafPt), never in a deck-wide text map.
- A single template object carries size but no spacing; a relationship (pitch) needs two
  adjacent template objects. Card size came 1:1 from the template; the pitch only became
  template-derived once the owner pasted two neighbours (the 3-card L).
- A caption's real inset is the shape's own `padding` (4.0pt here), not a subsystem constant;
  the inset sweep (3→69, 4→70, 12→64 of 71 gold captions) is what settled it.
- remap_keynote's say() path has no offline gate: a shadowed local (`source` reused for a
  label string) crashed the first live run after every reviewer had passed the diff.

**Speed (closed — do not rebuild)**
- JXA and AppleScript READ at the same speed (~11ms/property); wins come from doing less work.
  Each AS command on a heavy slide redraws (~100ms) even off-screen.
- Abandoned with load-bearing reasons: Stage B reopen-fold (a cold open of the 6.8 GB deck is
  ~3–4 s; the "17%" was a broken run), batch z-order (multi-select Bring-to-Front does not
  reliably raise above the map), batch delete (`delete {list}` throws -1700; the "315×" was a
  try-hidden failure).
- Keynote 15 doc-bind: `POSIX path of (file of d as alias)`; `name of document` drops the
  extension; close-by-name → open → `document 1` → verify name.

**Offline read/write facts**
- Keynote returns INTEGER geometry; line endpoints needed a mirror-flip fix; masked near-zero
  rotation collapses to the axis-aligned box; the group residual IS the autosize defect one
  level down. A no-op Keynote save rewrites the globals (stylesheet compaction, renumbering) —
  byte-level per-slide fingerprints are dead; a saved patch is laundered through Keynote's writer.
- Concurrent Keynote access corrupts warms; verify a fresh payload has no empty slides.
- Banked oracles go stale (the write-gate sidecar + A′ predated the group-scaling change and
  mis-read as a "0.48× shrink"): re-derive the plan from the current planner before comparing
  a deck against "the plan"; any A/B gate must hard-fail on an unhealthy baseline.

**The operator loop**
- Confirmation only bites where the template has a framing worth picking; pages with no
  candidate are the prompt to add template slides. Fit-to-frame still overrules overrides on
  pages the template does not describe — tell the operator per page, never in a footnote.
- **The metric-that-misleads pattern:** framing selection went through five rewrites in one
  session, each fixing a real case and creating the next — a metric asked to infer something
  the data does not contain. When selection needs a sixth exception, *ask* (the Sermon
  Checker's propose/correct/remember-by-digest pattern is the template).
