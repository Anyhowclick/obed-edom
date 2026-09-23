# GL-replay G3 + G4 plan — real seam in the core, host flag (one PR)

Status: **rev 2 (Opus EXTRA HIGH critique of §1–§2, 2026-09-23)** — supersedes rev 1 (Opus MAX planner, same day). Spec:
`.agents/handovers/keynote-live-continuity-2026-09-22-g3.md`. Parents: `keynote_live_gl_replay_g2.plan.md` rev 2 (§2.0, §2.5, **§2.6
seam**, §2.7, §4), `keynote_live_gl_replay_arming.plan.md` (§2, §3, §5, §10, §11). Owner go 2026-09-23 (OD-1..3 defaults taken). Next step:
implement per §5. Code cites are `9ad4fc69` (`live_continuity_js.py` unless another file is named; G2 = `live_gl_replay_js.py`).

## Critique table (rev 1 → verdict)

Scope: §1 zone semantics, §2 seam and instance selection, the `release` table, OD-1, F8. No headless run was needed; every
verdict is from code at `9ad4fc69` or the archived r5 results (`output/live-visible-content/g2/r5/*/result.json`).

| # | Rev-1 claim | Verdict | Evidence |
|---|---|---|---|
| K1 | §1: watchdogs run in "the sweep"; permissions change only "hn in the zone. Otherwise both are true, as today"; every → `retired` "retires every decoder of `movieKey`" | **BLOCKER** (applied §1) | The sweep returns at :1017 outside `[atScene−1, retireZoneEnd)`. Host goTo slide 3 from slide 1 jumps hash 1 → 6, and a go-to is DOM-painted, so no `glreplay-arm` fires. `unengaged` is therefore never evaluated and the zone stays `armed`. G2's ARM-PRE is sticky: `poll` never leaves it on a hash change (G2 :1126-1154). The 3→4 Magic Move arms G2 (R5), and G2 then stands down (`assetUnbound`, or `sceneMismatch` at settle) and calls `release` at hash 7 while G3 is still armed. Rows 4 and 5 then retire "every decoder of movieKey". That includes the slide-3 decoder that `stash` → `tryRemount` → `keepThroughBridge` is holding for the bridge (:543-545, :575, :1057, :654-708), because that decoder is still pooled and `data-obed-preserved` (:508-512), which is what both sweep selectors take (:1024-1030). Result: the qualified 3→4 bridge dies and slide 4 restarts from 0. |
| K2 | §2 row 4: only a primary ≠ `canvasRemoved` retires; `canvasRemoved` always hands off | **BLOCKER** (applied §2 row 4b) | G2's observer stands down `canvasRemoved` in ANY phase once `state.canvas` is set (G2 :1071), so also from ARM-PRE and ARM-POST. G2 has no stand-down reason for "never settled". A G2 that never went LIVE would therefore hand off at build 1: the movie jumps from a static poster to live, which neither retire nor the measured flow produces. Forced `canvasRemoved` is also pre-LIVE: it fires in the first `tickOnce` (G2 :1061), before `publishHandle` (:1062). In r5 `fail-canvasRemoved` the hand-off was at 3833 ms on `#1`, with no `glreplay-live`. |
| K3 | F3: "`captureLayout`'s parent walk and style fallback overwrite it with the removed parent's origin (:1310-1339)" | **corrected** | The overwrite comes from the detach-triggered `stash` → `captureLayout` (:519-520). The interval only visits in-document videos (:1350). The written origin is (0,0) because a detached node or parent has an all-zero box (`pr.left \|\| 0`, :1331-1335). The rule is unchanged. |
| K4 | F5: "The plan's source-instance rect is `instanceRect`" | **corrected (label)** | `instanceRect` is the DESTINATION instance (`live_continuity.py:803-817`, `_destination_instance(slide_instances[to_player_index], dst_rect)`). The source is within 0.5 px of it by pin, so 1.0 px = 0.5 (pin) + 0.012 (F4) + margin, and the number is right. Pin forbids two source instances with equal geometry: two would give ≥ 2 geometry-equal pairs, which is `_Refuse` (:1267-1275). A second source instance 0.5–1.0 px off is still possible; it answers `ambiguous` and the zone retires. |
| K5 | F6: "`release` … is called on every stand-down" | **corrected** | `release` runs only when `state.seam` was captured (G2 :870). It never runs from `refuseInstall` (:165-171) or on a `runtimeSeamAbsent` stand-down. Every r5 forced reason fired on hash `#1`, including the four LIVE-phase ones, because `debugForceFail` is read at the first tick (:1061) and by the wrapper during the move (:285-286). The push order is confirmed: `writebackFailed` :858, primary :859, `release` :871. |
| K6 | §2 row 10: `__obedParent = null` stops "the source-parent branch (:1058-1094, the ≈4 px pop)" | **corrected** | On the fixture `__obedParent` is the detached source parent, and `document.contains` is false, so that branch cannot fire. The pop comes from the footprint fallback (:1098-1118), reached because the detach capture left `__obedRect` at {0,0,…}. The r5 fail arms show it: `remount-footprint-rect` {109,795,960,276}. Setting `__obedRect = toScreen(rect)` prevents the pop; the null stays only as a guard. |
| K7 | §1: "The moment a zone becomes `retired`, the page is exactly today's retire" | **corrected (overclaim)** | Decoders pooled while armed keep their src, because no clear ever ran on them. They are retired by pause + detach (`retireDecoder` :998-1008), which is what today's sweep does to a decoder pooled before the zone. `retire-boundary` is noted only when there are victims (:1031). |
| K8 | F8 (r5 gate-6 parity = P2c green ROI only; 17/19 live after build 1) | **confirmed, extended** | In r5 after build 1, 17 arms show the counter decoded at P3/P4, 1 painting `<video>` and 11 `remount-*`. That is every arm except `planUnreadable`, `glReplayUnavailable` (install refusals, no seam call) and `writebackFailed` (a natural hand-off on `#2`). The control shows None/0/0. All 17 stub releases ran on `#1`. `posterAmbiguous` and `sceneMismatch` already had a decoded counter at P2c (108, 112) and still passed, because `analyse_r5.py:117-141` compares only `greenRoiMean` at P2c. |
| K9 | §6 gate 6 "forced `canvasRemoved` … equal the **armed** arm"; R4 "hands off mid-dwell" | **corrected** | Forced `canvasRemoved` is pre-LIVE on `#1` (K2), so rows 4b and 5 retire it and it equals the CONTROL. Only `writebackFailed` (with the natural `canvasRemoved` on `#2`) equals the armed arm. |
| K10 | §6 Q3: "r5 `q3b` handed off; this changes by design" | **corrected** | `q3b` never handed off. The 46.03 s clip had ended (`videoEnded: true`, pool `ended: true`), so `tryRemount` returned at :1056, and nothing painted after build 1. After-build == control already; only the notes change. |
| K11 | OD-1: the plans conflict | **confirmed** | Arming §3 (lines 76-85): LIVE guards ⇒ STANDDOWN ⇒ "hand the pooled decoder to the existing remount path". The other side: arming §2 (line 44) "each failure ⇒ stand down to `retire`"; §5 (116-118) says the fail-closed arm equals the retire artifacts; D4 was accepted (207-208, 218); and G2 §4(6) (line 109) agrees. Addition: the forced gate-6 arms cannot exercise OD-1 (K5); only Q3 and the new late-forced arms (§6) can. |
| K12 | §1 rows 4/5 armed: "move scene: stash + swallow; else real clear" | **GAP** (applied) | (a) At `hn = atScene−1`, an ATTACHED element's clear would be swallowed and `stash` would `play()` it (:539-542) where the player wanted it blank. That is a paint while armed. The fixture never clears src (r5 has 0 `preserve-skip-*` notes). (b) At `hn = atScene`, a real clear on the already-pooled carried decoder kills G2's source while LIVE. `perLiveUpload` silently skips `readyState < 2` (G2 :977-978), so there is no stand-down, and `release` would hand off an empty `<video>`. |
| K13 | `release` and watchdog robustness | **GAP** (applied) | A `release` during `pending` answered `notArmed`, and the zone could still arm later. A throw inside `release` left the zone `armed` with "release called", so the `moduleRetired` watchdog as worded ("release never called") never fired. |
| K14 | Call-site row 10: `clear()` "unchanged" | **GAP** (applied) | `pool.clear()` drops pooled decoders without pausing them (:115). After a host go-to that lands inside the zone, `released` would keep pin semantics for decoders that have nothing to do with the hand-off, and go-to is never armed (arming §1). |
| K15 | `note()` passes every `glreplay-*` kind | **GAP** (applied) | G2 could forge G3's own `glreplay-zone`/`-carried`/`-release`/`-hold`, which are the notes G6 will count. |
| K16 | `released` sweep "retire every decoder except the kept one" | **GAP** (applied) | Siblings are already retired at release (row 10). Keeping this sweep deviates from pin for any later decoder of the asset pooled on builds 2–4, which is what the gate-4 tail (A3) measures. |
| K17 | `pending` resolution: `readyState` gate and injection order | **confirmed** | The parser-inserted inline scripts (plan < core < `obed-gl-replay`) all run before `readyState` leaves `loading`, and the first in-zone stash is the 1→2 move, long after load. A consult during `loading` stays pending, which is retire-class and fails closed. The Node fake DOM has no `document.readyState` (0 hits in `tests/test_live_continuity_js.py`), so `undefined !== 'loading'` would resolve at install. The tests must model it (§5). |
| K18 | Selection: letterbox, ancestor transforms, sub-pixel, A4, equal geometry | **confirmed** | F4 is measured at s = 1 and s = 0.8333 (oy 50). `getBoundingClientRect` includes ancestor transforms. LayoutUnit rounding (1/64 screen px) is ≤ 0.02 authored px at s ≥ 0.8. A rotated or mid-animation capture fails closed (`ambiguous`). With K12 the armed attached-stash branch never runs, so `captureLayout` iteration 0 in the 200 ms interval is the only armed capture source (A4 unchanged). |
| K19 | Row 7: IoU ≥ 0.9 | **NIT** (applied) | This checks two plan constants and is traceable only to the fixture (0.961). The fixture texture pad is 4.19–4.23 px/edge; the same pad drops IoU below 0.9 for movies under ≈ 200×100. It is replaced by containment plus a margin, and a near-origin guard is added so the footprint fallback (:1098-1118) can never engage. |
| K20 | Deferred closures | **NIT** (noted §1) | The `bindFacade` swap observer (:1258-1281) has no liveness check. A facade bound in `released` whose stub is inserted after a retire would re-insert and `play()` a retired decoder. Today's pin has the same exposure. |

