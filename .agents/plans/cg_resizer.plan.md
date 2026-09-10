---
name: CG resizer — optimizations (read + write tracks), bug backlog, features
overview: "Single active plan for the CG resizer. As of 2026-09-09 (later same day), main is `a555f24` after PR #60 (parity round + R0.4), #61 `surface-raise-tokens`, #62 dead-code removal, #64 the Keynote-free golden plan gate, and #65 R2b `r-propose-two-tier`; the current branch `chore/golden-gate-hard-parity` carries one commit `20feac0` on top making propose/apply parity a hard gate. R0.1-R0.4, R2 readback, R2b, `surface-raise-tokens` and a six-survey refactor assessment are all complete. Open sequence: the W1 whole-deck gate on the Full wall (nap window), then `stat-raise-dead-4` from that gate's log, a shared osascript runner, IWA natural-size/sentinel unification, the W1 default flip, then W2. Owner soft deadline: W2 within ~1.5 weeks of 2026-09-09. Read `.agents/skills/obed-edom/SKILL.md` first. Measure first, never run Keynote concurrently, use copies for live probes, and obtain the owner's explicit hands-off acknowledgement for long Keynote runs. No PRs unless asked."
todos:
  - id: output-bugs-batch1
    content: "DONE 2026-09-03. Batch 1 of Map-deck output defects: the badge buried under the map, backdrop not at y=0, card stroke lost against the source, and caption-bearing groups misclassified as pins. Shipped `171fc65` ... `8e5d3b2`, including a geometry-guarded badge raise after the first live run raised the MAP on a reuse slide (index drift of one). Live-verified on the Map remap: `verify_batch1.py` and `verify_slide9.py` PASS, stroke 3.0 after pass 2, 66/66 slide-9 text groups at 0.483x, `score_resize` identical before/after. Full detail: the commit range plus the `Shipped record` row below; the verify deck and its previews were deleted with `output/`."
    status: completed
  - id: card-template-size-reflow
    content: "DONE 2026-09-03. Batch 2: photo cards take the template card rect, captions take the template swatch with a JOB-SCOPED whole-point step-down, and each card grid re-pitches to the template's own gutters (the 3-card L on slide 12) and reflows to 6 columns. Shipped `0ad68b0`, `0cdcd2b`, `753acef`. Live-verified on the Map remap: 71 cards matched, exactly the 5 predicted 9pt step-downs, 0 off-canvas cards, off-frame 29 -> 2, gold agreement 70/71; the accepted residual is 10 cards overlapping stat blocks (see `stat-group-template-sample`). The durable lessons (job-scoped sizes, pitch needs two template neighbours, inset is the shape's own padding) are in `Insights worth keeping`; verify deck deleted."
    status: completed
  - id: w-offline-write-stabilise
    content: "TRANCHE 1 (W1). SHIPPED ec20f4b/a8b27ac/5577e27 (OBED_OFFLINE_WRITE off|on|verify, default OFF = byte-identical production; deck-level patcher, streaming in-place rewrite, reconcile_counts refuse gate, AS fallback, read-back verify, scripts/offline_write_ab.py). The 'pass-2 0.48× group shrink' was an ORACLE ARTIFACT (banked specs_slide9.json + A_prime predate 8a8ef7a); the offline write itself is correct and survives pass 2. 2026-09-04 evening: GOLD BASELINE A/B KIT built and run — `remap` on main 869a28f vs this branch f083a67, PRODUCTION DEFAULT PATH (offline write OFF) — NO regression: geometry 0.00px on all 19 Gold slides, styles identical; the only diff between runs is Keynote's own drawablesZOrder scrambling (see w-zorder-patch). So the branch is safe to sit on at default OFF. Separately, opt-in mode (`on`) has a SEVERE REGRESSION, now root-caused: the IWA patcher writes correct frames but leaves Keynote's render-derived fields stale — shape pathsource naturalSize for non-bezier sources (`_find_bezier` only knows bezierPathSource), masked images (originalSize + mask naturalSize never written, displacement parked in the mask), text naturalSize never written, group children inheriting all of it. Content renders ÷4 inside otherwise-correct frames: 587 stale objects on the 12 offline Gold slides, 0 on the AppleScript ones. `verify_offline_frames` is structurally blind to this (compares the bytes it just wrote; skips masked/groups/text) — this also explains badgeUnresolved (10 Gold / 84 Full: stale-naturalSize plates + globes with a 467px anchor drift); the badge probe is correct and must stay as-is. So 'Map deck gate GREEN' in the tranche-1 handover was luck of object classes, not a clean gate. FIX SCOPE (2/1/2 planning, feature branch, in progress): universal path-natural writer (scalar corner constant, editable-bezier nodes rescaled per production); hard-miss on any unwritable field → AppleScript fallback for that object; masked media REFUSE for now; groups refuse on any unwritable descendant; text width naturalSize written (height stays informational); a spec-independent consistency audit (naturalSize==size, mask naturalSize==mask size, originalSize==size, mask offset within frame, 2% tol) that fails the run. TO CLEAR: (1) SUPERSEDED — see below, the whole-deck gate replaced the single-slide re-bank plan; (2) re-run offline_write_ab.py with a HEALTHY A (Accessibility granted; gate must hard-fail on an unhealthy A: pass-2 done/skipped counts, dedup counts), plan-as-oracle for exact classes, identity matching, group children bucketed separately, groups compared as a SET; (3) default-flip bar = gate GREEN on both gold decks with real patches AND one end-to-end `on` run placement-identical to a scripted run, now including the consistency audit. FLIP STAYS ON HOLD. The Full-deck A/B bank under output/offline-write-ab-full/ was deleted with output/ (owner); on 2026-09-07 the owner restored Full_Report_Card_Wall.key and the Full_Report_Card_CG.key reference, while Base_CG_Assets.key remains available, so a fresh ~1h-plus whole-deck bank is runnable. Design points that stand: deleteHides stays in pass 1 and the patcher bridges kindIndex (never both); reuse slides stay fully in Keynote; the JXA attrs pass stays in pass 1; mapReadback assertion moves to the verify. Payoff: replaces the ~100ms/command AS geometry phase (~100–155s Map, multi-minute Full) with seconds. UPDATE 2026-09-04 (fe44f6b) — the gate was hardened and earned its keep: 49cbc7e whole-deck gate (Accessibility pre-flight, clean-pass-2 bars, identity matching by drawable id — output ids == source ids on every non-reuse slide — plan-as-oracle for the exact classes via _spec_box, run records with digests, --mode on|verify, --no-validate); 36e2d81 REAL patcher defect found by the gate and fixed (iwa_write._text_fields wrote size_h onto an autosize text box whose stored h==0.0 is the sentinel; B's slide-8 text became a fixed 43pt frame); 6ac80d8 every bucket gates at doubled per-side budgets (measured Map: line 0.95 group 1.43 child:image 1.83); 3ca6385 refuses open Keynote docs + closes own stray decks; 08d2e2b --pass2-bar parity; 94df47f bulk-tier errors loud+durable (bulkErrors rides the cache) + gate quits Keynote between runs. MAP DECK GREEN in verify AND on modes (output/offline-write-ab-v2, -on; identity 100%, plan oracle B exact 0.00px, A ≤0.49 = AppleScript integer rounding). FULL DECK NOT GREEN, undebugged (output/offline-write-ab-full, A_unflagged + B_flagged banked with run records): offline-write verify FAIL image Δ2687px (n=174) line Δ88 shape Δ11 (keyed by bridged saved kindIndex — Full has hides mid-collection, so possibly mis-pairing); pass-2 badgeUnresolved 0→84 A vs B (badge raise scans the PLANNED frame — independent off-plan evidence); 30 specs on 26 slides missed the patch (AppleScript fallback ran); gate crashed at write_run_record(B) on int fallbackSpecs keys so the id-based compare never ran. Timing win is real: pass 1 20:12 (A) vs 10:40 (B) on 154 slides. NEXT: fix the round-trip, run the compare Keynote-free with --reuse-a --reuse-b --pass2-bar parity, then debug from the per-slide lines (bridge, masked/group scaling, the 30 misses, badge plates); missedSpecs with a healthy fallback should likely be WARN. DEFAULT FLIP still ON HOLD: patch at output/offline-write-ab-full/piece2-default-flip.patch, apply only on Full GREEN. The old plan's item (1) re-bank of the single-slide write_gate_ab kit was dropped by decision (the whole-deck gate supersedes it; stale sidecars are now refused by commit stamp). UPDATE 2026-09-07/08, branch `fix/w1-gate-integrity` off `9fa457c` (HEAD `b50f75b`, 4 commits: 31625d1, f76e8d3, e987a46, b50f75b), merged to main as PR #57 (`cd67e2e`) — the 2026-09-07 W1 RED gate (`output/bank/2026-09-07/write-gate-full/`) had THREE unrelated causes, and the first diagnosis was wrong. D1's headline verdict ('arm A was damaged by a stolen GUI focus/clipboard interaction, re-run, do not debug the code first') is DISPROVEN: a second live run on a verified-untouched machine (`write-gate-full-r2/A_unflagged.key`) reproduced arm A EXACTLY — 43 card-border refs vs source's 83 (`{94:12,126:27,127:2,128:2}` both runs), slide 125 = 0 of 44 cards both runs, pass-2 stat-finalize counters `312/323/630/57/78/41/135/319` character-identical between the two runs (`D6-arm-a-card-loss.md`). Random events do not reproduce to identical integers, so the seven `pass-2 A != B` RED lines are REAL systematic path differences, not stolen-interaction artifacts, and 31625d1's card-border-ref-count damage check is a TRUE POSITIVE on detection but a MIS-ATTRIBUTION on cause+remedy (see that commit's note below) — it would abort a healthy production arm. 31625d1 (gate integrity): `verify_offline_frames` group bar now gates at 2.5px (composed child-union vs planned rect); `needs_keynote`-flagged records route to a reported-not-gated `approx` list instead of silently vanishing, so a PASS with no group line is now structurally impossible; `group` stays in `oracle_kinds` with only the self-flagged tail skipped (union-vs-plan distribution is bimodal, empty gap between 7.41px and 91.45px, 9 of 13 outliers self-flagged); the false 'tolerated because A==B' summary text is fixed at both call sites; the SAME commit also added the pre-comparison card-border damage check described above — ITS STATED CAUSE AND REMEDY ARE WRONG per D1/D6 above and it has now been RE-ATTRIBUTED: the check keeps its detection and its exit-6 abort, but reports the ref shortfall as an observation, names D6's paste no-op as a hypothesis with the log tokens to check ('FATAL reuse slide', 'WARNING reuse slide'), and no longer tells the operator to re-run on an untouched machine or to skip debugging; the helper is renamed card_border_damage_reasons. `GATE_VERSION` deliberately NOT bumped so `A_unflagged.run.json`/`B_flagged.run.json` stay loadable. f76e8d3 (applyReuse paste fix, PRODUCTION DEFECT, root cause D6): reuse job 125's Cmd-V pasted the PREVIOUS job's clipboard because the Cmd-A/Cmd-C half silently no-oped under load, then `delete slide to+1` destroyed `orig` with all 44 report cards; NOT an A-vs-B property — slides 122-128 run identical JXA in both arms, arm B escaped only by reaching the paste ~5min into pass 1 vs arm A's ~17min on the same 5.3GB deck. The delete is now conditional on a measured per-kind collection-count delta matching `job.add`'s histogram; a deficit halts the deck with `orig` intact and nothing saved, never retried on a deficient-but-non-zero delta; `applied` no longer counted on the slide about to be deleted. Two further data-loss paths were found DURING REVIEW by executing probes: a summed retry rule that double-pasted, and the discovery that the `-1` 'unmeasured' sentinel was unreachable in production (a JXA property read builds an element specifier locally and never throws), which let a misread `beforeAdd` baseline measure a failed paste as pure surplus and delete anyway. KNOWN OPEN HOLE: a stale paste whose histogram DOMINATES the expectation is not caught; needs the deferred geometry post-condition. e987a46 (sparkle coincident-twin fix): the on-sparkle effect was missing from the '183 CHC Churches' and 'Total Churches 269' stat groups; cause = the plan-time geometric hide `coincident_duplicate_ids` (`map_remap.py`, matching kind + rect within 4pt + a group signature that is only `childCount`), running in `plan_transforms` — orthogonal to the W1 flip, so both write paths lost the twins identically. This exemption shipped once (`4cadd15`) and was reverted (`4654602`); the revert was correct, the one-line version is a net regression (12 unresolved, 8 dedup shortfalls, reproduced offline at the historical numbers). All three parts land together in e987a46. Measured on the real deck: hides 982→980, statJobs 390→392, groupRemoves 198→206, sigless 8→0, slide 124's add list gaining kindIndexes 5 and 7; Gold parity verified (slide 13, same two twins); no build-creation capability needed (a reuse `add` carries the drawable's build); `sigFallback` moves with four new `sigTwin(s=124,…)` entries — expected, not a regression. 2026-09-08 CONFIRMING LIVE RUN (directory since deleted; only the JSON censuses under output/bank/2026-09-08/{build-order,twin-zorder}/ survive; EXIT 0, plain production `remap`, `OBED_OFFLINE_WRITE=off`, deliberately NOT the A/B gate because the mis-attributed damage check would abort a healthy arm): card census of the produced deck 83 refs `{94:12,125:44,126:27}` identical to source (both prior production runs: 43, `125:0`); live log `Card-border stroke: … (269 refs)`, the healthy number; `Applied 3346, missed 0`; slide 124 carries 9 builds including both `KLNSparkle In` keys, identical to source; the `slide 125 lost 44 apple:dissolve` / `slide 124 lost 2 KLNSparkle` warnings are GONE; stat-finalize `381 done / 206 deduped / 11 skipped / 110 sig-fallback`, dedupShortfall 0, unresolved 0, `Builds follow source: 86 kept`; OWNER VISUALLY CONFIRMED the on-sparkle plays — original report CLOSED. Two honest caveats: sig-fallback landed at 110 against a predicted 112 (the prediction assumed arm B's baseline carries to the production path; this is the first healthy production-path run, so it stays unresolved — `childResize.detail` `sigTwin` tokens are not persisted by a plain CLI remap); no job needed a retry, so the new paste guard was never observed firing-and-recovering — the new polls may have PREVENTED the failure rather than caught it, and distinguishing the two needs the per-attempt `gates` data in `addReports`, which the CLI does not write. Rebase note: branch rebased onto `9fa457c` (PR #51, maps tab); overlap only `map_remap.py` (one line, `is_backdrop` gains `\"movie\"`) and `test_map_remap.py`; sparkle acceptance numbers re-measured post-rebase match exactly, forcing `is_backdrop` back to its pre-merge form also gives `hides 980` — the maps change is inert for this deck. Suite 1461 passed / 24 skipped, all 8 node harnesses green. NEW BACKLOG ITEM opened from this round's live-run comparison: `w1-build-order-nondeterminism` (build sequence, not membership, wrong on ~30 slides, pre-existing and non-deterministic run-to-run, not caused by these three fixes — see that item). STATUS: three defects fixed and live-verified on the real production deck, and the branch merged to main as PR #57 (`cd67e2e`); 31625d1's damage check re-attribution (detection and abort kept, cause/remedy replaced with a falsifiable diagnose-first message) did NOT land in this branch; it shipped as `917b00f` + `eab0cec` on follow-up branch `fix/w1-damage-check-reattribution`, MERGED to main in PR #59 (`2d6ae55`, 2026-09-09 morning); default flip stays ON HOLD. PATH NOTE 2026-09-09: every `output/offline-write-ab*` bank cited above is deleted (the Map `-v2`/`-on` banks, the Full `A_unflagged`/`B_flagged` pair and `piece2-default-flip.patch`, which must be re-derived); the surviving W1 artefacts are `output/bank/2026-09-07/write-gate-full{,-r2}/` (run records and `gate.log` only, both 5+ GB decks deleted) and the 2026-09-08 censuses under `output/bank/2026-09-08/{build-order,twin-zorder}/`."
    status: pending
  - id: r-nested-bulk-probe
    content: "TRANCHE 1 (R1) - DONE 2026-09-04, PROBE ANSWER = NO. `scripts/probe_nested_bulk.py` (`d4663ed`, `99b2e09`) ran live on APFS clones of the GW and Map decks: nested `<prop> of every <kind> of every slide` is CORRECT and safe on all four criteria, but not faster (GW 1.37x, Map 0.73x = slower). The load-bearing measurement is per-read seconds: the cost is per object-property inside Keynote (~70/33/9 ms), not per Apple Event, which refutes the overhead-dominated hypothesis and closed `r-bulk-counts-plan` with it. Findings sidecars `output/nested-bulk-probe/` were deleted; the failure semantics and the verdict survive in `Insights worth keeping` (Speed) and SKILL."
    status: completed
  - id: r-readback-two-tier
    content: "TRANCHE 2 (R2) - DONE 2026-09-07 on `fix/resizer-backlog-r2`, shipped `b50d22b` + fix round `7bb0f52`. The validated-resize readback now goes through a `_readback_payload` ladder (offline-write verify forces legacy, then the `OBED_OFFLINE_READ` kill switch, then two-tier ranged, with a fail-safe to ONE legacy read); `inspect_keynote_checker` gained `slide_range` and ranged reads never cache. Verified twice: a ranged A/B (identical scalars/flags, no cache write, only the documented zero-rect placeholder-tail difference) and a whole-deck field-parity A/B on all four Gold banks - childCount gate 0, zero blocking item differences, exact validate flags, and 2.4-2.6x timings (130.7 -> 52.5s on main). Evidence: `output/bank/2026-09-07/ranged-ab/` and `output/bank/2026-09-07/full-ab/`. Unblocked `r-propose-two-tier`."
    status: completed
  - id: r-propose-two-tier
    content: "TRANCHE 2 (R2b) - DONE 2026-09-09, PR #65 `feat/r2b-propose-two-tier` (`4627497`, 16 commits, Codex 4 passes). UTF-8 decode of CP437-mangled Data/ member names in `offline_inspect._build_data_index` (deck_slide_digests churn 3→0 slides on the Full wall); `remap_keynote.prepare_wall_payload` (enrichment extracted; called INSIDE `framing.propose_framings`); checker refuses a cache entry unless every eligible text item carries runs (`_payload_has_runs` coverage predicate) and a rejected entry never reaches the legacy reader (`use_cache=False`); `inspect.store_inspect_payload` caches the two-tier payload under the digest with reader=offline; propose reads through `acquire_wall_payload` (full deck then slice; navigator numbering always); `framing._transform_of` uses `map_remap.frame_affine`; `map_remap.carry_fit_context` shared by planner and propose; `planned_rects` rounds the serialised 2-dp apply coordinates; `tests/test_propose_two_tier.py` hard parity 0/155 (Counter multiset). LIVE-VERIFIED 2026-09-09 on Gold_Wall_Input.key (`output/bank/2026-09-09/nap-run/r2b/results.md`): cold propose 96s two-tier (vs 269s legacy), cache entry reader=offline, apply read `from cached offline payload` (Applied 832/0, 269 refs, 181 raises landed, no raiseDead), re-propose 4s cache hit; counter deltas vs r2-round all the sparkle-twin fix. OPEN R2b RESIDUAL: the apply→propose plan hand-off (survey obs. 9) is still not passed through."
    status: completed
  - id: w-zorder-patch
    content: "TRANCHE 2 (W2). Offline drawablesZOrder+ownedDrawables reorder (patch BOTH identically) at the W1 hook, LAST per slide, replacing pass 2's GUI Bring-to-Front raises (obedRaiseSlide + the badge raise) and the resizer's Accessibility dependency. PROBE LIVE PASS 99771bf (2026-09-02): Keynote 15.3.1 honours a patched order on open, a re-save keeps it, the render changes; permute within the target ids' slots (a fresh deck carries 3 placeholder drawables). Correctness is already handled by the index-guarded descending raise (23de0d2) — this is purely the optimisation: ~0.55s/raise × N GUI clicks + Accessibility + run-to-run group-index churn. 2026-09-04 evidence this is now COSTING content, not just speed: the gold-baseline A/B kit (w-offline-write-stabilise) ran the identical `remap` twice (main vs branch, same default path) and got two different renders purely from Keynote's own drawablesZOrder scrambling on save/open — banner text hidden on Gold slides 3/4/5/8/9 in one run, 'Global Missions' clipped to 'Glob' on slides 11-17 in the other. Same deck, same code, different z-order outcome each Keynote pass. Raises the priority of this item independent of the read-speed payoff. Must run after pass 2's font sizing (or recompute stat indices), and the read-back compares reordered kinds AS A SET. Gated on W1 stable. Risk MEDIUM. 2026-09-05, offline z-order reads of the banked gold decks: the pass-2 GUI raise arranged 0 of 227 reported objects on the `main` run (all 19 slides byte-identical to the source order) and 91 on the `branch-verify2` run, with identical 'front=' counters. frontRaised counts System-Events clicks, not arrangements. W2 also removes an unverifiable counter. D7 (2026-09-08, offline) measured build order and z-order as DISSOCIABLE arrays sharing only one upstream trigger (Keynote's non-deterministic slide-archive re-serialisation on save): 7 slides scramble builds with z-order perfectly intact, 3 scramble z-order with builds perfectly intact, and build-position/z-index Kendall tau is -0.016 output vs +0.058 source null control — so W2's own plan must NOT assume its z-order write also fixes build order (see w1-build-order-nondeterminism), and the build-order patch (`restore_source_builds`) must keep running LAST, after any future W2 z-order write, for the same reason it works today. D8 narrowed the build-order defect to our own patch (`plan_build_patch` writing `builds` order instead of `buildChunks` order on 3 reuse slides) — see w1-build-order-nondeterminism — so W2 inherits no build-order obligation of its own. D9 (2026-09-08, offline + owner playback) DISPROVES this item's own earlier claim that 'Correctness is already handled by the index-guarded descending raise (23de0d2) — this is purely the optimisation': `obedRaiseSlide` drains its per-slide raise targets highest-index-first, and because Bring to Front appends, every raised set with ≥2 members came out EXACTLY reversed — 16 slides deck-wide, 13 of them non-reuse, byte-deterministic across two separate production runs days apart (not Keynote's z-order churn). Fixed in `8a7b4bb`, MERGED PR #59 (`2d6ae55`): ascending raise gated on a verified per-target landing (new `obedGroupFrame` + the existing `obedTopReal`/`obedBadgeFind`), with `raiseMoved`/`raiseDead`/`raiseUnknown` counters replacing the unverifiable `front=` click count. CONFIRMED ON SCREEN 2026-09-09 (`raiseDead=0`, 11/15 subset slides preserved including the sparkle twins). Residual reversals on constellation slides 131/133/134/144 are owner-DEFERRED to the framing workstream, attribution not yet measured — tracked under `r-reuse-photo-placement`, not as an open z-order bug here. With the raise-order bug fixed, W2 remains PURELY the speed/Accessibility-removal optimisation it was always scoped as (replacing 699 GUI clicks + the Accessibility dependency with an offline `drawablesZOrder`/`ownedDrawables` write); it still gates on W1 stable, and the build-order patch (`restore_source_builds`, see `w1-build-order-nondeterminism`) must still run LAST after any future W2 z-order write — unchanged from D7's finding that the two arrays are dissociable. The 2026-09-09 parity run shows the ascending raise (`8a7b4bb`) at raiseDead=4/381 deck-wide, with the two located misses on non-reuse slides 106/110 (`stat-raise-dead-4`) — record here, do not re-plan W2 on it."
    status: pending
  - id: w1-build-order-nondeterminism
    content: "BUG (B) - CLOSED 2026-09-09. Reveal order on reuse slides 124/125/126 was wrong because `plan_build_patch` ordered survivors by the source's `builds` index and wrote that order into BOTH `builds` and `buildChunks`; D8 established that `buildChunks`, not `builds`, is Keynote's render timeline, which collapsed D7's 34-slide `builds`-array census to 3 slides on the render metric. FIXED in `59111fc` (merged PR #59, `2d6ae55`): survivors are ordered by the matched source build's `buildChunks` position, with a chunk-order read-back check and `chainHeadless`/`ambiguousPairs` WARNs; suite 1492/20, restricted chunk-key divergence vs source went [124,125,126] -> []. Verified twice on ground truth: owner playback confirmed the reveal order on screen 2026-09-08, and the 2026-09-09 parity remap (first FRESH production run at >= `59111fc`) passed V3 (order/surplus/transitions empty) and V4 (first chunk `referent` on all three patched slides). STANDING CONSTRAINTS: do NOT widen `slides` at `remap_keynote.py:1439` from `reuse_slides` to the whole deck (it would take a 3-slide defect to 66), and `restore_source_builds` must keep running LAST, after any future W2 z-order write - the two arrays are measurably dissociable (Kendall tau -0.016 output vs +0.058 source null control), so this never folds into W2. Full detail: `output/bank/2026-09-08/build-order/D8-build-chunks.md` and `plan-build-order-fix-v2.md` (whose line cite `remap_keynote.py:1396` is stale), plus `output/bank/2026-09-09/parity-run/`."
    status: completed
  - id: r-cache-quick-wins
    content: "R0 leftovers - ALL FOUR DONE. (1) `r-propose-from-cache`, (2) `r-acquire-cache-read`, (3) `r-digest-sidecar` landed 2026-09-07 under 1/1/1 with independent APPROVE each; (4) `r-misc-cleanups` (R0.4) shipped 2026-09-09 as `a89b9b3`, `006f68b`, `db3109d`, `bdc3ee4`, `bb04d91`, merged `b981eb0`. Load-bearing measurements: on the 6,771,226,182-byte Full deck a cold digest is 3.97205s against a 0.1197ms warm median (so ~3.97s saved per avoided hash, not the old speculative 30-60s claim); and the R0.4 live gate on the 9-slide Sermon_GW clone gave identical payloads, 0 differing pixels on 9/9 previews, one Keynote open instead of two, export 6.56 -> 4.38s and 0 documents left open. R0.4 was reviewed by Codex gpt-5.6-sol over three REQUEST-CHANGES rounds -> APPROVE-WITH-NITS (kept-open leaks, wrong-document export, stale-PNG-masked failures, a reset before the lock); suite 1535/20 on the merged round branch. BEHAVIOUR CHANGES to remember: a partial preview set is no longer served as a warm hit, and a module `_KEYNOTE_LOCK` now serializes every live JXA/AppleScript transaction. Full detail: the `R0.1-R0.4 outcomes` section below and `output/bank/2026-09-09/cp0/results.md`."
    status: completed
  - id: r-reuse-photo-placement
    content: "BUG BACKLOG (B). Reuse is KEPT (measured +39% on contiguous map series). Part (A) DONE in bf0fbe7 on branch fix/reuse-builds-side-panels: no (0,0) yank ever occurs (`ItemTransform.as_dict` always emits x/y; `applySpec` returns before any write when spec.x is null) — the real defect was a spec-less reuse add being silently skipped (not even counted as missed) and riding the paste at its wall coordinate; fixed by giving such adds a canvas-scaled rect and counting them as misses if still absent. Part (B) FRAMING COVER-FALLBACK OFF-FRAME on dense infographic slides (124/125-class, pairQuality=0) still open — reuse-INDEPENDENT (identical off-frame counts on/off); a framing item touching all slides, own workstream. Once W1 removes the AS-geometry bottleneck, dropping reuse becomes cheap — revisit then. Z-ORDER RESIDUAL (D9, 2026-09-08/09): after `8a7b4bb`'s ascending-raise fix (see `w-zorder-patch`), 4 constellation-band slides (131, 133, 134, 144 — 67/68/68-group reversals) still show relative z-order divergence from source; mechanism not yet attributed. Owner-DEFERRED to the framing workstream rather than tracked as an open z-order bug — group it with this item's Part B off-frame/cover-fallback work, since it lands on the same dense slide class. 2026-09-09 parity run (`output/bank/2026-09-09/parity-run/raise-order.txt`) reproduced the same OTHER-not-REVERSED pattern D9 first saw: 5 of 19 non-reuse id-matched slides diverge — 131 (tau+0.20), 132 (tau+0.20), 133 (tau+0.94), 134 (tau+0.94), 144 (tau+0.94) — 14/19 preserved overall, slide 124's twin still preserved. Slide 132 is NEW to this list versus the 4 slides (131/133/134/144) the owner named on 2026-09-08 — not yet reconciled with the owner; add it to the framing-deferred set pending that review."
    status: pending
  - id: full-deck-stat-finalize-unresolved
    content: "BUG (B) - CLOSED 2026-09-09. On the Full report deck, pass 2 left 134 stat groups unresolved (wall font size, buried) with 6 dedup shortfalls and 145 skips; the driver turned out to be the reuse-chain paste no-op fixed in `f76e8d3` (D6), not stat-finalize addressing. The 2026-09-09 parity remap measured the full counter table against THIS item's own 2026-09-04 originals: done 245 -> 381, skipped 145 -> 11, unresolved 134 -> 0, dedupShortfall 6 -> 0, jobs 390 -> 392, sigFallback 108 -> 110 (also recorded: sized 413, badgeMoved 319, dedupDeleted 206, raiseMoved 377). Two things did NOT close with it: `-1719`/`frontErr` stays unverifiable by CLI (`keynote.py:1421`/`:1508` keep it only in `result[\"raw\"]`, see `surface-raise-tokens`), and the run raised a new anomaly tracked as `stat-raise-dead-4`. Evidence: `output/bank/2026-09-09/parity-run/run.log`."
    status: completed
  - id: stat-raise-dead-4
    content: "BUG BACKLOG (B), NEW 2026-09-09, found in the parity remap (`output/bank/2026-09-09/parity-run/run.log`): `WARNING stat-finalize: 4 stat group(s) did not move on Bring to Front (0 abandoned mid-slide)` — raiseMoved 377 / raiseDead 4 / raiseUnknown 0 of 381 done groups, deck-wide, on `8a7b4bb`'s ascending gated raise. Offline localisation this round (`probes/find_raise_dead.py`, same run) found 2 of 4 by non-contiguous-group-block analysis: slide 106 group `18386827` ('Keiko', z=15, buried while siblings 'Daniel'/'Grace' raised to 18/19) and slide 110 group `19010920` ('Sunday Service', z=2, buried while siblings 'Children's Church'/'Bible Study' raised to 6/7) — both non-reuse, and both were CONTIGUOUS in the banked 2026-09-08 healthy run (`output/bank/2026-09-08/twin-zorder/PREFIX2.json`), so both are regressions against that baseline, not pre-existing. The other 2 raiseDead are unlocatable offline: a lone stat group on its slide leaves no z-order contiguity signal to test against. The reuse band 123-128 is internally contiguous on every slide with groups (self-consistency check, not a source comparison). Slide 42's own 2-group gap was checked and ruled out — identical in this run and the 2026-09-08 healthy run, pre-existing and unrelated. Facts only, no cause yet: the machine was hands-off by the owner's own timestamped ack (`ENV.txt`: 'I'm already hands off, out for breakfast. start!', 09:40:44) so the stolen-GUI-interaction story that explained the 2026-09-07 arm-A card loss does not apply by default here — but per 'measure before attributing', this is still n=1 on a single run and needs a second measurement before ruling it out formally. Precondition / first step: `surface-raise-tokens` below — the per-slide `raiseDead(s=,idx=)`/`raiseUnknown(s=,idx=)` tokens are not currently logged, so this round's localisation needed an offline z-order probe instead of reading the log directly; the next run should localise all 4 by log alone."
    status: pending
  - id: surface-raise-tokens
    content: "DONE 2026-09-09, PR #61 `fix/surface-raise-tokens` (`c5e9c34`, Codex 3 passes), precondition for `stat-raise-dead-4`'s diagnosis. `keynote._run_stat_finalize` now returns `tokens` {name: [args]} and `frontErr`; `obedRaiseSlide` emits a `raiseDead(s=,idx=)` token for EVERY dead raise (the `is 0` guards removed); `remap_keynote._say_stat_finalize_detail` logs `Stat raise detail: ` (chunks of ≤40, marker `(i/n)` after the prefix), `WARNING stat-finalize: GUI Bring to Front returned error(s) `, `Badge raise detail: ` (unchanged), `Stat resolve detail: ` (rare kinds uncapped, sigFallback capped at 40). Unblocks `stat-raise-dead-4` localising all 4 `raiseDead` occurrences by log alone on the next production run."
    status: completed
  - id: resizer-dead-code
    content: "DONE 2026-09-09, PR #62 `chore/resizer-dead-code` (`7e0d517`). Deleted `enforce_min_size`, `pair_maps`/`_basename`, `repack_free_text`, `fit_similarity`, `residual_rmse`, the dead `parked_left`/`_pack_left_groups`/`pack_columns_from_left` path (dead since `9bca221`; overlap now owned by `stat-group-template-sample`), dead locals, inlined `_groups_for_slide`, deleted `subset_keynote.py`/`.js`. No behaviour change."
    status: completed
  - id: golden-plan-gate
    content: "DONE 2026-09-09, PR #64 `chore/golden-plan-gate` (`4651b7b`, Codex 4 passes). `scripts/golden_plan.py` + `tests/test_golden_plan.py` + `tests/fixtures/golden-plan/{gold_wall_input,full_report_card_wall}.json` — a Keynote-free apply-plan SHA-256 gate through the real `remap_keynote.remap_keynote` with `_run_jxa` sentinel-stubbed; goldens keyed on deck/template digests, INSPECT_VERSION, env pins, plannerEnv {osBuild via `sw_vers`, caption faces via `_ns_font`}; `update --accept-input-drift`. Run this after any planner/driver change; see also `chore/golden-gate-hard-parity` (`20feac0`), which makes propose/apply parity a hard gate on top."
    status: completed
  - id: resizer-refactor-assessment
    content: "DONE 2026-09-09. Owner asked whether to refactor; verdict NO REWRITE. Six read-only surveys banked at `output/bank/2026-09-09/refactor-survey/`. Defects found (not style): `_KEYNOTE_LOCK` covers reads only (pass 1/2, fallback, template stat read unlocked); NO timeout on any JXA subprocess; `_read_template_stat_sizes_via_keynote` ignores rc → `{}`; stat-finalize and template-stat scripts bind `document 1` unverified then save; `_build_slide_geometry_script` itemIndex fallback addresses a typed collection; `deleteHides` failure → opacity-0 ghost; `layouts.error`/`sizeProp`/`saved` produced never read; `iwa_geometry._natural_size` (bezier-only) vs `_path_source` (6 kinds) disagree — editable-bezier text composes (0,0); autosize sentinel height-only on read vs either-axis on write; `_group_child_records` hard-codes the centre anchor; `_load_deck` silently drops undecodable members and is decoded ≥6x per verify run; `iwa_text_shape` anchor model (`compose_text_geometry`, `TextGeometry`, `geometry_flags`, `TEXT_INSET`) has no production caller; `slide_fingerprint.py` unwired; 12 osascript runners, 3 decode→re-encode→diff copies in `iwa_write`. Sequence ruled: shared osascript runner (timeout/lock/name-verified bind) before the W1 flip; IWA natural-size/sentinel unification + one decode→re-encode→diff before W2; planner split only when the next role lands."
    status: completed
  - id: stat-group-template-sample
    content: "BUG BACKLOG (B), follow-up from batch 2 (owner accepted the overlap for now). The re-pitched card grids overlap the affine-sized stat blocks (slide 4: date banner + '44 / Total Church Buildings' 109×265; slide 5: '110 / Full-Time Workers') — 4 + 6 cards, reported per card by caption in the say() line. Gold hand-reshaped those blocks (44 block → 509×88 bar above the grid). Fix = a stat-block sample in the template so those groups take a template size/shape (sibling of the constellation cluster affine: role-named group + template anchor). Until then the operator drags them; the grid origin already descends below stat blocks when the rows still fit (slide 5 y0=392)."
    status: pending
  - id: constellation-cluster-affine
    content: "BUG BACKLOG (B) / recipe work, after batch 2. Per-CLUSTER affine with template anchors (section below). Today one uniform fit-to-width (0.48×) leaves the top half empty; gold scales each CHC cluster ~0.82× as a unit and pushes clusters outward to fill the frame. Cluster discovery offline from line incidence; per-object size from the template circle swatches; placement by pairing clusters to template ANCHOR circles at gold positions (angular order around the building); hub lines rewritten by identity; radial frame-fit fallback when anchor count ≠ cluster count. Template needs one anchor circle per cluster + building/people rows/SOT at gold positions. Score offline against gold before any Keynote run."
    status: pending
  - id: builds-follow-source
    content: "DONE 2026-09-06 on `fix/reuse-builds-side-panels` (`69ede81` ... `80cb442`). Reuse targets lost the source slide's animations; the fix is the offline IWA patch `restore_source_builds`, run after stat-finalize, which computes a KEEP multiset keyed (effect, animationType, geometry-free target identity), emits kept builds in source order, copies transitions verbatim in the same SlideArchive rewrite, and raises on any surplus. Gold-verified at `output/bank/gold-baseline/reuse-builds2/` (`80cb442`): reuse slides 12-17 carry 0/9/44/29/1/3 builds in source order with the right six transitions and zero surplus deck-wide. Two known residuals: 2 KLNSparkle builds on slide 13 are reported as a loud shortfall WARNING (full-fidelity routes still a follow-up), and D8 later refined what `source order` means - it is the source slide's `buildChunks` order, not its `builds` order (see `w1-build-order-nondeterminism`). Full detail: `output/bank/2026-09-06/review-B/review.md` (the round-2 plan dir `output/handover-2026-09-05/` was deleted)."
    status: completed
  - id: side-panels-positional
    content: "DONE 2026-09-06, same branch and commits as `builds-follow-source`. The deck-wide list-hide arm was deleted and `--keep-side-panels [SLIDES]` became POSITIONAL and per-slide, keying off `is_side_panel_item` (content outside the centre wall band x in [1920,5760]); reuse reconcile became role-aware for persisted pairs including groups, and a phantom-remove filter drops `remove` refs for already-deleted donor objects. Round 2 refined the same gate with the owner's roster rule (roster kept only on the church-list slide(s), packed into frame, hidden everywhere else regardless of position). Gold-verified in the same `output/bank/gold-baseline/reuse-builds2/` build. Full detail: `output/bank/2026-09-06/review-B/review.md`."
    status: completed
  - id: autosize-rect-alignment-fix
    content: "DONE 2026-09-06 - read-side only, offline unit tests. `_autosize_rect` (`src/obed_edom/iwa_geometry.py`) assumed an autosize text box's stored y is always the visual CENTRE, which is true only for a `kFrameAlignMiddle` box; it now resolves `shapeProperties.verticalAlignment` up the style parent chain and branches Top -> `y`, Bottom -> `y - nh`, else `y - nh/2`. Measured on the Gold CG deck: 168 middle / 11 top of 179 autosize boxes, 0 unresolved, and the frame-containment oracle stopped false-failing the packed slide-11 columns at y ~ -140. NEVER re-add write-side `+-h/2` compensation for this (the bug reverted in `80cb442`); `iwa_text_shape.compose_text_geometry`'s independent `geometry.flags` anchor model is deliberately untouched and is worth its own item. Full detail: `output/bank/2026-09-06/anchor-diagnosis/diagnosis.md`."
    status: completed
  - id: pack-lists-gate-widen
    content: "DONE 2026-09-07 - `dcae6a7` + review-blocker fix `b6039ef` on `fix/resizer-backlog-r2`. The measured list packer only fired on whitelisted slides; it now targets role==list only, erases from the occupancy raster exactly the boxes it moves, and both gates widened from `slide_lists` to `slide_lists or slide_keeps_centre_roster`, with preview resolution decoupled from the whitelist (`preview_wanted_slides()`). Measured on the banked Full-wall payload: a flagless run goes 0 -> 93 placements, all role=list, overlap 0.0, where the naive widen would have moved and erased 120 hidden boxes; whitelisted runs are deliberately NOT byte-identical to parent because the parent moved 198 non-list boxes. Three residuals worth their own items: a LATENT Gold flip once a preview cache exists, bare `--keep-side-panels` still decoding all 155 previews, and 94/311 list boxes on whitelisted runs getting neither packer. Full detail: `output/bank/2026-09-07/review-pack-lists/`."
    status: completed
  - id: reuse-chain-preadd-duplicate
    content: "DONE 2026-09-06 - `08a5130`, stacked on `d31fedc`. The reuse chain pasted a slide's delta and deleted it again one slide later (Gold: 85 names pasted onto 12, deleted one AppleEvent at a time off 13's copy); `applyReuse` now duplicates the donor into the next target's slot BEFORE pasting its own adds, behind a four-part planner gate (donor immediately previous, every donor-pasted item dies on the target, no pasted GROUP, no donor mutate) with a `removeFallback`. Timed production Gold build `output/bank/gold-baseline/preadd/` (910s cold, EXIT 0): reuse deletes 91 -> 6, all 11 deferred acceptance items passed, `count_deck` exact, and the offline A/B vs `reuse-builds2` was 0.00px on all 19 slides with 19/19 previews byte-identical - the first trusted use of the alignment-aware containment oracle. The non-adjacent case was spun off as `reuse-chain-parked-snapshot`. Full detail: `output/bank/2026-09-06/plan/preadd-duplicate-plan.md`."
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
    content: "DONE 2026-09-04 - `cbde0a7`. `is_list_item` called any CHC/CHLI/CHEL text a roster list and the unticked-list gate (`loose` is True whenever there are no previews) deleted 23 single-line map labels on Gold slides 3/4/8/9. Fix: `name_columns()`/`name_column_ids()` - a name column is >= 3 same-left-edge rows (x tol 6, pitch 2.0xh) or a multi-line box, and a lone label demotes to role=other before the hide gate. Measured: Gold hide 491 -> 468 with everything else byte-identical, Full-deck sweep 0 roster rows demoted and 134 labels newly kept across 58 slides, live-verified within 1px of the human ideal on slide 9. `name_columns()` is the reusable primitive the side-panel work builds on; the `labelfix` Gold bank was deleted, the commit and the Full-deck sweep numbers are the record."
    status: completed
  - id: map-label-text-sizing
    content: "DONE 2026-09-07 - `e74e5fa`. Demoted map labels came out at 35pt instead of 40pt: the template palette holds TWO white Amplitude-Bold swatches (40pt Malaysia tile, 35pt China tile) and `match_character_style`'s colour tie broke on `predicted = wall x 0.5 = 20pt`, so 35 always won by penalty - `40 x 0.875 ~ 35` was pure coincidence, and slides 8/9 were right only by luck. Fix: unpaired list/other text predicts with the affine it rides (`size_ratio=aff.s`, 0.5 with no affine), so a translate-only map at s=1.0 predicts 40. LIVE-CONFIRMED on the r2-round Gold build: font census vs preadd differs ONLY on 'CHC Sitiawan' slides 3/4, previews diff only on 003/004, geometry 0.00px. Full detail: `output/bank/2026-09-07/label-sizing/diagnosis.md`."
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

