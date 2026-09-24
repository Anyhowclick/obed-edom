---
name: Pass 1 profile — attribute the ~12 min, then pull only the levers the profile names
overview: >-
  2026-09-23. Pass 1 of `obed-edom remap` (deck copy → template copy → JXA write → save/close) is
  ~12 of ~22 min on Full_Report_Card_Wall.key (`.agents/reviews/offline-fallback-2026-09-23/README.md`
  §1) and has never been timed stage by stage. Two Opus planner passes (extra-high draft, high
  critique). One always-on stage map in remap_keynote.js plus four Python timers, printed as `say`
  lines with closure residuals; one owner-gated run; then levers gated on the measured stage.
  MEASURE BEFORE BUILDING: only the first two todos are ungated.
  PROFILED 2026-09-23 (see `.agents/reviews/pass1-profile-2026-09-23/README.md`): pass 1 is 36%, not the assumed 55%; the z-order patch (23%,
  Python) and the bulk seed read (19%) are the other two levers; copy/save/layouts are dead or below gate.
todos:
  - id: m1-stage-timer
    content: >-
      Always-on stage timing. JS (`remap_keynote.js`): a `STAGES` object + `_stage(name, t0)` that
      adds elapsed ms; separate from `TIMING`/`_trec` (which stay unchanged, incl. their opt-in).
      Wrap in `run` (js ~717-831): open (:725), slideSize (:734, plus `sizeProp` — which property
      won), templateOpen (:746), layoutImport (:747), layoutApply (:748), trailingDelete (:749 +
      layoutNames), templateClose (:756), attrs (Σ applyTransforms inside applyNonReuseSlide, all
      paths), hides (Σ deleteHides), finish (readMapGeom + skipOutsideRange), save (:793-801, plus
      `saveRetried` = first save threw, and its error text), close (:806), total. Return `stages`
      on BOTH return objects (abort :776-786, normal :812-831). Python (`remap_keynote.py`):
      `time.monotonic()` around prep (from "Copying…" say to the `_run_jxa` call, minus the two
      copies), `copy_keynote(source, dest)` (:1415, + source bytes), `copy_keynote(template)`
      (:1420, + bytes), `_run_jxa(plan)` (:1487). `_say_pass1_stages(py_stages, jxa, say)` prints
      one line per stage (seconds, 1 dp), sizeProp, saveRetried, and residuals R1 = jxa total −
      Σ jxa stages, R2 = `_run_jxa` wall − jxa total (osascript start, plan JSON write, `open -b`
      + 0.4 s settle, osascript_runner.py:30/:81-83/:168-178). Tolerant of a jxa dict without
      `stages` (tests monkeypatch `_run_jxa` with bare dicts: tests/test_offline_write.py:2099-2103,
      :2164; tests/test_zorder_wiring.py:371-373). Keep the `_run_jxa(plan)` and
      `copy_keynote(source, dest)` signatures. Plus a Keynote-free census line from
      `transform_dicts` before :1487: slides by path (attrs / as / jxa — a slide that fails
      `_slide_geometry_addressable` py:653-662 or has an empty geometry script py:687-689 is in
      NEITHER set and takes the full "jxa" path, js:698-704; the "0 slide(s)" log line cannot rule
      that out), non-hide specs, hides, specs carrying no font/fontSize/color/opacity, locked
      specs, group specs with `children` (attrs mode still resolves every child via getItem and
      writes nothing, js:218-219/170-174).
      DONE 2026-09-23 (f3f7d0d2 + 65e7342e elapsed-seconds log prefix + bb5d8180 progress lines); Opus +
      Codex reviewed, fix-then-ship findings applied; full suite green.
    status: completed
  - id: m1-run
    content: >-
      ONE owner-gated run: same command/env as the m1 regrow run (defaults, `--slides
      1-129,135-143,145-155`), OBED_WRITE_TIMING unset. Record before it: source + template byte
      sizes, whether `output/` shares the source's APFS volume (`df`), Keynote cold or warm.
      PASS: R1 ≤ 2 s, R2 ≤ 15 s, "Applied N, missed M" and the fallback line equal the m1 run's
      (null control: the instrument changed no behaviour). Archive log + facts in
      `.agents/reviews/pass1-profile-<date>/README.md` and rank the stages. No lever below may
      start before this record exists. (Note: ditto preserves the source mtime on the copy, so the
      earlier "12 min from mtimes" cannot be decomposed and is context only.)
      DONE 2026-09-23, three runs, record `.agents/reviews/pass1-profile-2026-09-23/README.md`. Pass 1 = 267–280 s (36%) of a 769–785 s run — NOT 12 min
      (the mtime estimate was never decomposable). R1 0.1 s, R2 0.9 s, null control identical. Inside pass 1:
      attrs ~97 s + hides ~114 s = 79%. Outside: offline z-order patch 183 s (23%, pure Python), bulk live seed
      read 150 s (19%), fallback 81 s, stat-finalize 44 s.
    status: completed
  - id: h-attrs-roundtrips
    content: >-
      GATE: attrs + hides ≥ 60 s and projected saving ≥ 30 s. Measured cost model per non-hide
      spec in attrs mode: getItem = 1 AppleEvent (whole kind collection fetched, js:67-70/87-92,
      +1 via iWorkItems if the typed lookup misses :94-97), locked read = 1 (:204-206), +2 if
      locked (unlock :207-211, relock :254-258 — relock also when spec.locked), +1 each for
      opacity/font/size/color when present (+1 color fallback), +1 per child for group specs
      with children; per hide 2 (3 with the obj.delete fallback :267-280); per slide `doc.slides()`
      fetched twice (:683, :704). Levers, cheapest first: skip applyGroupChildren in attrs mode;
      skip the locked read/write when the spec has no attr to write; fetch each kind collection
      once per slide (the attrs pass performs no deletes; deleteHides keeps refetching).
      Applied/missed must stay identical (attrs specs count as applied js:460; 0-applied drives
      the abort js:771-786 and py:1496-1507). Oracle: same Applied/missed, same fallback line,
      pass-1 deck slide members byte-equal before/after (unzip -l + CRC diff).
      GATE MET (2026-09-23): attrs + hides ≈ 212 s. Census: 2443 no-attr specs, 947 hides at 122 ms, 1 slide on
      the full jxa path (identify it first). Next lever to build, after the two NEW todos are profiled offline.
      SIZED 2026-09-23 (owner asked): (i) skip getItem + locked read for the 2443 no-attr specs in attrs
      mode (still count applied) — most of the ~97 s attrs stage; (ii) skip applyGroupChildren's child
      resolution in attrs mode (56 groups); (iii) hides 947 × 122 ms = ~114 s: either batch the per-slide
      deletes into one AppleScript body (cuts JXA overhead, still one event per object) or delete offline in
      the IWA writer (remove from drawablesZOrder/ownedDrawables + the object; a NEW surgical write with its
      own live gate because `expected_base_counts` = source − hides addresses later stages). Ceiling ≈ 200 s
      of 780. Order: (i)+(ii) first (behaviour-preserving, node-stub testable), then decide (iii).
      DONE (i)+(ii) 2026-09-23 as "per-slide cached lookup + skip applyGeom" — NOT "skip getItem": the lookup is
      the only attrs-mode miss source, so skipping it would turn misses into applied. Live A/B (runs 5–8,
      review README): attrs ≈ 97–107 s → ≈ 19 s, null control identical, pass-1 slides equal modulo IDs.
      Deferred: one doc.slides() per slide (≈ 2–5 s, below gate). (iii) hides (≈ 100 s) stays a separate decision.
    status: completed
  - id: h-copy-clone
    content: >-
      GATE: deck copy ≥ 60 s AND same APFS volume. Lever: `cp -c` (clonefile) inside
      `copy_keynote` (py:699-707) with the ditto fallback across volumes; signature unchanged.
      Oracle: source byte-unchanged after the whole run (sha), Keynote opens and saves the clone,
      m1-run pass criteria repeat. "Save as" from the source is REJECTED (opens the owner's source,
      still writes 6.7 GB); the offline writer cannot replace the copy (pass 1 still needs Keynote
      for canvas + layouts). The template copy is small — measure before touching.
      DEAD 2026-09-23: copy 5 s.
    status: closed-not-pursued
  - id: h-save
    content: >-
      GATE: save + close ≥ 60 s. If `saveRetried`: the first `Keynote.save` (js:794) threw —
      JXA has no `with timeout`, so a save slower than the ~120 s AppleEvent reply timeout throws
      -1712 while Keynote keeps saving, and the `save in` retry (:797) queues a SECOND full save.
      Lever: drop the retry when the first save is still in flight (check dirty before close).
      Never drop save/close (`_require_pass1_saved_closed` py:1108-1117). If not retried: record
      that the save is the 6.7 GB package rewrite, no cheap lever.
      DEAD 2026-09-23: save 0.9 s, never retried.
    status: closed-not-pursued
  - id: h-layouts
    content: >-
      GATE: layoutImport + layoutApply + trailingDelete ≥ 60 s. Cost: findLayout (js:532-543) =
      1 fetch + up to L name() calls; applyCgLayouts (:617-634) per wanted slide does
      baseLayout().name() + findLayout + set + read-back ≈ 148 × (L+5) AEs; importCgLayouts
      (:576-615) scans per template layout and findSlideWithLayout (:566-573) scans template
      slides; deleteTrailingSlides (:636-654) fetches dest.slides() twice per deleted slide.
      Lever: build a name→layout map once per doc and skip the read-back. If the time is in the
      baseLayout SET itself, record, no lever.
      BELOW GATE 2026-09-23: 39 s total (layoutApply 30 s).
    status: closed-below-gate
  - id: h-open-size
    content: >-
      RECORD ONLY: Keynote.open (js:725; a -1712 here is uncaught and would fail the run, so it
      did not time out) and setSlideSize (:734; e1 swallowed, retried via slideWidth :350-362 —
      `sizeProp` now logged). No cheap lever; reordering vs layouts is a correctness change
      needing its own plan.
      RECORDED 2026-09-23: open 3.6 s, slideSize 6.0 s, sizeProp width.
    status: completed
  - id: h-zorder-patch
    content: >-
      NEW from the profile (2026-09-23): `run_offline_zorder` takes 183 s (23% of the run) for 83
      slides — pure Python, no Keynote. MEASURE FIRST, offline: cProfile the call on the run-3 output
      deck (or a copy of the pass-1 snapshot + the same zorder targets from the run record) and name
      the hot path (per-slide full-deck decode? re-encode per member? verify decode?). Gate: a
      projected saving ≥ 60 s. Owner-gated live run only for the null control after a change.
      DONE 2026-09-23 (d9cf7f2b, Codex reviewed): read-back loaded the deck once per slide; now once.
      Offline 170.3 → 14.5 s; live null-control run 4: z-order block 183 → 20 s, whole run 785 → 584 s,
      Applied/fallback/zorder-detail lines identical.
    status: completed
  - id: h-bulk-seed-read
    content: >-
      NEW from the profile (2026-09-23): the bulk live seed read (`inspect.bulk_geometry`,
      `bulk_geometry.js`) takes 150 s (19%) for 104 slides ≈ 1.4 s/slide. Establish what it reads
      per slide versus what the writer consumes (`_OFFLINE_SOFT_SEED_KINDS` = text only; group rows
      unused since the groups branch stopped) and whether the read can be narrowed to the kinds and
      slides that need a seed. Gate: projected saving ≥ 60 s; needs one owner-gated live run.
    status: pending
  - id: h-hides-offline
    content: >-
      DONE 2026-09-24 (branch `claude/pass1-hides-offline`, plan `pass1_hides_offline.plan.md`, gate record
      `.agents/reviews/pass1-hides-offline-2026-09-24/README.md`). Hides are deleted offline in the IWA writer after
      the pass-1 save, with identity proven by stable source archive id. Live gate: whole run −63 s / −88 s, runJxa
      −84 s / −103 s, 0 refused, 0 differing slides vs the Keynote delete. `OBED_OFFLINE_HIDES` defaults to on.
    status: completed
  - id: design-offline-attrs
    content: >-
      Only if attrs still ≥ 60 s after h-attrs-roundtrips: move font/size/color/opacity for
      offline slides into the IWA writer (offline_write handles none of them today); pass 1 shrinks
      to open/size/layouts/hides/save. Separate plan with its own live gates.
    status: pending
