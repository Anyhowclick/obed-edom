# GL-replay G3 review R-A (seam + zone), round 1

Reviewer: Opus, R-A, read-only. Diff: `git diff fa8a15be e59927e4` (core, core tests, G2 contract tests). Line cites are
`live_continuity_js.py` at `e59927e4`/`2884e116` (the core has the same bytes in both) unless another file is named. The
focused suites pass at `2884e116`: `uv run pytest tests/test_live_continuity_js.py tests/test_live_gl_replay_js.py`
gives 484 passed and 0 skipped.

Evidence sources:
- The Node harness via `tests/test_live_continuity_js.py::_run_gl`. Probes live in the scratch dir, not the worktree.
- Mutation runs: a pytest plugin in scratch that patches `PRESERVE_CORE_JS` in-process. The worktree is untouched.
- The gate runner's already-written r1 records (`output/live-visible-content/g3/r1/*/result.json`, `gates.json`). I read
  them only; no Chrome was run.

## Counts

| Severity | Count | Findings |
|---|---|---|
| BLOCKER | 0 | — |
| MAJOR | 2 | A1 (NEW CLASS), A2 (CLOSED CLASS: R2/R3/A3, newly measured) |
| MINOR | 6 | A3, A4, A5, A6 (EDGE CASE); A7 (NEW CLASS, test gap); A8 (CLOSED CLASS, harness fidelity) |
| NIT | 5 | A9, A10, A11 (EDGE CASE); A12, A13 (CLOSED CLASS) |

## Answers to the brief

**1. Can a failure end anywhere but exact retire?** Yes, in four places. The main one is A1: a decoder pooled before the
zone is not retired while `armed`, and it survives a hand-off. A3, A5 and A6 are edges.

Everything else checked ends in retire:
- throws: `glRelease` try/catch :636-647;
- `clear()` :143 (K14 holds; the memo and the armed pool are paused);
- `disable()` → `clear()`;
- go-to: host `goTo` clears first (`live_host.py:1254-1255`);
- generation bumps: only `clear()`;
- timers and closures created before a transition. Remount timers from `released` see either `refuse` in the zone or
  `__obedRemountEpoch === -1` on the retired memo (:1309). `keepAtFootprint` stops on `-1` or detach (:847). Only K20
  (`bindFacade`) stays open (A13).

**2. Can the carried decoder paint while armed?** Not inside the zone. Pooling is detached-only (:730). Remount and
scheduling are held (:793-796, :1297-1300). `createElement` is raw (:1700). Keep-warm plays detached nodes only.
Gate 2 (r1) found 2 pooled and 0 in document at settle.

Exceptions:
- A3: `armed` with `armSeen` at `hn ≥ retireZoneEnd`. `zoneMode` returns `allow` and the carried decoder is bridged while
  the zone is still armed.
- A4: an attached node that is `__obedGlPooled` keeps its src.
- A1: a DIFFERENT same-asset decoder (pooled before the zone) keeps painting through `armed`.

**3. Selection.** No fallback exists, and a lone sibling answers `ambiguous` (tested). `__obedAuthoredRect` is written
only from the element's own box with `w,h > 1`:
- stash's attached branch :749-753;
- `captureLayout` at `i === 0` :1568-1571;
- a null `stageMap` writes nothing (`authoredRectOf`).

The r1 armed-2 `glreplay-carried` bound elId 1 with Δ 0.01202. The candidate list was `{2: sibling rect, 1: big rect}`.

Gaps:
- The candidate filter does not require `__obedGlPooled` and does not exclude facade stubs (A1).
- Four of the five candidate guards are untested (A7).

**4. Release rows.** They match §2 in order: :617-626, then `releaseArmed` :651-681. Rows 1–3 mutate nothing except
the `glreplay-release` note; `zoneState(true)` running first is per plan. `toScreen` is correct at a letterboxed stage:
it is tested at s = 0.8333 with oy 50, and gate 4b passed.

