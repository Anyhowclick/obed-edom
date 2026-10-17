# Stage B pre-5a folds: open-issue fixes before the pixel round (plan r3)

Base: `claude/stage-b-c4c5` @ `6639d4f0` (C2-integration phases 1–3). Evidence and root causes:
handover `stage-b-c2-integration-2026-10-17.md` ("Pre-5a integration round, NON-PIXEL part", "Root causes of the three
open issues"); investigator reports `funny-pasteur-751a72/.cache/reviews/pre5a-debug-{cost,glint,mismatch}.md`.

**r2 history:** r1 coordinator draft → critique r1 by Codex GPT-6 Astra high (`pre5a-folds-critique-astra.md`) and Fable
(`pre5a-folds-critique-fable.md`), both read-only against the real code and saved artifacts → this coordinator fold.
Where the critics disagreed, the resolution is stated inline ("Coordinator:").
r3: critique r2 by Fable (`pre5a-folds-critique-fable-r2.md`; 1 blocker, 2 majors: the product `getError` stand-down,
the F6a read collision, the drain/record contradiction) folded by the coordinator. The phase-3 streams are already
landed on c4c5 (`6639d4f0`), so every fold's base is c4c5.

## Owner decisions (2026-10-17, ~22:45)
- **D-A.** Cost reduction option **(A)**: keep verifying every GL frame; restructure the reads. The `> 8` ms gate stays.
- **D-dil.** Yes: clean-null cost must also hold per GL frame, so a capture cannot pass by idle-frame dilution.
- **D-hold.** The unseparated Alpha holds become documented open items ("unseparated on moving footage", parent
  INVALID). Follow-up evidence: an exact-frame check on a counter deck. Never a threshold change.
- **D-np.** Narrow no-pause `posterHold False` to the connected carries; the detached carries are recorded as None.
- **D-gl.** Take the GL-interval fallback fold.
- **D-ts.** "As recommended" (the recommendation was optional hardening). **Coordinator (reversible): DEFERRED** — both
  critics showed the push-only skip breaks sampler integrity (seq gap, `rows != rafTicks`, `ppMismatch`), and Astra showed
  an equal-timestamp callback can carry a conflicting pre-paint observation, so a correct version needs its own design.
  PENDING OWNER CONFIRMATION of the deferral. The observed failure (1/71 arms) is fail-closed (inconclusive, never a false pass); the strict contract stays.

## Folds

### F1. GL-interval fallback (stream P; O delegates)
Amended frozen rule (replaces plan C2-int §3 lines 115–120): "Feed intervals come from scored `underArtwork.interval`.
Where a spec's substitution interval is ABSENT (`None`), the window of the single measured GL context for that entry and
scene is used instead: start = `min(createdAt, first finite producer `frameTime` whose `serial` equals the context's serial)`
(`createdAt` alone when that context has no frames), end = `closedAt`, with
`lost=false`, `evidenceComplete=true`, finite and ordered times. A present but malformed interval stays unreadable. No
context, more than one matching context (repeated visit), or an unmeasured context gives `None`. GL replay gives `None`."
- `scripts/live_continuity_probe.py`: exported helper `feed_context_window(capture, spec)`: count ALL contexts whose
  `entryIds` contains the entry AND whose scene matches the spec before checking health; exactly one, healthy, else
  None. Used in `gl_intervals_for` ONLY on the absent-interval branch (~2031-2032). Start uses the same frame-time rule
  as the producer's substitution interval (`mm_feed_instrument.py:789-791`) so fallback arms are not judged stricter
  than nulls after Q2. Specs with an interval are unchanged.
- O: `managed_obs_qualify.feed_gl_intervals` (~2326-2340) delegates to the probe's resolver (it already imports from
  the probe, `:112-126`, and its `scored` carries `feedEvidence.producer.contexts`); no mirrored code. This also gives O
  the probe's finite/order checks and replay guard it lacks today.
