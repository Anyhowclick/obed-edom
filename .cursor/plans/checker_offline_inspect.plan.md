---
name: Checker offline inspect (cold-inspect speedup)
overview: "Replace the Sermon Checker's per-slide JXA inspect (89% of cold time) with the validated offline IWA read + a slim O(slides) bulk-geometry pass. MEASURED on Sermon_PK (GW).key (63 slides, 2026-08-29): current cold inspect 305.9s (jxa read 273.6s / export 31.7s) → proposed ~94s (offline 0.8s + bulk 61.4s + export 31.7s) = ~3.25x, accuracy-IDENTICAL (overflow-flag A/B 63/63 identical, 0 fallback with the real bulk splice). Read `.cursor/skills/obed-edom/SKILL.md` 'Reading a .key offline (IWA)' first. Checker-SCOPED — inspect_keynote has 6+ callers; do NOT change it globally."
todos:
  - id: emit-rotation
    content: "offline_inspect._item_from_record currently OMITS `rotation` (offline_inspect.py ~L334); the checker reads it for the photo-tilt flag (diff_keynotes.py:736-780) AND the reuse fingerprint (baseline.py:212). Emit it from the frame angle iwa_geometry._xywha already computes. A/B: JXA has 5 rotated items on the GW deck, offline currently emits 0 → target parity."
    status: pending
  - id: grouped-text-offline
    content: "The offline read populates item['runs'] (resolve_style) but NOT slide['groupedText'] — that is attach_runs (iwa_runs.py), which the checker needs for group-slide pairing (_pair_quality via slide_plain_text include_grouped=True). Ensure the checker's offline payload carries groupedText: simplest is to run attach_runs on the offline payload (it sets item['runs'] AND slide['groupedText']) — reconcile so runs are not double-written, OR extend offline_inspect to emit groupedText. Single IWA decode preferred (both are ~0.4s)."
    status: pending
  - id: checker-offline-path
    content: "Add a checker-scoped offline+bulk inspect used ONLY by web/app.py:839,849 (the two checker inspects). = two_tier_wall_payload(deck, bulk_geometry_fn=bulk_geometry) + groupedText + rotation + preview export (reuse export_slide_images) + granular fallback + cache. Leave inspect_keynote's other 4+ callers (framing, single-inspect, remap template/readback) on the full JXA path. Payload must be a byte-shape DROP-IN so compare_inspects / deck_slide_digests / validate are untouched."
    status: pending
  - id: granular-fallback
    content: "Wire the per-slide JXA fallback for guard trips (font-size-unresolved / filename-dirty / bulk-missing) — mirror remap_keynote._merge_legacy_slides — and whole-deck JXA fallback on missing `iwa` extra or bulk raise. On the GW deck the real bulk splice gave 0 fallback; the fallback is the safety net for other decks."
    status: pending
  - id: inspect-version-bump
    content: "Bump INSPECT_VERSION 3→4 (baseline.py:40) so v4 offline+bulk payloads never mix with v3 JXA payloads in the digest-keyed cache. One-time cold refresh of checker caches."
    status: pending
  - id: verify
    content: "me + peer verify: (a) field-parity A/B offline+bulk vs full JXA on GW deck (every field the checker consumes); (b) overflow-flag A/B = 0 divergence (already proven for geometry; re-confirm end-to-end); (c) deck_slide_digests identical (pairings survive) — needs rotation emitted + whole-point geometry; (d) rotation matches JXA's 5 items; (e) end-to-end checker run on GW+DSK via the new path == a full-JXA run (pairings/flags/markup); (f) timing ~3.25x."
    status: pending
isProject: false
---

# Checker offline inspect — cold-inspect speedup

**Read `.cursor/skills/obed-edom/SKILL.md` 'Reading a .key offline (IWA)' first.** This
plan is peer-reviewed (two independent planning agents, reconciled) and MEASURED offline
before any code. It reuses the validated two-tier offline read shipped for the resizer
(`offline_inspect.py`, `inspect.bulk_geometry`, default-on `OBED_OFFLINE_READ`).

## Why (measured, not assumed)

Cold checker inspect on `Sermon_PK (GW).key` (63 slides), Keynote free, cache bypassed:

| Path | Time |
|---|---|
| Current cold `inspect_keynote` (open + O(objects) read + export) | **305.9s** |
| — per-slide JXA read | 273.6s (**89%**) |
| — preview export | 31.7s (10%) |
| Bulk geometry (open + O(slides), no export) | 61.4s |
| Offline read + attach_runs (no Keynote) | 0.8s |
| **Proposed** (offline + bulk + export) | **~94s → 3.25×** |

The per-slide JXA read is the whole cost; export is a small, unavoidable floor (previews
are user-facing). The offline read reconstructs text/runs/style for free (`attach_runs`
already decodes the same IWA graph on every cold inspect today), and the bulk pass supplies
the geometry the overflow flag needs.