The footprint fallback never engages AT the hand-off: row 7 checks :592-604, and gate 4 "hand-off never
-done/-footprint-rect" passed. It does engage again at every later build in `released`, and the movie then settles
misregistered by ≈4 px for the whole #5 dwell (A2).

**5. Flag-off.** Behaviour is equivalent: `GL === null`, so:
- `zoneState` → null;
- `zoneMode` ∈ {allow, refuse} with the same predicate as `preserveAllowedFor`;
- `swallowClear` is the old two branches;
- the sweep is identical;
- `authoredRectOf` returns before `stageMap()`;
- keep-warm reads an undefined flag;
- `clear()` never reaches `retireZone`.

No `glReplay` key is added, and `version: 8` is unchanged. Pre-existing tests are unedited: the only removed lines are
the version literal, the harness `readyState` addition and the `after_core` hook. The G-P2 gate (host ×3, P2 ×3 ==
baseline) agrees.

**6. Arming §7 Codex questions 1–7** (the G3 side only):

| Q | Answer |
|---|---|
| (1) | See item 1 above. |
| (2) | See item 2 above. |
| (3) | `release` runs synchronously inside G2's `standDown`, after `restorePoster` (G2 :847 < :871), so the DOM hand-off lands in the same task as the MutationObserver callback. |
| (4)/(5) | These are G2's; G2 is unchanged and pinned. |
| (6) | `glPooled` grows only at `atScene−1` while armed. `holdNoted` is bounded by key × via. No player names are used. The thresholds are 1.0 px (F4 + pin), 8 px (fixture pad 4.19–4.23), 2 px (mirrors :1351) and −0.5 (pin); all are traceable. |
| (7) | Nothing is evaluated on the flag-off path (item 5). |

**7. Tests.**
- The fail paths are forced, not grepped: real `standDowns` arrays, real hashes, real detaches, and `throwOnRead`
  forces a real `tryRemount` throw.
- The browser model is right on sloppy mode (`node -e`), `readyState` and `document.contains`.
- Harness fidelity:
  - the fixture's SUBTREE detach is not modelled (A8);
  - `querySelectorAll` ignores whether a node is connected;
  - `setTimeout` never runs (A12).
- 12 mutations were run. 8 survive: A7, A9, A10, A11.

---

## MAJOR

### A1 — MAJOR · NEW CLASS — `armed` suspends the retire zone's safety net for decoders pooled before the zone

**Evidence.**
- `sweepRetireZone` returns early for `armed`/`released` (:1259). Today that sweep is the only thing that retires a
  decoder pooled or remounted before the zone (docstring :1250).
- Row 10's sibling set is `glPooled` only (:668-670), and `retireZone` adds today's selection only on a transition
  (:548).
- `glCarried` candidates do not require `__obedGlPooled` (:569-575). A facade stub (whose `src`/`readyState`/`ended` are
  proxied, :1485-1507) is also a valid candidate.

**Probe (harness, SIBLING-geometry decoder detached at `#0`, then the normal flow).**
- At `#0` the decoder is pooled under pin and remounted synchronously: in document, `remounted: "1"`, playing.
- At `#1`, after `arm()`'s tick, it is still in document and playing. There is no `retire-boundary`.
- After `release` it is `handoff`, `retired: [sibling]`, and the early decoder is still in document and playing.
- The next `createElement('video').setAttribute('src', movie)` in `released` gives `reuse-decoder` with oldElId =
  **the early decoder**, not the carried one: the pool is FIFO (:1730-1740).

The literal retire on the same script gives `retire-boundary {elIds:[early]}` at `#1`, paused, detached, gen −1.

