# Keynote live continuity — P2 preserve runtime → live host (APPROVED 2026-09-19)

Drafted 2026-09-19 by Opus (read-only) at `6236ffe`; evidence spot-verified by Claude.
**Owner approved 2026-09-19 with decisions 1a · 2a · 3a · 4a ("go with your recs first" — revisitable).**
Parent scope: the Alpha Keynote live presenter (`live_host.py` / `live_session.py`), not P3 file export.
P2 index: [`keynote-alpha.md`](keynote-alpha.md).

## 1. What the host needs
`PRESERVE_SCRIPT` = `scripts/p2_recovery_html_dissolve_live.py:321-1723`.
- **Dead / probe-only (~40%)**: `LIFECYCLE_SCRIPT`; the whole canvas texture-feed stack (`textureFeed`,
  ctx/draw recorders, `movieTexids…uniqueKeyDecoder`, `stop/startTextureFeed`, `moFeedCanvas`, the
  `#stage` MutationObserver). Inert since `__OBED_MOVIE_TEXIDS__` is no longer injected. Do not port.
- **Keep, inert**: measurement surface (`snapshot`, `sampleFrame`, `footprintOwnerDecoderId`) — the host
  gate scores the host page through it.
- **Core (~850 lines, ~25 fixture constants)**: `stash`, `scheduleRemount`, `keepAtFootprint`,
  `slide4Rect`/`keepAtSlot`, `isCompositing`, `bridgeTo34`, `keepSuppressed`, `findMovieCanvas`,
  `beginMove`/`tryRemount`, `bindFacade`, `captureLayout` + keep-warm, `patchSrcAccessor`, the
  `removeAttribute` hook, detach observer, `createElement→setAttribute('src')` retire/reuse/bridge policy.

## 2. Fixture inputs → generic derivation (export `assets/<uuid>/<uuid>.json`)
| Input | Derivation |
|---|---|
| movie footprints, slide-3/4 rects | `renderMovie` node: baseLayer position/size + `isVideoLayer` sub-layer, anchor 0.5 |
| asset keys (`untitled.mov`, `wa0125`) | `renderMovie.movie.asset` → `assets[…].url.web` |
| restart / slide-4 min hash (6, 8) | cumulative `len(events)` over non-skipped slides (2,4,2,2); cross-check the player's `slideIndexFromSceneIndexLookup` |
| restart vs bridge zone | outgoing slide's last event effect: `apple:magic-move-*` ⇒ pin/bridge; `apple:dissolve` ⇒ restart |
| pin vs bridge | same asset both sides: geometry equal ⇒ pin; differs ⇒ bridge to the derived rect |
| "Play movie across slides" | **not present in the export** → owner decision 3 |

**Refuse** (fail-closed ⇒ `continuity: unsupported`, raw player, reason reported): ≥2 instances of one
asset adjacent to a boundary; rotated / non-identity-affine movie layer; unknown transition kind; >1 movie
changing geometry across one MM; unreadable export JSON; player-digest mismatch; unsupported codec.
**Scaled stage**: derive in authored space; map per rAF via `#stage` rect ÷ header slide size (identity at 1:1).
**Open discrepancy**: derived slide-3 rect y=797 vs P2 constant 795 (authored 794.6) — resolve in I1.
**Drift found**: `MOVIE_FOOTPRINTS_BY_KEY.movie2` x/y are stale vs the export (actual (1076,876)); ungated.

## 3. Packaging
New `src/obed_edom/live_continuity_js.py` (JS core + version/sha, mirrors `live_runtime.py`) and
`src/obed_edom/live_continuity.py` (derivation), so I0 and I1 own disjoint files: `PRESERVE_CORE_JS` (parameterised by one injected
`window.__OBED_CONTINUITY__` plan), `derive_plan(export_root, slides) -> ContinuityPlan | Unsupported`,
`CONTINUITY_VERSION` + `js_sha256()`. P2's `PRESERVE_SCRIPT` re-exports it; the adversarial script passes
the fixture plan explicitly. **One copy of the bytes.** Version + sha pinned beside `PLAYER_SHA256`,
surfaced in the session snapshot, recorded in the P2 artifact. P2 gates, thresholds and
`--disable-bridge34` untouched.

## 4. Host integration
Order in `_program_html`: main.js hook (unchanged) → style + black overlay → continuity core + plan → fit
shim. Hide/show only toggles the overlay; movies keep decoding. `goTo` calls preserve `clear()` before the
jump. Snapshot gains `continuity: {mode: qualified|unsupported|off, reason, revision}`; UI badge;
off-switch resolved once at session start.

## 5. Codec
Detect, report, headful plays originals; never transcode the source. HEVC + headless ⇒ unsupported with a
reason; HEVC + headful ⇒ attempt, gated by in-page decoder counters. Optional later: opt-in transcode into
the digest-keyed cache copy only. (Headful HEVC decode on the owner's Mac: untested.)

## 6. Qualification
`scripts/live_continuity_probe.py` drives the HOST page and scores with the existing `html_alpha_probe`
scorers + rVFC/owner identity. Every run: positive **and** red-without-the-fix (continuity off; bridge
disabled). Headless 1:1 → headless 2560×1440 → HDMI with the owner watching 1→2 and 3→4. HDMI proves the
visible carry, no restart flash, placement; it cannot prove decoder identity, panel frame drops, alpha or cadence.

## 7. Increments (disjoint files; Sonnet implements, Codex reviews)
| # | Files | Work | Acceptance |
|---|---|---|---|
| I0 | `live_continuity.py` (new), `p2_recovery_html_dissolve_live.py` | extract core, drop dead feed stack, re-export | P2 adversarial 14 green on both profiles; `--disable-bridge34` RED; sha recorded |
| I1 | `live_continuity.py`, `tests/test_live_continuity.py` | `derive_plan` + refusals | fixture plan == P2 constants; each refusal ⇒ unsupported + reason |
| I2 | `live_host.py`, `live_runtime.py` | inject core + plan, off-switch, window forced 1920×1080 | headless continuity probe green + red controls; backend suite green |
| I3 | `live_continuity.py` JS | authored→screen mapping | probe green at 2560×1440 and P2 rerun green at 1:1 |
| I4 | probe + docs | HDMI run | owner eyeball + artifact |
| I5 | `live_continuity.py` | codec report | unsupported codec ⇒ raw player + reason |
| I6 | `dashboard/src/live/` | badge + off-switch | UI tests |

First HDMI-visible result = **I2** (temporary: 1:1 stage with black bars; H.264 fixture assets; fixture-only).

## 8. Owner decisions (recommendation first)
1. **Codec**: (a) headful-only + report, refuse headless HEVC · (b) opt-in cache-side transcode.
2. **`forceTransparentChrome` in the HDMI build**: (a) off, keep for fill/key · (b) on.
3. **No play-across flag in the export**: (a) bridge every geometry-changing MM where the same asset
   continues (residual: a deck authored to restart at a MM would be carried) · (b) explicit allowlist only.
4. **Default**: (a) ON for qualified decks + off-switch · (b) OFF, opt-in per session.

**Risks**: tolerances (10/16 px, IoU 0.75) are authored-space and must scale with the stage (I3 gate);
`bindFacade` DOM-swap only exercised at 1→2; per-rAF pins at 4K. **Unknown**: headful HEVC; stage re-fit on
a display-mode change; >1 movie across one MM; a MM that also rotates.