- Do NOT relax the producer gate `mm_feed_instrument.py:793`.
- Red-first: extend `test_gl_intervals_are_never_empty_for_replay_or_unreadable_feed` (`tests/test_live_continuity_probe.py:13921`):
  absent interval + one healthy context → window with the frame-time start; malformed-present interval → None; scene
  mismatch → None; one healthy + one unhealthy matching context → None; unrelated contexts only → None; non-finite times
  → None; missing `entryIds` → None; GL replay → None; mixed specs with one still unreadable → None; valid interval takes
  priority over a context. Assert substitution intervals and paint verdicts are unchanged (cadence inputs only). One O
  test that the adapter calls the shared resolver.
- Acceptance: deterministic re-derivation of `runValidity` from the saved round artifacts: only `hold-upload-killed`,
  `ordinal`, `strip-bridge14-movie2` change, each to cadence-open only; every other holder byte-identical.

### F2. Ordinal hold scorer: False without a poster row (stream F; shared per-read helper with F4)
`score_hold_frame` (`mm_feed_instrument.py` ~1446-1470) returns None for a missing poster row before separation. The
ordinal tamper (`live_continuity_probe.py:1724`) legitimately leaves no poster row (poster sampled only for the planned
runtime ordinal, `:313`).
- Wording: "For zero poster candidates, keep every existing identity, completeness and target-neighbourhood check, in
  the existing order (target present with `frame == target` and zero target distance, finite distances, non-empty near
  set). If the distinguishable set is empty → None (`the Alpha hold poster measurement is missing or ambiguous`).
  Ring-only separation ≤ −`ALPHA_HOLD_MARGIN` → the existing False verdict with the same reason text and detail shape as
  the poster path. Any other outcome → None. Two or more poster rows → None. Missing poster never reaches True."
- Factor the per-read separation computation into one helper used by the scorer and by F4's gate rule (Astra/Fable:
  F2 and F4 must not duplicate the maths).
- Red-first tests next to `tests/test_mm_feed_instrument.py:830`: ordinal shape → False; separation exactly −6 → False,
  just above −6 → None; absent target → None; empty distinguishable set → None (no exception); all candidates within
  margin → None; duplicate posters → None; malformed measurement → None. Counter, legacy Alpha and texture-only paths
  unchanged; the existing "poster row missing" case (separation +15) stays None.
- Acceptance: re-score the saved round artifacts: ordinal b5to6 wa0125 → False (−6.67); every other saved holdFrame
  verdict unchanged.

### F3. No-pause expectation narrowed (F one-liner + stream G)
There is no detached-specific reason: `score_poster_hold` (~1502-1504) emits `inconclusive: the move-anchored hold pause
is missing` for both `clockStill True` (browser-paused on detach) and unreadable clocks, and the judged dict carries no
clock detail.
- F: pass the record's `clockStill`, `clockReadable`, `holdPauseMissing`, `complete` and `mediaOverflow` into that
  `_verdict` detail (no verdict change).
- G (`gate_checks.py`): exact-carry exception keyed `(ALPHA_DSK_PLAN_SHA256, "no-pause")` (precedent
  `MM_FEED_STRIP_EXPECTATIONS`, `:163-167`) with the full carry ids and scenes of b6to7 and b7to8 wa0125: expect verdict
  None AND the exact reason string AND `complete is True`, `mediaOverflow == 0`, `holdPauseMissing is True`,
  `clockReadable is True`, `clockStill is True`. A False on a pinned carry MISMATCHes by design. b5to6 wa0125 and b7to8
  wa0121 each remain individually required False; the ≥1-False aggregate stays as an extra guard. Pinned rows print an
  `N/A:`-style note.
- Attribution (unconditional; the evidence exists): require a `holder.paintCensus.findings[]` row with
  `elementId == row.elementId`, `reasons.detached > 0`, and `[t0, t1]` overlapping that carry's hold interval
  (saved no-pause: `arm.paintCensus.findings[1]`, `detached: 109`).
- Red-first mutants: saved record → MATCH; connected carry None → MISMATCH; pinned carry with `clockStill None` →
  MISMATCH; pinned carry with another reason → MISMATCH; wrong plan sha → MISMATCH; detach finding removed → MISMATCH; detach
  finding on the other decoder → MISMATCH.