**Failure scenario.** Take a deck with a build on the source slide before the Magic Move. In the Keynote export every
build tears down the movie's layer: r1 armed-2 shows `preserve-on-detach-subtree` at every slide-2 build.
1. The movie is pooled and remounted at `atScene−2` under pin.
2. Under `glReplay` it keeps painting through `atScene−1`. Today's retire would retire it at the first in-zone tick.
3. If it or its facade stub is not the node the move detaches, it survives the hand-off. You then get a double movie, or
   the player's next element is facaded onto the wrong decoder.

On failure it is retired only at the transition, possibly a whole move later. The fixture does not reach this: r1
armed-2 has no stash before `#1`. That is why gates 4 and 6 are green.
`test_armed_remount_is_held_for_every_caller` (tests :2040) builds exactly this `early` decoder and never asserts its
state.

**Fix (exact).**
1. In `sweepRetireZone`, replace the `armed`/`released` early return with:
   `if (b === GL && zone === 'released') return; if (b === GL && zone === 'armed') { retireVictims(b, zoneVictims(b, []).filter(function(v) { return !v.__obedGlPooled; }), true); return; }`
2. In `releaseArmed`, build the sibling set as
   `zoneVictims(GL, glPooled.filter(function(x) { return x.__obedGen !== -1 && movieKeyFor(x, x.currentSrc || x.src || '') === GL.movieKey; })).filter(function(x) { return x !== v; })`.
   That is: every pooled or DOM-preserved decoder of the key except `v`.
3. In `glCarried`, add `|| !v.__obedGlPooled || v.__obedFacadeFor` to the candidate reject at :573.
4. Test (RED first): the probe above as a Node test. After `arm()`'s tick, `early` is paused, not in document and gen −1,
   and `retire-boundary` names it. After the hand-off, `reuse-decoder.oldElId === big`. Add a second test: a
   facade-stub-shaped candidate is never bound.
5. Plan text: §1 row 7 "armed: no retire" becomes "armed: today's sweep minus `__obedGlPooled`". K16's "siblings were
   retired at release" becomes "every in-zone same-asset decoder except the memo is retired at release".

### A2 — MAJOR · CLOSED CLASS (R2/R3/A3, measured worse than stated) — after a clean hand-off, `released` = pin brings back the footprint pop and the top-z append, and #5 settles misregistered

**Evidence (r1 `armed-2/result.json` `coreEvents`; the same pattern in `armed`).**
- At `7954` the hand-off is clean: `remount-into-authored-layer` at the slot (105.123, 790.847, 960, 276).
- `#3` (`11660`): `preserve-on-detach-subtree` for the carried elId 1, then `remount-footprint-rect {109,795,960,276}`.
  This is the source-footprint fallback. The detach-triggered `captureLayout` wrote `{0,0}` (:755 → :1591), and :1365
  picks the plan footprint by elId parity.
- `#4` (`14013`, `15015`, `15018`): the footprint fallback fires three more times. At `15017` `reuse-decoder oldElId 1`
  copies the player's instance-size style onto the carried decoder (:1768-1770). Its size snaps from 960×276 to
  951.5×267.6 mid-slide.
- `#5` (`16297`–`17697`): 20× `remount-done`, the TOP-Z stage append (:1435-1474) that row 9 exists to forbid at the
  hand-off. Both elId 1 and the facade stub elId 3 take it.
- `gates.json` gate4 `_report R3 (not gating)`:
  - `footprintFallbackAfterHandoff [1,1,1,1,3,1]`;
  - `remountDoneAfterHandoffBeforeScene6: 20`;
  - `carriedRectAt#5 {105.117, 790.849, 951.53, 267.61}` against `authoredInstanceScreen {109.352, 795.036, 951.54, 267.62}`.
- The video is therefore at the slot origin with the instance size. It is shifted −4.23 px in x and y against the
  poster, and it does not cover the poster's right and bottom 4.2 px strips.
- Pixels: a crop of `T5-tail.png` (armed and armed-2) shows the double edge, with the stripes overhanging the poster's
  top edge and a poster sliver on the left. `T5.counter` is `None` in both armed runs (T4: 199/202). T5 outside the
  movie rect is 0 against control, so no breach outside the rect.