## 0. Facts relied on

**Measured for this plan.** One headless session (`output/live-visible-content/g3-planner/rects.log`, product host, continuity
`auto`, no GL module, fixture `output/p2-recovery/html-adversarial`; no other headless Chrome; `uptime` 8:54 load 13.49 before,
12.86 after; < 60 s, two viewports in sequence). At rest on slide 1 (`location.hash == "#1"`), each attached `<video>`'s own
`getBoundingClientRect()` mapped by the stage map to authored px:

| Viewport (stage s, ox, oy) | big instance (elId 1) | sibling (elId 2) |
|---|---|---|
| 1920×1080 (1, 0, 0) | 109.3517, 795.0362, 951.5313, 267.6094 | 1075.7865, 876.2469, 662.7813, 186.4063 |
| 1600×1000 (0.8333, 0, 50) | 109.3517, 795.0362, 951.5312, 267.6094 | 1075.7865, 876.2469, 662.7812, 186.4063 |

The plan's `instanceRect` is 109.3517, 795.0362, 951.5430, 267.6215: the largest per-edge difference is **0.012 px**, the sibling
is 966 px off. The keep-warm `captureLayout` had written this same attached rect into `__obedRect` (screen px) at both viewports.
Continuity at v4 reported `sha256 68262ab8…`. Focused suites at `9ad4fc69`: 1238 passed, 1 skipped (see F15).