### F4. Unseparated Alpha holds as documented open items (stream G; uses F2's helper)
Rule-based, not carry-pinned (the affected set varies by run). Scope: `(ALPHA_DSK_PLAN_SHA256, label)` for labels
`feed-off-2s/5s/12s`, `attach-once`, and for `after-feed` only its targeted b5to6 row; rows outside that scope keep their
current requirements (incl. the continuous-mode explicit N/A at `gate_checks.py:616`).
- A row's `holdFrame` MATCHES when True, or when None with exactly the reason
  `inconclusive: the Alpha hold neighbourhood is not separated from other frames` AND, evaluating EVERY phase
  (first/middle/last) with F2's per-read helper: all three phases readable and distinct, target present at zero
  distance, exactly one poster row with distance ≥ `ALPHA_HOLD_MARGIN` in every phase, no phase with separation
  ≤ −`ALPHA_HOLD_MARGIN`, at least one phase strictly between −margin and +margin, and the normalized hold record's
  completeness checks pass. Data source: reachability. The exact reason is emitted only after the scorer's `complete`,
  mode, overflow, stand-down and target checks pass (`mm_feed_instrument.py:1392-1452`), so the reason proves them; F
  adds `mode` and `targetFrame` to that None `_verdict` detail for the OPEN line. "Poster distance" means the
  read→poster `posters[0]["distance"]`, not `targetDistance`; phases are exactly {first, middle, last}. Any unreadable
  phase or later proven-False phase rejects OPEN (Astra blocker: the scorer returns at the first ambiguous phase and
  does not evaluate the rest).
- Helper signature (F-owned, fixed now): `alpha_read_separation(read, target) -> {ok, reason, near, distinguishable,
  separation, posterCount, targetPresent, best}`.
- Floor: each `feed-off-*` and `attach-once` arm needs ≥1 holdFrame True (all saved arms have one); `after-feed` judges
  only its target, so it carries no floor.
- Each OPEN row prints `OPEN: <carry> holdFrame unseparated on moving footage (owner D-hold) sep f/m/l=… best=… target=…`
  (the counter-deck follow-up's evidence). OPEN stays disqualifying on its own: add `Verdict.OPEN` to `gate_checks.py`'s
  verdict set (`:206-232`); the judge returns `_result(Verdict.OPEN, lines, candidate=Verdict.MATCH)` with `ok=False`
  when any row is OPEN and there are no problems; `run_gates.sh` prints `DONE … open=N`; the §7 row reads
  "MATCH (OPEN n)". It can therefore never pass when cadence is later resolved.
- Red-first tests: saved feed-off-2s → MATCH with 3 OPEN lines; ambiguous-first + proven-False-last → MISMATCH;
  ambiguous-first + unreadable-last → MISMATCH; poster within margin of a read → MISMATCH; missing read / reordered
  phases → MISMATCH; other reason → MISMATCH; holdFrame False → MISMATCH; all-None arm → MISMATCH (floor); D7 attach-once
  unaffected; non-target after-feed row unaffected; an
  arm with OPEN rows returns `Verdict.OPEN`, `ok=False`.

### F5. Sampler duplicate timestamp — DEFERRED (see D-ts)
Recorded follow-up design (both critics): handle a duplicate logical frame atomically BEFORE `frameSeq++`/`rafTicks++`/
paint controls/pre-paint toggle, still inside the `sampler.tick` span, with `meta.duplicateTs` (contract meta
whitelists `live_evidence_contract.py:605-620`, `:643`); a duplicate whose observation conflicts with the kept row stays
inconclusive. Needs an end-to-end sampler/ResizeObserver harness test.

### F6. Instrument GL-frame cost, option (A), plus `frame.gl` (streams F, V, P, contract)
Facts (verified by both critics): product contexts are **WebGL1** (`html_alpha_probe.py:2955`, `live_mm_feed_js.py:215`):
no `blitFramebuffer`/read-draw framebuffer split. Measured two-movie GL frame (D7): draw-time `sample()` ×2 (1.4 + 0.9 ms,
`mm_feed_instrument.py:349→227`), rVFC `sample()` ×2 (1.2 + 0.9 ms, `:133`), mid-frame pre-label `readPixels` ×2
(1.5 + 1.3 ms, `:341`), `labelStats` 2 × 0.9 ms (`:272`), finalize reads ≈0.1 ms each (cheap only because the GPU is
already drained). Required improvement per GL frame: D7 ≈ 3.1 ms (11.1 → 8), Alpha ≈ **5.1 ms** (13.1 → 8). Feasibility
is UNRESOLVED until measured; do not add component p95s.

**Invariant (Astra blocker, adopted):** the decoder reference stays INDEPENDENT of the product: "Preserve an
independent snapshot of the expected decoder at each feed draw. Never derive the sole decoder reference from a product
texture, the final framebuffer, or a cached rVFC sample." (Coordinator: Fable's product-texture read is rejected for
this reason; a stale/wrong upload would agree with itself.)