- Gate 4's tail check passes because it only counts painting `<video>`s per scene.

**Failure scenario.** On the happy path of the fixture, every build after build 1 has:
- a ≈50 ms 4 px pop (R3);
- a mid-slide size snap at build 3 (R2 said "until the next cut");
- for the whole of scene 5 (≈1.4 s), a movie misregistered by 4 px against its own poster edge, placed by a top-z append.
  On a deck with authored artwork overlapping the movie, that append paints over the artwork (the Finding-2 class).

**Fix (exact).** Owner decision, because R2/R3 were accepted pending the gate-4 tail and the tail is blind to this.
- **(a)** Hand off at `toScreen(GL.instanceRect)` instead of G2's slot rect. The cost is one 4.2 px/edge shrink at
  build 1; after that the hand-off geometry, pin's copied style and `captureLayout` all agree.
- **(b)** Keep the slot rect and make the memo's geometry sticky in `released`:
  - in `stash` at :754-756: `} else if (!(zone === 'released' && v === carriedMemo)) { captureLayout(v); }`, so the last
    attached own box survives the detach;
  - in `tryRemount`, when `zone === 'released' && v === carriedMemo`, return before the stage append if `posterCanvas`
    is null. Never take :1435-1474 for the memo;
  - in the reuse branch (:1767-1771), skip `preserved.setAttribute('style', st)` when `preserved === carriedMemo`.
- **Either way**, add a gating tail check: at T5 (and T4), the carried `<video>`'s rendered rect matches the
  hand-off geometry within 0.5 px, and there is no `remount-done` or `remount-footprint-rect` for the memo's elId
  after the hand-off.

---

## MINOR

### A3 — MINOR · EDGE CASE — `armed` has no exit at or past `retireZoneEnd` once `armSeen`

**Evidence.** The armed branch of `zoneState` (:528-531) retires only on `moduleRetired` or `unengaged` (which needs
`!armSeen`). Outside the zone, `zoneMode` returns `allow` (:475).

**Probe.** The `_GL_PLAN` without its restart makes `retireZoneEnd` 8. Run `arm()`, `goLive()`, `goToScene(8)`, `tick()`,
then create a fresh movie `<video>`. The zone is still `[pending→armed]`, and `bridge-3to4` gives oldElId = the carried
decoder, in document and playing, while armed. With the restart at 6, `retire-on-start-movie` retires the armed pool
behind the zone's back, and no `glreplay-zone` note is written.

**Scenario.** G2 is LIVE or ARM-POST and has not yet seen `canvasRemoved` when the hash reaches the next flow. This is
unlikely on the fixture, where canvas removal precedes the hash change. The plan's claim that "out of the zone, armed
with decoders pooled is unreachable" is false for this case.

**Fix.** In `zoneState`'s armed branch, add a third arm:
`else if (hn != null && hn >= retireZoneEnd(GL)) retireZone('leftDestination');`.
Test: the probe above expects `['armed','retired','leftDestination','#8']` and `bridge-3to4` absent for the carried
elId.

### A4 — MINOR · EDGE CASE (K12 class) — a src clear on an ATTACHED `__obedGlPooled` node is swallowed

**Evidence.** `swallowClear` (:1629) holds on `__obedGlPooled` before looking at attachment. §2 row 4 says "an attached
element is never kept painting".

**Scenario.** The player re-inserts the same detached node while armed and then clears it. It keeps playing its movie
where raw and retire show it blank. This has not been observed: r1 gate 2 found 0 pooled nodes in document.

**Fix.** At :1629, use `if (v.__obedGlPooled && !document.contains(v)) {`. The attached case then falls through to
`noteRefused` and a real clear. For the carried decoder, G2 then hits `videoNotReady` → row 4 → retire, which fails
closed.

### A5 — MINOR · EDGE CASE (K12 class) — a detached move-scene clear is swallowed even when `stash` declines

