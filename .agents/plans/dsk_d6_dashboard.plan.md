---
name: DSK d6 — ship the IMAGE/VIDEO path and wire it into the dashboard
overview: >-
  Owner decision 2026-09-15: "let's bench the verse / text resizing. video /
  image resizing works now, we ship that & wire it into the dashboard 1st."
  This plan adds a `--content-only` mode to the DSK assembler (keeps
  image/movie/content slides, SKIPS text-class slides and reports them), gives
  the d5 stage exporter the CLI wrapper it never got (d5b), replaces the
  `POST /api/dsk` 501 stub with a propose → review → apply flow plus an export
  flow, and turns `DskTab.tsx` into a segmented "DSK" tab with Generator and
  Exporter sub-tabs.
status: proposed
date: 2026-09-15
---

## §0 Summary

1. **Shipped mode** = a new `content_only` flag on `assemble_dsk_deck` / `--content-only`
   on `dsk-assemble`. It drops every slide whose `dsk_plan.SlideClass.is_text` is True
   (the classifier's own predicate, same object planning uses — no second source of truth),
   reports them on `AssembleResult.skipped` and in the job log, and keeps everything else
   the shipped path already does: image crop, clip insertion, anchors, stroke, z-order,
   build verification.
2. Content-only narrows the layout import to **`Blank Black` only** (measured: every
   content slide resolves to it; accept13 rows for GW 21/24/32/33/48 all say `Blank Black`),
   and forces `no_pills`/`no_style` on (both already self-skip with no verse/point layout).
   Split / `--text-fit shrink` / `--min-text-pt` become incoherent and are **refused**, not
   silently ignored.
3. **d5b** ships as `dsk-export-stages` — `dsk_stage_export.export_stage_pngs` is complete
   and tested; only a `cli.py` subcommand is missing.
4. **API**: `POST /api/dsk` (propose) → `POST /api/dsk/{id}/decisions` → `POST /api/dsk/{id}/apply`,
   mirroring `/api/resize`; plus `POST /api/dsk/export{,/{id}/decisions,/{id}/apply}` under
   feature tag `dsk-export`. Serialisation is already free: `JobRunner` has exactly one
   worker thread, and `LiveBatch.__enter__` refuses when Keynote is running.
5. **UI**: `DskTab.tsx` becomes a `.seg` shell over `tabs/dsk/DskGenerator.tsx` and
   `tabs/dsk/DskExporter.tsx`; labels change to "DSK" in `App.tsx:24` and `nav.ts:10/:20`;
   a new light per-slide review list (NOT `FramingReview.tsx`).
6. **The "editing phase"** (per-slide operator nudges to position/size/crop on top of the
   auto defaults) is **out of scope** — see §2.9.
7. Seven pieces, P1–P7, each sonnet-sized; P7 is the live acceptance run for the owner.

---

## §1 Current-state measurements

All line numbers are in worktree `.claude/worktrees/dsk-gen` at the time of writing.

### 1.1 The shipped path, end to end today

`python -m obed_edom dsk-assemble <FW.key> --out <DSK.key> --slides … [--include-side …]
[--anchor N=…] [--clip N=…] [--layout import|preserve] …` (`cli.py:114-214`, runner
`cli.py:329-520`) →

1. `cli._run_dsk_assemble` validates the source is exactly **7680×1080**
   (`cli.py:364`), range-checks `--slides`/`--include-side`, parses `--anchor` / `--clip`
   (`.mov`, must exist) / `--split`, and builds
   `{n: SlideDecision(n, "both" if n in clips else "in_deck", anchor=…, keep_side=…)}`
   (`cli.py:458-462`).
2. `assemble_dsk_deck` (`dsk_assemble.py:5058`): `guard_out_dir` → (if `layout_policy ==
   "import"`) `check_layout_import_preconditions` offline → resolve band (`--reference-deck`
   / `band` / `DEFAULT_BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)`, `:112`) →
   `load_assembly_inputs` (payload + `classify_deck` + runs) → `plan_assembly` →
   `resolve_slide_layouts` → `LiveBatch` (refuse-if-Keynote-running, process lock, display
   poke, RSS watchdog, scratch copy) runs one AppleScript batch that saves to a **staging**
   path → offline post-passes: refit, `verify_staged_layouts_alpha_safe`, `_restore_stroke`,
   `_restore_crop_zorder`, `_verify_builds`, `_write_style_pass`, `_write_pill_pass` →
   `copy_keynote(staging, out_path)`.
3. Returns `AssembleResult` (`:3520`): `path, slides_kept, ordinals, fits, clips_inserted,
   stroke, zorder, builds, size_bytes, source_size_bytes, wall_s, warnings, movie_props,
   overflows, ordinal_to_number, hidden`. **There is no "skipped" field.**

Refusal hygiene is already good: a refusal after pass 1 keeps the staged deck as
`*.refused.key`, a non-refusal exception as `*.failed.key`, and `out_path` is never written
with an unverified deck (`:5215-5245`).

### 1.2 How a text slide is detected (the exact predicate)

`dsk_plan._is_text_slide_kept` (`dsk_plan.py:146-177`), called from `_filter_kept_items`
(`:180`), called from `classify_slide` (`:438`):

> A slide is **text** when some kept `text` item's content has **more than
> `text_slide_words` (default `DEFAULT_TEXT_SLIDE_WORDS = 10`, `dsk_plan.py:133`)**
> whitespace-separated words, **or** a kept `group`'s DFS child-text join does.

The answer is surfaced as `SlideClass.is_text` with `long_text_ids` (`dsk_plan.py:434-436`).
Two measured consequences that matter for the contract:

- **A text slide can never be a `movie` or `mixed` slide.** When `is_text` is True,
  `_filter_kept_items` drops every kept `image`/`movie` item into `dropped_media_text`
  (`dsk_plan.py:221-229`), so `movie_count` falls to 0 and `classify_slide`'s category
  cascade (`:495-505`) can only yield `static`, `built` or `empty`. Skipping text slides
  therefore **cannot** drop a video slide.
- **It can drop an image slide** — an image slide carrying a >10-word caption classifies as
  text and loses its image. That is the honest boundary; `--text-slide-words` is the
  operator's escape hatch and stays available in content-only.
- `is_text` depends on `include_side`, `no_dedupe` and `no_drop_panel_backdrop`, so it must
  be read off the *same* `classify_deck` call planning uses, not recomputed.

"Split candidates" are not a separate class: `plan_assembly` only ever splits a slide that
has long text boxes, i.e. `is_text` slides. Two-column slides (`plan.two_column`) likewise
originate from the heading+verse text cluster. **Skipping `is_text` slides removes the
entire benched surface in one predicate.**

### 1.3 Which passes are text-only (measured)

| Pass | Gate | Behaviour with only content slides |
| --- | --- | --- |
| Layout resolve | `layout_for_slide(category="content", …)` returns `"Blank Black"` unconditionally (`dsk_assemble.py:172-203`) | every kept slide → `Blank Black` |
| Style patch | `_has_style_target(slide_layout_names)` — any name in `_STYLE_LAYOUT_NAMES` (`:4322`) | **self-skips**, logs `style: no verse/point-layout ordinals, skipped` |
| Pill mask | `_pill_specs` returns `{}` unless a resolved layout is one of the two verse layouts (`:4214`) | **self-skips** |
| Split / refit / `--min-text-pt` / `--text-fit` | keyed off long text ids | never fires |
| Image crop, clip insert, anchors, stroke restore, z-order restore, build verify | keyed off content items | **all still fire — this is the shipped path** |

`DEFAULT_DSK_LAYOUT_NAMES` (`:118`) imports five layouts; four are verse/point.
`DEFAULT_TRANSPARENT_LAYOUT_NAMES = ("Blank Black",)` (`dsk_live.py:42`).
`check_layout_import_preconditions` (`dsk_live.py:349`) refuses per name — fewer names is a
strictly narrower precondition.

### 1.4 Live evidence of the shipped path

`~/Desktop/dsk-d4-work/out-r13/Sermon_PK_DSK.key` + `evidence-r13/png`, driven by
`accept13.py`. Measured there:

- run was `--slides 5,13,17,21,24,28,32,33,38,44,46,48,50,51,52,53,54` (`accept13.py:20`);
- **21, 24, 48 are image slides; 32, 33 are movie slides** (`accept13.py:123-131`, comments);
- all five resolve layout `"Blank Black"` (same lines);
- all five produce exactly **one** output ordinal each (`_ALL_PART_COUNTS`, `accept13.py:96`) —
  no splits, so ordinals in a content-only run are a plain 1..N renumbering;
- crops are asserted for 21/24, clip loop/volume for 32/33 (`accept13.py:730-731`).

So the slides the owner wants shipped are exactly the ones already passing live acceptance.

### 1.5 Exporter (d5/d5b) state

- `dsk_stage_export.export_stage_pngs(deck, slides, out_dir, *, expected_stage_counts,
  transparent_layout_names=None, layout_template=None, exclude_items=None, clips=None,
  categories=None, rss_limit_bytes=…, include_skipped=False, log=print) -> list[StageAsset]`
  (`:415`). It refuses a deck whose offline geometry is not `EXPECTED_GEOMETRY` (1920×1080),
  refuses `skipped` slides unless `include_skipped`, calls
  `dsk_live.check_layout_import_preconditions`, validates alpha, and writes `manifest.json`.
  `exclude_items` raises `NotImplementedError("exclude_items export scoping is a d6 hook")`.
- `dsk_movie_export.export_slide_clips(fw_deck, slides, out_dir, *, include_side, codec,
  fps, crop_rects, delete_ids, log, rss_limit_bytes, layout_template, black_layout_names)`
  (`:642`) — **FW-only**: refuses a deck that is not a 7680×1080 LW wall (`:668`).
- **CLI gap:** `cli.py` has `dsk-export-clips` and `dsk-assemble` only (`grep dsk src/obed_edom/cli.py`).
  There is **no `dsk-export-stages`**. That is the whole of d5b's remaining work.

### 1.6 API gaps

- `POST /api/dsk` is a hard 501 stub (`web/app.py:494-499`); `dashboard/src/api.ts:233`
  `stubDsk()` just surfaces its detail string.
- The pattern to copy is `/api/resize`: `resize_keynote` (`:501`, form fields
  `path, template_path, range_from, range_to, slides, export, include_lists, validate`,
  slides resolved by `map_remap.resolve_slides`), `resize_thumb` (`:543`, with the
  `_safe_file`-style containment check), `save_resize_framings` (`:564`, persists decisions
  onto `job.result["pages"][…]["decision"]` via `RUNNER.update_result`), `apply_resize`
  (`:592`, re-reads `result["slideRange"]`, `_overrides_from_result`,
  `_side_content_slides_from_result` (`:1212`), then `RUNNER.rerun`).
- `_run_resize_propose` (`:1253`) is the propose shape: `acquire_wall_payload` →
  `inspect_keynote(template)` → `propose_framings`, which calls
  `framing.build_preview_thumbs` (`framing.py:201`) — it downscales **cached** previews and,
  when the cache is empty, runs `export_slide_images` (a live Keynote export). Result carries
  `wallThumbDir` / per-page `thumb` (`framing.py:432`, `:463`).
- **Serialisation is already correct.** `JobRunner` starts exactly one worker thread
  (`web/jobs.py:85`, `_loop` at `:323`), so two Keynote jobs can never run concurrently.
  On top of that `LiveBatch.__enter__` (`dsk_live.py:568-577`) raises
  `"Keynote is already running; close it before an export batch (strictly serial)."`,
  takes a process lock (`_acquire_lock`), starts the display poke and the RSS watchdog
  (`DEFAULT_RSS_LIMIT_BYTES = 3_000_000_000`, `dsk_live.py:32`; measured peak 2.3 GB on the
  669 MB GW deck), and `guard_out_dir` (`:45`) refuses `/tmp` and any dir inside the source
  `.key`. **No new job-queue machinery is needed** — only a friendly pre-flight 409.

### 1.7 UI gaps

- `dashboard/src/tabs/DskTab.tsx` (126 lines) has two `FileWell`s, a "Run validation"
  button wired to `validateKeynote(..., feature: "dsk")`, and a "Generate DSK" button
  wired to `stubDsk()`. No sub-tabs, no slide list, no run/progress.
- Labels to change: `App.tsx:24` `{ id: "dsk", label: "DSK Generator" }`, `nav.ts:10`
  `FEATURE_LABELS.dsk`, `nav.ts:20` `OPEN_IN_LABELS.dsk`. The `FeatureId`/`TabId` union
  stays `"dsk"` — `sessions.ts` and `HistoryTab.tsx` keep working unchanged.
- Segmented control already exists: `.seg` / `.seg button.on` at `styles.css:901-911`,
  used by `components/GenerateResultView.tsx` and `tabs/MapsTab.tsx`.
- **Test-runner measurement that contradicts the brief:** this worktree's
  `dashboard/package.json` has scripts `dev`, `build` (`tsc --noEmit && vite build`),
  `test:maps` (`node --test tests/*.test.cjs`), `preview`. **There is no Vitest and no
  `tests-ui/` directory here** (those live on the maps branch, `feat/w2-gate-ab`). The
  established dashboard test pattern is: compile one `.ts` module with `tsc --module
  commonjs` into a temp dir, `require` it, assert with `node:test`
  (`dashboard/tests/history.test.cjs:1-17` is the canonical example). DSK UI tests must
  follow that, not Vitest — see §3 P6.

---

## §2 Design and decisions

### 2.1 The `--content-only` contract

**Name:** `--content-only` (CLI) / `content_only: bool = False` (`assemble_dsk_deck`,
`plan_assembly` untouched).

**Where the skip happens:** inside `assemble_dsk_deck`, *after* `load_assembly_inputs`
returns `classes` and *before* `plan_assembly` — so the predicate is read off the same
`SlideClass` objects planning will use, with the operator's own `include_side` / `no_dedupe`
/ `no_drop_panel_backdrop` / `text_slide_words` already applied.

```
skipped: list[dict] = []
if content_only:
    by_number = {c.number: c for c in classes}
    for n in sorted(decisions):
        cls = by_number.get(n)
        if cls is not None and cls.is_text:
            skipped.append({"slide": n, "reason": "text",
                            "category": cls.category,
                            "longTextIds": [list(i) for i in cls.long_text_ids]})
    decisions = {n: d for n, d in decisions.items() if n not in {s["slide"] for s in skipped}}
```

Also record (in both modes, for the job report) the slides `plan_assembly` already drops
silently as `category == "empty"` — `reason: "empty"` — so the dashboard can explain every
requested slide that did not come out.

**Report:** new field `AssembleResult.skipped: tuple[dict, ...] = ()`, one log line per
slide — `slide {n}: skipped (text slide; content-only)` — and a CLI tail block mirroring
the existing `Overflows` / `Warnings` blocks (`cli.py:508-520`).

**Refusal:** if `content_only` and every requested slide is skipped, raise
`AssemblyRefusal("--content-only left no slides to assemble; N text slide(s) skipped: …")`
rather than driving Keynote to produce an empty deck.

### 2.2 Every flag/pass in content-only mode

| Flag / pass | State in `--content-only` | Reason |
| --- | --- | --- |
| `--slides`, `--include-side`, `--anchor`, `--clip` | **on, unchanged** | the operator's selection surface |
| `--text-slide-words` | **on** | it *defines* the skip boundary (§1.2) |
| `--layout import` | **on**, but `import_layout_names = ("Blank Black",)` | measured: content slides always resolve `Blank Black` (§1.3, §1.4). The stage exporter needs an alpha-safe base layout (`verify_staged_layouts_alpha_safe`; `export_stage_pngs(transparent_layout_names=…)`), so `preserve` would break alpha PNGs. Importing one donor instead of five narrows `check_layout_import_preconditions`. `--layout-name` still overrides. |
| `--layout preserve` | **allowed but warned** | `slide N: layout preserved; stage PNGs may export opaque` |
| `--no-pills` | **forced on**, logged | already a no-op (`_pill_specs` → `{}`); forcing it makes the guarantee explicit |
| `--no-style` | **forced on**, logged | already a no-op (`_has_style_target` False) |
| `--split N=k` | **refused**: `"--split has no meaning with --content-only (text slides are skipped)"` | a silent no-op would mislead |
| `--no-split` | **refused** for the same reason | ditto |
| `--text-fit shrink` | **refused** | shrink only ever touches autosize/overflowing text boxes |
| `--min-text-pt` | **refused** when passed explicitly | text-stack fit search only |
| `--no-image-crop`, `--crop-dir` | **on** | shipped image path |
| `--no-auto-anchor`, `--no-dedupe`, `--no-drop-panel-backdrop` | **on** | content geometry |
| `--reference-deck`, `--stroke-min-refs`, `--rss-limit-gb` | **on** | unchanged |
| refit pass, `verify_staged_layouts_alpha_safe`, `_restore_stroke`, `_restore_crop_zorder`, `_verify_builds` | **on** | refit is naturally empty; the other three are the shipped path's correctness gates |

Refusals are raised in `cli._run_dsk_assemble` (argument-level, `return 1` with a message on
stderr, matching the file's existing style) so the library stays flag-agnostic.

### 2.3 The Exporter

**What it needs:** nothing new in the engine.
`export_stage_pngs` is complete (48 tests, live-accepted 3 runs). d5b is a `cli.py`
subcommand:

```
dsk-export-stages <DSK.key> --slides 3,7-9 --out <folder>
    [--layout-template PATH] [--transparent-layout "Blank Black"]
    [--include-skipped] [--rss-limit-gb 3.0] [--clip N=/path/clip.m4v]
```

`expected_stage_counts` comes from `dsk_stage_export.stage_counts(...)` over the deck's own
`deck_builds`, and `categories` from `dsk_plan.classify_deck` (which works unchanged on a
1920-wide deck — `is_lw_wall(1920, 1080)` is False, so `_is_side_panel_item` returns False
for every item and the whole slide is in scope, per the d5b section of
`dsk_generator.plan.md`). Validation mirrors `dsk-export-clips`: range-check slides against
`offline_wall_payload`, refuse a non-1920×1080 deck early with a clear message rather than
letting `export_stage_pngs` raise a bare `ValueError`.

**Clip export** stays `dsk-export-clips`, which is **FW-only** (7680×1080 or 3840×1080,
`dsk_movie_export.py:668`). So the Exporter sub-tab offers *stage PNGs on any DSK deck*, and
*clip export on the FW deck*. That split is a property of the engine, not a UI choice —
the UI must label it that way.

### 2.4 Clips inside the Generator flow

GW 32/33 are movie slides; `assemble_dsk_deck` needs a `.mov` per movie/mixed slide
(`SlideDecision.action == "both"` + `clips[n]`). Rather than making the operator run
`dsk-export-clips` by hand first, **apply exports missing clips itself**, inside the same
job, before assembly: for every included slide whose class is `movie`/`mixed` and which has
no operator-supplied clip, run `export_slide_clips(fw_deck, [those slides], <outdir>/clips,
include_side=…)`, then hand the results to `assemble_dsk_deck(clips=…)`. Two live Keynote
batches, strictly sequential, inside one job — which the single worker thread and the
process lock already guarantee. The alternative (a separate `POST /api/dsk/{id}/clips`
button) is kept as a follow-up if the owner wants clips reviewable before assembly.

### 2.5 API

Feature tags: generator `dsk` (existing), exporter `dsk-export` (new) so History keeps them
apart. `validate_keynote`'s allowed tag set (`app.py:478`) gains `"dsk-export"`.

```
POST /api/dsk                      form: path, reference_deck="", range_from, range_to,
                                         slides="", content_only="true",
                                         text_slide_words="" (blank = default)
   -> job kind "dsk", feature "dsk", runs _run_dsk_propose
GET  /api/dsk/{job_id}/thumb/{filename}        (copy resize_thumb's containment check)
POST /api/dsk/{job_id}/decisions   body: DskDecisionsBody
POST /api/dsk/{job_id}/apply       body: DskDecisionsBody (optional) -> RUNNER.rerun

POST /api/dsk/export               form: path, range_from, range_to, slides=""
POST /api/dsk/export/{job_id}/decisions
POST /api/dsk/export/{job_id}/apply
```

`DskDecisionsBody` mirrors `FramingsBody` (`app.py:110`):
`{"decisions": [{"slide": int, "include": bool, "action": "in_deck"|"both"|"export"|"skip",
"anchor": "auto"|"centre"|"left"|"right", "keepSide": bool, "clip": str|null}] | null}`.
`keepSide` deliberately reuses the resizer's semantics; read it back with a
`_dsk_keep_side_from_result` sibling of `_side_content_slides_from_result` (`app.py:1212`).

**`_run_dsk_propose(job, path, slide_range, content_only, text_slide_words)`** — mostly
offline:

1. `offline_wall_payload(path)`; refuse anything but 7680×1080 with the CLI's message.
2. `classify_deck(path, payload=payload, text_slide_words=…)` — offline, no Keynote.
3. `framing.build_preview_thumbs(path, payload, log=job.log)` — reuses the preview cache;
   **may launch Keynote for a slide-image export on a cold cache**, so the job log must say
   so up front (`"No cached previews for …; exporting slide images (Keynote will open)."`).
4. Result:

```jsonc
{"phase": "review", "path": "...", "contentOnly": true, "textSlideWords": 10,
 "slideRange": [...] | null, "thumbDir": "...",
 "pages": [{"slide": 21, "thumb": "0021.jpg", "category": "static",
            "buildCount": 0, "movieCount": 0, "isText": false,
            "skipReason": null, "needsClip": false,
            "decision": {"slide": 21, "include": true, "action": "in_deck",
                         "anchor": "auto", "keepSide": false, "clip": null}}],
 "skipped": [{"slide": 13, "reason": "text"}, {"slide": 2, "reason": "empty"}]}
```

Default `include` = `not isText and category != "empty"` in content-only, so the operator
opens the review page on a correct selection. A page with `isText: true` is rendered
disabled in content-only and its `include` is forced False server-side on apply — the range
pre-filter can narrow the selection, never widen it past the mode.

**`_run_dsk_apply(job, …)`** — pre-flight, then work:

1. `dsk_live._keynote_running()` → `HTTPException(409, "Close Keynote before running a DSK
   job (strictly serial).")` at the endpoint, before submitting, so the operator learns in a
   second instead of 40 minutes in.
2. out dir = §2.7; `guard_out_dir` runs again inside the engine.
3. export missing clips (§2.4), then `assemble_dsk_deck(..., content_only=True, log=job.log)`.
4. Then, if the operator ticked "also export stage PNGs", `export_stage_pngs` on the output
   deck — the d5b engine, same job.
5. Result: `{"phase": "done", "deckPath", "clips": {...}, "skipped": [...], "warnings": [...],
   "overflows": [...], "ordinals": {...}, "sizeBytes", "wallS", "pngDir", "pngs": [...]}`.

PNG previews of the *output* deck are served through the existing
`GET /api/jobs/{job_id}/evidence/{filename}` (`app.py:279`) by pointing the job's evidence
dir at the render folder — no new static route.

### 2.6 UI

- `App.tsx:24` → `{ id: "dsk", label: "DSK" }`; `nav.ts:10` `dsk: "DSK"`; `nav.ts:20`
  `dsk: "Open in DSK"`. Union unchanged.
- `tabs/DskTab.tsx` becomes a ~40-line shell: `useState<"generator" | "exporter">`, a
  `<div className="seg">` with two buttons, and the two panes. Last choice persisted via
  `prefs.ts` if that is a one-liner there, else default `"generator"`.
- `tabs/dsk/DskGenerator.tsx` — FW deck `FileWell`, optional reference-deck `FileWell`,
  a range/slides input, a "Content only (skip text slides)" checkbox (**default on**),
  "Propose" → `useCurrentJob("dsk")` + `pollJob`, then the review list, then "Assemble"
  with progress/log (`LoadingOverlay`, as `DskTab` already does), then results: deck path +
  "Show in Finder" (`reveal`), skipped-slide table, warnings, PNG gallery (`Lightbox`).
- `tabs/dsk/DskExporter.tsx` — DSK deck `FileWell`, range/slides, propose → same list
  shape → "Export stage PNGs" → manifest summary + PNG gallery. A note that clip export
  runs on the FW deck (§2.3).
- `tabs/dsk/SlideReviewList.tsx` — new, light. One row per page: thumbnail
  (`/api/dsk/{id}/thumb/{name}`), slide number, category chip, `builds/movies` counts,
  include checkbox, action `<select>`, anchor `<select>`, keep-side checkbox, and a clip
  `FileWell` shown only when `needsClip`. A text-class row renders greyed with a
  "text slide — benched" chip and a disabled include box. Bulk "include all / none" and
  "keep side: all / none" buttons above the list, mirroring `FramingReview.tsx:519/:528`.
  **Do not import `FramingReview.tsx`** (1013 lines of CG-specific affine/anchor pairing).
- `api.ts`: delete `stubDsk`, add `startDsk`, `saveDskDecisions`, `applyDsk`,
  `startDskExport`, `saveDskExportDecisions`, `applyDskExport`, `dskThumbUrl`.

### 2.7 Where outputs live — **owner question Q2**

Recommended default: `output/<FW stem>/dsk/` under `paths.output_root()`, holding
`<stem>_DSK.key`, `clips/`, `crops/`, `stages/` (PNG + `manifest.json`), `report.json`.
This matches `generate`'s `output/<stem>/` convention (SKILL.md) and satisfies
`guard_out_dir` (repo `output/` is explicitly blessed; `/tmp` is refused). The alternative
is a per-run folder the operator picks with `chooseFolder`; the UI should offer that as an
override either way.

### 2.8 Owner questions

See §0 relay list at the end; each has a recommended default already encoded above.

### 2.9 Editing phase — out of scope (noted, not planned)

The owner's "editing phase" idea (operator nudges of position / size / crop on top of the
auto defaults) is **not trivial** here: every rect the operator would drag is computed
inside `plan_assembly` and consumed by the generated AppleScript, so an override needs
(a) a per-slide override map threaded through `plan_assembly` → `build_assembly_script`,
(b) a canvas-accurate preview in the browser, and (c) a persistence story like
`framing.save_framings`. That is its own plan (d6b). The one cheap down-payment included
here is that `SlideDecision.anchor` is already operator-controlled per slide and surfaced
in the review list.

---

## §3 Pieces

Each piece is one PR-sized change with its own tests. "Offline" = no Keynote; CI-safe.

### P1 — `--content-only` in the assembler and CLI (offline)

- Files: `src/obed_edom/dsk_assemble.py` (`assemble_dsk_deck` signature + skip block +
  `AssembleResult.skipped` + forced `no_pills`/`no_style` + narrowed `import_layout_names`),
  `src/obed_edom/cli.py` (`--content-only` arg, incoherent-flag refusals, report tail).
- Tests: new `tests/test_dsk_content_only.py`, using `test_dsk_assemble.py`'s `no_keynote`
  fixture (`tests/test_dsk_assemble.py:39`, forbids `subprocess.run`/`Popen`) so no Keynote
  can start. Cover: the skip predicate over synthetic `SlideClass`es (text / movie / static
  / empty); the report field and log lines; the "all slides skipped" refusal; each
  incoherent-flag refusal (`--split`, `--no-split`, `--text-fit shrink`, `--min-text-pt`);
  `import_layout_names == ("Blank Black",)`; `--layout preserve` warns.
- Acceptance: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_dsk_content_only.py
  tests/test_dsk_assemble.py tests/test_cli.py -q` green; the existing 100+ assembler tests
  unchanged.

### P2 — `dsk-export-stages` CLI (d5b, offline)

- Files: `src/obed_edom/cli.py` (subparser + `_run_dsk_export_stages`).
- Tests: `tests/test_cli.py` additions — 1920×1080 geometry refusal, slide range refusal,
  `--clip N=…` parsing (reusing `dsk-export-clips`'s parse shape), and that the runner calls
  `export_stage_pngs` with the expected kwargs (monkeypatched).
- Acceptance: `--help` documents it; refusals print to stderr and return 1.

### P3 — Generator API (offline-testable)

- Files: `src/obed_edom/web/app.py` — delete `dsk_stub`, add `POST /api/dsk`,
  `GET /api/dsk/{id}/thumb/{name}`, `POST /api/dsk/{id}/decisions`,
  `POST /api/dsk/{id}/apply`, `DskDecisionsBody`, `_run_dsk_propose`, `_run_dsk_apply`,
  `_dsk_keep_side_from_result`, the Keynote-running 409 pre-flight.
- Tests: `tests/test_dashboard_api.py` additions with `TestClient`, monkeypatching
  `classify_deck`, `build_preview_thumbs`, `export_slide_clips` and `assemble_dsk_deck`.
  Cover: propose result shape and default includes; a text page cannot be included in
  content-only even if the body says so; decisions round-trip and survive a re-propose;
  apply passes `content_only=True` and the derived `keep_side` / `anchor` / `clips`;
  thumb path traversal is refused; the 409 when `_keynote_running()` is stubbed True.
- Acceptance: `pytest tests/test_dashboard_api.py -q` green; no Keynote in CI.

### P4 — Exporter API

- Files: `src/obed_edom/web/app.py` — `POST /api/dsk/export{,/{id}/decisions,/{id}/apply}`,
  feature tag `dsk-export`, `_run_dsk_export_propose` / `_run_dsk_export_apply` over
  `export_stage_pngs`; add `"dsk-export"` to the `validate_keynote` tag set (`:478`).
- Tests: as P3, with `export_stage_pngs` monkeypatched; plus the 1920×1080 refusal.

### P5 — UI shell: labels + sub-tabs + build

- Files: `App.tsx:24`, `nav.ts:10`, `nav.ts:20`, `tabs/DskTab.tsx` (→ `.seg` shell),
  new `tabs/dsk/DskGenerator.tsx` (the current DskTab body, verbatim, minus `stubDsk`),
  new `tabs/dsk/DskExporter.tsx` (placeholder pickers), `api.ts` (`stubDsk` removed).
- Tests: none beyond `npm run build` (this is a pure move).
- Acceptance: `cd dashboard && npm install && npm run build` clean (`tsc --noEmit` included);
  restart `python -m obed_edom dashboard`; both sub-tabs render; History still lists old
  `dsk` runs.

### P6 — UI review list + full wiring + build

- Files: `tabs/dsk/SlideReviewList.tsx`, the two sub-tab components filled in, `api.ts`
  additions, `styles.css` only if a new row style is genuinely needed.
- Put the pure logic in a **separate non-React module** `dashboard/src/dsk/decisions.ts`:
  default-include derivation, bulk include/keep-side, the "text page can never be included
  in content-only" invariant, `needsClip`, and the propose→decisions body mapping.
- Tests: `dashboard/tests/dsk-decisions.test.cjs`, following
  `dashboard/tests/history.test.cjs:1-17` exactly (compile `src/dsk/decisions.ts` with
  `node_modules/typescript/bin/tsc --module commonjs`, `require`, `node:test` asserts).
  It runs under the existing `npm run test:maps`. **Note for the orchestrator:** this
  worktree has no Vitest and no `tests-ui/`; the brief's `npm run test:ui` does not exist
  here (§1.7).
- Acceptance: `npm run test:maps` green; `npm run build` clean.

### P7 — Live acceptance for the owner (operator-run, hands-off)

Prerequisites: Keynote closed, `pgrep -x Keynote` empty, work on a **copy** under
`~/Desktop`, one agent only, machine hands-off.

```
cp -R "<GW deck>" ~/Desktop/dsk-d6-work/gw-r14.key
PYTHONPATH=src .venv/bin/python -m obed_edom dsk-assemble \
  ~/Desktop/dsk-d6-work/gw-r14.key \
  --out ~/Desktop/dsk-d6-work/out-r14/Sermon_PK_DSK.key \
  --content-only --slides 21,24,32,33,48
```

Then the same selection through the dashboard (propose → review → apply) to prove the API
and UI agree with the CLI.

---

## §4 Acceptance

**Offline (CI, every piece):**

- `PYTHONPATH=src .venv/bin/python -m pytest -q` green, including the new
  `tests/test_dsk_content_only.py` and the `tests/test_dashboard_api.py` additions, with
  the `no_keynote` fixture asserting no Keynote process is ever started.
- `cd dashboard && npm install && npm run build` clean, and `npm run test:maps` green.

**Live (P7), on the copy, expected results measured from §1.4:**

1. The run keeps **exactly 5** slides — GW 21, 24, 48 (image) and 32, 33 (movie) — output
   ordinals 1–5 in source order, no splits.
2. `AssembleResult.skipped` is empty for this selection (none of the five is `is_text`);
   a second run adding a verse slide (e.g. 5) reports it as `{"slide": 5, "reason": "text"}`
   and still produces 5 slides.
3. Every kept slide's base layout is `Blank Black`; `verify_staged_layouts_alpha_safe`
   passes.
4. The log contains `style: no verse/point-layout ordinals, skipped` and the pill pass
   reports nothing to do.
5. Clips are auto-exported for 32/33 (loop/volume as `accept13.py` asserts), crops written
   for 21/24/48, the white 5 pt stroke is present on each card, `_verify_builds` reports no
   surplus, and `out_path` exists with no `*.refused.key` / `*.failed.key` beside it.
6. Keynote peak RSS stays under the 3 GB watchdog limit; the source deck fingerprint is
   unchanged afterwards.
7. PNG renders of all 5 output slides are produced and viewable in the dashboard results
   gallery; the owner eyeballs framing against `evidence-r13/png`.
8. The dashboard path produces a byte-comparable deck (same slide count, same ordinals,
   same skipped report) as the CLI path for the same selection.
