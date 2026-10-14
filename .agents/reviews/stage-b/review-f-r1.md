# Stage B WS-F review r1 — Opus 5.5 high, commit 65c15ab4

Round 1 → fold all severities (owner folds mediums and lows through r5). Scope: `git diff 3062b43a 65c15ab4`.

What I ran:
- Targeted suites: 33 tests green (`test_live_mm_feed_js.py` and the feed tests in `test_live_host.py`).
- A **joint Node run** of the real `INSTRUMENT_JS` (installed first, via `bootstrap`) and the real `MM_FEED_JS` on one
  fake WebGL context, in two variants: with and without a leading zero-draw frame.
- A check of the recorded player behaviour in the evidence:
  `output/evidence/stage-b-2026-10-13/glfeed/out/run2-direct/direct/*/report.json` (main checkout).

## Blocker
1. **(new class: frame model differs from the real player)** `live_mm_feed_js.py:396-404` (`finishFrame`), reached from
   `gl.clear` at `:491-492`.

   On every `clear` that closes a frame which did not reach `drawCount`, the module stands down every continuous record
   (and every requested-but-undone `once` record) whose decoder is ready but which was not fed in that frame. It does
   this whether or not the frame contained the record's draw.

   The real player opens every move with zero-draw frames. glfeed `run2-direct` per-frame draw counts:

   | Move | Draw counts | Leading zero-draw frames |
   |---|---|---|
   | 5→6 | `[0, 5, 5, …]` | 1 |
   | 6→7 | `[0, 0, 9, …]` | 2 |
   | 7→8 | `[0, 12, 12, …]` | 1 |

   So the first real frame's `clear` stands the entry down with `no-feed` / `baked` before any draw is reached. Both
   continuous feeding and the one-shot hold are therefore dead on every move.

   Reproduced in the joint run:
   - Without the zero-draw frame: `state fed`, `framesFed 3`, the instrument sees uploads at frames 1–3.
   - With one leading zero-draw frame: `state stoodDown`, `reason no-feed`, `hold baked`, 0 GPU video uploads,
     `onStandDown('no-feed')`.

   The unit test `test_runtime_stand_down_reasons_call_the_current_seam[no-feed]` (`gl.clear(); gl.clear();`) asserts
   exactly this behaviour. That is how 16/16 passed first time.

   This also contradicts §2.1: stand down on "no feed by the end of the first frame **containing an eligible decoded
   draw** for that entry".

   Fix:
   - In `draw()`, when `state.draws === record.binding.draw` and the decoder reads `readyState >= 2`, add the record to
     a per-frame `state.reached` set (reset in `clear` with `eligible`/`fed`).
   - In `finishFrame`, stand down `no-feed` only for `state.reached.has(record) && !state.fed.has(record)`.
   - Frames that never reach the record's draw (zero-draw lead-in frames included) are neutral.
   - Replace the `no-feed` test with: two zero-draw frames, then a fed frame → `state fed`; and a frame that reaches the
     draw with the feed skipped (e.g. `once` requested after the draw) → `no-feed`.
   - Add the zero-draw lead-in to the continuous and `once` tests.

## Major
None beyond the blocker.

## Medium
1. **(edge, unverified timing)** `activeRecords` (`:237-242`) wraps a context only while the hash still reads
   `atScene-1`. If the hash has already moved to `atScene` when the player creates the move's context, nothing is wrapped
   and the failure is silent:
   - continuous: the claimed decoder plays hidden for the whole move, with no stand-down and therefore no poster-hold
     pause, so the owner sees a jump at settle;
   - `once`: no upload, so the baked poster shows.

   The instrument handles both hash timings (r5). The module should too.
   Fix: accept armed records with `atScene - 1 === scene || atScene === scene`. Add a test where the hash moves to
   `atScene` before `getContext`.
2. **(test fidelity, beyond the blocker)** The harness never models the player's zero-draw frames or multi-leaf draw
   order with the fed leaf in the middle. It installs the G2 wrapper *after* the module (`:144-146`), the reverse of the
   host's order (`gl_replay_script` before `mm_feed_script`). It also replaces the instrument with a bare `getContext`
   pass-through, so module-over-instrument wrapping is never exercised.
   Fix:
   - Install the G2 stub before the module.
   - Add one joint test that loads the real `mm_feed_instrument.INSTRUMENT_JS` first and asserts the instrument's
     `uploads` (frameN per fed frame) and `claims` (serial patched) for a continuous move with a zero-draw lead-in. The
     joint run above is a ready template.

## Low
1. After a stand-down while still idle at the source (e.g. a pre-departure stand-down), `poll` re-arms on the next tick
   and claims again (the joint run shows two claims). The core refuses a re-claim in the same generation, so this is
   benign but noisy in the claim stream. Fix: do not re-arm a record stood down in the current idle visit (clear the flag
   in `reset`).

## Verified as meeting the plan
- **Binding checks** (`:281-297`):
  - planned ordinal and size of the regular upload, per bound texture;
  - active unit 0;
  - with `to`: a `mixFactor` value set on the current program;
  - with `to: null`: no `mixFactor` set or queried;
  - unit 1 for `to`.
- **State restore** (`:303-340`): flip/premultiply set from each texture's own regular-upload state; units, bindings and
  unpack state restored.
- **Stand-down reasons:** `binding-invalid`, `claim-refused`, `decoder-mismatch`, `identity-change`, `binding-mismatch`,
  `shared-texture`, `upload-failed`, `no-feed`, `gl-error`, `context-lost`. Each calls `seam.onStandDown` by call-time
  lookup.
- **`once`:** never claims; one upload per bound texture at its draw; no re-upload; `held` / `exact`; a stood-down
  record re-arms only through the core's `once` call (the pre-departure path).
- **Warm-up:** in a module-owned, id-less context (wrapped by neither the module nor the instrument).
- **Frozen interfaces:** binding source `__OBED_CONTINUITY__`; keyword-only builder; writable page API; `decoderFor`
  re-resolved per fed draw; `entries` keyed by `src.objectId`; `take` a telemetry no-op (Phase 0).
- **With the instrument installed first** (joint run): the module captures the instrument's GL spies as its originals,
  so the instrument's `uploads` record every module upload with its `frameN` and the regular ordinal. Its claim spy
  records the idle-time claim, patched to serial 1. Ordinals agree, since both count non-video uploads only.
- **Host/probe:**
  - static import with `MM_FEED_VERSION`/`js_sha256` in `_mm_feed_info`;
  - `injected_feed_variant` patches the host's binding and reports the sha of the variant `MM_FEED_JS` (same unit as the
    shipped sha);
  - `--feed-variant` choices come from `mm_feed_variants.VARIANTS`;
  - the hand-back census excludes the Stage B fixtures.

Verdict: not ready. The frame model stands every feed down on the player's zero-draw lead-in frames. Counts: blocker 1,
major 0, medium 2, low 1.