**Evidence.** At :1633-1636, `stash(v, why); return true;` runs unconditionally. `stash` may return without pooling:
- `readyState < 2 && currentTime ≤ 0.05` (:735);
- a stale generation (:714);
- `__obedRemounting`, `__obedBridged34` or `__obedSuppressed34` (:705-713).

**Probe.** A detached node at `#1` with `readyState 1` and `currentTime 0` is cleared, then the zone retires
(`moduleRetired`). The node still has its src, and it is neither pooled nor glPooled, so nothing ever retires it. Today's
retire really clears it.

**Fix.** At :1634-1635, use `stash(v, why); if (v.__obedGlPooled) return true;`, falling through to `noteRefused(v, cur,
via); return false;`. Test: the probe expects `src === ''` and `preserve-refused/src-clear`.

### A6 — MINOR · EDGE CASE — a re-purposed armed-pooled node is still a victim and still a hand-off target

**Evidence.**
- `reidentify` (:440-457) drops pool membership and `data-obed-preserved`, but not `__obedGlPooled`, `glPooled` or
  `carriedMemo`.
- `retireZone` takes `[carriedMemo].concat(glPooled)` with no key check (:545-547). Row 10's sibling filter already
  checks the key (:668-670).
- Row 6 does not check the key (:660).

**Probe.** `ctx.sib.src = '…/WA0125.mov'`, re-attach, then `moduleRetired`. The sibling, now movie2, is paused, removed
from the DOM and set to gen −1.

**Fix.**
- In `retireZone`, filter the memo/glPooled list with
  `movieKeyFor(v, v.currentSrc || v.src || '') === GL.movieKey`.
- In `reidentify`, when `prev !== next`, add
  `v.__obedGlPooled = false; const gi = glPooled.indexOf(v); if (gi >= 0) glPooled.splice(gi, 1); if (carriedMemo === v) carriedMemo = null;`.
- In row 6, add `|| movieKeyFor(v, v.currentSrc || v.src || '') !== GL.movieKey` to the `noCarried` condition.

### A7 — MINOR · NEW CLASS (test gap) — the candidate guards and the memo victim are untested

**Evidence.** Mutations applied to `PRESERVE_CORE_JS` in-process. All of these leave `test_live_continuity_js.py`
green (289 passed):

| Mutation | Code |
|---|---|
| drop `document.contains(v)` from the candidate reject | :571 |
| drop `obedRemounted === '1'` | :573 |
| drop `v.ended` | :573 |
| drop `isLive(v)` | :573 |
| drop `carriedMemo` from the `retireZone` victims | :545 |
| drop the stash attached-branch authored capture | :752-753 |

**Fix.** Add a parametrised `carried` test. In each case the only rect-matching decoder is made ineligible, and the answer
must be `notPooled`:
- (i) it is attached (in document);
- (ii) `ended = true`;
- (iii) `__obedGen = preserveGeneration − 1`, forced by setting `__obedGen = -2` before `S.carried`;
- (iv) `dataset.obedRemounted = '1'`;
- (v) with A1: `__obedGlPooled` false (pre-zone), and a facade stub.

Add one case where the memo is not in `glPooled` (after A1(3) this is unreachable: assert it). Also either assert the
stash attached-branch capture (a detached-at-`#0` stash from an attached `src=''` under `allow`), or delete it: the
interval's `i === 0` capture already covers it.

### A8 — MINOR · CLOSED CLASS (F13/K17 harness fidelity) — the fixture's subtree detach is not modelled

**Evidence.** r1 armed-2 shows the carried and sibling decoders arriving via `preserve-on-detach-subtree`. The node's
`parentNode`/`parentElement` stay the DETACHED layer, so stash :763-767 sets `__obedParent`/`__obedLayer`. That is the
K6 case row 10's `__obedParent = null` guards.