## Current state (2026-09-09 evening, branch `chore/golden-gate-hard-parity` @ `20feac0`)

- `main` is `a555f24`. Merged today, in order: PR #60 (parity round + R0.4), #61
  `fix/surface-raise-tokens` (`c5e9c34`), #62 `chore/resizer-dead-code` (`7e0d517`), #64
  `chore/golden-plan-gate` (`4651b7b`), #65 `feat/r2b-propose-two-tier` (`4627497`). The current
  branch carries one commit on top of `a555f24` — `20feac0`, making propose/apply parity a hard
  gate now that R2b is merged.
- `surface-raise-tokens` and R2b `r-propose-two-tier` are both DONE (see their todos); their
  shared precondition/successor `stat-raise-dead-4` is next, unblocked, and should localise all 4
  `raiseDead` occurrences by log alone on the next production run.
- `resizer-refactor-assessment` is DONE: no rewrite, six read-only surveys banked, and the defects
  found reorder the sequence ahead of W1/W2 — see that todo and "Order of work" below.
- **W1 default flip stays ON HOLD** (`w-offline-write-stabilise`: universal naturalSize writer +
  a healthy whole-deck gate are its bar), now with a **nap-window whole-deck gate run on the Full
  wall** as the next concrete step (`output/bank/2026-09-09/nap-run/`). **W2 `w-zorder-patch`
  stays gated on W1** and is purely speed/Accessibility removal, since `8a7b4bb` fixed the
  raise-order correctness bug W2's own plan had assumed was already handled.