---

# Pass 1 profile

## What pass 1 does today (OBED_OFFLINE_WRITE on)

py: ditto deck (:1415, `copy_keynote` :699-707) → ditto template (:1420) → build plan (as_dict on
3822 transforms, `_build_as_geometry` twice — once inside `_offline_write_slides`, once at :1459)
→ `_run_jxa` (:1487; `open -b` + 0.4 s settle, plan JSON to a temp file osascript_runner.py:167-170,
wall limit `DEFAULT_TIMEOUT` 3900 s unless `OBED_OSASCRIPT_TIMEOUT`; `OsaResult.elapsed` :123 is
dropped by `parse_json_stdout` :184-193, so `_run_jxa` is timed from outside).
js `run`: open → setSlideSize → template open, importCgLayouts, applyCgLayouts, deleteTrailingSlides,
layoutNames, template close → per slide in `slidesInPlan(transforms)` (js:329-340, NOT the wanted
range): applyTransforms "attrs" for suppressed slides else "as"/"jxa" (:670-706), then deleteHides
→ readMapGeom, skipOutsideRange (writes `skipped` on every slide, ~155 AEs) → save, on throw
`save in` again → close saving yes (:793-811).

Attrs mode writes per spec (applyGeom :200-261): opacity, objectText font / size / color (color
fallback to attributeRuns[0]), unlock/relock around them if locked. No size, position or child write.