**Invariant (Fable r2 blocker, adopted): the instrument never calls `getError()`, and every instrument GL call is
error-free by construction.** The product core polls `getError()` at the end of every frame and stands down every
active feed on any error (`src/obed_edom/live_mm_feed_js.py:467-480`, from its draw wrapper `:583-588`). The core wraps
the context after the instrument, so instrument calls inside `finalizePixels` precede that poll. An instrument error
would stand the product down (a null misread as a product regression); an instrument `getError()` would drain a real
product fault (a false pass). Therefore: scratch textures are (re)allocated to `drawingBufferWidth × drawingBufferHeight`
whenever either changes; copy rects are clamped to the drawing buffer AND the scratch; `checkFramebufferStatus` (which
generates no error) gates every FBO read, incomplete → today's path; the instrument's `texImage2D(video)` runs only when
`readyState >= HAVE_CURRENT_DATA && videoWidth > 0`, inside try/catch, else today's 2D path. Record fallbacks (not
errors) as evidence. The harness fake GL throws on every invalid-state call and asserts zero throws across the fixture
run, and counts `getError` calls and asserts the instrument made none.

**Step 0 (no GL-state risk; run first, one quiet D7 + Alpha pair):** `willReadFrequently: true` on the ring/reference
2D canvas (`:230`; the calibration canvas already uses it at `:245`). Measure per-hook costs and the GL-frame split with the
dbg-cost diagnostic wrapper (`frame.gl` lands with F6a, so step 0 cannot use it), and the instrument `texImage2D(video)`
call cost for F6b; keep the flag only if
verdicts are identical on re-scored captures. Its result decides how much of F6b is needed.