- **Deck facts:** `Map_Extracted_Wall_1st.key` is gone from the decks folder (58 oracle tests
  skip); `Full_Report_Card_Wall.key` was re-saved by autosave 2026-09-09 10:34 (content identical,
  digest `291b0322`, old cache stale) and is owner Finder-locked — `ditto` preserves `uchg`, so the
  W1 gate must run from an unlocked working copy (`RUNBOOK.md` step B0). Owner soft deadline: W2
  within ~1.5 weeks of 2026-09-09.
- `scripts/e2e_run_parity.py` has NOT been run since R0.4 landed, and R0.4 changed the
  read/export path — Discipline requires it. It opens Keynote, so it needs an owner-acked window.
- **Artefacts:** the 5.4 GB parity output deck was DELETED by the owner on 2026-09-09; the B-side
  evidence that survives is the JSON censuses + `run.log` under
  `output/bank/2026-09-09/parity-run/`. The R0.4 checkpoint-0 bank
  (`output/bank/2026-09-09/cp0/`) and the R2b nap-run results
  (`output/bank/2026-09-09/nap-run/r2b/results.md`) are still on disk. No output `.key` deck
  survives anywhere under `output/` — `output/bank/gold-baseline/*` holds logs and previews only.

### R0.1–R0.4 outcomes (all complete)

