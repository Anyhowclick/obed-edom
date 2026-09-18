# Step 1 — Ownership & targeting: pinned contracts

Frozen coordination surface for the three parallel implementation streams (PR #158,
Finding 1). Streams touch **disjoint files** but agree on the two data shapes below.
Do not change these shapes without updating this doc and all three streams.

Owner/Astra directive being implemented (handover `.agents/handovers/keynote-alpha-html-2026-09-18.md`):
1. Bind the one authored movie object + its **outgoing** and **incoming** texture ids to
   **one exact decoder**.
2. Remove ready-video fallbacks **and** max-of-same-key clocks.
3. **Passively record** the context type returned by the player's own `getContext` calls;
   stop probing newborn canvases with `getContext('2d')`.

Out of scope for Step 1: no capture-tech change (Step 3), no Keynote, no P3, no claiming
Finding 1 closed. Step 1 ends when ownership is deterministic and the feed's engagement at
`#1→#2` is **provable in events** (not merely a green screenshot).

---

## Contract 1 — `window.__OBED_MOVIE_TEXIDS__`

Producer: `scripts/p2_recovery_html_adversarial.py` (`_derive_movie_texids`,
`_extract_movie_texids`, and the injection assignment). Consumer: the injected
`PRESERVE_SCRIPT` in `scripts/p2_recovery_html_dissolve_live.py`.

**Old shape (delete):** a flat `["canvasId", ...]` union of every footprint-sized
`isVideoLayer` + `contents`-crossfade texture id across **all** slides. Over-broad — it
matched same-sized `contents` animations on unrelated slides (Codex defect #5).

**New shape:**

```json
{
  "decoderKey": "movie1",
  "outgoing": ["<canvasId>", "..."],
  "incoming": ["<canvasId>", "..."]
}
```

- `decoderKey` — the continuing movie's asset key (`movie1` = untitled.mov, the footprint
  movie). The single decoder the feed binds to is the one whose `currentSrc`/`src` maps to
  this key. No other decoder is ever fed.
- `outgoing` — canvas id(s) the continuing movie draws into on the **pre-cut** side of the
  `1→2` boundary (slide-1 steady `isVideoLayer` texture and/or the crossfade `from`
  texture for the footprint-matched movie).
- `incoming` — canvas id(s) on the **post-cut** side (the crossfade `to` texture and/or
  slide-2 steady `isVideoLayer` texture for the footprint-matched movie).

Producer requirements:
- Bind to the **single** `1→2` boundary crossfade for the footprint-matched movie. Do not
  union across the whole deck. Keep the `initialState` w/h size gate; additionally require
  the crossfade be the one at the gated boundary (the movie whose footprint == `MOVIE_ROI`).
- `from` → `outgoing`, `to` → `incoming` (a genuine crossfade has `from != to`).
- If the boundary cannot be resolved unambiguously, emit `{"decoderKey": null,
  "outgoing": [], "incoming": []}` and a `warning` — **never** fall back to a whole-deck
  union.

Consumer requirements:
- Read the object; tolerate a missing/malformed value by noting `mo-no-texids` and skipping
  the id-bound feed (never crash, never guess the other movie's slot).
- Feed a canvas **only** if its id ∈ `outgoing ∪ incoming` **and** the player itself created
  a 2D context for it (see Contract 2 / getContext instrumentation). Never call
  `getContext('2d')` on a canvas as a probe.

---

## Contract 2 — per-sample event schema (motion/continuity scoring)

Producer: sample builders in `scripts/p2_recovery_html_adversarial.py` (`_footprint_target`
and the `_target_*` bracket resolvers) plus `footprintOwnerDecoderId` in `PRESERVE_SCRIPT`.
Consumer: `score_motion_across_flip` / `score_playback_continuity` in
`src/obed_edom/html_alpha_probe.py`.

Each sample fed to `score_motion_across_flip` is:

```
{
  "roi":            np.ndarray,   # H×W×4 crop, required, all samples same shape
  "sceneHash":      str|int,      # scene hash at capture
  "captureOffsetS": float,        # wall/capture clock — NEVER treated as media time
  "decoderId":      str|None,     # the ONE bound decoder's element id (see below)
  "w":              int|None,     # that decoder's decoded width (>0 == decoded)
  "movieKey":       str|None,     # that decoder's asset key; must == expected_key
  "contextType":    str|None      # passively recorded: "2d" | "webgl" | "webgl2" | null
}
```

Binding rules (both producer and scorer enforce):
- `decoderId` is the footprint-owning decoder from `footprintOwnerDecoderId`. **No
  first-decoded / ready-video fallback** — if the footprint owner is unresolved, emit
  `decoderId=null` (the scorer fails the gate), not some other video.
- Across the whole window the gate relies on, `movieKey == expected_key` on every sample
  and every post-flip sample shares one non-null `decoderId`. A same-key handoff or a
  restart later in the after-window must **fail**.
- **No max-of-same-key clock**: when collapsing multiple observations that share a movie
  key to one clock, do not take the max across decoders. Use only the bound decoder's own
  clock. A stall on the bound decoder must not be masked by a sibling decoder's higher clock.

---

## Integration

Each stream edits only its files and writes a patch to the shared scratchpad; the main
session applies all three (disjoint files → no conflicts), runs
`pytest tests/test_html_alpha_probe.py` and the offline harness
(`--reuse-export --disposable`, both wait profiles), then routes the integrated diff to
Codex (GPT-5.6 Sol) for review, folds findings, and re-reviews.

- Stream A: `scripts/p2_recovery_html_dissolve_live.py` (`PRESERVE_SCRIPT` only)
- Stream B: `scripts/p2_recovery_html_adversarial.py` (texid derivation + target resolvers)
- Stream C: `src/obed_edom/html_alpha_probe.py` + `tests/test_html_alpha_probe.py`
