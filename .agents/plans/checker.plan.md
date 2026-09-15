---
name: Checker — active performance work and diagnostics follow-ups
overview: >-
  Consolidated 2026-09-15. The two-tier offline read and replayable diagnostics are shipped.
  Active work is limited to partial-edit caching, incremental previews, cautiously slimming the
  live geometry tier, cache management, and diagnostics tuning based on real staff data.
todos:
  - id: l5-bulk-cache
    content: >-
      Cache live bulk-geometry rows per unchanged slide using the shipped save-churn-immune slide
      fingerprint, with a global-key gate, uncacheable misses, and verify-sample burn-in.
    status: pending
  - id: incremental-previews
    content: >-
      Export only changed slides and merge them with fingerprint-keyed cached previews while
      preserving original slide-number mapping and pixel parity with a full export.
    status: pending
  - id: shaper-wiring
    content: >-
      Wire the built but inert AppKit text shaper behind explicit fallback reasons; this is the
      prerequisite for removing text from the live bulk pass.
    status: pending
  - id: slim-bulk
    content: >-
      After shaper wiring, remove vouched classes from BULK_KINDS without weakening count guards or
      the resizer gold gate; fold the bounded group-frame work into this item.
    status: pending
  - id: cache-cleanup
    content: >-
      Add protected-path metadata and a History cache manager so throwaway checker entries can be
      removed without deleting expensive gold/development caches.
    status: pending
  - id: cross-serve-decision
    content: >-
      Decide whether to keep provenance consistency by rebuilding cached JXA payloads, or accept
      exact JXA geometry across consumers to avoid the rebuild. Current behavior stays KEEP.
    status: pending-owner-decision
  - id: diagnostics-images
    content: >-
      Optional evidence bundle for photo diagnostics. Build only after the owner accepts the
      privacy trade-off; include cropped evidence and heatmaps, never full slide previews.
    status: pending-owner-decision
  - id: diagnostics-message-tuning
    content: >-
      Use real staff diagnostics to evaluate text.word presentation and duplicate grouping before
      changing classifier thresholds or result merging.
    status: pending-staff-data
isProject: false
---

# Checker — active plan

## Shipped foundation

The checker reads IWA addressing, styles, runs, and exact shape/line geometry offline, then splices
one live Keynote bulk read for soft classes (`group`, `image`, `movie`, `text`). Item-level and
whole-slide fallbacks keep uncertain geometry on the live path. This is about 3.25× faster cold
than the old all-JXA read and matched operator-visible results in the end-to-end parity probe; the
one known benign divergence was the documented rotated-mask classification on LW slide 21.

The same reader serves validated CG-resize readback, so geometry changes are resizer-shared and
must keep the gold-deck gate green. Resize propose is tracked in `cg_resizer.plan.md`.

The checker already folds preview export into the live bulk session when exporting, binds the
document by the close-by-name → open → exact-name pattern, and handles skipped-slide preview counts.
Do not reopen those completed optimization items.

## Order of work

Two independent tracks remain:

1. Partial-edit loop: `l5-bulk-cache` → `incremental-previews`.
2. Cold-read slimming: `shaper-wiring` → `slim-bulk`.

Cache cleanup and the cross-consumer provenance decision are standalone. Diagnostics tuning waits
for staff data; the optional image bundle waits for an explicit privacy decision.

## Partial-edit loop

### L5 bulk cache

`slide_fingerprint.fingerprint_deck` is shipped but inert. Its global key covers masters, document
state, font environment, OS/Keynote inputs, and normalized non-slide records. Per-slide keys cover
the id-normalized slide graph, directly reached styles, and referenced media CRC/size. A stylesheet
catalog is deliberately a closure boundary because Keynote recompacts it on every save; applied
styles remain covered through direct references.

The cache wraps the existing `bulk_geometry_fn` injection point; it does not belong inside shared
`inspect.bulk_geometry`. On a hit it must assemble a complete bulk map from cached unchanged rows
plus freshly read changed rows before the splice. Passing only changed rows would mark every omitted
soft item bulk-missing and turn the optimization into mass fallback.

Treat `uncacheable` slides as misses. A matching fingerprint is the staleness guard; the count check
on cached rows is only an addressing/scheme guard because the rows were validated against that same
payload. Burn in with random cached-slide re-reads and alarm on any mismatch before trusting the
cache. Persist source-path metadata so cleanup can distinguish protected decks.

