# G2 round-3 review — D1 fix, sentinel audit, PR readiness

172 pass (`test_live_gl_replay_js.py` + `_oracle_parity.py`), 254+1s in `test_live_continuity.py`.
`js_sha256() == aeaaea6f1e9ed6da7609bf6be859a11d79848b204d0c32a96c932d7405eee2c6` == the pinned
literal (`tests/test_live_gl_replay_js.py:152`). Instrument re-validated by me, not taken on trust
(see Closed checks).

## Round-2 + D1 verification

| # | Finding | Verdict | Site |
|---|---|---|---|
| r2-1 | transient `settleSignalAbsent` mid-record | **verified**, exact wording | `live_gl_replay_js.py:1006` |
| r2-2 | `state.retained` fallback stamped + evented | **verified** | `:302`, `:940-944`, `:143` |
| r2-3 | one emitting site for `unflaggedPlayerCall` | **verified** — force moved to the real wrapper site `:272`; the test counts emitting *uses* of the bound constant | `:272`; test `:229-268` |
| r2-4 | `</SCRIPT` escape + non-vacuous test | **verified** | `:1169` (`re.IGNORECASE`); test `:307-319` |
| r2-5 | five regression cases | **verified** | tests `:1586,1603,1619,1634,1647` |
| r2-S1 | one-site comment no longer false | **partial** — `:122-124` now says the sites "are listed in plan §2.7"; §2.7 (plan:66) lists no sites (Standards 1) | `:122` |
| r2-S2 | `greenAuthored` + `greenRoi` both reported | **verified** | `:207-208`; test `:1670` |
| r2-S3 | `latencyFromMutationMs` → `mutationScanMs` | **partial** — module/stats/plan §2.5 renamed, plan §5 (`plan:145`) still says `latencyFromMutationMs` | `:146,202`; plan:145 |
| r2-S4 | `wrappedCount` deleted | **verified** | absent |
| r2-S5 | `pendingOr` + duplicate assertion dropped | **verified** | test `:1494-1514` |
| r2-S6 | `debugForceFail` documented as non-product | **verified**, and extended to `API.debug` | docstring `:20-22` |
| **D1** | probe value never survives a replay | **verified** (one debug-only hole, spec 2) | `:407-436` |

**D1 trace.** `opacityFor` (`:407-411`) returns a value for *every* draw on every path:
`only` (incl. `-1`/`0`) → `value` for the target, `rest` for all others; `rest:true` → `rest`;
default → `overrides[slot] ?? rest`. `replayFrame` (`:426-431`) writes it *before* the
`opts.skip === slot` `continue`, so the ablated draw's program is still normalised. Paths:
proofs `:715-717` each followed by `finally { replayFrame({rest:true}) }` `:718`; post-proof
`:735`; LIVE/paused tick `:894` (paused only skips `perLiveUpload`, not the replay); markerSwap
`:747/:753` and the post-`restorePoster` replay `:753`; stand-down write-back `:787-798` restores
`restOpacity` for overridden slots, and non-overridden programs already hold `rest` from the last
replay. **No path leaves a program at a probe value.** The rest capture (`:675`) is taken after
`replayFrame({rest:true})` `:660`, which writes nothing (`state.restOpacity` is still empty ⇒
`value` `undefined` ⇒ `value != null` false at `:428`), i.e. from a clean frame replay, not from
whatever the player left — as required. `getUniform`/`getUniformLocation` are in `SKIP` (`:224`),
so the capture cannot trip `unflaggedPlayerCall`.

## Sentinel/truthiness audit