| # | Fact | Source |
|---|---|---|
| F1 | One predicate `preserveAllowedFor` decides pooling AND mounting. Only a literal `retire` opens a zone. The zone is `[atScene−1, next restart/bridge)`. | `live_continuity_js.py:358-361, 383-387, 391-399, 404-408, 443-447` |
| F2 | `preserveAllowedFor` has six call sites: `stash` :502, `scheduleRemount` :557, `tryRemount` :1048, src setter :1376, `removeAttribute` :1396, `createElement` src hook :1428. The sweep :1015-1043 runs from the 200 ms interval :1347-1361. That interval also `play()`s every paused pooled decoder (:1351-1360). | code |
| F3 | `__obedRect` is screen px (:516-518). The detach-triggered `stash` finds a zero own box and calls `captureLayout` (:519-520). Its parent walk and style fallback then write `{x:0,y:0}`, because a detached node or parent has an all-zero box (`pr.left \|\| 0`, :1331-1335), plus the style size × s. The 200 ms interval re-captures only in-document videos (:1350). In the r5 `pooledRects`, both pooled decoders read `{x:0,y:0}` with sizes 951.543×267.621 and 662.794×186.411. (rev 2, K3) | code; `g2/r5/armed/result.json` |
| F4 | The attached own box, mapped to authored px, equals `instanceRect` within 0.012 px at s=1 and at s=0.8333 (letterboxed). | measured above |
| F5 | `instanceRect` is the DESTINATION instance's rect (`live_continuity.py:803-817`). Under pin the carried source instance is within 0.5 px of it, so it is also the source-instance rect to within 0.5 px (rev 2, K4). `glReplay` requires `pin` (`live_continuity.py:1296-1299`). `pin` means `src.close_to(dst)` within 0.5 px (:31, :652-658, :1265-1266), and a multi-instance asset needs exactly one geometry-equal pair (:1267-1275). On the fixture, `src_rect == dst_rect` byte-exact (measured). **No new plan field is needed.** | code, measured |
| F6 | How G2 uses the seam. It reads the seam at every ARM-PRE preflight and checks `version !== 1` (`live_gl_replay_js.py:1093-1105`). It calls `carried()` at the first per-clear upload (:412-420). `setKeepWarm` runs on pause/resume (:902-916) and at stand-down (:860-866). It never calls `movieKeyOf`. `release(movieKey,{rect: slotRects[movieSlot]})` takes **authored** px. It is called on every stand-down where `state.seam` was captured (:870), so never from `refuseInstall` and never on `runtimeSeamAbsent`. It is called **after** `API.standDowns.push(reason)` (:858-859 vs :869-873), and G2 sets `state='RETIRED'` only after `release` returns (:884). `canvasRemoved` is emitted in any phase once `state.canvas` is set (:1071), including before LIVE (rev 2, K2/K5). `window.__OBED_GL_REPLAY__` is published before the entry is validated (:130-131). Install refusals set `state='RETIRED'` without a seam (:165-171). `glreplay-arm` fires when the context is armed, while the hash is still `atScene−1` (:1123, :1129-1134). | code |
| F7 | r5 armed order: stash on detach at 2157 ms, then `glreplay-arm` 2163, `glreplay-live` 3813, hand-off 7464. The hand-off was `remount-into-authored-layer` into canvas `935F…` at screen (105.11, 790.86, 960, 276). | `g2/r5/armed/result.json` |
| F8 | **r5 gate 6 compared only the P2c green ROI** (`g2/analyse_r5.py:117-141`). After build 1, 17 of 19 forced-failure arms were LIVE (counter decoded, 1 painting `<video>`, 11 `remount-*`), while the control showed a static poster (counter None, 0 painting). The cause: the stub's `release` always remounted (`g2/stub.py:102-128`). Only `planUnreadable` and `glReplayUnavailable` matched the control. Every forced reason fired on hash `#1`, before the flip. `posterAmbiguous` and `sceneMismatch` were already live at P2c (counter 108, 112) (rev 2, K8). | r5 results |
| F9 | Hand-off (Q0b). The player creates no `<video>` at build 1, so the hand-off goes `tryRemount` → `remount-into-authored-layer`. Remounting both same-asset decoders gives a double grating. Remounting at the source footprint gives a ≈4 px pop. | `keynote_live_alternatives_research.md:295-307`; arming §10 |
| F10 | Allowlist = {`bafe26…` flag-off, `6a0596…` flag-on}; both re-derive byte-exact today (measured). The P2 injected plan is the retire shape (`p2_verdict.py:432-470`), pinned equal to `EXPECTED_RUNTIME_PLAN` (`test_p2_adversarial.py:3269-3283`). The P2 script consumes the builder and verdict verbatim (`p2_recovery_html_adversarial.py:2862, 3487-3518`), so no script change is needed. | code, measured |
| F11 | Host facts. Body injection order is overlay + `continuity_script` + fit (`live_host.py:428`). `_continuity_scripts` = plan + core (:80-81). The env-off check is at :816. The env-fallback `_UNSET` pattern is at :750-751. `goTo` calls `clear()` first when qualified (:1197-1199). The output key-set test is at `test_live_host.py:1325`. The inactive-continuity HTML sha pins are at `test_live_host.py:1464-1484`. | code |
| F12 | The core has no pinned js-sha literal: its test recomputes the sha (`test_live_continuity_js.py:28-32`). The version literal is at :24. The in-page `__OBED_P2_PRESERVE__.version: 8` (:82) has no reader (grep of `scripts/ src/ tests/`). | code |
| F13 | The core's Node harnesses concatenate the core into a non-strict preamble, so it runs in sloppy mode (`test_live_continuity_js.py:640-805`). G2 uses `new Function` for the same reason (`test_live_gl_replay_js.py:950-966`). | code |
| F14 | `scripts/run_gates.sh` runs the host probe at 2560×1440, 1600×1000 and 1920×1080 (the DEFAULT path), then P2 fast, fast + `--disable-bridge34`, and slow. The `gate-runner` worktree in memory no longer exists (`git worktree list`). | code |
| F15 | `test_real_export_matches_trimmed_fixture_plan` skips everywhere: `REAL_EXPORT_ROOT` is hard-coded to a removed worktree (`test_live_continuity.py:25-28, 353`). This is out of scope and flagged separately. | measured |
| F16 | The web layer passes only `continuity` (`web/live.py:30, 132`). The dashboard's `LiveContinuity` type tolerates extra fields (`dashboard/src/live/api.ts:8`). | code |

**Assumptions (unverified).** Each one fails closed to retire.
- A1: stash-before-first-`clear` (F7) also holds in OBS CEF. If it does not, `carried` returns `notPooled`, G2 stands down `assetUnbound`, and the zone retires.
- A2: the destination poster canvas exists when G2's MutationObserver callback runs at build 1. This held in Q0b and r5. If it does not, the pre-check fails and the zone retires.
- A3: the pin path survives slide-2 builds 2–4 after the hand-off. The gate 4 tail measures this.
- A4: show→advance faster than 200 ms leaves no authored rect, so selection answers `unmeasured` and the zone retires.

## 1. G3 zone semantics (`live_continuity_js.py`)

**The retire-class boundary `b`** is the lowest-`atScene` entry whose action is `retire` or `glReplay` (`to_runtime` emits at most one, `live_continuity.py:780-781`). `retireZoneEnd`/`inRetireZone` keep their logic and take `b`. A literal `retire` behaves byte-for-byte as today. A `glReplay` `b` runs a per-session state machine:

`pending → armed | retired` · `armed → released | retired` · `released → retired`. `retired` is terminal. There is no re-arm, matching G2's one-shot life (G2 §2.5).

**Evaluation (rev 2, K1).** One function, `zoneState()`, owns every transition below except `release`'s own. It is evaluated
**synchronously** at three points, and never only in the sweep:
- the top of each of the six permission checks (F2);
- every interval tick, **before** the `inRetireZone` early return at :1017;
- every seam member.

