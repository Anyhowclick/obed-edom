# G2 round-2 review — `live_gl_replay_js.py` + G1b + S2/S4

All 168 tests in `tests/test_live_gl_replay_js.py` + `tests/test_live_gl_replay_oracle_parity.py`
pass; `tests/test_live_continuity.py` 254 pass, so no G1b flag-off byte moved.

## Round-1 verification

| # | Finding | Verdict | Site |
|---|---|---|---|
| 1 | stand-down before video resolves must still `release` | **verified** | `live_gl_replay_js.py:761` `if (state.seam){` |
| 2 | `observerNotArmed` must stand down, not refuse install | **verified** (as worded; `refuseInstall` now only `planUnreadable`/`glReplayUnavailable`) | `:950`, `:1005-1006` |
| 3 | ARM-PRE polled, deferred until a context exists | **verified, with a new edge case (spec 4)** | `:129`, `:944-957`, `:984` |
| 4 | `settleToHashMs` unreachable | **verified** — `armPost()` no longer `return`s, tail rAF re-arms, `else if` on `LIVE` is unreachable on the arming tick | `:996`, `:998-1001` |
| 5 | duplicate loops | **verified** — `gen !== state.loopGen` is the *first* test in both `step`s, so a queued stale rVFC uploads nothing | `:859,864,872,874` |
| 6 | pending `sample(n)` never settles | **verified, and the resolution is right** (see Closed checks) | `:722-723` |
| 7 | `toBuffer` out-of-range ROI | **verified**, exact wording | `:397-405` |
| 8 | player GL call during ARM-POST | **verified** | `:240` |
| 9 | `unflaggedPlayerCall` cannot be forced | **partially** — both alternatives were applied, giving two emitting sites (spec 3) | `:241`, `:839` |
| 10 | write-back touches programs we never overrode | **verified** — `written` gated on `state.overrides[i] != null` | `:727-732` |
| 11 | unmeasured constants | **verified** — `MARKER_BAND_EPSILON` hoisted, plan §2.9 added | `:40`; plan §2.9 |
| 12 | frozen `handle.epoch` | **verified** — test invariant added | test `:1216-1231` |
| 13 | `settleGapMs` measured the last call | **verified** — `state.lastClearAt` | `:245`, `:990` |
| 14 | duplicate destination rects | **verified**, incl. docstring | `live_continuity.py:887-906` |
| S1 | `state.retained` write-only | **verified (fallback option)** — but see spec 2 | `:271`, `:889` |
| S2 | `frozenSceneId` undeclared | **verified** | `:113` |
| S3 | G1b docstring | **verified** | `live_continuity.py:887-891` |
| S4 | hot-path ordering | **verified** | `:239` |

No regressions found in 1, 2, 4, 5, 7, 8, 10–14. `state.pending` cannot mask a real failure
(`state.arming` is true only inside `preflight`, `:948/954`); `preflight` *is* re-run from
`onContextCreated:967` after `state.gl` is set, so a deferred item converts there or on the next
ARM-PRE tick; a deferred reason cannot be emitted twice (the deferral pushes nothing and
`standDown:715` is idempotent). `armPost` is not re-entered (phase is `LIVE` or `down`).

## Standards

- **The load-bearing comment is now false.** `:123-124` still claims each §2.7 reason is emitted
  "from exactly one site"; `canvasRemoved` is emitted from `:831` and `:930`, `unflaggedPlayerCall`
  from `:241` and `:839`. Fix: replace with `// Every stand-down reason of plan §2.7 is a literal
  defined once; the sites that can emit it are listed in plan §2.7.` and fix the test (spec 3).
- **Name hides state (two).** `stats().greenRoi` (`:175`) returns `geometry.greenAuthored`, the
  unrounded CSS rect, not the buffer ROI actually read (`geometry.green`). Fix: rename the stats key
  to `greenAuthored` and add `greenRoi: state.geometry ? state.geometry.green : null,` beside it.
  `latencyFromMutationMs` (`:929`) is `now() - at` where `at` is taken at the top of the *same*
  synchronous callback (`:921`): it measures the record scan, never the mutation latency. Fix: set
  `state.latencyFromMutationMs = now() - (records[i].timeStamp != null ? records[i].timeStamp : at);`
  or rename the field `mutationScanMs` in the module, `stats()` and plan §2.5.