| Site | Value that can be falsy | Verdict |
|---|---|---|
| `:409` `opts.only != null` | `only: -1`, `0` | **correct** (the D1 fix; `-1` now writes `rest` everywhere) |
| `:409` `opts.value` | `value` omitted | **hole, debug-only** — `undefined` ⇒ no write ⇒ sticky (spec 2) |
| `:410` `opts.rest` / `:431` `opts.skip === slot` | `rest:false`, `skip:0` | **correct** (strict `===` for slot 0) |
| `:411/:782` `overrides[i] == null` | override `0` | **correct**, and `0` is impossible (`:113` requires `>0 && <1`) |
| `:428` `value != null` | `rest` `null` (incomplete program) | **correct** — intended skip |
| `:134/:250/:532/:533` `MOVIE_SLOT` | `movieSlot === 0` | **correct**; `i > MOVIE_SLOT` at `:533` deliberately yields no green slot when the movie is front-most (documented D1(a) ⇒ INCONCLUSIVE) |
| `:691` `unit == null` | sampler unit `0` | **correct** (`== null`, not truthiness) |
| `:686` `mix === 1 \|\| mix === 0` | `mixFactor 0` | **correct** |
| `:706` `restOpacity[i] === 1`, `:783 != null` | `0` | **correct** |
| `:1045` `lastClearAt == null` | `performance.now() === 0` | **correct** |
| `:1041` `readyAt == null`, `:1053` `settleToHashMs == null` | `0` | **correct** |
| `:1043` `lastPlayerTick >= 0` | tick `0` | **correct** (explicit, not truthy) |
| `:941` `tick - retainedTick <= 3` with `retainedTick: -1` | ticks 0–2 | **safe** — gated on `isDelimited(state.retained)`, `[]` at init |
| `:198/:832/:840` `epoch` | `0` | **report-only**, never tested for truth |
| `:407-411` `restOpacity[slot]` `NaN` | `getUniform` oddity | **theoretical**; `NaN != null` ⇒ would write `NaN`. Not reachable on WebGL float uniforms |
| `:963` `canvas.id \|\| ''` | `id === ''` | **correct** (regex rejects) |
| `:37` `PRESET.version` truthiness | `version: 0` | **cosmetic**; product publishes `version: 1` (`:59`) |
| `:494` `G.green` | object or `null` | **correct** |
| `:445-448` `toBuffer` `x/y/w/h === 0` | ROI at origin | **correct** — `Math.max(0,…)`/`Math.max(1,…)` clamps, no truthiness |

No second boolean-vs-sentinel defect of D1's class remains on the product path.

## Standards

1. **The comment at `:122-124` still asserts something the plan does not say.** It points at
   plan §2.7 for the per-reason site list; `plan:66` lists reasons only. **Fix:** either add to
   §2.7 `Emitted from one site each, except canvasRemoved (LIVE guards() + MutationObserver).`,
   or change the comment to name the exception inline, as the test already does (`test:222-226`).