As a result, no transition waits up to 200 ms, and none depends on `hn` being inside the zone. `release` evaluates it too, with the
`moduleRetired` watchdog excluded: G2 is in `STANDDOWN` during `release`, and sets `RETIRED` only after `release` returns (G2 :884).

G3 records two facts from the kinds G2 passes through `note()` (§2), and does not read `__OBED_GL_REPLAY__.events`:
- **`armSeen`**: a `glreplay-arm` received while `hn === atScene − 1`;
- **`liveSeen`**: a `glreplay-live` received.

| Transition | Trigger (evaluated in order) | `glreplay-zone` reason |
|---|---|---|
| pending → retired | first evaluation with `document.readyState !== 'loading'`: `b.fallback !== 'retire'`, `movieKey ∉ movies`, or `instanceRect` not four finite numbers with w,h > 0 | `entryInvalid` |
| pending → retired | `window.__OBED_GL_REPLAY__` absent / `.version !== 1` / `.state === 'RETIRED'` | `moduleAbsent` / `moduleVersion` / `moduleRetired` |
| pending → armed | otherwise | `moduleReady` |
| armed → retired | G2 `state === 'RETIRED'` while the zone is still armed, **whether or not `release` was ever called** (never called, or it threw) | `moduleRetired` |
| armed → retired | `hn ≥ atScene` (ANY such `hn`, including past `retireZoneEnd`) and not `armSeen`. The normal flow arms at `hn = atScene−1` (F6/F7). A go-to, a non-WebGL move, or G2's sticky ARM-PRE arming on a LATER move (R5, K1) never sets it. | `unengaged` |
| armed / released → retired | `clear()` (host goTo, F11: go-to is never armed, arming §1) | `cleared` |
| armed → released / retired | `release()`, §2 | `handoff` / per §2 |
| released → retired | `hn < atScene` | `leftDestination` |

`pending` behaves retire-class.

**Transition sweep (rev 2, K1/K7).** Every transition to `retired` runs synchronously and does three things:
- It retires the memoised carried decoder (any generation) and every decoder stamped `__obedGlPooled` (pooled while armed, row 1). This applies at any `hn`.
- Only when `hn` is inside `[atScene−1, retireZoneEnd)` does it also run today's sweep body: pool by key, plus DOM-preserved. Out of the zone it never touches a decoder that was pooled under pin, bridge or restart. This protects the 3→4 bridge decoder (K1).
- It notes `retire-boundary` only when there were victims, as today (:1031).

From then on the in-zone 200 ms sweep is today's. Decoders pooled while armed keep their src and end paused and detached (`retireDecoder` :998-1008), which is what today's sweep does to a decoder pooled before the zone. Every decoder that was never pooled while armed sees exactly today's retire.

**Permissions** (`v` of `b.movieKey`, `hn` in the zone; otherwise both are true, as today, and `zoneState()` still runs first). Out of
the zone, an `armed` or `released` state with decoders pooled under it is unreachable: `unengaged`, `leftDestination` and
`cleared` fire at the first consult.

| State | `poolAllowedFor` | `mountAllowedFor` |
|---|---|---|
| literal retire · pending · retired | false | false |
| armed | `hn === atScene − 1` **and** `!v.isConnected` (the move scene; the element is already detached) | false |
| released | true (pin) | true (pin) |

Notes:
- Retire-class refusals keep `preserve-refused` via `noteRefused` (:448-454).
- An armed hold notes **`glreplay-hold {key, via}`** once per key and via. It is never `preserve-refused`, so G6 can tell a hold from a refusal.

**Call-site table** (DOM decisions: pending/retired = retire-class; armed = pool-but-never-mount, never-paint):

| # | Site | Today (retire zone) | pending / retired | armed | released |
|---|---|---|---|---|---|
| 1 | `stash` :502 (pool, rect capture :515-533, play :539-542) | decline, `preserve-refused/stash` | same | pool iff `hn==atScene−1 && !v.isConnected` and stamp `v.__obedGlPooled`; else decline | pool |
| 2 | `stash` → `scheduleRemount` :543-545, check :557 | refused | same | refused → `glreplay-hold/remount`, no epoch, no timers | allowed |
| 3 | `tryRemount` :1048 (also `remountAll` :94-107, every timer :575-585, `onHash` :582-586 — timers created before a transition are gated when they fire) | refused | same | refused → `glreplay-hold/remount` | allowed (release sets `released` before its own call) |
| 4 | src setter :1376 | real clear | same | **(rev 2, K12)** already `__obedGlPooled` → swallow + `glreplay-hold/src-clear`, at any in-zone `hn`; else `hn==atScene−1 && !this.isConnected` → stash + swallow (arming §3); else real clear, `preserve-refused/src-clear` (an attached element is never kept painting) | swallow |
| 5 | `removeAttribute` :1396 | real remove | same | as #4 (`via: removeAttribute`) | swallow |
| 6 | `createElement` src hook :1428 (reuse/facade :1453-1501) | raw | same | raw `origSA`, **pool untouched**, `glreplay-hold/reuse` | pin (reuses the kept decoder) |
| 7 | sweep :1015-1043 | retire key, `retire-boundary` | same | no retire (transitions live in `zoneState()`, which runs first) | no retire: pin (K16; siblings were retired at release) |
| 8 | keep-warm :1351-1360 | play all pooled | same | skip `v.__obedGlNoWarm` | same (flag cleared at release) |
| 9 | `captureLayout` :1312-1318, `stash` :516-518 | `__obedRect` | + `__obedAuthoredRect` (§2), only when the plan has a `glReplay` entry | same | same |
| 10 | `clear()` :108-132 | bump gen, drop pool | unchanged for pending/retired. armed/released → retired `cleared` after the pool drop; the transition sweep pauses the memo and `__obedGlPooled` decoders that `pool.clear()` (:115) dropped without pausing (K14) | | |
| 11 | `disable()` :87-93, `keepAtFootprint` :603-633, `snapshot`, `footprintOwnerDecoderId` | — | unchanged; seam answers `disabled` (reachable only before any stash, :88); the census lists the pooled carried decoder (G6 re-scopes) | | |

NIT (K20, optional, not a gate): the `bindFacade` swap observer (:1258-1281) has no liveness check. Consider gating the swap on
`real.__obedGen === preserveGeneration && real.__obedRemountEpoch !== -1`. It is reachable only when a facade bound in
`released` gets its stub inserted after a retire. Today's pin has the same exposure.

## 2. The seam (G2 §2.6, exactly)

It is installed on `window.__OBED_P2_PRESERVE__.glReplay` **only when the plan has a `glReplay` entry**, so flag-off plans keep today's object shape. The object carries exactly these members; a test asserts the key set.