### Incremental previews

Keynote has no slide-range export. The measured viable route marks all unchanged slides skipped on
a scratch copy: `skipped slides:false` excludes them and renumbers the exported PNG sequence over
the retained slides. Map that deterministic sequence back to original slide numbers, then merge
fresh and cached PNGs under one uniform naming scheme.

Before shipping, pixel-compare incremental and full exports on the gold decks and DSK. Detect or
refuse position-sensitive fields such as slide-number placeholders. Use unique scratch basenames;
never risk binding an unrelated open copy of the same deck.

## Slimming the cold bulk tier

The AppKit text shaper exists but is not wired. Vouch only the measured plan-neutral autosize case;
fall back for missing/uncalibrated fonts, unresolved traits, unsupported line-spacing modes,
autowidth-soft boxes, and uncalibrated multiline families. Mixed-run-size autosize remains a known
tail requiring cheap live confirmation or explicit acceptance.

Only after this is proven may `text` leave `BULK_KINDS`. Dropping a kind from the JavaScript reader
without changing the Python contract detonates the count guard and falls back every slide. Any
later image/group removal must fold in the bounded group-frame rule: connector-only children are
vouched only when their origins lie inside the real-child union; groups with no real child remain
unbounded and live-read.

Run `scripts/e2e_run_parity.py` after each read-path change. For shared IWA geometry changes, also
run the Map and Full resizer gold gates and require cleared accuracy tests in the existing L1/L2a
style.

## Cache maintenance and cross-serving

`.cache/inspect` and `.cache/previews` are intentionally outside job purge because warm gold caches
can take about an hour to rebuild. A cache manager must show name/path/slides/size/last-used, protect
configured gold/development paths, and clear non-protected entries without guessing from filenames.

The reverse cross-serve guard currently rejects cached JXA geometry when the checker expects an
offline-composed payload. JXA payloads do contain runs and their geometry is exact, so this is a
consistency policy rather than an accuracy necessity. Keep the safe rebuild until the owner chooses
to accept cross-provenance inputs.

## Measured dead ends

- Dropping the live bulk pass entirely is not viable: naive offline-only reads fell back on roughly
  46% of GW and 88% of DSK slides.
- Category-based uncertainty flags over-reported errors. Vouch measured accuracy, not object class.
- Whole-deck IWA decode/re-encode corrupts real decks. Only surgical member writes are viable.
- PPTX export adds autosize width but does not replace specialized line/group handling while the
  two-tier reader remains available.
- Byte-level slide hashes are invalid because a no-op Keynote save rewrites and renumbers global
  archives. Use the normalized, style-resolved fingerprint only.

## Diagnostics follow-ups

Replayable diagnostics shipped in `e6ad6f8` and passed eight Opus plus six Codex rounds. The review
files are deleted because every finding was resolved and both final verdicts were APPROVE.

### Privacy and replay boundary

- The default JSONL contains the rendered text of both decks. It is effectively a sermon transcript,
  not a redacted artifact. The UI must say so; there is no upload or telemetry.
- Exact text is required to replay branch selection and classification. Hashing or redaction protects
  the copy only by destroying the tuning value.
- Text decisions are replayable. Pixel and geometry findings are descriptive without evidence images.
- Record every paired slide, including no-finding pairs, so tuning can reveal newly firing findings.

### Format, lifecycle, and security

- The first line pins schema, version, thresholds, and rule severities. After the first staff file
  leaves a church laptop, bump `SCHEMA` for breaking record changes and reject older shapes loudly.
- Publishing is atomic; diagnostics failure never fails the checker; one bad record does not discard
  the rest of the run.
- Download, reveal, and purge use the canonical server-owned `.diff/<job>/diagnostics.jsonl` path.
  Reject client-patched paths and symlinked targets; purge never follows a symlink out of output.
- Replay compares source selection, every attempt, `typedSkip`, accumulated carry, raw finding,
  severity-mapped outcome, and message drift. Message-only changes fail only under strict mode.

### Optional images and message tuning

If approved, bundle only `diagnostics.jsonl`, cropped `evidence/`, and `heat/`. Full previews expose
the whole deck and defeat the privacy boundary.

The likely `text.word` usability problem is presentation: padded opcode fragments obscure the
changed span, while exact-message grouping multiplies similar rows. A low-risk first experiment is
visually delimiting the changed span. Do not alter thresholds or merge semantics until real staff
logs can be replayed before and after.