2. **Plan §2.8's S1 gate (`plan:84`) is now false as written** — "every reason string of §2.7
   emitted from exactly one site". **Fix:** `…from exactly one site (canvasRemoved: two,
   documented)`.
3. **`plan:145` still names `latencyFromMutationMs`.** **Fix:** rename to `mutationScanMs` there
   too (f7c862f6 changed §2.5 only).
4. `paintTexture` (`:330-341`) leaves `UNPACK_FLIP_Y_WEBGL`/`UNPACK_PREMULTIPLY_ALPHA_WEBGL`
   changed; only `restorePoster` (`:346-361`) restores them. Harmless today (markerSwap always
   ends in `restorePoster`), but it is an invisible coupling. **Fix:** save/restore both in
   `paintTexture` as `restorePoster` does.

No dead code, no misleading names, no stray comments elsewhere.

## Spec

1. **(new, MED — unmeasured) The D1 fix makes every replay force `Opacity` on every draw from a
   value captured at END of frame, so two draws sharing one program replay at the same opacity.**
   `:675` reads `getUniform(program, Opacity)` after a full frame replay, one read per *slot*;
   `:426-429` then writes that value immediately before each draw, clobbering the frame's own
   per-draw `uniform1f` for that program. If the real frame ever binds one program to two draws
   with different `Opacity` (Keynote reuses shaders), the second draw's value wins for both and the
   LIVE composite differs from the player. The measured deck has five distinct programs
   (`tests/fixtures/gl_replay/settle_frame.json`), so the fixture and S2 cannot see this, and the
   only pixel evidence (S3 gate 3, residual ≤0.46/ch) was taken at `c145afb8` — **before** this
   change. **Fix (exact):** hoist the program/location discovery loop (`:662-678`, all static —
   `programBefore`, `getUniformLocation`, `uniformNames`) above the first
   `replayFrame({rest:true})` at `:660`, then capture per-draw rather than end-of-frame: add an
   `opts.capture` branch to `replayFrame` that, for each draw and before executing it, does
   `state.restOpacity[slot] = (loc && loc.Opacity) ? g.getUniform(state.programs[slot], loc.Opacity)
   : null;` and writes nothing, and replace `:660` with `replayFrame({capture: true});`, deleting
   the `try { state.restOpacity[j] = … }` at `:675-676`. Then re-run S3 gate 3 on the fixed module
   and record the clean-replay residual — the fix is not shippable on r1's numbers.
2. **(edge case, LOW — debug only) `API.debug.replay({only: n})` with no `value` writes nothing to
   slot `n`,** because `opacityFor` returns `opts.value === undefined` and `:428` skips it — the
   exact shape of D1, surviving in the hook S3 will drive the gate-3 readback with. **Fix:** at
   `:409` use `return opts.only === slot ? (opts.value == null ? rest : opts.value) : rest;`.
3. **(gap, LOW) `stats().opacityAfterProofs` is per-slot, so it cannot detect spec 1.** With a
   shared program, slots i and j report the same value and the D1 invariant stays green while the
   composite is wrong. **Fix:** after spec 1, add `programsDistinct: new Set(state.programs).size
   === state.programs.length` to `statsOf()` (`:196`) and assert it in
   `test_proofs_leave_every_program_at_its_recorded_rest_opacity`; S3 should report it from the
   real deck.

## Closed checks

- **D1 invariant is a real instrument (positive control run by me).** I rebuilt the pre-fix
  `replayFrame` (from `2cd672aa`) into the shipped module by monkeypatch and re-ran the suite:
  `test_proofs_leave_every_program_at_its_recorded_rest_opacity`,
  `test_slot_unproven_after_the_probes_is_left_opaque_not_transparent` and
  `test_live_replay_writes_opacity_for_every_draw_not_just_overrides` **all three fail**
  (program 4 reads `0` where `1` is required), while `test_override_applied_before_mapped_draw`,
  `test_writeback_precedes_forwarded_player_call` and
  `test_happy_path_uses_the_current_segment_not_the_retained_fallback` still pass. The fake's
  uniforms are genuinely sticky (`test:669-674`), so the invariant is not vacuous.
- **One-site test catches a second emitting use (control run).** Injecting a dead
  `standDown(CONTEXT_LOST, null)` into `now()` fails
  `test_each_reason_is_emitted_from_exactly_one_site[contextLost]`. `_emitting_sites` correctly
  excludes declarations and `===`/`!==` force-comparisons, so `:272` and `:800` count as one each.
- **`API.debug` / `debugForceFail` unreachable from the product path.** Both are seeded only
  inside `if (PRESET)` (`:68-85`, `:64`), and `:37` returns whenever a pre-existing global carries
  a version. Repo-wide, `window.__OBED_GL_REPLAY__` is written only at `:130` of the module itself
  — nothing in `live_continuity_js.py`, `live_host.py` or `scripts/**` creates or pre-seeds it, and
  `gl_replay_script` (`:1163-1170`) emits the module bytes unmodified. Asserted by
  `test_debug_hooks_are_absent_on_the_normal_install_path:1725`, which also proves both hooks share
  one gate. **Closed.**
- **No remaining vacuous assertion** in the reworked tests: the escape test now monkeypatches a
  payload and asserts it survived; `test_live_replay_writes_…` guards on `out["dirtied"] == 0` and
  `out["liveTicked"]`; `test_proofs_leave_…` guards on `after is not None`.
- **Still not provable in S2** (unchanged, carry to S3): real `readPixels`, a real player draw in
  ARM-POST, rAF timing of a late `__obedLive`, the real 88-call delimiter, program sharing (spec 1).

## PR readiness

Must be stated in the PR body as **not measured**: CEF/OBS (headless Chrome only), any viewport but
1920×1080, the **real** G3 seam (gates 1–4 are stub-seam), Q3 long-run (`plan:93` gate 5, NOT-RUN),
and — the one that changed under our feet — **gate 3's opacity residual and gate 6's artifact
parity predate the D1 fix**; S3 r1's numbers do not certify the shipped bytes. Also: one deck, one
boundary, `frameLenHistogram` shows 89/93/125 variants that stand down as `frameLengthChanged`.
Plan amendments still owed: §2.8 S1 gate wording (Standards 2), §5 `mutationScanMs` (Standards 3),
§2.7 site list (Standards 1), and a §2.9 line for the end-of-frame rest capture once spec 1 lands.
**Gate a fourth round on:** S3 re-run of gates 2/3/6 against `aeaaea6f…` (now possible — `API.debug.
programs` supplies the `progOpacityBefore` readback that made two gate-3 sub-assertions NOT-RUN),
plus `programsDistinct` from the real deck. A second measured deck and the real seam belong to G3,
not to this PR; Codex can review the module as it stands.

**Summary: the D1 fix and all five r2 spec items landed and the new tests are a proven instrument,
but the fix replaced a sticky-uniform bug with an end-of-frame rest capture that is unsafe for
shared programs and whose only pixel evidence predates it — 1 MED + 2 LOW spec, 4 standards, and
an S3 re-gate before merge.**