## The instrument (M1)

One `STAGES` map in the JS, always on, separate from the opt-in `TIMING`; four Python timers; one
`say` line per stage and two residual lines:

    Pass 1 stage copy-deck: 212.4 s (6.77 GB)
    ...
    Pass 1 stage save: 188.0 s (retried: no)
    Pass 1 unattributed: js 0.3 s, osascript/launch 1.1 s

Controls: R1 and R2 (closure) and the unchanged Applied/missed + fallback line (null). Making
`_trec`/`TIMING` always-on was rejected: `_say_write_timing` prints every bucket (~296 per-slide
rows with timing on) and every `if (TIMING)` would change; `OBED_WRITE_TIMING` output stays as is.

## Levers

Pursue a lever only if its stage is ≥ 60 s (~8% of 720 s) and the projected saving is ≥ 30 s; take
them in profile order, not prior belief. Each lever run repeats m1-run's pass criteria plus its own
oracle.

## Must not change

`_require_pass1_saved_closed` (py:1108-1117, :1678) and the saved/closed contract; applied/missed
semantics incl. attrs specs counting as applied (js:460) and the 0-applied abort (js:771-786,
py:1496-1507); hides deleted after attrs, per slide, highest index first (js:2, :482-498); byte rules
for untouched ZIP members; never quit Keynote, bundle-id addressing (js:22, py:694), KEYNOTE_LOCK;
always work on a copy; `_run_jxa(plan)` / `copy_keynote(source, dest)` signatures; `OBED_WRITE_TIMING`.

## Tests

JS (node, style of tests/apply_geom.test.js): export `_stage`/`STAGES`; accumulation and reset.
`run` is not unit-testable, so stage names are asserted on the Python side.
tests/test_remap_keynote.py: `_say_pass1_stages` ordering and residual arithmetic; tolerant of no
`stages`; census counts on a small transform list (attrs/as/jxa split, group-with-children, no-attr
specs, locked); the existing `_run_jxa` monkeypatch tests still pass.

## Streams

A: `src/obed_edom/remap_keynote.js` + JS test. B: `src/obed_edom/remap_keynote.py` + py test
(timers, census, printer). C: the review record after the run. `osascript_runner.py` untouched.
