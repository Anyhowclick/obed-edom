---
name: Checker diagnostics — replayable finding log
overview: >-
  Church staff trialled the Sermon Checker and the text.* findings (text.word "Wording
  differs" above all) are verbose and full of false positives. The decks are the church's
  IP and cannot be shared, so tuning has to run off a LOG the staff send instead. Ship a
  structured per-finding diagnostics file written during the check pass, downloadable from
  the dashboard, plus a `diag-replay` CLI that re-runs the classifier over the recorded
  inputs. The log is not just readable — it is REPLAYABLE, so a staff file alone mints
  regression fixtures from real false positives. Images stay opt-in and out of the default
  file.
todos:
  - id: writer
    content: New src/obed_edom/diagnostics.py — DiagnosticsWriter (header + JSONL records) and load_records
    status: done
  - id: select-sources
    content: Extract the typed-vs-clean branch out of compare_inspects into a pure select_text_sources() in diff_keynotes.py
    status: done
  - id: wire-text
    content: Record a text record per pair from compare_inspects (both compare() attempts, branch reason, outcome)
    status: done
  - id: wire-other
    content: Record every other Flag (photo.*, style.*, bible.*, bounds.*, diff.*, outline.*) as finding records
    status: done
  - id: app-wiring
    content: Open the writer in _run_diff_check, put diagnosticsPath in the result, add GET /api/jobs/{id}/diagnostics
    status: done
  - id: replay
    content: CLI `python -m obed_edom diag-replay <file>` — re-run select_text_sources + classify_text_diff, report mismatches
    status: done
  - id: ui
    content: One "Download diagnostics" link in the DiffResultView playlist-bar; npm install && npm run build
    status: done
  - id: tests
    content: tests/test_diagnostics.py (writer, replay round-trip), one endpoint test in tests/test_dashboard_api.py
    status: done
  - id: images-optin
    content: Opt-in ?images=1 zip bundling evidence/ + the pair PNGs — LAST, only if the owner says yes
    status: pending
isProject: false
---

# Checker diagnostics — replayable finding log

## Goal

A staff run of the Sermon Checker must produce **one file** that (a) lists every finding
with enough context to judge it a true or false positive, and (b) can be fed back into the
code offline to reproduce the classification bit-for-bit without the `.key` decks. That
second property is what makes it a tuning tool rather than a report: a staff-reported false
positive becomes a pytest fixture by copy-paste.

## Verification of the design hypothesis

Read and confirmed:

- `classify_text_diff` ([text_diff.py:305](src/obed_edom/text_diff.py)) is **pure**. It
  touches only its arguments and module constants (`TRANSLATIONS`, `BIBLE_BOOK_WORDS`,
  `LINE_MATCH`, `VERSE_RUN_TOKENS`, `BLOCK_MIN_TOKENS`, the symbol tables). No file, clock,
  or global state. Recording `(left, right, left_label, right_label, ignore_left_tokens,
  split_labels)` replays it exactly.
- It reads `left.split("\n")` / `right.split("\n")` in the `_residual_lines` branch, so the
  records must keep the strings **with their newlines intact and untruncated**. JSON strings
  do this; any "brief for readability" truncation would silently break replay. No caps.
- `strip_carried_point_title` ([diff_keynotes.py:448](src/obed_edom/diff_keynotes.py)) is
  also pure given `(lw_text, dsk_text, titles)`, and `point_title_keys` is a deck-level
  function — record the resolved `titles` list once per run, not per pair.

**Where I disagree with the hypothesis: recording the classifier inputs alone is not
enough.** A large share of the text.* false positives will not come from the classifier at
all but from the *branch selection* above it ([diff_keynotes.py:1320-1339]): whether the
pair is compared on `typed` text, on `outside_photos` ("clean"), or on the full rendered
`text`. That block calls `compare()` up to **twice** — the typed attempt first, then a
second attempt on clean/full whenever the first returned `None` — and the second attempt
silently keeps `carried` from the first. So the plan records:

1. all four candidate strings per side (`typed`, `text`, `outside_photos`, and the
   post-`strip_carried_point_title` `compare_text`),
2. the gate values, not just the booleans — `_share(a_typed, a_text)`, `_share(b_typed,
   b_text)`, `_share(a_clean, a_text)`, `_share(b_clean, b_text)` — so a near-miss on
   `TYPED_COVERAGE = 0.6` or `FILTER_TOLERANCE = 0.25` is visible as a number,
3. **both** attempts, each with its own inputs and outcome.

To make that replayable rather than merely readable, the branch is lifted into a pure
function (step 2 below). Replay then covers the whole decision, not its tail.

**Second disagreement, smaller:** `photo.*` is *not* replayable from a text log. Those rules
read pixels and item geometry (`photo_findings_for_pair`, `compare_slide_regions`,
`image_item_diff`). For them the record is descriptive only — rule, message, evidence file
name, the item metadata already in the inspect payload — and tuning needs the opt-in image
bundle. That is fine; the owner's pain is text.*, and the plan should not pretend otherwise.

**Agreed:** the OCR / rendered-text stage is the right replay boundary. `render_slide`
([rendered.py:156](src/obed_edom/rendered.py)) needs the preview PNG and the Vision
framework; its *outputs* (`text`, `extracted`, `ocr`, `ocr_used`, `outside_photos`, `typed`)
are strings and go in the record. The PNGs themselves are the deck's content and stay out of
the default file.

## The privacy problem — read this before building

The rendered text of every slide **is** the sermon: the verses, the point titles, the
speaker's copy. A "text-only" diagnostics file is not a redacted artefact — it is a full
transcript of both decks. The owner's stated blocker is that staff cannot share the decks
for IP reasons; a log that carries every word may hit the same wall.

This cannot be engineered away: replay needs the exact strings, and any hashing or
redaction that protects the copy also destroys the ability to tune the classifier, which
works on words. So the plan makes it **explicit and consensual** rather than quiet:

- The download button is labelled with what it contains ("Download diagnostics (includes
  all slide text)"), not a bare "Download diagnostics".
- The file header carries `"contains": "rendered slide text, both decks"`.
- No auto-upload, no telemetry. The file is written locally and the operator chooses to
  send it.

See Open questions — the owner must confirm the staff can send slide text at all. If the
answer is no, the whole approach changes and this plan should not be built as written.

## Design

### Where it is written

`diff_work_dir(job.id) / "diagnostics.jsonl"` — the same work dir that already holds
`heat/`, `evidence/`, `left-inspect.json`. It is created in `_run_diff_check`
([app.py:972](src/obed_edom/web/app.py)), the check pass, and its path is published as
`result["diagnosticsPath"]` next to the existing `evidenceDir` / `heatDir` keys, so
`_purge_artifacts` cleans it up with the rest of the work dir and no new lifecycle appears.

The match pass (`_run_diff`, `check=False`) writes nothing — it produces no findings.
Re-running checks overwrites the file (`"w"`), matching the rest of the job's re-run
semantics.

### Format

JSONL, one JSON object per line, first line a header. JSONL because it streams (no
accumulate-then-dump), stays diffable, and `load_records` is three lines. Not the `logging`
module: the codebase has none, and a structured artefact is not a log stream. Not
`job.log(...)`: that is the operator-facing UI log and must not carry hundreds of lines.

**Header record** (`{"kind": "header", ...}`) — everything needed to pin a replay:

| field | source |
| --- | --- |
| `schema` | `1` (int, bump on any breaking field change) |
| `version` | `obed_edom.__version__` |
| `createdAt` | epoch float |
| `jobId`, `leftLabel`, `rightLabel`, `leftDeck`, `rightDeck`, `sameType` | job / result |
| `leftSlideCount`, `rightSlideCount`, `leftSize`, `rightSize` | `compare_inspects` locals |
| `useOcr`, `ocrUnavailable` | `use_ocr`, `rendered.ocr_unavailable()` |
| `pointTitles` | `point_title_keys(left_slides)` — the deck-level input to the carry strip |
| `thresholds` | `{alignThreshold, typedCoverage, filterTolerance, lineMatch, nearDuplicate, verseRunTokens, blockMinTokens, pointTitleTokens}` read from the module constants, never hardcoded |
| `ruleSeverities` | `load_rules().get("rules")` snapshot, verbatim |
| `contains` | `"rendered slide text, both decks"` |

Deck file names/paths are **not** written (`leftPath` would leak the church's folder
structure and sermon title for no tuning value).

**Text record**, one per pair that reached the text-compare block
(`kind: "text"`):

```
pairIndex, pairNumber, leftIndex, rightIndexes, leftNumber, rightNumbers,
score, leftSkipped, rightSkipped, ocrUsed, location
left:  {text, typed, extracted, ocr, outsidePhotos, ocrUsed}   # verbatim, untruncated
right: {text, typed, extracted, ocr, outsidePhotos, ocrUsed}   # right sides joined as compare_inspects joins them
shares: {typedLeft, typedRight, cleanLeft, cleanRight}   # the raw _share floats
typedSkip: "typed-empty" | "typed-below-coverage" | null # why the typed attempt was not tried; null when it was
carried: str | null                                      # accumulated `carried or dropped` across every attempt tried
attempts: [
  {source: "typed"|"clean"|"full", reason: "...",
   inputLeft, inputRight,                                # post-strip_carried_point_title
   ignoreLeftTokens: [...], carried: str|null,            # this attempt's own dropped title, not the accumulator above
   finding: {rule, message, default} | null}
]
outcome: {rule, message, severity} | null                # after make_flag; null when the rule is `off` or nothing fired
```

`ocrUsed` at the top level is `left.ocrUsed or any(right ocrUsed)`; the per-side `ocrUsed`
fields inside `left`/`right` are that side's own value.

`reason` (per attempt, in `attempts[].reason`) is one of the three admitting-gate constants:
`"typed-covers-both"`, `"filter-symmetric"`, `"filter-asymmetric"`. The two typed-skip causes
(`"typed-empty"`, `"typed-below-coverage"`) live in the separate pair-level `typedSkip` field,
not in `reason` — `select_text_sources` returns `(attempts, typed_skip)`, and `typed_skip` is
non-null exactly when no `typed` attempt appears in `attempts`.

**Every pair gets a text record, including the ones with no finding.** They are the
near-misses, they are how a threshold change is evaluated against a real run, and they cost
nothing that the with-finding records do not already cost: a 200-slide deck writes 200
records of mostly slide text, a few MB. Skipping them would make a replay's "no regression"
claim meaningless because the pairs that *start* firing after a tuning change are exactly
the ones that were silent before.

**Finding record**, one per `Flag` that is not a text.* pair outcome
(`kind: "finding"`): `rule, severity, category, message, location, slide, deck, evidence,
pairIndex` (resolved through the same `_flag_on_pair` logic the pairs already use, or
`null` for deck-level flags like `diff.count`). These are descriptive; they make the file a
complete finding inventory, which is half of what the owner asked for.

### How it is downloaded

`GET /api/jobs/{job_id}/diagnostics` in `create_app`, modelled directly on the existing
`job_evidence` handler ([app.py:279](src/obed_edom/web/app.py)): read
`(job.result or {}).get("diagnosticsPath")`, 404 when missing, return
`FileResponse(path, media_type="application/x-ndjson", filename=f"diagnostics-{job_id}.jsonl")`.
No `_safe_file` traversal check is needed (no user-supplied path component), but keep the
`is_file()` guard.

Frontend: one `<a className="btn secondary" href={...} download>` in the existing
`playlist-bar` `actions` div ([DiffResultView.tsx:403](dashboard/src/components/DiffResultView.tsx)),
rendered only when `result.diagnosticsPath` is set (i.e. after the check pass). Mirror the
`evidenceUrl` helper in `dashboard/src/api.ts` with a `diagnosticsUrl(jobId)`. That is the
whole UI change.

### Replay tool

`python -m obed_edom diag-replay <file>` — a new `sub.add_parser("diag-replay")` in
[cli.py:18](src/obed_edom/cli.py), with `--rule`, `--pair`, `--verbose`.

For each `kind: "text"` record it re-runs `select_text_sources(...)` and replays the **full
attempt sequence** it returns (not just the one that fired): for every `(source, a, b, reason)`
in order it applies `strip_carried_point_title`, accumulates `carried = carried or dropped`
exactly as `compare_inspects` does, and calls `classify_text_diff`, stopping at the first
non-`None` finding (or falling back to the last attempt tried when none fires). It then
compares, against the recorded record:

- the replayed `typed_skip` against `typedSkip`,
- the whole replayed attempt list (source, reason, both inputs, ignore tokens, that attempt's
  own `carried`, its raw finding) against `attempts`, entry for entry,
- the accumulated `carried` against the pair-level `carried`,
- the selected attempt's raw finding against the recorded selected attempt's finding,

and only once all of those agree does it map the finding through `ruleSeverities` and compare
the published `outcome` (rule, severity, then message separately as a softer signal):

```
pair 37  text.word  MATCH
pair 41  text.word  MISMATCH  recorded=text.word  replayed=None
41 findings replayed, 2 mismatches, 0 message-only
```

Exit 0 when everything matches, 1 on any mismatch (`--strict` also fails on message-only
mismatches). That inverts into the tuning loop: run it before a change (expect all MATCH —
proves the log is faithful), make the change, run it again, and the MISMATCHes are precisely
the findings the change moved — including one on an attempt that was tried but not selected,
which a check of only the selected attempt would miss. `--verbose` prints the recorded inputs
for a mismatching pair, ready to paste into a test.

Non-text records are counted and skipped with a note; `photo.*` cannot be replayed.

## Implementation steps

1. **`src/obed_edom/diagnostics.py`** (new). `SCHEMA = 1`. A `DiagnosticsWriter` class:
   `__init__(path)` opens the file `"w"` and holds the handle; `header(**fields)` writes the
   header line; `record(kind, **fields)` writes one line (`json.dumps(..., ensure_ascii=False)`);
   `close()`; support the context-manager protocol. Every method is a no-op when the writer
   is `None` at the call site, so the wiring stays `if diag: diag.record(...)` — no null
   object, the codebase does not use one. Plus a module-level
   `load_records(path) -> tuple[dict, list[dict]]` returning `(header, records)`, raising on
   a schema mismatch.

2. **`select_text_sources` in `diff_keynotes.py`** (new, pure, placed next to
   `_filter_symmetric` around line 975). Signature:

   ```py
   def select_text_sources(
       a_text: str, a_typed: str, a_clean: str,
       b_text: str, b_typed: str, b_clean: str,
   ) -> list[tuple[str, str, str]]:  # [(source, left, right), ...] in attempt order
   ```

   It returns the attempt list the current code walks: the `typed` attempt when
   `both_typed and _covers_slide(a_typed, a_text) and _covers_slide(b_typed, b_text)`, then
   the clean-or-full attempt chosen by `_filter_symmetric`. Behaviour must be **byte-identical**
   to today's block — this step is a refactor with no semantic change. Then rewrite
   [diff_keynotes.py:1320-1339] to loop over its result, stopping at the first non-`None`
   finding, keeping the existing `carried = carried or dropped` accumulation.

3. **Text records.** Add `diag: object | None = None` as a keyword-only parameter to
   `compare_inspects`. Write the header right after `same_type` / `point_titles` are known
   (note `point_titles` is computed at line ~1145, after the slots block — write the header
   there). Inside the pair loop, after the finding/flag block, emit the `kind: "text"` record
   with the fields above. The `shares` values come from `_share` calls made once and reused
   by `select_text_sources` — pass them out rather than recomputing.

4. **Finding records.** The cheapest correct hook is `_add_flag`
   ([diff_keynotes.py:984](src/obed_edom/diff_keynotes.py)): every pair-level flag already
   funnels through it. Give it an optional `diag`/`pair_index` and emit a `kind: "finding"`
   record for any flag whose rule does not start with `text.`. Deck-level flags
   (`diff.count`, and the `validate_inspect` flags appended at the end) do not pass through
   `_add_flag`; record those in a short loop over `inspect_flags` and over the `diff.count`
   branch, with `pairIndex: null`.

5. **`_run_diff_check` wiring** ([app.py:972](src/obed_edom/web/app.py)). Build
   `diag_path = Path(result["workDir"]) / "diagnostics.jsonl"`, open a `DiagnosticsWriter`
   in a `with`, pass it to `compare_inspects`, and set `result["diagnosticsPath"] = str(diag_path)`
   in the `result.update({...})` block. Add one `job.log(...)` line — *one*, e.g.
   `job.log("Wrote diagnostics for 214 pair(s).")` — never per finding. Wrap the writer
   construction so an IO failure degrades to `diag=None` and a single log line rather than
   failing the check run; diagnostics must never break a staff check.

6. **Endpoint.** `GET /api/jobs/{job_id}/diagnostics` as described above, placed directly
   after `job_evidence`.

7. **Replay CLI.** `diag-replay` subparser in `cli.py` dispatching to a
   `replay(path, rule=None, pair=None, verbose=False) -> int` in `diagnostics.py` (keeps
   `cli.py` thin, as the other subcommands do).

8. **Dashboard.** `diagnosticsUrl` in `dashboard/src/api.ts` beside `evidenceUrl`; add
   `diagnosticsPath?: string` to the diff result type; the one anchor in the `playlist-bar`.
   Then, per the obed-edom skill: `cd dashboard && npm install && npm run build`.

9. **Opt-in images — do not build until the owner answers.** Proposed shape when approved:
   `GET /api/jobs/{id}/diagnostics?images=1` streams a zip of `diagnostics.jsonl` + the
   `evidence/` directory (the `photo.region` / `photo.marker` crops — already cropped to the
   changed region, so they are the cheapest useful pixels) + `heat/` heatmaps. **Not** the
   full preview PNGs: those are the whole deck as images and defeat the point of not sending
   the deck. For `text.*` tuning no image is needed at all — the rendered strings are the
   entire input. For `photo.*` the evidence crop is exactly the tuning signal. A second
   button, labelled with what it contains.

## Test plan

`tests/test_diagnostics.py` (new, `tmp_path`, verbose in the house style):

- **writer round-trip** — write a header + two records, `load_records` returns them; a file
  with a bumped `schema` raises.
- **replay round-trip, agreeing** — build a record by hand from a known LW/DSK string pair
  that fires `text.word`, run `replay`, assert 0 mismatches and exit 0.
- **replay catches a behaviour change** — monkeypatch a `text_diff` threshold (e.g.
  `LINE_MATCH`) and assert the same record now reports a mismatch and exit 1. This is the
  test that proves the tool does its job; without it the replay is decoration.
- **no-finding pairs are recorded** — a record whose `outcome` is `null` still replays.

`tests/test_diff_keynotes.py` (extend):

- **`select_text_sources` is a pure refactor** — a table of (typed/clean/full share)
  combinations asserting the attempt order, including the `typed`-below-coverage and
  `filter-asymmetric` paths.
- **`compare_inspects` writes one text record per pair** — the existing fixtures in that
  file with a `DiagnosticsWriter` over `tmp_path`; assert the record count equals the pair
  count, that the recorded `outcome.rule` matches the flag actually produced, and that the
  recorded strings replay to the same finding.
- **findings inventory is complete** — every flag in the returned `flags` list appears
  exactly once across the `text`/`finding` records.

`tests/test_dashboard_api.py` (extend, `TestClient`):

- 404 when the job has no `diagnosticsPath`; 200 + `application/x-ndjson` + the first line
  parsing as the header when it does.

Run the full `pytest` suite — step 5 touches `app.py` and the work-dir contract, and
`jobs.py` purge behaviour is covered there.

## Risks

- **The log is the sermon.** Addressed above; it is a consent problem, not a code problem,
  and it can sink the approach. Resolve the open question first.
- **Step 2 is a refactor of live comparison logic.** The typed/clean/full block is the
  hottest tuning surface in the checker and a silent behaviour change there would corrupt
  exactly the baseline this work exists to establish. Land step 2 on its own, with the
  table test green, before any recording is wired in.
- **Record volume.** ~200 records of full slide text per run, a few MB. Acceptable. If a
  deck ever makes this unpleasant, the fix is gzip on the endpoint, never truncation.
- **Schema drift.** `schema: 1` plus a hard raise in `load_records` means an old staff file
  fails loudly rather than replaying against shifted field meanings. `SCHEMA` has stayed `1`
  through several field additions (`carried`, `typedSkip`, per-side `ocrUsed`) because no real
  staff file exists yet to drift against; bump it on the next field change made after the
  first staff file leaves a church laptop, not before.
- **`diag` threading through `compare_inspects`.** That function is already long and has two
  callers. Keep the parameter keyword-only and defaulted to `None` so the match pass and
  every test are untouched.

## Message verbosity — assessment, and what I would *not* change

Asked to assess why staff found `text.word` hard to pinpoint. Reading the message
construction ([text_diff.py:437-470](src/obed_edom/text_diff.py)) and
`mergeDuplicateFindings` ([DiffResultView.tsx:79](dashboard/src/components/DiffResultView.tsx)):

1. `text.word` joins up to **three** opcodes, each rendered by `_phrase` with `pad=2` on both
   sides — so a two-word difference arrives as up to six quoted fragments of ten words. The
   changed span is not visually distinguished from its padding, so the reader re-diffs the
   sentence by eye. This is the real complaint.
2. `text.major` emits four lines (both briefs plus two "Only in …" lists of up to eight
   tokens). Verbose by construction, but it is genuinely a whole-slide difference; leave it.
3. `mergeDuplicateFindings` keys on the **exact** message string, so the same wording
   difference on ten paired slides produces ten separate walls of text instead of one row.
   This is probably the biggest perceived-volume driver.

One low-risk change I would make, and only after the diagnostics land so its effect is
measurable by replay: in `_phrase`, wrap the changed span in `[` `]` while keeping the pad
outside it. Purely presentational, does not touch any rule decision, and `diag-replay`
would report it as a message-only mismatch — which is itself a good check that the tool
distinguishes message changes from classification changes.

I would **not** touch `mergeDuplicateFindings`' key in this pass: merging on rule+slide-set
rather than exact message changes which finding's text survives, and that judgement needs
the log first. It is the obvious follow-up once real staff data is in hand.

## Open questions for the owner

1. **Can staff send a file containing every word of both decks?** If the IP constraint
   covers the copy itself and not only the `.key` files, this plan does not work as written
   and the alternative (structural-only records: token counts, opcode shapes, share values,
   no strings) is a much weaker tuning tool. Answer this before step 1.
2. **One file per run, or an appended history?** The plan overwrites on re-check, so a staff
   member who runs checks twice sends only the second. An appended `diagnostics/` folder
   keyed by timestamp would preserve the before/after of an operator's own re-run. Cheap
   either way, but it changes the result key and the endpoint shape.
3. **Should the check pass write diagnostics always, or behind a settings toggle?** Always
   is simpler and the cost is a few MB per job; a toggle in `load_settings()` is one more
   thing to explain to staff and one more way for the file to be missing when it is needed.
   The plan assumes always.