**R0.1 `r-propose-from-cache`** — a ranged proposal now reuses a complete digest-current
`reader: jxa`/`offline` cache instead of a full wall JXA read; the subset plans while the full
payload keeps digests, decisions, numbering, skips and thumbnails, and any malformed cache falls
back. Review caught skip-aware navigator overflow and permissive numeric coercion. Keynote-free
gate: 1,223 Python passed / 20 skipped, all JS harnesses green, no Keynote opened. Live
cached-vs-fresh A/B is still owed (it opens Keynote).

**R0.2 `r-acquire-cache-read`** — `acquire_wall_payload` serves complete digest-current caches
(`on`: jxa+offline, `off`: jxa only), always returns the full deck even for a ranged Apply, stamps
fresh two-tier payloads `reader: offline`, refuses to leak a rejected cache through the legacy
fallback (`use_cache=False` after a rejected hit), and keys group-child attachment to
`wall["reader"]` rather than the requested mode. Gate: 1,233 passed / 20 skipped, no Keynote opened.

**R0.3 `r-digest-sidecar`** — regular-file deck digests now use a strict, path-keyed, atomically
written sidecar guarded on device/inode/size/mtime_ns/ctime_ns; package decks keep the content
walk. Measured on the 6,771,226,182-byte Full deck in an isolated cache: cold 3.97205s, warm median
0.1197ms, identical SHA-256 all four calls — so ~3.97s saved per avoided hash, not the old
speculative 30–60s whole-cycle claim. Combined R0.1–R0.3 gate: 1,248 passed / 20 skipped.