- **Write-only counter.** `wrappedCount` (`:192,257,260`) is returned and the return value is
  discarded at `:1020`; nothing else reads it. Fix: delete the variable and make `wrapContexts()`
  return nothing.
- **Dead regex alternative + redundant assertion (tests).** `pendingOr` in `_emitted_reasons`
  (`tests/test_live_gl_replay_js.py:189,192`) names a helper that was never written. Fix: drop
  `pendingOr|` from both the docstring and the pattern. `tests/…:1362` is a weaker, `+1`-off
  duplicate of `:1363-1365`. Fix: delete line 1362.
- **`debugForceFail` is undocumented as a non-product path.** Plan §2.7 requires it documented.
  Fix: add to the module docstring: `"debugForceFail is seeded only from a pre-existing partial
  window.__OBED_GL_REPLAY__ (:28-29 returns whenever one carries a version), so no product
  injection can set it."`

## Spec

1. **(new class, MED) `stats()` reports a `pending` that a real stand-down never clears, and the
   ARM-PRE poll turns a transient signal into a hard stand-down.** `:984` runs `preflight()` on
   *every* ARM-PRE tick, including after `state.gl` exists and recording has begun. From then on a
   single tick on which `window.__obedLive.snapshot()` throws or returns null (`liveSnapshot:163`
   swallows the throw into `null`) is an immediate `settleSignalAbsent` stand-down mid-record, where
   round 1 tolerated it. §2.2 asks for the poll, not for a per-frame liveness gate on a core we do
   not own. **Fix:** in `preflight()` at `:951` change the settle-signal assert to
   `assertOr('settleSignalAbsent', !!liveSnapshot() || state.segment.length > 0, null)` so the
   requirement is proven once, at arming, and a later transient null cannot retire a recording
   module.
2. **(edge case, MED-LOW) The `state.retained` fallback can replay a mid-move frame as the settle
   frame, silently.** `:889` falls back to `state.retained`, which `record():271` sets to the frame
   *before* the current one. The current segment is only non-delimited when the player has begun a
   new frame — which resets `lastPlayerTick` and would defeat the 3-quiet-tick rule — so in the real
   timeline the fallback fires only on a malformed final frame, and then hands ARM-POST a frame
   drawn before the quiet window, i.e. possibly mid-Magic-Move. Nothing records that the fallback
   was taken, so `stats()` cannot tell the two apart. **Fix:** stamp the retained segment and
   require it to be fresh — at `:271` write `state.retained = seg; state.retainedTick = state.tick;`
   (declare `retainedTick: -1,` in the `state` literal at `:113`), and at `:889` change the fallback
   to `if (!isDelimited(seg) && isDelimited(state.retained) && state.tick - state.retainedTick <=
   SETTLE_QUIET_TICKS){ seg = state.retained; event('glreplay-retained-frame', {tick:
   state.retainedTick, len: seg.length}); }`.
3. **(closed class re-opened — r1 finding 9, MED-LOW) Two emitting sites for
   `unflaggedPlayerCall`, and the one-site test cannot see it.** Both of r1's alternatives were
   applied: `:241` (the real wrapper site) and `:839` (a per-tick force hook that is `assertOr(...,
   true, ...)` in production). `test_each_reason_is_emitted_from_exactly_one_site` counts quoted
   literals, so routing through `UNFLAGGED_PLAYER_CALL` (`:141`) makes the count 1 and the test
   green while two sites emit; the same hole covers `canvasRemoved` (`:831`, `:930`).
   **Fix:** delete `:839` and force the reason at its real site instead — change `:240` to
   `if (state.phase === 'LIVE' || state.phase === 'ARM-POST' || API.debugForceFail ===
   UNFLAGGED_PLAYER_CALL){`. Then strengthen the test: in
   `test_each_reason_is_emitted_from_exactly_one_site`, when the literal is bound to a `var NAME =
   '<reason>';`, count `standDown(NAME`/`assertOr(NAME` call sites instead of the literal, and
   assert that count is 1 (`canvasRemoved` legitimately has two — list it as the one documented
   exception with its two sites named).