**F6a (pixel-identical; hard equality acceptance):**
1. Pre-label "under" regions: replace the two mid-frame `readPixels` (`:341`) with `copyTexSubImage2D` of the exact
   existing `bounds(..., grow=4)` rectangles from the default framebuffer into an instrument-owned RGBA8 screen-sized
   texture (NEAREST, CLAMP) at identity coordinates, after asserting `FRAMEBUFFER_BINDING === null` (otherwise mark the
   region unreadable → today's None path). Lossless, so `labelStats` inputs are bit-identical.
2. At the existing finalizer (`draw === drawCount`, `:395-411`): ONE GPU stall per context per frame, not one call.
   (a) Bind the scratch FBO once and `readPixels` the bounding box of all saved PRE-label regions (the only stall);
   (b) restore the default framebuffer and perform the existing final-region `pixelPatch` reads unchanged (post-stall,
   ≈0.1 ms each as measured). Identity placement is for the pre-label copies only (the post-label rect is the same
   rect; copying it into the scratch would overwrite the pre-label pixels and make every null `labelsOverFeed False`).
   `bestGeneric()` ordering and `cellMean` geometry are untouched. Read before returning from finalization; never defer
   to a later rAF (drawing buffer not preserved after presentation). A true single read (2×-height scratch) is a
   deferred ≈0.3 ms item.
3. `labelStats` with running sums (prototype 1.9 → 1.25 ms); classification must be identical on zero-variance,
   exclusion-mask, spread and slope boundaries.
- Honest savings: item 1 removes stalls 3 → 1 (≈ −1.8…−2.2 ms, not −2.8), item 3 ≈ −0.65 ms. F6a alone is marginal on
  D7 and insufficient on Alpha.

**F6b (reference path; numerics may change; distribution acceptance):** at the existing draw-time sampling point,
upload `decoderForEntry(e)` with `texImage2D(video)` into an instrument-owned NPOT level-0 RGBA8 texture
(NEAREST, CLAMP, no mipmaps; colour-renderable as in `live_gl_replay_js.py:406-410`) with explicit
`UNPACK_FLIP_Y_WEBGL=false`, `UNPACK_PREMULTIPLY_ALPHA_WEBGL=false`,
`UNPACK_COLORSPACE_CONVERSION_WEBGL=BROWSER_DEFAULT_WEBGL` (recorded in `referenceSource`). Its cost is UNVERIFIED (the
0.3–0.7 ms figure is for the product's upload): measure it in step 0, and count the extra upload bandwidth (two
video-sized uploads per GL frame on top of the product's) as a risk. Orientation: with flip false, texture row 0 is the
video's top row, so `PATCH_UV` windows map with `iy = round(uv[1]·(h−1))` scaled to the texture height; the
asymmetric-pattern test covers it explicitly. and read its nine `PATCH_UV` windows plus counter centres back on the SAME end-of-frame sync via a second
instrument FBO, area-averaging in JS to the existing 27-vector at the existing sample dimensions/orientation. No shader
pass (avoids program/buffer/attrib/viewport/blend state). Guard against a second upload of the same decoder in the frame
(serial/ordinal/presentedFrames mismatch → reference null, today's unreadable path). Incomplete FBO → today's 2D
fallback, counted and stamped `referenceSource`. The poster stays 2D-sampled, so `dSep` becomes cross-domain:
acceptance is a before/after distribution report of `dVideo`/`dPoster`/`dSep` on paired captures of the same pixels;
`dSep` must never cross `ALPHA_POSTER_FLOOR` (2.5, its
only consumer at `:1200`) on any read; if any registered verdict would change, keep the 2D path (no threshold or red changes to compensate). Keep rVFC ring
sampling unchanged (timing, 18 candidates, geometry); zero savings credited to it.

**GL state (both critics):** use the instrument's saved ORIGINAL functions (`O.*`), never the wrapped ones, so product
bookkeeping (`G.unit/G.bindings/G.flip`, ordinals, draw counts) is untouched. Save/restore in `finally` per transaction:
`FRAMEBUFFER_BINDING`; active texture unit and `TEXTURE_BINDING_2D` on the touched unit; `UNPACK_FLIP_Y_WEBGL`,
`UNPACK_PREMULTIPLY_ALPHA_WEBGL`, `UNPACK_COLORSPACE_CONVERSION_WEBGL`, `UNPACK_ALIGNMENT`/`PACK_ALIGNMENT` when set.
`copyTexSubImage2D`/`readPixels` ignore viewport/scissor; no other state is touched (no program, buffers, VAO, blend).
Parameters only on instrument textures. No `getError()` (see the invariant above).
Context loss resets scratch; delete owned objects in `S.cleanup`. Precedent: `live_gl_replay_js.py:395-430`. Any
allocation/upload/copy/readback failure or incomplete resource fails closed to today's path; never reuse
previous-frame bytes (keep the incomplete-frame behaviour at `:411-415`).

**`frame.gl` row (D-dil; name follows the dotted hook grammar):** the whole-frame union of instrument time for each
distinct recorder timeline key on which an actual product draw in a PLANNED feed context is observed, marked by an
explicit recorder call at that draw boundary before the native draw (not `enter('feed.draw')`, which also covers wrap
and upload work). New recorder API: `__obedCost.mark('frame.gl')` sets a per-frame flag; `flushFrame` appends flagged
frames to a second store; `read('frame.gl', offset, n)` pages it; `mark` returns false when stopped or uninstalled,
and the instrument counts rejected marks in `hookHealth`. The unframed draw path (`mm_feed_instrument.py:335`) marks
too. Reconciliation: every distinct `producer.frames[].frameTimestamp` must be among the marked keys (both are
`document.timeline.currentTime`, so equality is exact), else the row is `installed=False, count=0` (unproven). Multiple entries/draws/contexts on one key count once; failed/unframed draws count. Canonical grammar:
applicable+installed+zero → `{applicable:true, installed:true, count:0, p95:null, max:null, overBudget:0}`; inapplicable
→ `{applicable:false, installed:false, count:0, p95:null, max:null, overBudget:0}`; applicability from feed
configuration only; GL frames present in producer evidence but none marked → unproven accounting. Co-land together:
recorder storage + chunked `read()` (`paint_instrument.py:36-147`, `:1905-1930`), probe `instrument_applicability`
(`:1880-1891`) and pager, `INSTRUMENT_COST_HOOKS` and the exact-set contract (`live_evidence_contract.py:212-213`,
`expected_applicability` `:762`), `REQUIRED_HOOKS` (`live_run_validity.py:26`),
`summarize_instrument_cost` (`paint_instrument.py:161-200`), probe `instrumentAccounting` (`live_continuity_probe.py:1990-2008`),
the shared fixture
`tests/fixtures/instrument_cost_rows.json`. The `> 8` gate then applies to `frame.gl` through `_cost` unchanged.

**F6 tests (Node 16.0.0 fake GL at `tests/test_mm_feed_instrument.py:330-430`, ES5 only):** fake
`createTexture/createFramebuffer/bindFramebuffer/framebufferTexture2D/checkFramebufferStatus/copyTexSubImage2D/delete*/getParameter`
with real pixel snapshots; golden `labelStats` equality after labels overwrite `pixels`; per-frame state-neutrality with
non-default seeded state on success and failure paths and on the next native product draw; product ordinals/draw counts
unchanged by instrument calls; fallbacks (incomplete FBO, non-null framebuffer, context loss, allocation failure);
independent-reference mutants (stale upload, wrong decoder, corrupted product texture, rVFC lag) still score as today;
mid-frame re-upload → reference null; recorder: expensive GL frames among many idle/setup frames, multiple draws per
key, nested spans, chunk boundaries, missing marker, exactly 8 vs > 8.

## Acceptance (replaces r1 "exact equality with round artifacts")
- Deterministic replay: re-score/re-derive the saved round artifacts with the folded code; only the named F1/F2 changes
  appear (F3/F4 change judging lines only, as specified).
- Fresh runs: registered per-check expectations, the approved OPEN/N/A rules and every registered red hold. F6a/F6b:
  paired old/new diagnostic captures on the same pixels establish measurement equivalence (F6a exact; F6b distributions);
  separate performance captures of the new instrument alone: interleaved D7 and Alpha feed-on-1920 clean nulls with
  `frame.total` p95 ≤ 8 AND `frame.gl` p95 ≤ 8; the calibration red still INVALID for measured cost; then D7s, the other
  viewports, hold/attach/stand-down arms, and a full `run_gates.sh` round. Final validity stays cadence-open (Q2).

## Sequencing
1. Parallel Sol folds, disjoint files: P (F1 incl. O delegation) and F (F2 + `alpha_read_separation` + the F3 clock
   detail + the F4 `mode`/`targetFrame` detail); then G (`gate_checks.py` + `run_gates.sh` `open=N`: F3 + F4) after F
   lands, because G depends on F for both. Opus 5.5 high review, r1–r3 all severities.
2. F6 step 0 on a quiet window (can run now; no code change beyond a probe-only flag or scratch wrapper).
3. F6a → review → measure; F6b only if step 0 + F6a do not clear both decks with margin; `frame.gl` co-lands with F6a.
4. Re-run affected arms interleaved, full round, pixel round, merge only on the owner's go.

## Non-goals / never
Never relax `ALPHA_HOLD_MARGIN`, `PRE_DRAW_GRACE_MS`, the 8 ms gate or any registered red; no promotion of None to True;
no change to the producer gate at `mm_feed_instrument.py:793`; pixel discovery stays out of judged paths; no product
texture as the sole decoder reference; no `getError()` from the instrument.