**R0.4 `r-misc-cleanups`** (DONE 2026-09-09, merged `b981eb0`) — Checkpoint 0 measured both JXA
export forms throwing `Can't convert types.` in ~20ms with 0 PNGs, so deleting them was a
correctness fix, not a speed win. Shipped: canonical `export_applescript` bind, checker export
folded into the bulk session behind `keep_open`, the exact-count export-only cache hit ported to
legacy, and a module `_KEYNOTE_LOCK`. Live gate (9-slide Sermon_GW clone): payload identical, 0
differing pixels 9/9, one Keynote open not two, export 6.56→4.38s. `output/bank/2026-09-09/cp0/`.

### W1 fresh full-deck gate — RED 2026-09-07, fully diagnosed

**Outcome:** the whole-deck `offline_write_ab.py` gate on the restored Full wall went RED — the
writer itself was strong (147 slides patched, consistency PASS, live verify 0.00px) but 689 of 3,200
specs fell back to AppleScript, pass 2 diverged A→B, and identity geometry failed on 12 slides
(max 6.12px). D1–D6 found **three unrelated causes**, all since fixed and merged: `f76e8d3` (paste
no-op), `e987a46` (coincident-twin hide), `31625d1` + `917b00f`/`eab0cec` (gate integrity and the
mis-attributed damage check; D1's "stolen GUI interaction" verdict is DISPROVEN). Artefacts:
`output/bank/2026-09-07/w1-diagnosis/` and `write-gate-full{,-r2}/` (run records + `gate.log`
only; both 5+ GB decks deleted). W1 stays default OFF, W2 stays gated.

## Historical state log

Durable, not narrative:

- **Pipeline:** two-tier offline source read (`OBED_OFFLINE_READ` default ON: IWA for everything +
  one bulk Keynote read of group/image/text frames) → pass 1 in Keynote (canvas set, layout
  import/apply, JXA attrs pass, AS geometry with `set properties`, reuse duplication, deleteHides,
  save) → optional offline IWA geometry patch (`OBED_OFFLINE_WRITE`, default OFF) → pass 2
  stat-finalize (dedup, index-guarded font pass, recorded raises, badge raise, export).
- **Owner's contract (2026-09-03):** the template `Base_CG_Assets.key` dictates SIZE (and position
  where appropriate) for matched objects, **including text point sizes**; colour, font
  family/style, run formatting and each slide's builds/animations always come from the SOURCE
  (memory `template-size-source-style`, SKILL "Text styling").