4. **(edge case, LOW) `gl_replay_script`'s `</script` guard is case-sensitive, and its test is
   conditionally vacuous.** `:1114` escapes only lowercase `</script`; an HTML parser ends the
   element on `</SCRIPT` too. `test_script_builder_escapes_the_script_close_sequence:262-263` guards
   the escaping assertion with `if "</script" in _js_source():`, which is false today, so the
   escaping is never exercised. **Fix:** change `:1114` to
   `body = re.sub(r"</(?=script)", "<\\\\/", GL_REPLAY_JS, flags=re.IGNORECASE)` (import `re`), and
   replace the conditional in the test with a direct exercise:
   `monkeypatch.setattr(live_gl_replay_js, "GL_REPLAY_JS", "var s = '</SCRIPT>';")` then assert
   `"</script" not in script.lower()[len(prefix):-len(suffix)]`.
5. **(edge case, LOW) Six of the fourteen round-1 fixes have no regression test.** No test in S2
   exercises the ARM-PRE deferral (a requirement that appears one tick late must *not* stand down),
   `settleToHashMs` (the harness never flips the hash to `atScene`, so finding 4's actual value is
   still unobserved), the `loopGen` guard, the collector drain on stand-down, the
   `state.retained` fallback, or the second-Magic-Move no-re-arm path. **Fix:** add five cases to
   the sandbox — `lateSeam` (install the seam only after N ARM-PRE ticks; assert
   `standDowns == []` and `stats().pending == 'runtimeSeamAbsent'` before it appears, then LIVE
   after), a hash flip to `atScene` after LIVE asserting `stats().settleToHashMs` is a finite
   number, `pause(); pause(); resume()` asserting `stats().iter` advances by one per tick, a
   `sample(24)` left outstanding when the canvas is removed asserting the promise resolves with
   `< 24` samples, and a second `getContext('webgl')` on a new canvas while LIVE asserting
   `state == 'LIVE'`, `standDowns == []` and no new `glreplay-arm` event.

## Closed checks

- **Finding 6, resolve-vs-reject:** resolving with a PARTIAL list is correct, not merely
  convenient. `html_alpha_probe.score_inpage_liveness` validates each sample with
  `_valid_inpage_sample` (`html_alpha_probe.py:1948`), which is a *per-sample* shape check that a
  short list passes, and then fails closed on count at `:2098` (`len(samples) < min_samples` ⇒
  INCONCLUSIVE "too few samples", `INPAGE_MIN_SAMPLES = 24` at `:85`); an empty list is
  INCONCLUSIVE "no samples" at `:1998`. A truncated window therefore can never reach LIVE, and the
  probe keeps the diagnostic `n`. Rejecting would be strictly worse: `sample()` has no `.catch` in
  the probe's in-page script, so a rejection would surface as an unhandled rejection, and a hang
  (the pre-fix behaviour) would surface as a bare timeout with no `n`.
- **3(a) `greenRoi` D1(a):** correct on the fixture. `greenAuthored():489-499` walks slots from the
  back, takes the first with index > `movieSlot` overlapping the movie rect (slot 4,
  `[788.7255, 672.9159, 353, 313]` vs movie `[105.123, 790.847, 960, 276]`), and
  `largestOutside:471-487` picks the top band (353 × 117.93 = 41 629 px² over the right band's
  76.60 × 313 = 23 976) and insets 8 px ⇒ `{796.7255, 680.9159, 337, 101.931}` ⇒ `toBuffer` ⇒
  **{797, 681, 337, 102}**. No overlapping front slot ⇒ `null` ⇒ `G.green` falsy ⇒ `sampleOnce:446`
  leaves `green: NaN`/`greenRGB: [NaN,NaN,NaN]` ⇒ `_valid_inpage_sample` false ⇒ INCONCLUSIVE, as
  §2.7's D1 note requires. **Closed** apart from the stats-key naming above.
