---
name: Pass 1 profile — pull only the levers the profile names
overview: >-
  2026-09-23. `obed-edom remap` on Full_Report_Card_Wall.key was profiled stage by stage
  (`.agents/reviews/pass1-profile-2026-09-23/README.md`): pass 1 is 36% of the run, not the assumed
  55%. The levers it named are pulled or measured dead; the bulk seed read is the one still open.
  Whole run 785 s → 584 s (z-order patch) and a further −63/−88 s (hides offline).
todos:
  - id: h-bulk-seed-read
    content: >-
      NEW from the profile (2026-09-23): the bulk live seed read (`inspect.bulk_geometry`,
      `bulk_geometry.js`) takes 150 s (19%) for 104 slides ≈ 1.4 s/slide. Establish what it reads
      per slide versus what the writer consumes (`_OFFLINE_SOFT_SEED_KINDS` = text only; group rows
      unused since the groups branch stopped) and whether the read can be narrowed to the kinds and
      slides that need a seed. Gate: projected saving ≥ 60 s; needs one owner-gated live run.
    status: pending
  - id: followup-single-rewrite
    content: >-
      GATED (moved from the hides-offline plan). Fold the hide delete into `patch_deck_geometry`'s rewrite
      (one decode and one rewrite instead of two). Precondition: the bulk seed read must run on the
      undeleted deck, with rows re-keyed through `bridge_kind_index`, which changes a live-validated
      path (offline_write.py:122-133). Pursue only if the measured hide stage is ≥ 10 s AND
      `h-bulk-seed-read` has settled what the seed read looks like.
    status: pending
---

# Pass 1 profile

## Done (detail in git history, `git show 0f0a70aa:.agents/plans/pass1_profile.plan.md`)

| todo | outcome |
|---|---|
| `m1-stage-timer` | always-on pass-1 stage map (`STAGES`/`_stage`, `_say_pass1_stages`), 2026-09-23 |
| `m1-run` | three runs, record in the review README; pass 1 = 267–280 s of a 769–785 s run |
| `h-attrs-roundtrips` | (i)+(ii) per-slide cached lookup + skip applyGeom: attrs ≈ 97–107 s → ≈ 19 s; one `doc.slides()` per slide deferred (≈ 2–5 s, below gate) |
| `h-copy-clone` | dead: copy 5 s |
| `h-save` | dead: save 0.9 s, never retried |
| `h-layouts` | below gate: 39 s total |
| `h-open-size` | recorded: open 3.6 s, slideSize 6.0 s |
| `h-zorder-patch` | read-back loads the deck once (`d9cf7f2b`): z-order block 183 → 20 s |
| `h-hides-offline` | `git show 1379b2df:.agents/plans/pass1_hides_offline.plan.md`, `OBED_OFFLINE_HIDES` default on |
| `deferred-build-hides` | not planned: hides carrying a build (slide 122, ≈ 0.7 s) stay on the Keynote delete; offline would need `buildEventCount`/`hasBuilds`, formula unknown — revisit only if a deck puts material time there |
| `design-offline-attrs` | not triggered: its gate was attrs ≥ 60 s after `h-attrs-roundtrips`; attrs is ≈ 19 s |

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

With `OBED_OFFLINE_HIDES` on (default) eligible slides skip `deleteHides`; the IWA writer deletes their
hides after the pass-1 save (`git show 1379b2df:.agents/plans/pass1_hides_offline.plan.md`). Line numbers above are from 2026-09-23.

## Levers

Pursue a lever only if its stage is ≥ 60 s (~8% of 720 s) and the projected saving is ≥ 30 s; take
them in profile order, not prior belief. Each lever run repeats m1-run's pass criteria (residuals
R1 ≤ 2 s and R2 ≤ 15 s; "Applied N, missed M" and the fallback line unchanged — the null control)
plus its own oracle.

## Must not change

`_require_pass1_saved_closed` (py:1108-1117, :1678) and the saved/closed contract; applied/missed
semantics incl. attrs specs counting as applied (js:460) and the 0-applied abort (js:771-786,
py:1496-1507); hides deleted after attrs, per slide, highest index first (js:2, :482-498); byte rules
for untouched ZIP members; never quit Keynote, bundle-id addressing (js:22, py:694), KEYNOTE_LOCK;
always work on a copy; `_run_jxa(plan)` / `copy_keynote(source, dest)` signatures; `OBED_WRITE_TIMING`.