| Member | Behaviour |
|---|---|
| `version` | `1` |
| `carried(movieKey)` | → `{video, reason}`. Runs `zoneState()` first, which resolves `pending`. Reasons: `disabled`, `notArmed` (state ≠ armed or key ≠ `b.movieKey`), `notPooled`, `unmeasured`, `ambiguous`. On success it memoises the video, stamps `v.__obedGlCarried`, and notes `glreplay-carried {elId, delta, candidates:[{elId, rect}]}` once. |
| `movieKeyOf(v)` | `movieKeyFor(v, v.currentSrc‖v.src)` (:413-415) |
| `setKeepWarm(v, on)` | Honoured only when `v` is the memoised carried decoder: `v.__obedGlNoWarm = !on`. Other calls are no-ops. |
| `release(movieKey, {rect})` | Decision table below. Returns `{ok, reason, mode:'handoff'|'retire'|null, elId, retired:[elIds]}`. **Exception-safe (K13):** the whole body is in `try`. Any throw after row 3 → retired `releaseError`, returning `{ok:true, mode:'retire', reason:'releaseError'}`. |
| `note(kind, detail)` | **(K15)** Passes only G2's closed kinds to the core `note()` (:463-467): `glreplay-arm`, `-live`, `-standdown`, `-handoff`, `-opacity-unproven`, `-retained-frame`. Every other kind is ignored, including G3's own `glreplay-zone`/`-carried`/`-release`/`-hold`, so G2 can never forge a note G6 counts. `glreplay-arm` and `glreplay-live` also set `armSeen` and `liveSeen` (§1). |

**Instance selection (the rule the stub approximated).**
- **Capture.** `__obedAuthoredRect` is written only from the element's OWN attached, non-zero box: the `stash` attached branch (:516-518) and `captureLayout` iteration 0 (:1312-1318). The box is mapped `{(l−ox)/s, (t−oy)/s, w/s, h/s}` via `stageMap()`. A null `stageMap()` writes nothing, a parent-walk or style fallback never writes it, and a zero box never overwrites it (F3). Under armed, row 1 pools only detached elements, so iteration 0 of the 200 ms interval (:1350) is the only armed source (K18). That is why A4 answers `unmeasured`.
- **Candidates.** Pooled, not-in-document decoders with `movieKeyFor === movieKey`, `__obedGen === preserveGeneration`, `!ended`, not remounted.
- **Match.** `|Δx|, |Δy|, |Δw|, |Δh| ≤ 1.0` authored px against `entry.instanceRect` (the destination instance; the carried source is within 0.5 px of it by pin, K4). The tolerance is the measured 0.012 px (F4) plus the 0.5 px pin tolerance. The fixture sibling is 966 px off.
- **Outcome.** Exactly one match returns the video. No candidate with a captured rect returns `unmeasured`. Zero or two-plus matches return `ambiguous`. A candidate without a captured rect never binds, and never blocks a unique measured match.
- **No fallback.** There is no size-only fallback and no "only candidate wins", so a lone sibling never binds.

**`release` (runs `zoneState()` first, without the `moduleRetired` watchdog, §1; checked in order; the first hit decides; checks 1–3 have no side effects):**

| # | Condition | Result |
|---|---|---|
| 1 | `disabled` | `{ok:false, reason:'disabled'}` |
| 2 | no `glReplay` entry or `movieKey ≠ b.movieKey` | `{ok:false, 'unknownMovie'}` |
| 3 | state ≠ armed (a **second call**, watchdog-retired, `cleared`, already released) | `{ok:false, 'notArmed'}` |
| 4 | G2's primary stand-down ≠ `canvasRemoved`. The primary is the last element of `__OBED_GL_REPLAY__.standDowns`, because `writebackFailed` is pushed first (F6); unreadable counts as failure. | → retired `failure` (+`standDown`); `{ok:true, mode:'retire'}`. Default of OD-1. |
| 4b | **(rev 2, K2)** not `liveSeen`: G2 never reached LIVE, so this `canvasRemoved` is not the normal exit. Examples: forced `canvasRemoved` at the first tick, or a canvas removed while G2 waited in ARM-PRE. | → retired `notLive` |
| 5 | `hn ∉ [atScene, retireZoneEnd(b))` (go-to off the destination during LIVE) | → retired `notOnDestination` |
| 6 | no live carried decoder: the memo is absent or stale (`__obedGen ≠ preserveGeneration`), `ended`, `readyState < 2`, or has neither `currentSrc` nor `src` (K12(b)) | → retired `noCarried` / `ended` |
| 7 | **(K19)** `rect` is not four finite numbers with w,h > 1; or it does not contain `instanceRect` (±0.5 px) with every edge margin ≤ 8 authored px (fixture 4.19–4.23); or `toScreen(rect)` is within 2 px of (0,0) or of the stage origin, the :1098-1099 test that would send `tryRemount` to the footprint fallback | → retired `badRect` |
| 8 | `stageMap()` null | → retired `noStageMap` |
| 9 | `findMovieCanvas(toScreen(rect), v)` null (pre-check: the hand-off lands in the authored layer or not at all, never the top-z stage append :1182-1224) | → retired `noAuthoredLayer` |
| 10 | otherwise | Retire same-asset siblings: every `__obedGlPooled` decoder of `movieKey` except `v` (`retireDecoder` :998-1008, prune the pool). Set `v.__obedRect = toScreen(rect)`: G2 passes AUTHORED px, and the stub stamped them raw, which is correct only at s=1. This non-zero rect is what keeps `tryRemount` off the footprint fallback (:1098-1118, the Q0b ≈4 px pop, K6). Set `v.__obedParent = null` as a guard, so a re-attached source subtree can never take the :1058-1094 branch. Clear `__obedGlNoWarm`. Transition to released `handoff`, then `tryRemount(v)`. Landing check: unless `v.parentNode === canvas.parentNode && v.previousSibling === canvas` (the pre-checked canvas), → retired `remountFailed`. The transition sweep retires `v` too; it is the memo. |

**Edge cases.**
- **G2 never loads** (P2, host `off`, install refusal): the zone goes pending → retired at the first post-load evaluation. Nothing was pooled under armed, so this is today's retire, plus one `glreplay-zone` note.
- **G2 loads but never engages** (go-to, non-WebGL move): `unengaged` fires at the first consult with `hn ≥ atScene`, inside the zone or past it.
- **Go-to slide 3 from slide 1, then advance to 4 (K1, R5):** `unengaged` fires at hash 6. When G2's sticky ARM-PRE arms on the 3→4 context, `carried` answers `notArmed`, G2 stands down `assetUnbound`, and `release` answers `notArmed` with no side effects. The bridge decoder is untouched.
- **Release after a stand-down that already retired the zone**: returns `notArmed`.
- **The carried clip ends during the dwell** (46 s fixture clip; r5 `q3b`): row 6 answers `ended` → retire.

## 3. Version, allowlist, P2 injected plan