- **3(b) `stats()`:** carries every report-only field §2.3/§2.5 name — `settleGapMs`,
  `settleToHashMs`, `latencyFromMutationMs`, `occludedBands`/`occluderMask`/`bandCount`,
  `opacityUnproven`, `epoch`, `frameLen`, `uploads`, `glErrors`, `iter`, `canvasId`, `geometry` —
  and nothing that could be mistaken for a verdict. **Closed** apart from the naming item.
- **3(c) `debugForceFail`:** reachable only from a pre-existing `window.__OBED_GL_REPLAY__` without
  `version` (`:28-29`); the product path publishes `API` with `version: 1` at `:101`, so a second
  evaluation returns before reading it. The §2.5 steps are each guarded: write-back `:736` try,
  poster restore `:338` try, resume `:752` try, handle delete `:759` try, `release` `:762` try,
  observer disconnect `:769` try; `event()` wraps `seam.note` at `:154`. The only unwrapped
  statements are `API.standDowns.push` (`:749-750`) and the collector drain (`:722`), neither of
  which can throw synchronously. **Closed.**
- **3(d) second Magic Move:** `onContextCreated:960` returns on `state.gl || phase !== 'ARM-PRE'`,
  so no re-arm. The new context's calls exit the wrapper on `this !== state.gl` (`:239`), and
  `state.recording` is false outside ARM-PRE, so nothing records or wraps forever. The prototype
  patches are never removed after RETIRED — one boolean read per GL call for the page lifetime,
  acceptable for v1. **Closed.**
- **3(e) script tag:** `<script id="obed-gl-replay">…</script>\n`, body embedded once, asserted by
  `tests/…:256-268`. **Closed** apart from spec 4.
- **3(f) G1b flag-off:** `_destination_instance`'s change is on the flag-on destination path only;
  `test_gl_replay_defaults_to_off_and_is_byte_identical_to_today`
  (`tests/test_live_continuity.py:2645`) and `EXPECTED_PLAN_SHA256` are green. **Closed.**
- **S2/S4 as an instrument:** the fake GL is not a rasteriser but it is not vacuous — the
  write-back pair is controlled (`test_override_applied_before_mapped_draw:1381` proves the
  override *is* written at 0.2947 in LIVE, `test_writeback_precedes_forwarded_player_call:1347`
  proves it is restored to `restOpacity` and that the forwarded call is last), so neither passes
  against a module that skips the override or skips the write-back;
  `test_each_reason_stands_down_exactly_once:1305` asserts exactly one `release` per reason outside
  `NO_RELEASE_REASONS`, so a never-releasing module fails 15 cases; `test_context_lost_exempts_
  writeback:1370` asserts an empty call log. `_valid_plan_validates_and_builds:360` is a real
  positive control for the 27 refusal cases. Order-independence holds: every scenario is a fresh
  `node -e` subprocess and both `_plan_with`/`_mutate_frame` deep-copy. `PINNED_JS_SHA256:152`
  matches the shipped bytes (`c13d6787…`). `test_each_opacity_unproven_reason_is_present:226` is
  subsumed by the closed-set assertion at `:209-213` and is harmless but redundant. S4 derives both
  field sets from source (`INPAGE_LIVENESS_JS`, `_valid_inpage_sample`) and executes the real
  scorer — the strongest instrument in the round. **Closed** apart from spec 3 and 5.
- **Still not provable in S2 (carry to the S3 gate table, unchanged from r1 Q10):** real `readPixels`
  range behaviour, a real player draw inside ARM-POST, rAF timing of a late `__obedLive`, the
  `clearColor,clear` delimiter against the real 88-call frame, and Float64Array churn.

**Summary: 5 spec findings (1 med, 2 med-low/low-med, 2 low) + 5 standards items; all 14 round-1
findings and 4 standards items landed, finding 9 over-applied into a second emitting site, and six
of the fixes ship without a regression test.**
