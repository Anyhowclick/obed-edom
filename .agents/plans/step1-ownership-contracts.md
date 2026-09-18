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

---

# Round 2 — fold Codex r1 (7 findings). 2 peers. Grounded in the offline gate trace.

Round-1 landed at `cba921a`; the offline gate (both profiles) ran honestly:
`continueThroughMagicMove1to2 = False`, Findings 2 & 3 still green. Codex r1
(`.agents/reviews/step1-ownership-codex-r1.md`) found 7 real defects. This round folds them.

## Empirical facts the fixes must honor (from the cba921a gate run)
- The 1→2 Magic Move is a **7-step hash sequence** `#0…#6`, all `?currentSlide=1`. The movie
  canvases are **rebuilt mid-sequence** — `mo-prepaint-draw` fires at `#4` (canvas `2A29…`, a
  steady) and `#6` (canvas `0885…`, the crossfade `from`), never at the scorer's `#1→#2` flip.
  All prepaint draws were `slot=outgoing`; **zero incoming draws**.
- The movie canvases are **2D** (`contextType:"2d"`). So player-draw derivation = wrapping
  `CanvasRenderingContext2D.prototype.drawImage`.
- **Two `movie1` decoders** (elId 1 & 2) both `texture-feed-start` at `#1`; decoder 3 reuses 2 at
  `#4`. The rVFC feed drew **0** (fails 80+) — only mo-prepaint drew.
- Texids resolved the new shape correctly (steady-anchored single boundary `0885…→A223…`); F3's
  whole-deck fallback did NOT fire here, but is still reachable and must be closed.

## Scope reminder
Round 2 makes ownership **exact** and the instrument **honest/fail-closed**. It does **NOT** make
Finding 1 green — engaging the feed at the real cut (the `#4/#6` rebuild vs `#1→#2` scored flip,
and the 0-draw rVFC) is Step 2 (poster-write interception). A correct round-2 result keeps
`continueThroughMagicMove1to2 = False` but now RED for a proven reason, with the engagement
events visible and the gate failing **closed**.

## Peer 1 — `scripts/p2_recovery_html_dissolve_live.py` (PRESERVE_SCRIPT). Codex F2, F4, F7.
- **F2 (one EXACT decoder via player draw):** install a `CanvasRenderingContext2D.prototype.drawImage`
  wrapper (next to the getContext wrapper) that, when the PLAYER draws an `HTMLVideoElement` into a
  canvas whose id ∈ `outgoing∪incoming`, records `(canvasId → that exact video element)` as the
  canvas's **authored decoder**. Bind the feed to that exact element by identity — not by asset key.
  `boundDecoder` returns exactly the player-authored element for the target canvas (or null); no
  last-wins over same-key siblings. `startTextureFeed` runs for that one element only; multiple
  same-key decoders must NOT all feed. `footprintOwnerDecoderId` returns the player-authored element
  for the footprint canvas (+`contextType`). Emit `authoredBy:'player-draw'` when bound this way,
  `'geom'`/`'none'` otherwise.
- **F4 (getContext = element-stamp ONLY):** delete the `canvas.id → type` map fallback (misfires on
  id reuse → turns a passive read into a forbidden probe). A canvas with no `__obedCtxType` stamp is
  context-unknown → skip it, never call `getContext('2d')` to find out. Only draw where the stamp is
  `'2d'`.
- **F7 (both-sided texids):** `movieTexids` returns `null` unless BOTH `outgoing` and `incoming` are
  non-empty (a real `from≠to` boundary supplies both). One-sided/empty → `null` + `mo-no-texids`.
- **Events (contract seam — Peer 2 depends on these):** emit `texture-feed-draw` on every SUCCESSFUL
  draw (drawn incremented) with `{decoderId:<bound elId>, canvasId, contextType, slot, hashNum,
  authoredBy}`. Keep the skip notes. These MUST exist for Peer 2's collector + gate.

## Peer 2 — `scripts/p2_recovery_html_adversarial.py` + `tests/test_p2_adversarial.py` (new). Codex F1, F3, F5, F6.
- **F1a (collector):** add `texture-feed-draw`, `texture-feed-skip`, `texture-feed-skip-canvas`,
  `mo-prepaint-skip` to the `keep` list (~line 1531) so the engagement events survive.
- **F1b (fail-closed engagement gate):** add a sub-verdict `feedEngagedAt1to2` and fold it into
  `continueThroughMagicMove1to2` so the finding can pass ONLY when ALL hold: both-sided texids
  resolved; `motionAcrossFlip.ok`; one stable non-null `decoderId` across the after-window;
  `contextType=='2d'` on the fed canvas; AND ≥1 `texture-feed-draw`/`mo-prepaint-draw` into an
  **incoming** canvas bound to that decoder within the boundary window. Absence of ANY ⇒ fail
  (never pass by absence). Record which sub-condition failed for diagnosis.
- **F3 (texid provenance):** track each crossfade's occurrences (slide JSON + count). Reject unless
  the steady-anchored boundary is unique; **DROP** the whole-deck "sole footprint-sized crossfade"
  fallback → `null` + warning instead. A spurious slide-4 tween must never become the boundary.
- **F5 (steady folding by identity):** fold only the steady texture from the **same enclosing
  layer/object** as the resolved crossfade `from`/`to` — not every footprint-sized steady. If the
  owning layer can't be identified, fold no steady (keep just crossfade `from`/`to`).
- **F6 (load-bearing tests):** `tests/test_p2_adversarial.py` importing the script module: (i)
  spurious same-sized `contents` tween rejected; (ii) two-candidate ambiguity → null+warning; (iii)
  steady folding picks same-object not same-size; (iv) `_times(decoder_id=…)` returns the bound
  decoder's clock, not max-of-sibling (must actually call `_times`); (v) the engagement gate fails
  closed when the feed-draw event is absent / decoderId unstable / contextType≠2d.

## Contract seam (pinned)
`texture-feed-draw` event fields: `{kind:'texture-feed-draw', detail:{decoderId, canvasId,
contextType, slot:'outgoing'|'incoming', hashNum, authoredBy}}`. `movieTexids` null unless both
sides present. The gate keys off `slot=='incoming'` + `authoredBy` + `decoderId` stability.

## Integration (both rounds)

Each stream edits only its files and writes a patch to the shared scratchpad; the main
session applies all three (disjoint files → no conflicts), runs
`pytest tests/test_html_alpha_probe.py` and the offline harness
(`--reuse-export --disposable`, both wait profiles), then routes the integrated diff to
Codex (GPT-5.6 Sol) for review, folds findings, and re-reviews.

- Stream A: `scripts/p2_recovery_html_dissolve_live.py` (`PRESERVE_SCRIPT` only)
- Stream B: `scripts/p2_recovery_html_adversarial.py` (texid derivation + target resolvers)
- Stream C: `src/obed_edom/html_alpha_probe.py` + `tests/test_html_alpha_probe.py`