## Accuracy is already proven (offline A/B vs cached JXA, GW deck, no Keynote)

- **Pure-offline is INSUFFICIENT**: 12/63 slides diverge on overflow flags; 8 autosize text
  boxes have stale width. So this is NOT a pure-offline change.
- **Offline + bulk geometry is a perfect drop-in**: overflow-flag A/B **63/63 identical**,
  `bulk_ok=True`, **0 fallback slides**, 310 frames spliced. The bulk read supplies Keynote's
  laid-out autosize width, which is exactly the field the flag needs.
- **`rotation` gap is real**: JXA has 5 rotated items; offline emits 0 → must emit it, else
  the photo-tilt flag and the reuse fingerprint drift.

## Design (checker-scoped, minimal blast radius)

`inspect_keynote` has 6+ callers (framing, single-inspect, remap template/readback, checker).
Only the **two checker call sites** (`web/app.py:839,849`) switch to the offline+bulk path:

1. **Payload** = `two_tier_wall_payload(deck, bulk_geometry_fn=bulk_geometry)` — offline
   text/runs/style + exact shape/line geometry + bulk image/group/**text** frames.
2. **groupedText** — ensure the payload carries `slide["groupedText"]` (see `grouped-text-offline`).
3. **rotation** — emit it in `offline_inspect._item_from_record` (see `emit-rotation`).
4. **Preview export** — unchanged: reuse `export_slide_images(deck, export_dir)`. (Optional
   later: fold export into the bulk_geometry Keynote session to save one ~4s open; not required
   for the 3.25×, which was measured with separate opens.)
5. **Granular fallback** — per-slide JXA re-read on any guard trip; whole-deck JXA on
   missing `iwa` extra / bulk raise. Fails safe to today's behaviour.
6. **Cache** — write the payload as today; bump `INSPECT_VERSION` 3→4.

The payload stays a byte-shape drop-in, so `compare_inspects`, `deck_slide_digests`, and
`validate_inspect` are untouched — the checker cannot tell the difference except in speed.

## Fields the checker consumes (all must be present + accurate)

Top-level: `slides`, `slideWidth/Height`, `slideCount`, `path`, `previewDir`, `_cached/_timing`.
Per-slide: `index`, `number`, `skipped`, `items`, **`groupedText`**.
Per-item: `text`, `kind`, `kindIndex`, `x/y/w/h` (bulk), `size`/`font`, `runs[]`
(color/size/capitalization/smallCaps), `fileName`, **`rotation`**, `duplicateOf`.
Fingerprint (`baseline.deck_slide_digests`): loose text + image `fileName:x:y:w:h:rotation`
+ `skipped` — so geometry must be whole-point-rounded and rotation emitted, or pairings churn.

## Risks & mitigations

- **Overflow font-size approximation** → the existing `font-size-unresolved` guard forces a
  per-slide JXA fallback for exactly the slides where offline size can't be trusted.
- **rotation omission** → emit it; A/B against JXA's 5 rotated items.
- **Reuse-fingerprint drift** → whole-point geometry + rotation make digests byte-identical;
  worst case is a one-time re-align (pairing churn, not accuracy loss); operator-saved pairings
  are keyed by path and survive.
- **Blast radius** → checker-scoped; other `inspect_keynote` callers unchanged.
- **`iwa` extra absent / bulk raise** → whole-deck JXA fallback (existing contract).
- **Concurrency** → one Keynote open per deck (bulk + export), same open/close discipline; never
  run during a live checker run (cache-corruption lesson).

## Verification (me + peer, after implementation)

Field-parity A/B (offline+bulk vs full JXA on GW) over every consumed field; overflow-flag A/B
= 0 divergence; `deck_slide_digests` identical; rotation parity; **end-to-end checker run on
GW + DSK via the new path == a full-JXA run** (pairings, flags, markup); timing ~3.25×.

---

## Parked: routine cache cleanup (lower priority — do the speedup first)

The History delete/purge (`web/jobs.py:_purge_artifacts`) deliberately never touches `.cache/`
(warm cache, ~hour to rebuild). `.cache/inspect` + `.cache/previews` are keyed by deck digest
only — no marker separating throwaway *user checker decks* from *gold/dev decks* (Map, Full,
Base_CG_Assets, Sermon_PK). Every payload stores its source `path`, so the split is recoverable.
**Proposed shape:** a protected-paths allowlist (gold/dev deck dirs) + a cache manager in the
History tab listing each cached deck (name/path/slides/size/last-used), gold/dev rows protected
and unselectable, everything else clearable + a one-click "clear all non-protected inspect+preview
cache." Routine cleanup for fresh-run churn; dev caches never touched unless explicitly overridden.
Own plan→peer→implement→verify when picked up.