- **`CONTINUITY_VERSION` 4 → 5** (`live_continuity_js.py:70`, test :24). The in-page `version: 8` is untouched (F12). Stream A adds a **pinned core-sha literal** and re-pins it last, mirroring G2's `PINNED_JS_SHA256`.
- **`QUALIFIED_PLAN_SHA256`: no byte change.** G3 needs no plan field (F5), and both shapes stay derivable behind the G4 flag (off → `bafe26…`, auto → `6a0596…`). Replacement would therefore swap each hash for itself. The baseline "replace, don't append" rule targets an underivable old shape, which does not exist here. **Re-qualifying both shapes against v5 is the gate's job:**
  - `bafe26…`: host probe ×3 viewports in `run_gates.sh` (default path);
  - `6a0596…` fallback: P2 ×3;
  - `6a0596…` armed: the §6 harness.
  - `live_continuity.py` is not edited.
- **P2 plan.** `p2_verdict.build_continuity_plan` injects the flag-on shape: the `glReplay` boundary as a literal copy of `EXPECTED_GL_REPLAY_RUNTIME_PLAN["boundaries"][0]` (byte-exact, F10), then restart and bridge, plus `transparentBackground`. With no GL module in P2, the v5 core takes the pending → retired `moduleAbsent` path, so the full adversarial harness qualifies G3's fallback on the real export.
- **`refusedCarry1to2`.**
  - Clause (a) accepts `action == "retire"` **or** (`action == "glReplay"` and `fallback == "retire"`) at `retire_scene`/`target_key` (:770-778).
  - For a `glReplay` plan, a new clause requires ≥ 1 `glreplay-zone` note with `to == "retired"`, none with `to ∈ {armed, released}`, and zero `glreplay-live`. New reasons: "glReplay zone never fell back to retire" and "glReplay went live inside the refused zone".
  - The output keys stay (`planRetire` holds the matched boundary) and add `glReplayFallback`.
- **Tests that move.**
  - `test_p2_adversarial.py`: 3000-3007, 3243-3252, 3263-3266. For 3269-3283, load `EXPECTED_GL_REPLAY_RUNTIME_PLAN` by `importlib` from the test file (its literal names `REAL_SLOT4_OPACITY`, so `eval` breaks) and assert `plan_signature(injected − transparentBackground) ∈ QUALIFIED_PLAN_SHA256`.
  - `_refused_args` gains the zone note, with positive and negative clause tests.
- **Flag-off bytes.**
  - MUST stay identical: the runtime plan (`bafe26…`); `test_continuity_inactive_html_is_byte_identical_to_pre_i2` with its existing literals (continuity off/unsupported inject no core); the served page = today's recipe with no `obed-gl-replay` tag; `__OBED_P2_PRESERVE__` without `glReplay`; every pre-existing core Node test green **unedited** (except the version literal).
  - CHANGE: the core script bytes (v5), hence `continuity.sha256` and `version` in `output()`.
- **Commit order (bisectable).** The core commit (v5) lands before the P2-plan commit. No commit may inject a `glReplay` plan into a v4 core, which would carry it into the overlap (G1 decision B).

## 4. G4 host (`live_host.py`)

| Item | Decision |
|---|---|
| Switch | `GL_REPLAY_ENV = "OBED_LIVE_GL_REPLAY"`. `LiveOutputHost(..., gl_replay=_UNSET)`: an explicit `"off"`/`"auto"` wins (anything else raises `LiveHostError("GL replay must be auto or off.")`). Unset falls back to the env: `strip().lower()`, `""`/`off` → off, `auto` → auto, anything else raises `LiveHostError("OBED_LIVE_GL_REPLAY must be off or auto.")` in `start()`, like ADVANCE (:952-954). **Default off.** Continuity off ⇒ GL off. |
| Off path | `derive_plan(...)` is called **exactly as today** (no `gl_replay` kwarg), so `continuity_script == _continuity_scripts(runtime, canvas)` and nothing from `live_gl_replay_js` is called. |
| Auto path | `derive_plan(..., gl_replay=True)`. If the result is Unsupported, has no `glReplay` entry, `CONTINUITY_VERSION < 5`, or `gl_replay_script(runtime) == ""`, re-derive exactly as the off path and record the mode/reason. Otherwise keep the flag-on runtime and `self._gl_replay_script`. |
| Injection | In `start()`: `continuity_script = _continuity_scripts(plan, canvas) + self._gl_replay_script` (:976-980). `_continuity_scripts` stays unchanged. The order is plan < core < `obed-gl-replay` < fit < `#stage` < `main.js`. |
| Attach | OD-2 default: auto + attach ⇒ not injected, `unavailable`, reason `attach output not qualified`. |
| Surface | `output()["continuity"]["glReplay"] = {mode: off\|injected\|notApplicable\|unavailable, reason?, version: GL_REPLAY_VERSION, sha256: gl js_sha256()}`. The `continuity` log record carries the same. The key set at `test_live_host.py:1325` gains `glReplay`. The dashboard and web layer need no change (F16). README: OD-3. |
| Tests | Off (unset, ctor off, env off, continuity off): no tag, `continuity_script` equals the recipe, `gl_replay_script` monkeypatched to raise is never called, and `derive_plan` is spied without the kwarg. Auto with a fake plan pair: tag order, flag-on runtime injected. `CONTINUITY_VERSION` monkeypatched to 4 gives no tag, flag-off plan, `unavailable`; to 5 gives injected. No entry gives `notApplicable` and bytes equal to off. Script `""` gives `unavailable`. Env/ctor parsing and precedence. Attach. Output shape. Existing inactive-HTML sha pins untouched. |

## 5. Work split