The harness's `playerDetach` (tests :1773) nulls `v.parentNode`, so `__obedParent` is never set. The
`parentGuard is None` assertion (tests :2306) passes because the key is `undefined` and gets dropped: deleting
:673 fails only with `KeyError: 'parentGuard'`.

**Fix.**
- Add `playerDetachSubtree(v)`: give `v` a parent layer with a zero box, set
  `v.parentNode = v.parentElement = layer`, then null `layer.parentNode` and fire the MutationObserver with
  `removedNodes: [layer]` plus `layer.querySelectorAll('video') → [v]`.
- Use it in `arm()`.
- Assert `ctx.big.__obedParent === layer` before `release` and `=== null` after.

---

## NIT

### A9 — NIT · EDGE CASE — `disable()` before the first consult leaves a non-terminal `armed` zone

Probe: `P.disable(); S.carried('movie1')` gives `[pending→armed moduleReady]` and nothing more. The interval no longer
runs (:1605), so neither watchdog ever fires. G6 would count an armed zone that never ends.

Fix: as the first line of `zoneState` after `if (!GL)`, add
`if (disabled && zone !== 'retired') { retireZone('disabled'); return zone; }`.

### A10 — NIT · EDGE CASE — `nearZero` in `handbackRectOk` is untested and effectively dead

At identity, `nearStageOrigin` implies it. At a letterboxed stage, it needs a negative authored `y`, which containment
of `instanceRect` rules out. The E-mutation survives. Keep it (it mirrors :1351), but say so in the test docstring, or
drop it.

### A11 — NIT · EDGE CASE — the `decided` catch branch (:640-643) is untested

It is reached only when `retire()` throws after `setZone('retired')`. In that case the victims may be only partly retired.

Fix: in that branch also run
`retireVictims(GL, [carriedMemo].concat(glPooled).filter(function(v) { return v && v.__obedGen !== -1; }), true);`,
and force it in a test by making `retireDecoder`'s `dataset` access throw once.

### A12 — NIT · CLOSED CLASS (harness) — two more places where the fake DOM differs from a browser

- `querySelectorAll('video[data-obed-preserved="1"]')` returns DETACHED nodes (tests :731-735). A browser returns only
  connected nodes.
- `setTimeout` is a no-op (:781), so `beginMove`'s `__obedRemounting` reset never runs.

No current assertion depends on either. Model connectivity in the selector filter (`document.contains(v)`) so that
future `zoneVictims` tests cannot pass on a detached node.

### A13 — NIT · CLOSED CLASS (K20) — the `bindFacade` swap observer has no liveness check, and is now reachable in `released`

r1 armed-2: at `#4`, `reuse-decoder oldElId 1` facades stub elId 3 onto the carried decoder. The stub is then pooled and
remounted (`remount-done` elId 3 at `#5`). The optional gate from plan §1 still applies at :1512:
`if (stub.parentNode && real !== stub && real.__obedGen === preserveGeneration && real.__obedRemountEpoch !== -1)`.

---

## Verified clean (no finding)

- **K1:** there is no bridge damage from an out-of-zone retire. The `goto3walk` r1 arm gives `release notArmed` at `#7`,
  and `bridge-3to4 oldElId 3` at `#8`.
- **K2 / 4b, K13, K14, K15 and K17** are all implemented and forced in tests.
- **G2 contract pins** in `tests/test_live_gl_replay_js.py`:
  - :2309: the last stand-down is the reason, and the state is `STANDDOWN` at release;
  - the `writebackFailed` ordering;
  - :2329: arm on `atScene−1`, then live.

  All three drive the real module.
- **The retire family on a flag-on plan** (tests :2884) re-runs the pre-existing tests unedited through a monkeypatched
  `_run_retire`, and asserts exactly one `pending→retired` note.
- **Row order** 1→10 matches §2, and the landing check is real (`misplace` is forced).
- **Letterbox mapping** is correct at s = 0.8333 and oy 50, in the harness and in gate 4b.