One line per round (full detail lives in the completed todos and in git history):

- **2026-09-02/03 — W0 probes + output bugs.** W0 DONE (`2ac04db` tmp-path, `695199d` skipped-slide
  bulk skip, `99771bf` z-order, `c4dc5e5` stroke); batch 1 (`171fc65`…`8e5d3b2`) and batch 2
  (`0ad68b0`/`0cdcd2b`/`753acef`) shipped and live-verified on the Map deck. Verify decks deleted.
- **2026-09-04 — gold-baseline A/B kit.** Production default path clean (0.00px on 19 Gold slides;
  the only run-to-run difference was Keynote's own z-order scrambling). W1 opt-in root-caused to
  stale render-derived fields; whole-deck gate hardened; `cbde0a7` map-label classification and
  `94d2969` card-border floor fixed off main. All `output/offline-write-ab*` banks since deleted.
- **2026-09-05/06 — `fix/reuse-builds-side-panels`.** Rounds 1–2 (`3296ef3`, `80cb442`) Gold-verified
  at `output/bank/gold-baseline/reuse-builds2/`; alignment-aware `_autosize_rect`; reuse pre-add duplicate
  `08a5130` with the timed cold Gold build `output/bank/gold-baseline/preadd/` (910s, all 11 acceptance
  items). Round docs `output/bank/2026-09-06/` (the 09-05 plan dir is deleted).
- **2026-09-07 — `fix/resizer-backlog-r2`.** `dcae6a7`+`b6039ef` pack-lists gate, `e74e5fa` label
  sizing, `b50d22b`+`7bb0f52` R2 two-tier readback; Gold build `output/bank/gold-baseline/r2-round/`;
  ranged + four whole-deck R2 A/Bs passed. The fresh whole-deck W1 gate on the restored Full wall
  completed RED. Docs `output/bank/2026-09-07/`.
- **2026-09-08 — PR #57 (`cd67e2e`).** `31625d1` gate integrity, `f76e8d3` reuse-paste card loss,
  `e987a46` sparkle-twin hide, live-verified on a production remap (that directory is deleted;
  censuses survive at `output/bank/2026-09-08/{build-order,twin-zorder}/`). D7→D8 settled
  `buildChunks` as the render timeline; D9 found the descending-raise exact reversal.
- **2026-09-09 — PR #59 (`2d6ae55`) + parity round + PRs #60-65.** PR #59 landed the damage-check
  re-attribution (`917b00f`, `eab0cec`), the build-order fix (`c1d916a` probe + `59111fc`) and the
  raise-order fix (`8a7b4bb`). The round branch ran the parity remap
  (`output/bank/2026-09-09/parity-run/`) and merged as PR #60 with R0.4. Same day: PR #61
  `surface-raise-tokens`, PR #62 dead-code removal, PR #64 the golden plan gate, PR #65 R2b
  two-tier propose (live-verified in `output/bank/2026-09-09/nap-run/r2b/`), the
  refactor assessment (six surveys, no rewrite), and `chore/golden-gate-hard-parity` (`20feac0`).
  See "Current state".

## Order of work

**Done** (see the completed todos): W0 probes; output-bugs batches 1–2; the reuse/builds/side-panel
rounds and the pre-add duplicate; R0.1–R0.4; R1 (probe answer NO); R2 readback; R2b two-tier
propose; PR #57 and PR #59 fixes; the 2026-09-09 parity remap; `surface-raise-tokens`; the dead-code
cleanup and golden-plan gate; the refactor assessment.

**Open sequence** (reordered 2026-09-09 evening per the refactor assessment):

1. **W1 whole-deck gate on the Full wall**, nap window 2026-09-09
   (`output/bank/2026-09-09/nap-run/`) — run from an unlocked working copy (deck facts above).
2. **`stat-raise-dead-4`** from that gate's `raiseDead(s=,idx=)` log lines — localise all 4 by log
   alone, now that `surface-raise-tokens` is merged.
3. **Shared osascript runner** (timeout/lock/name-verified bind) — before the W1 flip.
4. **IWA natural-size/sentinel unification** + one decode→re-encode→diff — before W2.
5. **W1 default flip** (`w-offline-write-stabilise`) — bar is the universal naturalSize writer plus
   a healthy whole-deck gate (green on both gold decks, with the consistency audit).
6. **W2 `w-zorder-patch`** — gated on W1 stable; purely speed + Accessibility removal now.
   `restore_source_builds` must still run LAST, after any future z-order write.
7. **Bug backlog:** `map-label-offslide-parked-delete`, `card-border-source-ref-floor-fix`
   (residual: output card refs 10-31 still refuse on the Full wall), `r-reuse-photo-placement`
   part B including the constellation z-order residual, `stat-group-template-sample`,
   `constellation-cluster-affine`, `reuse-chain-parked-snapshot`.
8. **Features:** `propose-pins-flag`, `recipe-library`, `stat-drift`, `outline-editor`,
   `image-cues`, `iwa-surgical-write-generator`.

Standing: re-run `scripts/e2e_run_parity.py` after R0.4 (needs an owner-acked Keynote window).

### Tranche map

| Tranche | Item | Keynote | Status |
|---|---|---|---|
| W0 | tmp-path, skipped-slide bulk skip, z-order + stroke probes | probes only | DONE (`2ac04db`, `695199d`, `99771bf`, `c4dc5e5`) |
| Fixes | output-bugs batches 1–2, `map-label-classification-fix`, `map-label-text-sizing`, `card-border-source-ref-floor-fix` | one live remap each | DONE + live-verified, except the card-border residual (refs 10-31) still open |
| **W1** | `w-offline-write-stabilise` | gate on both gold decks | OPEN — Map GREEN, Full gate RED 2026-09-07 and diagnosed; its three production defects merged in PR #57/#59; default flip ON HOLD |
| **W2** | `w-zorder-patch` | yes | OPEN — gated on W1; purely speed/Accessibility removal since `8a7b4bb` |
| **R0** | `r-cache-quick-wins` (R0.1–R0.4) | no | DONE — parts (1)-(3) 2026-09-07, R0.4 merged `b981eb0` 2026-09-09 |
| **R1** | `r-nested-bulk-probe` | yes | DONE — correct+safe but NOT faster (object-bound); closed with `r-bulk-counts-plan` |
| **R2** | `r-readback-two-tier` → `r-propose-two-tier` | output-deck A/B | both DONE — readback 2.4–2.6x; R2b PR #65 (`4627497`), cold propose 96s vs 269s legacy |
| B (merged) | `w1-build-order-nondeterminism`, z-order raise-order fix | owner playback + parity remap | both DONE and CLOSED — `59111fc` and `8a7b4bb`, PR #59 |
| B (merged) | `surface-raise-tokens` | none (log surfacing) | DONE — PR #61 (`c5e9c34`); precondition for `stat-raise-dead-4` |
| B (new) | `stat-raise-dead-4` | a second production run | OPEN, NEXT — `raiseDead=4/381`; 2 of 4 located offline on non-reuse slides 106/110; localise all 4 by log now |
| B (branch) | `builds-follow-source`, `side-panels-positional`, `autosize-rect-alignment-fix`, `pack-lists-gate-widen`, `reuse-chain-preadd-duplicate` | Gold builds | all DONE + Gold-verified; backlog spin-off `reuse-chain-parked-snapshot` open |
| B / features | reuse framing fallback, cluster affine, stat/photo/label residuals | mixed | open, independent — see "Order of work" 6–7 |
| drop | `w-hides-offline`, skipped-slide option (2), Stage B / batch z-order / batch delete | | closed with reasons (see Insights) |

R1/R2 touch `inspect.py` / `bulk_geometry.js` / `remap_and_inspect`; W1 edits `remap_keynote.py` —
sequence, don't interleave. The checker's edit-loop cache wraps `bulk_geometry_fn` at the inspect.py
call site and depends on the `plan.slides` subset path: any nested-bulk rewrite must preserve it.

## Write track — what still stands

- Dominant cost is the AS geometry phase (~70% of a heavy-slide run, ~100ms/command redraw even
  off-screen, no cross-object bulk write); surgical IWA float patches are the missing bulk write.
  Byte-risk ladder: float patches < list reorder < object removal.
- Proven mechanics: object-level patching of ONE stored member; locality (every slide's drawables
  in exactly one member, derived from `id_to_file`, never from the slide id); Keynote opens patched
  decks clean and re-saves them first-class; size lives in `bezierPathSource.naturalSize` (patch
  size AND naturalSize; a line's length is `naturalSize.width`); write patched bytes IN PLACE
  (`com.apple.macl`); group-child scaling (`s = spec / REPORTED union`, origin = spec +
  (stored − reported)·s, descendants ×s, masks too); NBSP zip member names preserved raw.
- Group move = DELTA on the stored origin (stored ≠ reported on stale-frame groups); soft classes
  (group/text/masked image) seed from a bulk read of the SAVED deck, never from the offline
  composition alone; refuse a slide whose reconcile counts disagree. Reuse slides stay fully in Keynote.
- Known cosmetic: AS geometry `set properties {width,height}` renders as two origin snaps; gone on
  offline slides.
- **Gold-baseline A/B kit:** one `remap` per branch, then offline IWA reads (~1–3s per 2.5GB deck)
  plus preview PNG diffs — Keynote is only needed for the two remaps and one preview export. It is
  what caught the z-order nondeterminism. A run that lost a paste reads `Card-border stroke: …
  (12 refs)` instead of 269 — root-caused 2026-09-08 as the `applyReuse` paste no-op and fixed in
  `f76e8d3`, so that signature is now a regression alarm, not an operator-error tell.

## Read track — what still stands

- Bulk-read inspect (227s → 57s, byte-identical) and the two-tier read (Map 51.8s / Full 283.7s vs
  ~12.6 min JXA) are shipped and gate GREEN on both decks; the bulk tier is Apple-Event-overhead
  dominated, which R1 measured and closed.
- Correctness guards that exist: `reconcile_counts` wired into the splice (text slack [0,2]
  trailing-only, placeholder tail check); array-length guards per bulk array; granular
  per-slide/per-class legacy fallback. Only `role="hide"` geometry is write-dead — lines and group
  w/h ARE written; verify "is this field written?" against `remap_keynote.js`.
- Compare output groups as a SET, never by index; the canvas shrink jitters the map ~8px/run — read
  pixel diffs against that floor.
- Cache facts: `deck_slide_digests` hashes no geometry; ranged reads never cache; cross-serve
  (checker-written payloads served to propose) is consumer-compatible but carries a `reader`
  provenance guard — keep it. Since R0.4, a partial preview set is a miss, not a warm hit.

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
under `output/.outline-backups/{stem}/` (deleted), **surgical edits only** (operation list against
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
- UNCONFIRMED production reports from the 2026-09-01 full Map run (bank `output/write-gate/A_png` (deleted)), never localised: (b) the yellow "269 churches" text deleted on several slides yet
  present + mis-positioned in the slide-7 PNG; (d) right-side photo z-order wrong on slides 4 & 5
  (may be subsumed by the badge/z-order work — re-check on the next live run before opening an item).
- Never dedupe images (stacked map layers are coincident on purpose). The first ranged propose
  on a never-read deck cannot translate the range into Keynote's numbering and says so.
  Composite preview text is scaled wall pixels (close, not right). The JXA export never worked and
  was DELETED in R0.4 after Checkpoint 0 measured both forms throwing `Can't convert types.` in
  ~20ms with 0 PNGs; `exported`/`exportError` survive as hardcoded false/"" for payload shape.
  PNG export fidelity differs 117px @ ≤2/255 between Keynote versions — keep watching.

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
| `autosize-rect-alignment-fix` | d31fedc | `_autosize_rect` resolves `verticalAlignment` up the style parent chain; composed autosize tops are visual truth for every anchor |
| reuse pre-add duplicate | 08a5130 | reuse deletes 91→6; timed cold Gold build 910s, 0.00px vs reuse-builds2 |
| pack-lists gate widen, map-label text sizing, R2 two-tier readback | dcae6a7+b6039ef, e74e5fa, b50d22b+7bb0f52 | 2026-09-07 round; R2 readback 2.4–2.6× |
| PR #57: gate integrity, reuse-paste card loss, sparkle-twin hide | cd67e2e (31625d1, f76e8d3, e987a46, b50f75b) | three unrelated W1-RED causes fixed, live-verified, owner confirmed the sparkle |
| card-border damage-check re-attribution | 917b00f, eab0cec | detection + exit-6 abort kept; cause/remedy rewritten diagnose-first |
| build-order probe + fix | c1d916a, 59111fc | `buildChunks`, not `builds`, is the render timeline; survivors ordered by source chunk position; confirmed on screen |
| z-order raise-order fix | 8a7b4bb | ascending raise gated on a verified landing; fixes the descending Bring-to-Front exact reversal |
| PR #59 merge | 2d6ae55 | `917b00f`/`eab0cec`/`c1d916a`/`59111fc`/`8a7b4bb`/`7c200a4` on main, 2026-09-09 |
| R0.4 misc cleanups + three Codex fix rounds + merge | a89b9b3, 006f68b, db3109d, bdc3ee4, bb04d91, b981eb0 | closes all four R0 leftovers; suite 1535/20; live gate PASS |
| PR #60: parity round + R0.4 merge | (see above) | round branch folded into main |
| PR #61: surface-raise-tokens | c5e9c34 | `tokens`/`frontErr` result keys; `raiseDead`/`raiseUnknown` always emitted; new say() detail lines |
| PR #62: resizer dead-code removal | 7e0d517 | deleted unused functions, dead left-pack path, `subset_keynote.py`/`.js`; no behaviour change |
| PR #64: golden plan gate | 4651b7b | Keynote-free apply-plan SHA-256 gate through the real planner; run after any planner/driver change |
| PR #65: R2b propose two-tier | 4627497 | propose reads through `acquire_wall_payload`; cold propose 96s vs 269s legacy; hard parity 0/155 |
| golden-gate-hard-parity | 20feac0 | propose/apply parity promoted to a hard gate now that R2b is merged |

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
- Nested `<prop> of every <kind> of every slide` is correct and safe but NOT faster (GW 1.37×,
  Map 0.73×): the cost is per object-property inside Keynote (~70/33/9 ms), not per Apple Event.
  Failure semantics are worth remembering — a per-element failure SUBSTITUTES `missing value` in
  position, an invalid property raises for the whole event, and `count of characters …` collapses
  to one integer.
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
- An autosize text box's stored y is the visual TOP for `kFrameAlignTop` and the visual CENTRE
  only for `kFrameAlignMiddle`; Keynote's AppleScript/JXA `position` (read and write) is always
  the visual top-left. Never re-add write-side `±h/2` compensation for a read-side anchor bug.
- KeynoteKit (Swift, same 14.4 schemas) is a reference only — it does not unblock W2 (evaluated
  2026-09-09).

**The operator loop**
- Confirmation only bites where the template has a framing worth picking; pages with no
  candidate are the prompt to add template slides. Fit-to-frame still overrules overrides on
  pages the template does not describe — tell the operator per page, never in a footnote.
- **The metric-that-misleads pattern:** framing selection went through five rewrites in one
  session, each fixing a real case and creating the next — a metric asked to infer something
  the data does not contain. When selection needs a sixth exception, *ask* (the Sermon
  Checker's propose/correct/remember-by-digest pattern is the template).

**What the 2026-09-07…09 rounds settled** (appended 2026-09-09)
- **`buildChunks`, not `builds`, is Keynote's render timeline.** `builds` is an unordered owning
  set Keynote re-serialises freely on save, so a `builds`-array diff is not a render diff. Chain
  coherence (a `referent` chunk heads a chain) is 45/45 under `buildChunks` and 13/45 under
  `builds`. D7's "34 reordered slides" collapsed to 3 on the render metric.
- **A positive control that shares its model with the fix proves nothing.** D7's "19/19
  order-exact" compared the output's `builds` against the source's `builds` — the array the patch
  had just copied. At least one check must reach ground truth by a path your model never touches;
  here the owner played the slide and settled it in two minutes.
- **Bring to Front APPENDS**, so draining raise targets highest-index-first reverses every
  ≥2-member set exactly — 16 slides deck-wide, byte-deterministic across runs days apart. Raise
  ascending and gate each target on a verified landing.
- **The exporter cannot capture build stages** (Keynote's export `Kxpa` is a print key), so preview
  A/B is structurally blind to build defects — a build-order or animation bug needs owner playback.
- **Reuse slides mint fresh drawable ids**, so never pair objects by id inside the reuse band
  (123–128 on the Full deck); identity matching only holds on non-reuse slides.
- **Bank censuses, not decks.** Every output `.key` this project has produced has since been
  deleted, including the 5.4 GB parity deck the owner removed on 2026-09-09. JSON censuses, run
  records and logs are what survive a round — write them before you need them.
- **A second model family in review found lifetime bugs a same-family review missed.** Codex on
  R0.4 caught `document 1` binding whatever deck was frontmost, kept-open leaks across exception
  and early-return paths, a stale PNG that turned a failed export into `exported: true`, and an
  ownership reset that ran before the lock was acquired.
- **Keynote-free tests must stub the exporter**, or they launch Keynote for real — an implementer
  did exactly that on 2026-09-09 by leaving the export path live in a "Keynote-free" test.
- **A counter you will need to diagnose must reach the log.** The AppleScript
  `raiseDead(s=,idx=)`/`raiseUnknown(s=,idx=)` tokens exist but are dropped, and `frontErr` only
  reaches `result["raw"]`, so the 2026-09-09 `raiseDead=4` localisation needed an offline z-order
  probe instead of the log — that is what `surface-raise-tokens` fixes.