| Stream | Owns | Forbidden | Done when |
|---|---|---|---|
| **A: JS core** (Opus) | `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py`, `tests/test_live_gl_replay_js.py` (**test-only**: the fake seam's `release` snapshots `__OBED_GL_REPLAY__.standDowns`/`.state`; assert that for every §2.7 reason the last element is that reason at release time, which is the contract §2 row 4 relies on. Also assert that `API.state === 'STANDDOWN'` during `release`, which the §1 `moduleRetired` exclusion relies on, and that `glreplay-arm`/`glreplay-live` reach `seam.note`, the `armSeen`/`liveSeen` source) | `live_gl_replay_js.py` (pinned `985afeb1…` must not move), everything else | §1–§2 are in; v5. New Node tests are RED against the `9ad4fc69` core, then GREEN. They cover: every armed call site (#1–#8); selection at identity, scaled and letterboxed stages with `__obedRect` zeroed by a detach; each `release` row driven by real `standDowns` arrays (FORCED, not grepped); watchdogs; released → retired; seam key set; notes schema. **Rev 2 additions:** (a) the fake DOM models `document.readyState` (`'loading'` at install, flipped later; today it is absent, K17), and a consult during `loading` stays pending; (b) K1: armed at hash 1, then hash 6 with no `glreplay-arm` ⇒ `unengaged` at the first consult. Then a pooled + DOM-preserved bridge-shaped decoder at hash 7 survives `release` (`notArmed`), and a forced out-of-zone retire touches only `__obedGlPooled` + the memo; (c) K2: `canvasRemoved` without `liveSeen` ⇒ `notLive`; (d) K12: an attached clear at `atScene−1` really clears; a clear on a `__obedGlPooled` decoder at `atScene` is swallowed; an empty-src memo ⇒ `noCarried`; (e) K13: `tryRemount` made to throw inside `release` ⇒ `releaseError`; G2 `RETIRED` with `release` called but the zone still armed ⇒ `moduleRetired`; `release` during `pending` resolves first; (f) K14: `clear()` from armed and from released ⇒ `cleared`; (g) K15: `note('glreplay-zone', …)` is ignored. The whole retire test family (:1119-1530) also runs parametrised on a `glReplay` plan with the module absent, RETIRED, or at version 2, with identical outcomes plus one `glreplay-zone` note. Pre-existing tests stay unedited. The core sha literal is re-pinned LAST. |
| **B: Python** (Opus) | `src/obed_edom/p2_verdict.py`, `tests/test_p2_adversarial.py`, `src/obed_edom/live_host.py`, `tests/test_live_host.py`, `tests/test_live_continuity.py` (one test: on the flag-on fixture, exactly one source-slide same-asset instance is within 1.0 px/edge of `instanceRect`, the offline half of §2's rule) | `live_continuity_js.py`, `live_gl_replay_js.py`, `live_continuity.py` (stop and ask if a change looks needed), `scripts/**`, `dashboard/**`, `README.md` | §3 P2 and §4 are in. The P2-plan commit lands only **after** A's core commit. Host tests pin `live_host.CONTINUITY_VERSION` by monkeypatch (4 and 5), so B does not depend on A's bump. `-rs` shows no new skips. |
| **C: gate runner** | `output/live-visible-content/g3/**`, `output/gates-g3/**` (git-ignored); the pinned detached worktrees it creates (`git worktree add --detach`, fixture symlinked) and removes | `src/**`, `tests/**`, `scripts/**` (run only), other worktrees (`dsk-generator-template-memory-9b60ba` is another session's) | The §6 records exist, plus a `gates-r<N>.md` for the PR in the `s3-gates-r5.md` format. |

**Order.**
1. ~~Critique of §1–§2, then rev 2~~ — done (rev 2, critique table). Owner review of rev 2.
2. **Day one**: C runs G-0 on pinned `9ad4fc69`. A and B start in parallel. C ports the harness against A's WIP, injecting the module via a harness-side `_continuity_scripts` wrapper until B's G4 lands, then repeats gate 1 on the product flag.
3. A's core commit, then B's P2 commit, then **G-P2 (BLOCKING before any review)**.
4. B's G4 commit, then the §6 harness gates.
5. Two Opus reviews in parallel: R-A on seam and zone (arming §7 Codex questions 1–7 plus: can a failure end anywhere but retire; can the carried decoder paint while armed; can selection ever bind "the only video"). R-B on host and P2 (does `off` inject or evaluate anything).
6. Fixes. Each applies the reviewer's exact wording or a measured refutation, with the test RED first. C then re-runs G-P2 plus the affected arms.
7. Codex, fixes, re-gate.
8. A re-pins the core sha.
9. Full suites: `uv run pytest tests/ -n auto --dist loadfile` (baseline 5792 passed / 89 skipped / 1 xfailed), `test:ui` 222, `test:maps` 2.
10. Integration PR (no merge without the owner).

**Paste into every brief.**
- Stage only owned paths.
- Force paths get FORCED, not grepped (N4: a one-site helper refactor silently disabled a force arm).
- Sandboxed JS runs in sloppy mode like a real `<script>` (F13).
- On the P2 frame, only program 4 reveals a missing `Opacity` write: target slot 4 and dirty it first.
- `MutationRecord` has no timestamp; take mutation → hand-off latency from CDP only.
- Transition texture layers carry `objectID: None`, so `movieSlot` is positional.
- Tests count only once proved RED against the pre-fix bytes.
- Run real-export tests with `-rs` and the P2 symlink present.
- No `timeout` binary on macOS.
- New worktree setup: `uv sync --all-extras --all-groups`, `cd dashboard && npm ci`.

## 6. Gates (real seam, product injection path) and harness adaptation

**Harness `g3/`**
- Copy `g2/{common,g2_flow,analyse_r5}.py` and delete `stub.py` (scratch core, hold, stub seam, `__GLR`).
- Arms are built with `LiveOutputHost(..., gl_replay="auto")`; the control uses the default.
- Observation-only splices on top of the real `_continuity_scripts`:
  - `ORDER_PROBE` appended after the `obed-gl-replay` tag.
  - For `fail:<r>` arms, the partial `__OBED_GL_REPLAY__` seed inserted immediately **before** `<script id="obed-gl-replay">`.
- Additionally records:
  - every `glreplay-zone`/`-carried`/`-release`/`-hold` note;
  - `__obedAuthoredRect` per pooled decoder;
  - `output.continuity.glReplay`;
  - a counter burst of 10 shots ≥ 100 ms apart across build 1.
- Up to 3 harness lanes at once. `run_gates.sh`, the go-to arm and Q3 run alone.

| Gate | Pass condition (must match r5 where the module is unchanged) |
|---|---|
| **G-0** baseline | `run_gates.sh` on `9ad4fc69`: host verdicts ×3 and P2 True/False lists ×3 are recorded as the reference. |
| **G-P2 (BLOCKING)** | `run_gates.sh` on the branch: host ×3 verdicts == G-0 (default path, v5 core); P2 ×3 `success`, True count == G-0, False list == G-0; `refusedCarry1to2.ok` with `glReplayFallback` = `moduleAbsent`; printed runtime sha == branch core sha. |
| 1 install order | `wrappedAtInstall` 245, `getContextWrappedAtInstall`, `mainJsSeenAtInstall` false (r5); served HTML order per §4. |
| 2 full 1→2 | Events `glreplay-arm`, `glreplay-live`; `settleGapMs` ≈ 100.8 and `settleToHashMs` ≈ 99.2 (report-only); frameLen 88, GL errors 0, occluded 20/128, `programsDistinct`; real oracle LIVE n=24 with the **paused control DEAD (the real `setKeepWarm`)**; control (flag off) has no handle and no tag. New: `glreplay-zone pending→armed moduleReady`; `glreplay-carried` binds the big instance with Δ ≤ 0.02; 0 `preserve-refused`; `glreplay-hold` present; 2 pooled, 0 in document at settle. |
| 4 hand-back + Q0b (n=2) | Settled 2 / P2c / P3 / P4: max\|Δ\| outside movie rects ∪ slot 4 = 0 vs control (r5: 0/0/0/0). `glreplay-release {mode:'handoff', retired:[sibling elId]}`, then `remount-into-authored-layer` (never `-done`/`-footprint-rect`) at `toScreen(slotRects[3])` ± 0.5 px. Exactly one painting `<video>` after build 1, zero `remount-*` before the hand-off, same elId with `currentTime` strictly increasing, and counter-burst deltas mod 256 in [0, 64) with sum > 0. **Tail:** builds 2–4 show one painting movie1 `<video>` at each settled scene 3–5, and its elId retires at scene 6 (A3). |
| 4b letterboxed | Gate 4 at 1600×1000, armed vs control. Rect == `toScreen` at s 0.8333, oy 50. This is new: the units bug the stub could not show (§2 row 10). |
| 6 fail-closed | All 20 reasons (19 forceable plus `writebackFailed` as secondary). Every r5 forced reason fires on hash `#1`, before `glreplay-live` (K5/K8). So every arm except `writebackFailed` equals the control at P2c **and** P3/P4: counter None, 0 painting, 0 `remount-*` for movie1 after the stand-down, pool empty for movie1. Each carries `glreplay-zone …→retired` with reason `failure/<r>`, `notLive` for forced `canvasRemoved` (K9), or `moduleRetired` for `planUnreadable`/`glReplayUnavailable`. Only `writebackFailed` (+ the natural `canvasRemoved` on `#2`) equals the **armed** arm after build 1. **Expected to differ from r5 for 17 arms (live → static), by design (F8, K8).** **Late-forced arms (new, K11):** these exercise row 4, i.e. OD-1; the hash-`#1` arms cannot. The harness sets `window.__OBED_GL_REPLAY__.debugForceFail` by CDP after hash == `atScene`, at P2c, for `contextLost`, `frameLengthChanged` and `glError`. Each must give `failure/<r>` and equal the control after build 1. Late `canvasRemoved` is report-only (R4: hand-off into the hidden layer, or `noAuthoredLayer`). `unflaggedPlayerCall` cannot be late-forced: 0 player GL calls at rest. |
| 7 go-to | Flag on: show, `goTo` slide 2 ⇒ `armed→retired unengaged` at the first consult at hash 2; artifacts == control go-to arm; no `glreplay-live`. **New arm (K1/R5):** show, `goTo` slide 3 from slide 1, then advance to 4. Pass condition: `unengaged` at hash 6; G2 stands down on the 3→4 context with `release` answering `notArmed`; `bridge-3to4` fires at 8 with the slide-3 decoder's elId; no `retire-boundary` names that elId; artifacts == the flag-off arm of the same walk. One full-deck walk shows `bridge-3to4` still fires at 8. |
| Q3 | One continuous 20-min armed session, `loseContext()` at minute 10 ⇒ `contextLost`, write-back skipped, `armed→retired failure/contextLost`, after build 1 == control. This matches r5: `q3b` never handed off because the clip had ended (K10); only the notes change. Heap flat (r5 9.85–10.87 MB), 0 GL errors, dropped 0/1381, rVFC→rAF at end of media. |

## 7. Risks and owner decisions

**Risks.**
- R1: G3 reads G2's published `version`/`state`/`standDowns`, and takes `armSeen`/`liveSeen` from the `glreplay-arm`/`-live` kinds G2 passes through `note()` (rev 2; it no longer reads `events`). This is a reverse coupling. This is pinned by stream A's contract test in `test_live_gl_replay_js.py`; a G2 reorder turns it red.
- R2: The hand-off rect is the texture slot (960×276), not the authored instance (951.54×267.62). The DOM movie stays ≈4 px/edge larger and 2 % aspect-stretched until the next cut. This was G2's choice to avoid the pop (F9); G3 honours the rect G2 passes.
- R3: `released` = pin for the rest of slide 2. A later layer teardown re-enters pin's source-footprint fallback (:1095-1118), which is the Q0b pop. The gate 4 tail measures this.
- R4: A `canvasRemoved` forced at hash `#1` is pre-LIVE and retires `notLive` (K9). Only a LATE-forced `canvasRemoved` (after hash == `atScene`) hands off mid-dwell, into the hidden layer or `noAuthoredLayer`. It is debug-only and report-only.
- R5: G2's ARM-PRE is sticky after a go-to, so a later unrelated WebGL move (3→4) arms it. This is fail-closed only because `unengaged` fires outside the zone and the out-of-zone retire is limited to `__obedGlPooled` + the memo (K1). G3 then answers `notArmed`, and G2 stands down `assetUnbound`. Covered by the gate 7 go-to-3 arm.
- R6: Every default session runs v5 bytes. G-P2's host ×3 covers this.
- R7: A1/A4, and nothing measured in OBS CEF.
- R8: The stage-gate `disable()` path with GL injected ends in G2 `assetUnbound` (seam `disabled`).

**Owner decisions (default taken unless overruled).**
- **OD-1: LIVE-phase failures (`contextLost`, `frameLengthChanged`, `glError`, `unflaggedPlayerCall`) → retire.** The plans conflict, and the conflict was verified at rev 2 (K11). Arming §3 says any LIVE guard hands off. Arming §2/§5, D4 (accepted) and G2 §4(6) say every runtime failure reverts to retire artifacts. The alternative (hand off at build 1) looks better but is unmeasured beyond the stub; it would be a one-row change in §2 row 4. Only Q3 and the late-forced gate-6 arms exercise this decision; the hash-`#1` forced arms retire through rows 4b/5 whichever way it goes.
- **OD-2: `auto` in OBS attach mode is not injected** (`unavailable`) until the pool keep-warm and stash-order measurement inside CEF (arming §8 D1 answer: "G3 still waits on the pool keep-warm-inside-CEF measurement"; still open per G2 §4). D5 already keeps the flag off by default.
- **OD-3: no operator surface this PR.** No README line, no presenter badge, and `notCarried` keeps listing the 1→2 boundary even when GL replay is injected. Document at G6 re-qualification (D5).

**Handover corrections.**
- (1) "Replace `QUALIFIED_PLAN_SHA256` (both entries → new shape)" is vacuous: no shape moves (§3).
- (2) r5's "artifact parity for all 19" covered one ROI at P2c only (F8).
- (3) The re-run list must add gate 6 (semantics change) and gate 1 on the product injection path.
- (4) The stub's unlisted approximation: authored px stamped as screen px.
- (5) There is no pinned core-sha literal to "re-pin" today.
