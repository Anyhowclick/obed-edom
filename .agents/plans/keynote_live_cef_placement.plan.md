# Alpha Keynote: CEF/OBS placement calibration and the fractional movie freeze

**rev 3.3 — 2026-10-13; contracts frozen (§11), step 0 recorded (§7), owner decisions O1–O5 unchanged in §8.** Base: rev 3.2 `ace08c4e` on `claude/cef-obs-placement-plan`.
Plan only: overwrite the scratch plan for coordinator copy; no product edits, commit, OBS, Chrome or Keynote run.
Parent: `keynote_live_dissolve_crossfade.plan.md` **rev 17**, landed #262; its §12 decisions 1–16 govern except where
today's explicit follow-up request restores probe work. Earlier probe design: `git show 41ef609b:.agents/plans/keynote_live_dissolve_crossfade.plan.md`,
§3.3 and §9. Handover: `.agents/handovers/keynote-live-dissolve-crossfade-followups.md`, items 1–5, r13 and W5.
All repository anchors below were read at this base; proposed names and behavior are design, not claims of existing code.

## 0. Summary

Extend the private placement channel with a compositor-measured `frac` grant. Probe a dedicated `AK-Probe` browser source
in **hidden Studio Mode preview of `AK-Calibrate`**, outside the program graph. Select the placement at qualification for
the pinned OBS version: preview if it passes, otherwise the qualified off-canvas nested scene on `AK`, installed
disabled → positioned → read back → enabled. No runtime fallback after a failed preview probe. Passive
off-program scenes, disabled items and hiding behind `Program` are rejected by the owner and measured evidence (§1.2).

Fresh host challenges visible in OBS screenshots and changing video pixels must establish a live source before the paused
two-pose classifier runs. A successful, isolated, cleaned-up transaction grants a context-bound lease; every uncertainty
means no freeze. The player draws the snapped underlay plus CEF's fractional quad, only at DPR 1 and integer stage origin.
W5 records the tone-path map; the take remains identity-tone. Include the bounded r13 #1 raw/preview fix. Chrome keeps its
knowledge-based `snap` without expiry; r13 #3 stays open. Only managed OBS gains a product probe, lease and recalibrate.
Chrome probe-page runs are harness-only. No acceptance result is claimed by this plan.

## 1. Facts

### 1.1 Verified code seams

| ID | Fact and verified anchor |
|---|---|
| F1 | The take reads `window.__obedPlacement`, admits only `snap`, retains the DPR/translation/paint guards, draws once, scans the whole backing for opacity, then draws foreground canvases into that backing. D3 attaches holders to the transition wrapper. `src/obed_edom/live_runtime.py:74`, `:79`, `:113`, `:147`, `:148`, `:149`, `:154`. |
| F2 | Both supported stock players have output pins; `patch_player` applies count-checked rendering replacements plus the observation hook; `patch_rendering` uses the same rendering replacements without the hook. Thus the rendering-only variant contains the executable take today. `src/obed_edom/live_runtime.py:11`, `:298`, `:324`, `:338`. |
| F3 | The first-run private getter/updater currently accepts only `snap`, without expiry. Installation precedes navigation; attached hosts install the channel but never grant. Eligible launched Chrome is major 154 with readable enabled GPU compositing; the round trip revokes in `finally`, and commit targets a unique context. `src/obed_edom/live_host.py:53`, `:110`, `:1198`, `:1222`, `:1265`. |
| F4 | CDP events are consumed while waiting for replies; default contexts are tracked, and `evaluate_in` uses `uniqueContextId`. Browser-target calls require the launched Chrome socket; `_gpu_compositing` uses that route. `observe()` synchronizes placement; fingerprint failure revokes an existing grant. These are not autonomous reconnect/probe machinery. `src/obed_edom/live_host.py:653`, `:676`, `:705`, `:708`, `:727`, `:1253`, `:1280`, `:1402`. |
| F5 | `ManagedObs` serializes jobs and runs liveness only when its queue is empty. Its seed contains `Program` in `AK` and transition `Cut`; hidden launch/readiness identify the managed target. `_launch` calls `_seed` before launch; it writes `AK.json` but neither writes nor removes `AK.json.bak`. `src/obed_edom/managed_obs.py:96`, `:116`, `:157`, `:168`, `:333`, `:607`, `:889`, `:914`, `:938`, `:953`. |
| F6 | The WebSocket client documents read-only product use, subscribes to no events, skips unrelated responses and has absolute request deadlines; its message cap is 4 MiB. Mutating calibration requests are a deliberate new product capability, not an existing screenshot API. `src/obed_edom/obs_websocket.py:1`, `:21`, `:75`, `:93`, `:121`. |
| F7 | The router passes the managed endpoint, target and bridge to `LiveOutputHost`, but no calibration adapter. `CommandBody` and session validation accept advance/goTo/hide/show/stop. Capabilities enumerate the first four; non-navigation commands currently enter `pending_visibility`. Recalibrate cannot simply use that branch. `src/obed_edom/web/live.py:48`, `:279`, `:302`; `src/obed_edom/live_session.py:112`, `:280`, `:293`, `:379`. |
| F8 | The presenter has the same operation union, output metadata without placement typing, capability-based disabling and a shared command sender. `dashboard/src/live/api.ts:1`, `:29`, `:41`; `dashboard/src/live/LivePresenter.tsx:204`, `:215`, `:305`. |
| F9 | DX-2 captures `AK`, unpremultiplies OBS RGB for the dissolve scorer, and currently enforces `attached`/no holders on every dissolve session. The harness can make lossless recordings. `scripts/managed_obs_qualify.py:288`, `:297`, `:526`, `:722`, `:1558`; `src/obed_edom/managed_obs.py:146`. |
| F10 | Holder scoring already requires a verified foreground mask and tests interior and edge band separately; reference capture and scope/grant checks are distinct. Reuse these rather than creating a second pixel oracle. `scripts/dissolve_probe.py:1760`, `:1790`, `:1814`, `:1829`, `:2427`, `:3317`. |
| F11 | Packaging currently includes YAML/JS, NE data and JPG, not MP4. A source-tree-only fixture would not ship. `pyproject.toml:58`. |

### 1.2 Evidence and its limits

`E` below is the absolute main-checkout directory
`/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored).

- `E/obs-feasibility-2026-10-13/README.md` (whole file) and `astra/REPORT.md:3`, `:5`, `:23`, `:59`:
  cold passive sources are empty; warmed passive/disabled sources retain stale pixels. Hidden Studio preview is live with
  active=false/showing=true; off-canvas is live. The independent recording has 1,006 byte-identical decoded YUV frames;
  separate full-size RGBA captures preserve the half-transparent program. These establish feasibility, not product acceptance.
- `E/obs-feasibility-2026-10-13/astra/REPORT.md`, **Controls**, **Q3**, final cleanup paragraph: decode can advance on an
  empty source; rAF can advance with frozen pixels; repeated challenges can accidentally match stale textures. Hiding behind
  transparent `Program` contaminates 1,036,800 pixels. Full-size source PNGs cost 90.15 ms median / 107.41 ms p95.
  Removal returned both already-absent errors and acknowledgements preceding actual disappearance; live absence was not
  verified in those runs. The report's post-exit file restoration is not proof of product cleanup.
- `E/cef-frac-2026-10-12/README.md:14`, `:23`, `:38`; `scripts/probe.js` and `scripts/probeana.py`:
  `fdrawu` is a snapped underlay plus unsnapped quad. It measured 2 LSB / 0% over threshold in CEF 127, while the snapped
  rule missed by 183 LSB. The two-pose self-referential probe separates correct (≤0.58%) and wrong (≥39.8%) rules. Its
  synthetic edges have larger residuals than a real holder; classification is not holder-fidelity qualification.
- `E/q0bbis-2026-10-12/README.md`, **Results**: indicative W5 GPU/software separation, repeatability, cost and geometry
  results; GPU-state invalidation and CEF hevc10/Keynote-HEVC tone remained untested. Four DPR-1.5 mask checks were
  INCONCLUSIVE; the emulated-DPR run was void. Neither becomes PASS by inheritance.
- `E/hidpi-2026-10-12/README.md`, **Method/Results/Root cause** and `scripts/genvid.py:1`, `:47`:
  `p2like` is a **still pattern** encoded for three seconds, not a moving-video freshness stimulus. The MP4 was pruned.
  Rev 17 §13.1 (`.agents/plans/keynote_live_dissolve_crossfade.plan.md:1140`) retains only sha256 prefix `7b7d66b5…`;
  rev 16 §3.3 records 144,100 bytes. A full digest was not found in the retained evidence read here.

## 2. Design

### 2.1 Boundaries and transaction contract

Add `placement_probe.py` for the probe page, immutable measurement record and pure classifier. Keep browser/OBS ownership
in the existing hosts (F3–F6). `LiveOutputHost` owns grant state; `ManagedObs` exposes a narrow calibration transaction
adapter, passed by `web/live.py`. Never pass its password into API JSON, page URLs or logs. External `obs-cdp` remains
unqualified: an arbitrary attached browser provides neither owned isolation nor cleanup authority.

The adapter creates a run-bound source, discovers its exact source UUID and CDP target/context using a unique loopback URL,
captures with a deadline, verifies isolation and restores state. The probe module returns evidence, never grants itself.
One transaction per engine; completion is tagged with engine launch identity, program target/context, connection generation,
probe target/context, run ID, fixture digest and geometry. A result from another generation is discarded.

The calibration transaction runs on its own bounded thread with its own `ObsWebsocket`, never as a `_submit` job.
It takes an engine-generation token under `ManagedObs`'s lock. Quit/restart/setup set cancellation, wait at most the 5 s
cleanup budget for verified cleanup, then proceed; invalidate the generation and close transaction transports before a
replacement engine can be touched. Serialize each short mutation against generation change, not the whole transaction.
Liveness keeps running. A generation change aborts without grant; cleanup timeout remains an error, never a clean result.
Do not hold the session adapter lock or execute probe work in a CDP callback. Short program-context operations use the
existing serialized transport. Stop holds no lock needed by cleanup. Observations expose progress, not recursive probes.

### 2.2 OBS isolation, primary and fallback

Before any mutation, snapshot Studio Mode, preview scene, program scene, canvas dimensions, transition state and relevant
scene items/transforms/order. Require the owned ready engine and expected program `AK`; reject a transition already in
flight. Before enabling Studio Mode, read back current transition = `Cut` and no DeckLink preview output active;
otherwise no probe. Step 0 records the exact response for an unconfigured DeckLink preview output. That response
(and only it) means absent = pass; any other error or timeout = unreadable = no probe. Record the request/response route
for both checks; do not guess a not-found code. Record identities as well as names. Never operate on a colliding object
whose ownership is unproved.

**Primary:** create `AK-Calibrate` and its enabled `AK-Probe` without adding either to `AK`. Enable Studio Mode if needed,
select `AK-Calibrate` as preview, and verify program is unchanged, source active=false/showing=true, correct target and
visible probe document. Never call a transition-to-program operation. Keep OBS inactive with no on-screen window; do not
use `isHidden()` alone as proof (feasibility report, **Ranked product recommendation**). Use the program browser's source
FPS, source dimensions and measured DPR; initially qualify 1920×1080/DPR 1 in managed OBS.

Seed `SceneDuplicationMode=false` in managed `user.ini` through `render_tree` (W3; existing seed at
`src/obed_edom/managed_obs.py:150`) only if step 0 shows the default duplicates and fails the moving-program gate.
Its readback is the seeded `user.ini` value verified on disk after launch plus the step-0 behavioral result. Do not
require a runtime API readback unless step 0 finds one. Static feasibility recording does not prove no stutter.

**Fallback, selected at qualification:** create the calibration scene reference in `AK` **disabled**, with the probe
still silent. Set a translation beyond the current canvas (positive margin), identity scale/rotation, no crop/bounds
surprises, no filters or show/hide transitions. Read back the complete effective bounds and prove their disjointness
from the canvas before enabling. Verify active/showing and freshness. A nested scene is preferred so one disabled
reference isolates the whole probe. Never briefly enable at the default origin. Recheck geometry/source size/canvas
and state before every capture; unexpected mutation aborts, disables the reference and invalidates the result.

Select per pinned OBS version: preview if `iso-obs-preview` passes, else off-canvas only if its own gates pass. At runtime
a failed preview transaction → invalid (stock movie), never an automatic off-canvas attempt in the same or a later run.
No qualified placement means no probe. Do not implement zero-scale, full-crop, occlusion or projectors. Both must be silent:
no audio track, muted HTML video, OBS audio rerouted and muted, mixers disabled, monitoring off, each read back before use.

**Restoration, every exit:** revoke pending grants; disable any fallback reference first; restore the saved preview before
turning Studio Mode back off; remove owned scene references, inputs and scene; continue past verified already-absent errors;
poll enumerations for absence and read back Studio Mode/preview/program. Attempt remaining steps after each error. Never
transition `AK-Calibrate` to program. If an unexpected program change occurs, invalidate and report isolation failure;
restore the saved program directly only while managed ownership is still established. A transient leak still fails the gate.

**Persistence (O5, measure first):** step 0 measures `AK.json` and `AK.json.bak` before/during the transaction, after
cleanup and after clean quit. Baseline = parsed `AK.json` as saved by OBS before the transaction; step 0 records whether
a pre-transaction save exists; if not, use the seeded file normalized by the same parser. Compare a normalized scene
graph: the set of sources and scenes with ids/uuids/names/settings, each scene's items with transforms/visibility/order,
`current_scene`, `current_program_scene`, transitions. Ignore only an explicit allowlist that step 0 justifies field by
field: the allowlist is the difference set of the no-transaction null run (seed → clean quit, which also covers keys OBS adds
to a seed baseline) plus `id_counter` monotonic increase; a candidate FAILs on any difference beyond the null's. No blanket
settings/module exclusions.
The authoritative checkpoint is after clean quit. The after-cleanup read is authoritative only if its mtime postdates
the last removal; otherwise it is diagnostic. Mid-transaction saves are accepted only with normalized restoration at
these checkpoints; stale saved files never prove cleanup. No calibration seed entries or persisted grant; restore
through OBS, never rewrite live JSON or copy scratch post-exit restoration into product. `_seed` rewrites `AK.json`
before every launch (F5), covering a crash mid-transaction. `AK.json.bak` may hold mid-transaction state. It is unreachable
by managed launches because `_seed` writes a valid primary first; record it, no mutation. Per O5, OBS reads the backup
only if the primary is damaged; do not claim the backup is sanitized.

### 2.3 Chrome boundary and program verification

Launched Chrome keeps its rev-17 knowledge grant unchanged (decision 16; O2 = NO). This PR adds no Chrome product probe
target, lease or migration. r13 #3 stays open in the handover with its residual. W6 alone runs the probe page in a
harness-launched Chrome via CDP screenshot → classifier must return `snap`; this adds no product grant.

For both OBS placements, verify target identity, program scene/graph and source geometry before/during/after measurement,
and sample a known static program. The release gate also records actual OBS program continuously; `GetSourceScreenshot(AK)`
is not the program wire (§1.2). During every transaction, through the existing Program CDP connection, record
`visibilitychange` count, max rAF gap and every playing video's `currentTime` monotonicity/advance: zero visibility events,
rAF gap ≤2 observed frame periods, no video stall beyond one frame. Record the pre-transaction cadence; missing or unstable
baseline is INCONCLUSIVE. Compare a no-transaction null; in scratch, toggling `Program` off/on must FAIL. A failure revokes
and prevents qualification for on-air use; static pixel equality cannot substitute for this moving-program gate.
A runtime moving-program or isolation failure revokes, records the reason, and disables automatic probes for that engine
launch identity; only an operator `recalibrate` may retry. A new engine launch re-enables them. A manual retry on the same
launch does not clear automatic-probe suppression.

On-air calibration must not pause a live program to manufacture a static reference. With natural program motion, compare
structural isolation invariants and record captures as diagnostic, not a false byte-equality PASS. Permit on-air operation
only for the placement whose static RGB+RGBA and moving-program gates have passed; defer while a transition is in flight.
No qualified isolation implementation means invalid placement and stock movie behavior.

### 2.4 Freshness, clip provenance and classifier

**Assets.** During implementation, promote the retained `hidpi/scripts/genvid.py` recipe into a reproducible generator.
Generate `p2like` at 1920×540, seed 7, three seconds/30 fps, libx264 High, QP 1, yuv420p, TV-range BT.709 with the exact
retained scale/tags/x264/faststart arguments. Record generator, NumPy/Pillow, FFmpeg and encoder versions, generated PNG
digest, MP4 byte count, full sha256 and decoded-frame/color metadata. Regenerate twice in the pinned toolchain. Recover
the old full digest if possible; the prefix and byte count are corroboration, **not a cryptographic pin**. If exact recovery
fails, O3 authorizes a newly full-pinned clip after both-engine requalification (CEF product, Chrome harness) and all controls;
never invent the missing suffix or claim the regenerated file is the old artifact. Ship `data/placement_probe.mp4` and a provenance manifest,
verify the full digest before serving, and include them explicitly in package data (F11). Runtime never invokes FFmpeg.

**Freshness phase.** The still-pattern clip cannot satisfy video-ROI change. Ship a separate small silent, moving binary
frame-counter clip, generated and full-pinned by the same generator. Use the same probe `<video>` for this phase, then switch
to the placement clip and prove the newly painted pattern before scoring. At least three distinct unpredictable per-run
host nonces must be painted as multi-cell color patches, decoded exactly from successive backend screenshots, in order,
with distinct moving-video ROI hashes/counter values and matching source/context. Challenge regions stay outside classifier
ROIs. Readiness, advancing rAF/rVFC/decode counters and nonempty/known static swatches are supporting checks only.

**Paused measurement phase.** Load and verify the pinned still pattern, play/seek to the specified frame (1.0 s), pause and
read back decode dimensions/color tuple. Use both poses `(0.352, 0.036)` and `(0.73, 0.41)` from the retained probe. Each
contains the composited video and snap/frac canvases drawn from that same decoded frame, in integer-separated regions.
After six rAFs and at least 200 ms, capture a stable pair per pose. Give each capture a fresh nonce: compare the movie and
candidate ROIs for exact stability, excluding only the explicitly separate challenge/motion regions. Require the second
nonce in the second screenshot; reusing a whole stale screenshot cannot pass. Freeze or remove the motion stimulus during
these pairs; do not require entire PNG equality while deliberately changing a challenge.

Pace all screenshot calls serially, one outstanding request, at least 200 ms between starts; each call has a 2 s deadline.
Use a proposed 15 s measurement budget plus a separately bounded 5 s cleanup budget; log stage durations and total latency.
These are deadlines to qualify, not a claim that the old “about 1.5 s” estimate holds. The probe requires DPR 1; any other
DPR → unknown. Timeout, cancellation, wrong PNG size, program/probe DPR mismatch, unreadable state or insufficient fresh
captures aborts without a grant. Bound screenshot messages for full-size PNG/base64 plus envelope; the existing 4 MiB
cap (F6) must not truncate valid captures or become unlimited.

**Classifier, host only.** For each pose and candidate `c ∈ {snap, frac}`, over the box eroded by **3×DPR device pixels**:

`share(c, M) = count(max(|V.R−M[C.R]|, |V.G−M[C.G]|, |V.B−M[C.B]|) > 4) / inner_pixel_count`.

At DPR 1 the erosion is exactly three pixels. `M` is identity or the fixed analytic GPU table
`round(255·sRGB((i/255)^1.961))`. A map is consistent for a pose iff one rule ≤2% and the other ≥20%. Grant iff exactly
one map is consistent for both poses with the same rule. An intermediate share disqualifies **only that map**; a GPU
capture with intermediate identity-map scores may still qualify under the GPU map. Any second map consistent with a
different rule → unknown. Empty masks, malformed evidence or no unique consistent result → unknown. Only a GPU-map
classification can grant; record identity/software results but leave invalid pending separate holder qualification.
Do not infer `frac` from a CEF UA. Record every share/map, tuple, readiness, DPR, geometry, identity, hash and capture timing.

### 2.5 Grant lifecycle and operator command

Restore rev 16's **invalid → probing → valid** lifecycle for managed-OBS probe-derived grants. A managed-OBS host probes
once its first program context is grant-eligible, then on reload/reconnect/engine change and on `recalibrate`; defer while
a transition is in flight. Reload/reconnect/engine-change triggers respect §2.3's launch-scoped suppression; only a new
engine launch resets it. Calibration never blocks Take output or presentation startup; output may run with invalid
placement. `valid` means a successful classifier, verified isolation and completed cleanup for the same engine/connection/
program context. Revoke before starting every
probe. Commit only to its original `uniqueContextId`, after rechecking generation/fingerprint; late completion never grants
into a replacement page. A failed re-probe never restores the previous result. Reload, source refresh, reconnect, engine
restart, observed GPU change, DPR/canvas/source change and lost calibration placement invalidate the active transaction.

Extend `__obedGrant` to `(token, value, ms)`, keeping private state and non-writable/non-configurable properties.
A host-knowledge `snap` on launched Chrome is set without expiry, exactly as today. Every probe-derived value (`frac`,
or `snap` from a CEF probe) carries a **lease of at most 15 s** on a clock bound before page code runs. Fix the channel's
knowledge/probe mode at installation: a missing/invalid TTL in probe mode cannot create an indefinite grant. Knowledge
eligibility/revocation stays unchanged. Node tamper rows cover both modes. Retain eligibility-before-round-trip (r13 #2):
one context-bound synchronous set/read/revoke/read with revocation in `finally`, then verified commit. Test rule forcing
uses the privileged channel, never page assignment. The mode is a `LiveOutputHost` constructor argument used only by
`scripts/`; the product router never passes it. Product mode is selected from host ownership. `wrongrule-chrome` selects
probe mode at construction and forces leased `frac` through the token; a Node row verifies expiry and fixed mode.
Chrome's product knowledge channel still admits only indefinite `snap`; no Chrome product lease or probe is introduced.

**CEF renewal (O4):** every 3 s and immediately before advance/goTo, require the same CDP connection/context and managed
engine launch identity (pid, launch date, ready generation), with UA and DPR re-read and unchanged. Unreadable or changed
inputs revoke. Do not require unavailable CEF browser-target `SystemInfo` (F4), invent an attached route, or re-run the
probe periodically. Initial classification still requires the GPU map. An unchanged-fingerprint CEF GPU fallback may
keep renewing the old rule indefinitely: accepted residual, as for Chrome r13 #3. Observed reset/change re-probes.
Keep-alive maintains the lease; the calibration source is removed after measurement. W4 renewal runs on a host-owned
timer thread, started on the first probe-derived grant and stopped in `stop()`, independent of session/UI polling.
It uses `evaluate_in` with a deadline below the remaining lease. Budget lock acquisition too: a queued renewal must not
execute after its budget. A missed renewal lets the lease lapse and is logged (`leaseLapsed`), never extended. The current
CDP lock covers the reply wait and its default is 15 s (`src/obed_edom/live_host.py:653`, `:654`, `:661`); renewal must
not inherit that timeout. These scheduling deadlines do not establish page-side expiry (§2.5 reconnect rule).

On managed CDP/OBS connection loss, drop host state immediately and cancel renewal. Reconnect must successfully revoke
in the program document (or verify a fresh invalid context), then re-probe before granting again. If revocation cannot
be delivered, navigation waits for that reconnect revoke; **expiry is never inferred from host time**. A fake-clock unit
row covers suspension/expiry; no live sleep/wake gate. Internal automatic transitions can still run during a stale window.
Hide and Stop remain usable. None of this adds Chrome lease/reconnect-probe behavior.

`recalibrate` is supported **only on managed-OBS sessions**; HDMI/headless and external `obs-cdp` report unsupported with a
reason. Add it end to end (F7–F8), without a slide argument. It acknowledges scheduling and exposes the run state;
it must not enter `pending_visibility`, change `outputVisible`, advance the slide or wait for a navigation revision.
Duplicate request IDs do not schedule twice. Keep
Stop prompt; reject/coalesce another recalibration while probing, and discard results for a stopped/superseded session.
The presenter offers **Recalibrate output**, “Calibrating…”, valid, or a concise unavailable reason. Disable only according
to capability/connection/run state; do not expose tokens, source UUIDs or classifier internals in operator copy.

Extend `output.placement` compatibly: `state`, `grant`, `reason`, `at`, existing product/GPU fields, `method`, `probeId`,
lease expiry (null for Chrome knowledge grants) and `tone: {observed, applied: "identity"}`. Detailed evidence belongs in logs.
Channel compromise retains the existing hide/refuse-show rule (F3); ordinary unqualified placement keeps the presentation
usable with the baked-frame jump. Update engine/host reasons without turning an ordinary probe failure into session error.

### 2.6 Fractional take and immutable player rules

Make changes only through **sha-pinned, count-checked in-memory `patch_player` replacements** (F1–F2); never edit an
export's `main.js` on disk. Preserve `mm_opacity=off`, `RUNTIME_VERSION=2`, D1/D2 cross-fade/cut semantics, the scene/paint
allowlists and add-only D4/D3 lifecycle. Minimal code comments. Re-pin both supported players and every intentionally
changed rendering variant; prove unrelated replacement composition and anchors remain intact.

**O1, included and bounded:** `patch_rendering` omits the freeze take and attachment entry: no `__obedFreezeTake`/D3 entry,
cross-fade/cut unchanged. Split the host freeze replacements and re-pin `SUPPORTED_PLAYERS[*][2]` for both players.
Intentionally rewrite `tests/test_live_runtime.py:312`: rendering = live minus hook **minus take/attachment**, and verify
absence of executable freeze entries. Build Preview already calls this patcher (`src/obed_edom/html_preview.py:144`);
no `html_preview.py` change. Add assignment/non-configurable-getter forgery rows for both `snap` and `frac` in the existing
`m-raw-prod` / `m-preview-prod` arms (`scripts/dissolve_probe.py:330`): no holder. No further O1 scope or files.

Read the grant once. `snap` retains its measured DPR {1,1.5,2}, stage-local snapping and fractional letterbox support.
`frac` additionally requires DPR=1 and integral stage `R.left/R.top`. Both retain stage scale 1, base layer equal to slide,
translation-only chains and integral computed scene `left/top`; outside these classes skip.

Draw the current snapped movie first. Under `frac`, overlay rev 16's `fdrawu` quad. At the admitted DPR=1/kx=ky=1:

`fx = dx + (r.left−R.left) + round(cx−r.left) − u0`

`fy = dy + (r.top−R.top) + round(cy−r.top) − v0`; width=`round(cw)`, height=`round(ch2)`.

Here `dx=u0−a0`, `dy=v0−b0` retain the clipped-region offset. Near-side clipping must not reset either to zero. Keep holder
bounds/backing snapped and scan **every backing alpha pixel after both draws**, before foreground redraw. Fractional-only
drawing or an interior-only alpha scan is forbidden. Do not tone-map foreground canvases. Do not move/pause the program's
video. Publish total `__obedTakeMs` on every path, including rejection; extra draw cost is included in the 50 ms bound.

### 2.7 W5: observe now, qualify application separately

Record the classifier's map without applying it to the take. Extend W5 on the same isolated source/target: tone ramp,
color patches and skin tones; two fresh launches each of managed OBS acceleration on/off and harness Chrome GPU/software;
same tagged tuple, plus CEF hevc10 and Keynote-HEVC. W5's Chrome GPU/`--disable-gpu` rows run in W6's harness script via
CDP screenshot of the probe page in a harness-launched Chrome. No product Chrome probe target or grant is added for W5.
Record unsupported decoding explicitly. Verify repeatability, GPU/software discrimination and invalidation on GPU
loss/reset/acceleration change. The feasibility test's video ROI
differences are freshness evidence, not tone qualification (§1.2).

Non-identity application requires W5 go, owner approval of the player-boundary change, and parent decision 5's bars:
each measured encoding in the qualified tuple fits within 2/255, two CEF launches agree within 1, analytic vs measured
table within 1 or use the measured table. Requalify geometry, foreground and cost on the exact tone-writing bytes.
Until then `Q` and identity `L` stay unchanged, tone gates report only, Q5 stays open. G2 use of a qualified map is a
separate follow-up; no adjustment of `EXPECTED_STATS` to accommodate an unexplained change.

## 3. Scope

Implement handover items 2–5 on today's settled item-1 isolation: probe/fixture, leased channel, reconnect/recalibrate,
`frac`, OBS qualification and harness-only Chrome classifier/tone controls, report/UI and docs. Product mutations are
limited to owned calibration resources and temporary preview state; OBS lifetime remains explicit Take/Release output.
Do not seed calibration into the collection.

Include O1 exactly as §2.6. O2 preserves Chrome's knowledge-based `snap` without expiry; apply leases only to probe-derived
grants. No Chrome product probe or recalibrate, no indefinite fallback when the CEF probe fails. r13 #3 remains open.

## 4. Interplay

| Area | Contract |
|---|---|
| r13 #1, raw/preview forgery | **Included, O1:** remove executable take/attachment from `patch_rendering`, re-pin both rendering digests, intentionally rewrite the equivalence test, add forged rows to existing production-path arms (§2.6). Close only after those gates pass. |
| r13 #3, stale GPU fallback | **Open, with CDP connected too.** O2 leaves Chrome knowledge/revocation unchanged (F3–F4); no guaranteed stale-grant bound. Keep the handover residual (`.agents/handovers/keynote-live-dissolve-crossfade-followups.md:34`). O4 accepts the analogous CEF residual: unchanged fingerprints can renew a stale lease indefinitely. Neither a tagged tuple nor a timer proves the compositor path. |
| r13 #2 | Already addressed by eligibility-first, synchronous round-trip revocation and context-bound commit (F3). Preserve this ordering for probe eligibility and cancellation. |
| D1/D2, MM opacity, hand-back | No arithmetic/switch changes. Extend admission/draw and the bounded O1 split; both stock pins, off bytes, anchor non-overlap and composition remain gates (F1–F2). |
| Continuity/S2/bridge | Keep the parent Q6 decoder-hold follow-up separate. `m-bridge` remains report-only; do not solve holder engagement by stopping or reparenting a decoder. Parent handover §(a), `.agents/handovers/keynote-live-dissolve-crossfade-followups.md:62`. |
| Output/session | Calibration failure disables freeze, not the show. A managed ownership/cleanup violation is separately surfaced. Recalibrate is not visibility or navigation (F7); stale UI/network replies cannot resurrect a lease. |
| W5 and G2 | Classifier compensation is host scoring, not a product LUT. Tone application and G2 reuse remain separately qualified decisions (§2.7). |

## 5. Acceptance gates

Controls run before candidates. Each gate has a null and an injected positive defect, plus a known-good candidate.
Missing/malformed evidence, failed control, ambiguous classification or incomplete cleanup is **INCONCLUSIVE = fail closed**;
INCONCLUSIVE never satisfies an expected FAIL. Store exact code/fixture/player digests, run/context IDs, image hashes,
timestamps, classifier shares, state changes and cleanup readbacks. Re-score saved evidence without OBS. No pruned evidence
is a substitute for a fresh gate on final bytes.

| Gate | Candidate and null | Positive defect/control and required outcome |
|---|---|---|
| `probe-*` | Two fresh CEF launches → frac, both poses/GPU map. Stable paused ROI pair passes; intermediate identity-map scores do not veto a valid GPU map. Software identity, undecodable/mismatched clip → no grant/no next holder. | Cold/warmed dormant or disabled, frozen video with live rAF, replayed challenges/prior-run PNG, wrong source/context/size or DPR≠1 → invalid. Boundary rows: 2% passes, 2%+ε disqualifies that map; 20% passes, 20%−ε disqualifies it; both-low/high, channel-only mismatch and no unique consistent map/rule → unknown. |
| Harness classifier control | W6 harness-launched Chrome, DPR1, probe page via CDP screenshot → snap, two fresh launches; no product probe/grant. Requalification uses the shipped clip. | Wrong candidate rule and software/undecodable controls distinguish snap, frac and unknown; an invalid capture cannot count as an expected classifier rejection. |
| `iso-obs-preview`, `iso-obs-offcanvas` | Static program/no-transaction null: sampled full-frame RGBA unchanged, program identity unchanged. Startup and failed on-air recalibration, both prior Studio states. OBS inactive/no on-screen windows. Moving-program leg records zero visibility events, rAF gap ≤2 frame periods, monotonic playing-video time/no stall >1 frame throughout (§2.3). | `iso-leak` visible-origin/on-program and behind-transparent-Program → FAIL. Scratch `SetSceneItemEnabled(Program)` off/on → liveness FAIL. No painting or missing baseline is INCONCLUSIVE. Select the passing placement at qualification; runtime failure never changes placement. |
| Program-wire integrity | Continuous **lossless actual program recording**, started before install and stopped after verified cleanup/restoration: every decoded frame byte-identical to the static baseline; all PCM samples silent. Run both placements, success, failure and cancellation. | One-frame visible flash and brief audio injection detected. A missing/truncated recording, uncovered transaction interval or encoder mismatch is INCONCLUSIVE. Compare decoded frame bytes, not container-file hashes. |
| Alpha integrity | Transparent and half-transparent static baseline; raw OBS RGBA equality in all four channels, zero tolerance, sampled before/install/each capture/cleanup/restore. Supplements the recording, which may drop alpha. | Behind-Program leak and alpha-only change held across a sample → FAIL. Preserve raw PNGs; no unpremultiplication for equality. A transient alpha-only flash between samples remains a stated residual; closing it costs an alpha-preserving recorder. |
| `life-cal-*`, channel | Managed valid grant → next take engages. Reload/source refresh/reconnect/reprobe failure/changed or unreadable O4 inputs/expiry/cancel/Stop → invalid until fresh probe, subject to launch-scoped suppression. Prior Studio/preview state restored. Chrome knowledge grant remains indefinite; recalibrate unsupported there. | Navigation during commit, late result, lost renewal reply, delayed callback, lock contention/missed timer → `leaseLapsed`, tampered clock/updater/token/getter and failed restore. Runtime moving/isolation failure suppresses automatic retries across reload/reconnect; only manual retry or a new launch probes. Expiry never inferred from host time; fake-clock suspension row, no live sleep/wake gate. Reconnect requires revoke/fresh invalid context. Repeat cleanup; absent/delayed-delete rows verify absence. |
| Persistence/worker | Step-0 before/during/after-cleanup/after-quit AK.json/backup records; normalized graph equals the OBS-saved baseline (seed normalized if no save), with a field-justified allowlist (§2.2). Clean quit is authoritative; cleanup read only if mtime postdates last removal. No-transaction null. Calibration thread leaves liveness running; quit/restart/setup cancel/drain within 5 s. | Leftover saved source/scene or non-allowlisted difference → FAIL; stale cleanup read cannot pass. Inject missing input, delayed deletion, quit/restart while capture blocks and old-generation completion → no grant. Crash/relaunch proves `_seed` writes valid AK.json first; backup recorded, unreachable by managed launch, untouched. |
| `m-snap-cef[clip]` | DPR1/integer origin, P2 paused current frame: none, near/far fractional x and y clips, foreground crossing; DSK 7→8 two holders. Each cell has browser-rendered live reference, stable pairs, `perfect`, same-frame omit twin, verified mask, interior **and edge** scoring. | `m-snap-cef-nooffset[x\|y]` on near-side clips → RGB FAIL with opaque backing; far-side nooffset is not a meaningful red. `wrongrule-cef`/`wrongrule-chrome`, forced through privileged channel (Chrome uses script-only probe-mode constructor, leased frac) → pixel FAIL. Shifted holder/`perfect-shift` → FAIL. Fractional-only underlay-omission → alpha refusal. |
| Geometry/foreground | CEF frac translation-only/integer-origin positives and every clip cell engage, opaque backing and foreground intact. W1 byte inspection proves snap draw/admission unchanged apart from shared `pl` admission. Chrome regression is the DX-1 arms that passed at merge plus `wrongrule-chrome`. | Frac DPR1.5/2, fractional origin; scaled stage/nested scale/mismatched base/fractional scene left/top → published take/no holder. Transparent backing-edge pixels skip; foreground omit/swap fail. Run Chrome's 18-cell real-DSF matrix only if snap draw/admission changed; prior DPR1.5 INCONCLUSIVEs stay recorded, not waived. |
| DX-2/DX-1 fidelity and cost | CEF dissolve/cut/opaque/frozen-frame/foreground gates with calibrated grant; CEF DSK 7→8 total take ≤50 ms including extra draw, two holders, plus all measured DSK transitions. Chrome regression scope as above. | Off/baked-frame, hold-at-full-strength, no-blend and 50 ms+ε controls. `cef-skip` becomes an invalid-probe/unsupported-geometry control, not a blanket attached expectation (F9). |
| Raw/preview scope | Existing `m-raw-prod` / `m-preview-prod`, no host script: retain cross-fade/cut and stock movie behavior. Assignment and non-configurable-getter forgeries of snap/frac each bind no holder. | Current rendering variant is the known-bad forgery control. Never substitute a harness-installed channel for these production-path arms. |
| W5 | GPU/software maps across §2.7, Chrome rows harness-only; identity take unchanged. | Raw/uncompensated tone, unknown tuple/map, insufficient coverage and reset/invalidation controls. Report inability to detect unchanged-fingerprint fallback; O4 accepts it. Non-identity application still requires its separate qualification. |

Keep DX-2's existing unclamped calibration: `n` from `opaque-off`; τ=`max(4,ceil(n)+1)`, complement=`2+ceil(n)`,
no-dip=`252−ceil(n)`; caps 8/6/248, hence n>4 invalid (`scripts/managed_obs_qualify.py:669`). These holder/fade limits
do **not** replace the classifier's fixed 4-LSB / 2% / 20% rules or isolation's zero tolerance. Keep capture/reference
coverage, tone compensation only on exposed video, mask missed=0/excess≤1%, and `perfect` instrument gate (F10).

Run at 25 and 30 output fps with matching source rates, hidden OBS, two fresh launches for classification/tone. Record
load; serialize harness Chrome and OBS; use AC/no Low Power Mode and invalidate accidental Sleep/Wake runs (no deliberate
sleep test). Qualification uses test programs, never an operator's live show. CEF screenshots are paced measurements,
not a claimed output-rate capture.
Owner visual check: current movie frame freezes/fades with foreground intact, no flash/leak during recalibration; compare
`mm_opacity=off`, explicitly show the retained identity-tone step. DeckLink/physical keyer integrity is not proven by recording.

## 6. Tests

Prefer table rows in existing functions; **at most three new test functions**: one pure probe/fixture table, one OBS
transaction/fault table, one presenter calibration interaction table. Avoid duplicate implementation-mirror tests.

- Extend `test_dissolve_real_patched_methods_on_node` (`tests/test_live_runtime.py:1820`) on both players with frac geometry,
  two draws/offsets, whole-alpha scan, forbidden geometry and cleanup rows. Extend anchor/pin/composition/parse functions
  (`:297`, `:306`, `:312`, `:541`, `:630`), including O1's deliberate rendering/live-minus-hook-minus-freeze split and both
  rendering pins. Off remains byte-identical; prove unchanged snap bytes except shared admission.
- New `tests/test_placement_probe.py`: one parameterized function for known-pixel classifier boundaries, maps, inner mask,
  max-over-channels, identity-intermediate/GPU-valid, DPR≠1 refusal, nonce replay/freshness, capture stability/identity/size
  and shipped full-digest validation. Use crafted
  inputs whose correct result is independently specified, including edge-only vs inner defects.
- Extend host placement tests (`tests/test_live_host.py:3223`, `:3263`, `:3305`, `:3325`, `:3356`, `:3431`) with fake clocks,
  transport/context generations, managed lease cap/expiry, cancellation races, O4 timer ownership/stop/lock contention,
  `leaseLapsed`, and managed reconnect/reprobe. Runtime moving/isolation failure suppresses reload/reconnect probes; manual
  retry is allowed without clearing suppression; new launch resets it. Node exercises assignment/delete/getters/wrong-token/
  clock changes, both values and indefinite-knowledge/leased-probe modes. Add a script-only Chrome probe-mode row: token
  forces leased frac, expiry clears it, mode cannot change; product knowledge mode rejects frac. Retain existing Chrome
  knowledge/revocation tests; no new Chrome GPU-fallback or product probe lifecycle scope.
- Add one parameterized managed transaction test in `tests/test_managed_obs.py` for preview/fallback sequences and every
  partial-failure boundary, wrong ownership, absent object, delayed disappearance, O5 normalized baseline/allowlist and
  mtime checkpoints, Cut/preview-output preconditions (exact measured unconfigured response passes; other errors/timeouts
  fail), conditional duplication seed/on-disk readback plus behavioral result, audio and Stop. Include blocked capture
  with liveness still running, cancellation's 5 s bound, generation replacement and no runtime placement fallback.
  Extend seed/lifetime tests (`:108`, `:126`, `:1322`)
  for no calibration seed entries, AK.json crash reseed/untouched backup and bounded cleanup before quit. Extend
  WebSocket tests (`tests/test_obs_websocket.py:113`, `:135`, `:144`, `:163`) for bounded image size/timeouts/errors without
  credential leakage; do not add another generic client.
- Extend session/API command tests (`tests/test_live_session.py:382`, `:435`, `:590`, `:785`;
  `tests/test_live_api.py:232`, `:566`) for recalibrate idempotency, capability propagation, no visibility/navigation ack,
  cancellation, stale completion, engine-adapter injection and managed-only capability (Chrome/external attach unsupported).
  Add one UI table alongside existing delayed-command/Stop
  tests (`dashboard/tests-ui/live-presenter.ui.test.tsx:205`, `:273`, `:350`) for states, error reason and retry.
- Extend the single scorer table (`tests/test_dissolve_probe.py:1235`) with all new controls and evidence omissions. Extend
  DX-2 arm/gate tests (`tests/test_managed_obs_qualify.py:98`, `:180`) for per-arm grants, positive holder expectations,
  program recording+sampled RGBA, moving-program liveness, persistence coverage and no-OBS rescore. Add forged rows to the
  existing raw/preview arms. Diagnose failures before changing expected values.

Implementation checks: targeted rows first, then full Python suite
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`; Python 3.10 compatibility; dashboard
`npm install`, `npm run build`, `npm run test:maps`, `npm run test:ui`. Verify wheel-installed probe assets/hash as part of
the fixture table. Then §5 gates and parent regression: `run_gates.sh` full tier, `mm_opacity_probe.py`, `mm_handback_probe.py`,
managed `mmo`, `g2`, `mmo-cef`. A plan-only change runs none of these product/browser gates.

## 7. Work streams

Implementation only: **Codex GPT-5.6 Sol high, one implementer per stream; disjoint files; only the coordinator commits.**
No implementers are launched by this planning task. O1–O5 are decided; coordinator freezes adapter/result/schema contracts
before parallel work; ownership transfers are explicit, never concurrent edits to a shared file.

| Stream | Exclusive files | Deliverable |
|---|---|---|
| W1 player | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | Frac draw/guards/pins; bounded O1 take/attachment removal from rendering, two rendering re-pins and equivalence-test rewrite; unchanged snap byte proof. |
| W2 probe | new `src/obed_edom/placement_probe.py`, `src/obed_edom/data/placement_probe.mp4`, `placement_motion.mp4`, `placement_probe.json` (all under `data/`), new `scripts/generate_placement_probe.py`, `tests/test_placement_probe.py`; `pyproject.toml` | Reproducible assets, freshness protocol, pure classifier, schema, packaging; W5 map observation. |
| W3 OBS | `src/obed_edom/managed_obs.py`, `src/obed_edom/obs_websocket.py`, `tests/test_managed_obs.py`, `tests/test_obs_websocket.py` | Separate transaction thread/WebSocket, generation/cancel contract, qualification-selected placement, Cut/preview-output and duplication checks, restore/cleanup/O5 persistence, narrow adapter. |
| W4 host | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | Managed probe state machine, leased-vs-knowledge channel, script-only mode override, O4 host timer/lock-budget/leaseLapsed, launch-scoped retry suppression, Program liveness, cancellation/context binding/report. Chrome product grant unchanged. |
| W5 command/UI | `src/obed_edom/web/live.py`, `src/obed_edom/live_session.py`, `tests/test_live_api.py`, `tests/test_live_session.py`, `dashboard/src/live/api.ts`, `dashboard/src/live/LivePresenter.tsx`, `dashboard/tests-ui/live-presenter.ui.test.tsx` | Adapter wiring and recalibrate lifecycle/capabilities/status, no visibility misrouting. This stream label is distinct from the parent W5 tone investigation. |
| W6 qualification | `scripts/dissolve_probe.py`, `scripts/managed_obs_qualify.py`, `tests/test_dissolve_probe.py`, `tests/test_managed_obs_qualify.py` | Step-0 persistence measurement; freshness/isolation/lifecycle, moving-program/null controls, continuous recording+sampled RGBA, CEF clips/tone/cost, harness-only Chrome classifier/W5, O1 forged rows, offline rescore. |
| W7 docs/coordinator | `README.md`, `.agents/skills/obed-edom/SKILL.md`, `.agents/handovers/keynote-live-dissolve-crossfade-followups.md`, this plan | Operator behavior, residuals, gate evidence/owner dispositions. Update skill under its writing rules during implementation. |

**Step 0, before implementation fan-out:** W6 measures persisted `AK.json`/`AK.json.bak` before/during one transaction,
after cleanup and after clean quit. Establish the OBS-saved (or normalized seed) baseline, field-by-field allowlist and
mtime checkpoints (§2.2); apply O5 and record the untouched backup. Record the exact request/response for an unconfigured
DeckLink preview output and transition check. Measure Studio toggle effects on moving Program under the default
duplication setting; seed false only if default duplication fails that gate, then verify disk value and behavior. Record
any available runtime readback route, without requiring one. Select placement only after these results. This is future
implementation work, not a browser/OBS run authorized by this plan-writing task.

**Step 0 results (2026-10-13, coordinator, 3 managed launches; evidence
`output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-step0-2026-10-13/README.md`):**
- **Placement: preview selected.** Studio Mode on/off with the default `SceneDuplicationMode=true`, create, preview, shots,
  restore and removal left the moving Program page at baseline (0 `visibilitychange`, rAF max gap 20.1 ms at 50 fps, rVFC max
  60 ms, 0 skipped frames); program `AK` unchanged; probe active=false/showing=true. **No duplication seed.** The off-canvas
  fallback measured equally clean (x 2048 read back exactly); it stays the qualification fallback only.
- **Moving-program positive control:** `Program` item off 1 s → on gives 2 `visibilitychange`, rAF gap 1020 ms → FAIL, as required.
- **Freshness latency:** the OBS screenshot trails the page's rAF counter by ~10 frames (~200 ms at 50 fps); a challenge must
  be painted ≥ 300 ms before the capture that must show it.
- **Preconditions:** transition → `GetCurrentSceneTransition` `transitionKind` `cut_transition`. DeckLink with no device:
  `GetOutputStatus("decklink_preview_output")` → code 600 "No output was found with the name `decklink_preview_output`."
  This is the only absent=pass response; it is identical for any unknown name, so the name is a pinned constant. Behaviour
  with a configured device is untested (DeckLink field test). `GetCurrentPreviewScene` outside Studio Mode → 506. No websocket
  route reads `SceneDuplicationMode`; OBS writes it to `user.ini` at launch.
- **Persistence (O5):** OBS saves `AK.json` on every create/remove (the mid-transaction file holds `AK-Probe`) and rotates the
  previous file to `.bak`; after clean quit both are the cleaned state. Null-run allowlist (seed → quit, uuids stripped):
  `modules/{auto-scene-switcher,output-timer,scripts-tool}`, `virtual-camera`, `scaling_level`, per-source `hotkeys/*`,
  scene-item `{bounds,pos,scale}_rel`. Preview quit = null quit; off-canvas differs only by `AK` `settings/id_counter` 1 → 2.
  Repeat removal of an absent object → 600 "No source was found by the name of `<name>` within the canvas `Main`."

Order: step 0/contracts → W1–W6 (within concurrency) → exact-adapter asset/probe/cleanup gates → integration/review →
targeted/full suites → previously passing DX-1 arms plus required controls → CEF preflight/DX-2 → regressions/owner check →
coordinator's PR. Failed isolation or authoritative persistence check (§2.2) blocks that placement. W5 observation rides
these captures; tone-application failure does not block identity-tone placement. Only rerun the 18-cell Chrome matrix if
snap bytes changed.

## 8. Owner decisions (2026-10-13; no open questions)

1. **O1 = INCLUDE r13 #1, bounded.** Drop the take/attachment from `patch_rendering`, re-pin both rendering digests,
   intentionally rewrite `tests/test_live_runtime.py:312`, and add forged rows to existing `m-raw-prod`/`m-preview-prod`.
   Only files already in this PR; no `html_preview.py` change or further scope.
2. **O2 = NO Chrome migration.** Launched Chrome keeps knowledge-based `snap` without expiry; parent decision 16 stands.
   No Chrome second-target/product probe or lease; recalibrate is managed-OBS-only. Chrome probe-page/classifier and W5
   tone rows are harness-only. r13 #3 stays open in the handover, including the unbounded connected-CDP residual.
3. **O3 = YES regenerated clip.** If `7b7d66b5…` cannot be recovered/reproduced exactly, replace it with a newly full-pinned
   regeneration after both-engine requalification. Never treat the prefix as a full digest or inherit old qualification.
4. **O4 = YES CEF renewal.** Renew on unchanged connection, context, engine launch identity, UA and DPR. Accept and state
   the unchanged-fingerprint GPU-fallback residual, as for Chrome r13 #3; no periodic on-air re-probe.
5. **O5 = Measure first.** Mid-transaction scene saves are accepted if the saved collection is verified identical to
   pre-probe state after cleanup, using §2.2's normalized graph/baseline and explicit allowlist. Clean quit is authoritative;
   cleanup reads are authoritative only if newer than the last removal. Crash leftovers in `AK.json` are covered by
   `_seed` on each launch. `AK.json.bak` may hold mid-transaction state but is unreachable by managed launches because
   `_seed` writes a valid primary first. Record it, no mutation; OBS reads it only if the primary is damaged.

Today's primary preview, qualified off-canvas fallback, pixel freshness, hidden OBS and restoration decisions also stand.

## 9. Risks / out of scope

- Feasibility did not prove live cleanup absence or saved-state restoration. O5 accepts mid-transaction saves, not failed
  cleanup. Never report clean without live absence and saved-state verification at §2.2's authoritative checkpoints.
  AK.json.bak may hold mid-transaction state; it is unreachable by managed launches because `_seed` writes a valid primary
  first (F5, O5). Record it, no mutation; no claim that the backup is sanitized.
- Preview and program source compositors may diverge after a GPU change. Challenge freshness proves a live probe, not
  equivalence of every program video path. Final holder gates and explicit fallback residuals remain necessary.
- Screenshot cost/load can exceed the old probe estimate. Deadlines fail closed; no overlapping screenshot burst or
  recurring scene installation every three seconds disguised as cheap lease renewal.
- Sampled RGBA cannot detect every transient alpha-only flash; the lossless program recording may drop alpha. Closing
  that residual requires an alpha-preserving recorder. Moving-program telemetry separately gates Studio-toggle stutter.
- No scaled-stage/nested-scale model, software holder qualification, arbitrary external attach, F2 transitions, bridge/held
  decoder changes, new G2 tone behavior or physical DeckLink/keyer proof. Identity-tone step and parent Q5 remain open.
- O1 closes raw/preview forgery only after its explicit controls pass. Chrome r13 #3 stays open; O4 accepts analogous CEF
  fallback that leaves renewal inputs unchanged. Keep unsupported geometry/ambiguous maps as skips; no tolerance widening.

## 10. Critique log

### r1 — Opus 5.5 high, on rev 1 db11b278

Source: scratch `critique-r1.md`; all 16 findings addressed. Owner O1–O5 decisions dated 2026-10-13 govern the folds.

| # | Severity | Disposition |
|---|---|---|
| 1 | major | Folded: no Chrome product probe/second target/lease/migration; explicit indefinite-knowledge vs leased-probe channel and managed-only recalibrate (§2.3–§2.5, §3, §5–§8). |
| 2 | major | Folded: O4 fixes CEF renewal inputs and accepts unchanged-fingerprint fallback; no SystemInfo requirement or periodic re-probe fork (§2.5, §8). |
| 3 | major | Folded: step-0 persisted-state measurement, O5 transient-save acceptance and AK.json crash reseed (§2.2, §7–§9). **Proposed backup sentence refuted:** `_seed` neither removes nor rewrites AK.json.bak (`managed_obs.py:914`, `:920`; `render_tree` file list `:148`, `:157`, `:165`; `write_tree` `:168`). Preserve the owner-specified damaged-primary backup residual; no backup-mutation scope. |
| 4 | major | Folded: moving-Program visibility/rAF/media-time gates, no-transaction null and Program off/on positive; evaluate/read back SceneDuplicationMode=false (§2.2–§2.3, §5–§7). Duplication effects are to be measured, not inferred from static captures. |
| 5 | medium | Folded: consistency per map; intermediate shares disqualify only that map; GPU-valid/identity-intermediate control (§2.4, §5–§6). |
| 6 | medium | Folded: choose preview/off-canvas at pinned-version qualification; failed runtime preview leaves invalid, never falls through (§2.2, §5). |
| 7 | medium | Folded: own calibration thread/WebSocket and engine-generation token; quit/restart/setup cancel and wait ≤5 s, liveness continues, no `_submit` calibration job; fault-table row (§2.1, §5–§7). |
| 8 | medium | Folded, O1 INCLUDE: rendering omits take/attachment; both rendering pins and equivalence test intentionally change; forged rows use existing production arms, no html_preview edit (§2.6, §4, §6–§8). |
| 9 | medium | Folded: W5 Chrome GPU/software rows are W6 harness-only CDP captures, no product grant (§2.7, §5, §7). |
| 10 | medium | Folded: previously passing DX-1 arms plus wrongrule-chrome; snap byte proof; 18-cell matrix only if snap draw/admission changed; prior INCONCLUSIVEs retained (§5–§7). |
| 11 | low | Folded: first eligible managed program context triggers a probe without blocking Take output/startup, then explicit lifecycle triggers (§2.5). |
| 12 | low | Folded: RGBA explicitly sampled before/install/each capture/cleanup/restore; transient alpha-only residual and alpha-recorder cost stated (§5, §9). |
| 13 | low | Folded: no host-time expiry inference or live sleep/wake gate; reconnect revoke/fresh invalid context plus fake-clock unit coverage (§2.5, §5–§6). |
| 14 | low | Folded: package list at pyproject.toml:58, lossless setting at managed_obs.py:146, foreground drawn into backing at live_runtime.py:148–150 (§1.1). |
| 15 | low | Folded: probe requires DPR1, other DPR unknown; fractional erosion machinery removed (§2.4–§2.5, §5–§6). |
| 16 | low | Folded: before Studio Mode, verify current transition Cut and no active DeckLink preview output; unreadable/failed precondition means no probe (§2.2, §6–§7). |

### r2 — Opus 5.5 high, on rev 2 d72238ac

Source: scratch `critique-r2.md`; all six findings folded, none refuted. O1–O5 and scope unchanged.

| # | Severity | Disposition |
|---|---|---|
| 1 | medium | Folded: OBS-saved/normalized-seed baseline, normalized scene graph and field-justified allowlist; clean quit authoritative, cleanup read authoritative only when mtime postdates last removal (§2.2, §5–§8). |
| 2 | medium | Folded: step 0 pins the exact unconfigured-preview response, absent passes while other errors/timeouts fail; duplication seed only after default fails moving gate, disk value plus behavioral readback, no invented runtime API (§2.2, §6–§7). |
| 3 | medium | Folded: runtime moving/isolation failure revokes and suppresses automatic probes for that launch; operator recalibrate may retry, new launch resets suppression (§2.3, §2.5, §5–§7). |
| 4 | low | Folded: W4 host-owned renewal timer starts on first probe grant, stops in stop(); evaluate_in deadline below remaining lease includes lock wait, missed renewal logs leaseLapsed and never extends (§2.5, §5–§7). CDP lock/default verified at live_host.py:653–661. |
| 5 | low | Folded, option (b): script-only LiveOutputHost constructor mode override; product router never passes it, Chrome product remains indefinite snap only. wrongrule-chrome forces leased frac in harness probe mode; Node fixed-mode/expiry row (§2.5, §5–§7). |
| 6 | low | Folded: backup may retain transaction state but managed launch reseeds valid primary first, so backup is unreachable there; record without mutation (§2.2, §5, §8–§9; managed_obs.py:889, :914, :920–921). |

### r3 — Opus 5.5 high, on rev 3 091a366c — READY (1 low)

| # | Severity | Disposition |
|---|---|---|
| 1 | low | Folded by the coordinator (rev 3.1): the persistence allowlist is the no-transaction null run's difference set plus `id_counter`; any difference beyond the null's FAILs (§2.2). |

## 11. Frozen contracts

New interfaces below are implementation contracts, not claims of existing APIs. Anchors verified at `ace08c4e`.
Records are Python 3.10 `@dataclass(frozen=True)`; tuples are immutable, bytes are raw bytes, times ending `_s` are
host monotonic seconds unless stated otherwise. JSON uses the field names shown; enums serialize to their string values.
`S0` = §7's step-0 evidence directory. Selected product placement: **preview**, OBS **32.2.2**, no duplication seed.
Off-canvas remains harness qualification only; no runtime fallback. O1–O5, existing acceptance gates and file ownership stand.

### 11.1 W2 → W3/W4/W6: assets, page and classifier

Existing seams: package data `pyproject.toml:58`; loopback server/range serving `live_host.py:385`, `:394`, `:433`;
probe layout/analysis `E/cef-frac-2026-10-12/scripts/probe.js` and `probeana.py`; latency `S0/README.md:16`.

```python
class ProbeVerdict(str, Enum):
    SNAP = "snap"; FRAC = "frac"; UNKNOWN = "unknown"
class ToneMap(str, Enum):
    IDENTITY = "identity"; GPU_ANALYTIC = "gpu_analytic"

@dataclass(frozen=True)
class ProbeAsset:
    name: str; sha256: str; data: bytes
@dataclass(frozen=True)
class ProbeAssets:
    manifest_sha256: str; pattern: ProbeAsset; motion: ProbeAsset
@dataclass(frozen=True)
class ProbeSpec:
    run_id: str; width: int; height: int; fps: int; dpr: float
@dataclass(frozen=True)
class ProbeIdentity:
    run_id: str; source_uuid: str | None; target_id: str; context_id: str
    connection_generation: int; ua: str; dpr: float
@dataclass(frozen=True)
class ProbeCapture:
    identity: ProbeIdentity; sequence: int; nonce: str
    phase: str; pose: int | None; png: bytes
    paint_observed_s: float; capture_started_s: float; capture_finished_s: float
@dataclass(frozen=True)
class PoseGeometry:
    pose: int; rect: tuple[float, float, float, float]
    content_box: tuple[float, float, float, float]; box: tuple[int, int, int, int]
    snap_dy: int; frac_dy: int
@dataclass(frozen=True)
class ClassifierInput:
    spec: ProbeSpec; assets_sha256: tuple[str, str, str]  # manifest, pattern, motion
    identity: ProbeIdentity; ready_state: int; video_size: tuple[int, int]
    color_tuple: tuple[str, str, str, bool]  # primaries, transfer, matrix, fullRange
    freshness: tuple[ProbeCapture, ...]; poses: tuple[PoseGeometry, ...]
    captures: tuple[ProbeCapture, ...]  # pose 0 pair, then pose 1 pair
@dataclass(frozen=True)
class PoseScore:
    pose: int; tone_map: ToneMap; snap_share: float; frac_share: float; inner_pixels: int
@dataclass(frozen=True)
class ProbeResult:
    verdict: ProbeVerdict; tone_map: ToneMap | None; grant_eligible: bool
    reason: str; scores: tuple[PoseScore, ...]

def load_probe_assets() -> ProbeAssets: ...
def render_probe_page(spec: ProbeSpec) -> bytes: ...
def classify_probe(data: ClassifierInput) -> ProbeResult: ...
```

- Package paths: `obed_edom/data/{placement_probe.mp4,placement_motion.mp4,placement_probe.json}`.
  W2 exports `PATTERN_SHA256`, `MOTION_SHA256`, `MANIFEST_SHA256`: full lowercase 64-hex release pins. `load_probe_assets`
  hashes bytes against these pins, verifies manifest agreement, raises `ValueError` before serving on any mismatch.
  **Literal digests unpinned:** old pattern full digest unavailable; motion not generated. W2 supplies them after §2.4/O3
  generation and qualification. No prefix, null, placeholder or mutable manifest alone can authorize a runtime asset.
- Manifest schema: `{schemaVersion:1, pattern:{file,sha256,bytes,width:1920,height:540,fps:30,durationS:3,
  frameTimeS:1,colorTuple}, motion:{file,sha256,bytes,width,height,fps,durationS},
  generator:{sha256,python,numpy,pillow,ffmpeg,x264,argv:string[],pngSha256,repeatSha256}}`.
  `repeatSha256` equals pattern hash from the second generation; motion is silent with a changing binary frame counter.
- W4 `_AssetServer.set_probe_run(spec: ProbeSpec | None) -> str | None` registers/clears one active run.
  URL `http://127.0.0.1:<port>/__obed_probe/<run_id>/index.html`; sibling MP4 filenames above, correct MIME/range handling.
  Only registered 32-hex `run_id` and the three fixed paths (page/two clips) resolve; no export-root resolution for them.
  Page uses relative URLs. Closing the run makes all three 404. No password or grant token in URLs/page/manifest.
- Page API: `window.__obedProbe.command({runId,sequence,nonce,phase,pose}) -> boolean` queues work;
  `snapshot() -> {runId,sequence,paintedSequence,phase,pose,readyState,videoSize,colorTuple,dpr,ua,geometry,error}`.
  `phase` is `motion|pattern`; `pose` null for motion, 0 or 1 for pattern. New sequence must increase; one pending command;
  wrong run/repeated sequence/malformed nonce returns false. Async work is polled, not returned as a Promise through
  `evaluate_in` (current `awaitPromise=False`, `live_host.py:733`). `geometry` is `PoseGeometry` with camelCase keys or null.
- Host generates a fresh `secrets.token_hex(16)` nonce for **every** capture; 128 bits, MSB-first, row-major 16×8 grid of
  8px cells at `(1600,16)`, opaque black/white, outside all movie/candidate ROIs. Decode central 2×2 pixels per cell:
  all RGB ≤32 means 0, all RGB ≥223 means 1, otherwise invalid; alpha must be 255. Decoded bits must equal nonce exactly.
  `paintedSequence` advances after painting and a subsequent rAF; it is supporting telemetry, never freshness proof.
- Wait from host observation of matching `paintedSequence` **≥300 ms before capture starts**, even after six rAFs;
  this supersedes §2.4's 200 ms settle minimum. Hold nonce/pose unchanged until capture returns. Serial captures,
  starts ≥200 ms apart, each deadline ≤2 s, total measurement ≤15 s; source dimensions 1920×1080, DPR1 only.
  Require ≥3 motion captures with distinct nonces and distinct video-ROI hashes, then switch the same video to the
  pinned pattern, seek/pause at 1.0 s; ≥6 rAFs and ≥300 ms paint wait for each of two captures per pose.
- Geometry preserves retained probe: two translation ancestors `(6+fx/2,4+fy/2)` and `(4+fx/2,6+fy/2)`, video CSS
  `480.53125×135.140625`; poses `(fx,fy)=(.352,.036),(.73,.41)`. Box floor near edges/ceil far edges +1;
  snap canvas at box y+140, frac at y+280. Candidate pixels use same paused frame; background `#404040`.
  Host validates bounds/nonoverlap, expected poses, target/context/source, decode tuple/size, full asset pins and timing.
  `source_uuid=None` is allowed only for W6's Chrome harness. Motion video ROI = the same visible video box; counter
  changes must affect it. Still pairs require identical video/snap/frac ROI bytes, excluding the separate nonce grid.
- Classifier is pure, never grants or owns CDP. Shares are fractions `[0,1]`, four scores (2 poses × 2 maps), §2.4 exact
  mask/max-channel/4-LSB/≤.02/≥.20 rules. Unknown → `tone_map=None,grant_eligible=False`; uniquely classified identity
  may return snap/frac but `grant_eligible=False`; GPU analytic uniquely classified → true. Reasons:
  `classified|invalid-evidence|stale-capture|unstable-capture|unsupported-dpr|ambiguous|software-map`.

### 11.2 W3 → W4/W6: managed calibration transaction and persistence

Current ownership/queue/error seams: `managed_obs.py:383`, `:388`, `:480`, `:484`, `:495`, `:586`, `:607`, `:914`;
`obs_websocket.py:36`, `:39`, `:52`, `:93`. W3 owns the following records/protocols in `managed_obs.py`, importing W2;
no import of `live_host`. W4 passes this adapter; no other stream touches W3 internals.

```python
@dataclass(frozen=True)
class EngineIdentity:
    pid: int; launch_date: float; ready_generation: int
@dataclass(frozen=True)
class CalibrationRequest:
    spec: ProbeSpec; url: str; engine: EngineIdentity
    program_target_id: str; program_context_id: str; connection_generation: int
    placement: Literal["preview", "offcanvas"] = "preview"
@dataclass(frozen=True)
class ProgramCheck:
    ok: bool | None; visibility_events: int; baseline_frame_ms: float | None
    max_raf_gap_ms: float | None; media: tuple[dict[str, object], ...]
    reason: str | None
class ProgramGuard(Protocol):
    def begin(self) -> None: ...
    def sample(self, phase: str) -> None: ...
    def finish(self) -> ProgramCheck: ...
class CalibrationIO(Protocol):
    request: CalibrationRequest
    source_uuid: str
    cdp_endpoint: str
    cancel_event: threading.Event
    deadline_s: float
    def capture_png(self, *, timeout_s: float = 2.0) -> bytes: ...
    def check_current(self) -> None: ...
@dataclass(frozen=True)
class CollectionSnapshot:
    state: dict[str, object]; mtime_ns: int; saved_by_obs: bool
@dataclass(frozen=True)
class PersistenceRule:
    path: str; before: object; after: object  # JSON values; missing uses {"$absent": True}
@dataclass(frozen=True)
class PersistenceCheck:
    phase: str; authoritative: bool; ok: bool | None
    differences: tuple[str, ...]; allowed: tuple[str, ...]
@dataclass(frozen=True)
class CalibrationResult:
    request: CalibrationRequest; evidence: ClassifierInput | None; program: ProgramCheck | None
    isolation_ok: bool; cleanup_verified: bool; restored: bool
    persistence: PersistenceCheck | None; errors: tuple[str, ...]
    started_s: float; finished_s: float
class CalibrationAdapter(Protocol):
    def identity(self) -> EngineIdentity | None: ...
    def start(self, request: CalibrationRequest, *,
              measure: Callable[[CalibrationIO], ClassifierInput],
              guard: ProgramGuard) -> Future[CalibrationResult]: ...
    def cancel(self, run_id: str, *, timeout_s: float = 5.0) -> bool: ...

def read_collection(path: Path, *, saved_by_obs: bool) -> CollectionSnapshot: ...
def persistence_allowlist(null_before: CollectionSnapshot,
                          null_after: CollectionSnapshot) -> tuple[PersistenceRule, ...]: ...
def check_persistence(before: CollectionSnapshot, after: CollectionSnapshot, *,
                      null_allowlist: tuple[PersistenceRule, ...], phase: Literal["cleanup", "quit"],
                      last_removal_mtime_ns: int) -> PersistenceCheck: ...
# ManagedObs.calibration_adapter() -> CalibrationAdapter
```

- `start` returns immediately; W3 creates one dedicated thread/OBS WebSocket, rejects concurrent runs with
  `ManagedObsError("Calibration is already running.")`. Validates engine/program and URL before mutation. Worker calls
  guard.begin → install → measure(io) → cleanup/restore → guard.finish → resolves future **after all cleanup attempts**.
  `guard.sample` phases: `before-install|installed|before-capture|after-capture|before-cleanup|restored`.
  `media` entries: `{id:str,playing:bool,monotonic:bool,maxStallMs:float,frameMs:float}`; unknown baseline/media → ok null.
  W4 implements guard on existing Program CDP, and measure on a separate probe CDP transport discovered by exact URL.
  The probe transport registers `io.cancel_event`; W4 closes it in measure-finally. Server run clears only after cleanup.
  Captured evidence must retain W3's source UUID and original program/connection binding from request.
- `check_current` before/after each short mutation/capture checks cancellation, generation, ownership and deadline;
  raises `ManagedObsError` on failure. No grant in callbacks/W3. Exceptions become `errors`, evidence may be null;
  guard/cleanup errors still resolve a failed result. `capture_png` rechecks isolation and returns raw decoded PNG bytes,
  never unpremultiplies; WebSocket max message = 16 MiB, per-request timeout ≤remaining budget. Existing other calls retain
  their defaults. Cancellation closes measurement transports; cleanup gets its own ≤5 s budget/connection if needed.
- `cancel` sets event, waits at most timeout (capped 5 s), returns verified cleanup success; absent finished run is idempotent.
  Quit/restart/setup cancel before generation change; fence/close old transports before replacement. Old worker cannot
  mutate new engine. No `_submit` job, session-lock hold, CDP event callback work, or future wait on the request thread.
- Exact prechecks/constants (`S0/README.md:17–21`, `preview/result.json`):
  `CALIBRATION_SCENE="AK-Calibrate"`, `PROBE_SOURCE="AK-Probe"`, `PROGRAM_SCENE="AK"`, `OBS_CANVAS="Main"`;
  `PREVIEW_OUTPUT="decklink_preview_output"`; `GetCurrentSceneTransition` must return
  `{transitionName:"Cut",transitionKind:"cut_transition"}`. `GetOutputStatus({outputName:PREVIEW_OUTPUT})` must return
  `outputActive:false`, or `ObsRequestError` with request_type `GetOutputStatus`, code **600**, comment exactly
  `No output was found with the name \`decklink_preview_output\`.`. No other name/error/timeout means absent.
  `GetCurrentPreviewScene` **506** is expected only while Studio Mode is off (measured comment null); snapshot off,
  enable Studio, then capture the retained preview before switching it. A 506 while on is failure, not absence.
- Removal absence constants: `(RemoveInput,600,"No source was found by the name of \`AK-Probe\` within the canvas \`Main\`.")`
  and `(RemoveScene,600,"No source was found by the name of \`AK-Calibrate\` within the canvas \`Main\`.")` only.
  Still poll scene/input/item lists to prove absence. No generic code-600 catch; unmeasured RemoveSceneItem errors fail.
  Restore saved preview before disabling Studio; restore Studio/program and verify ownership/identity, attempt every
  cleanup step despite earlier errors. Collision with unowned names fails before creation. Never transition to program.
- O5 compare source/scene sets by UUID/name, item order/visibility/transforms and remaining state; preserve UUIDs within
  the transaction. Only null-run derivation canonicalizes cross-launch UUIDs by original source/scene names, never drops
  new sources/refs. `last_removal_mtime_ns` is the wall-clock ns checkpoint at final removal acknowledgement, not monotonic.
  Cleanup authoritative iff `after.mtime_ns > last_removal_mtime_ns`; otherwise ok null. Quit always authoritative;
  missing/malformed file is failure. W6 supplies quit snapshot; product never quits merely to complete calibration.
  A non-authoritative cleanup file does not block a grant after live cleanup and already-qualified persistence gates;
  an authoritative mismatch blocks it. Backups are recorded separately, never restored/mutated by this API.
- Null allowlist is exact **before→after values**, not wildcard deletion. `STEP0_NULL_ALLOWLIST` comes from
  `S0/null/{0-ready,5-quit}-AK.json`: missing modules `auto-scene-switcher`
  `{interval:300,non_matching_scene:"",switch_if_not_matching:false,active:false,switches:[]}`,
  `output-timer` (streamTimerHours/Minutes/Seconds and recordTimerHours/Minutes/Seconds all 0,
  autoStartStreamTimer/autoStartRecordTimer/pauseRecordTimer false), `scripts-tool=[]`; missing `virtual-camera={type2:3}`;
  `scaling_level:0→-49`; missing Program hotkeys `ObsBrowser.Refresh`, `libobs.{mute,unmute,push-to-mute,push-to-talk}`
  and AK hotkeys `OBSBasic.SelectScene`, `libobs.{hide,show}_scene_item.1`, each `[]`;
  original Program item additions `bounds_rel={x:3.555555582046509,y:2}`, `pos_rel={x:-1.7777777910232544,y:-1}`,
  `scale_rel={x:1,y:1}`. Already-normalized baseline fields must stay equal. Plus only original scene `settings/id_counter`
  may increase monotonically; item membership/order still equal. New keys/values outside these measured transitions fail.
  W3 pins exact null records in its existing test file; W6 remeasures for a changed OBS version, never expands allowlist silently.

### 11.3 W4 → W1/W5/W6: host, grant and status

Seams: `LiveOutputHost.__init__` at `live_host.py:892`; private channel `:54`, `:103`, `:110`, `:118`;
context evaluation `:727`; output `:961`, `:1126`, `:1248`; stop `:1614`.

```python
# Add keyword-only constructor parameters (all existing arguments preserved):
calibration: CalibrationAdapter | None = None
placement_mode: Literal["knowledge", "probe"] | None = None
# placement_mode is script/test-only; router never supplies it.
# None resolves to probe iff calibration exists + bridge == "obs-managed", otherwise knowledge.
def placement_init_script(token: str, *, mode: Literal["knowledge", "probe"] = "knowledge") -> str: ...
def _placement_set_expr(token: str, value: str, ms: int | None = None) -> str: ...
def _placement_round_trip_expr(token: str, *, mode: Literal["knowledge", "probe"] = "knowledge") -> str: ...
```

| Channel contract | Exact behavior |
|---|---|
| `window.__obedPlacement` | Getter → `"snap"|"frac"|"invalid"`; initially invalid; no setter, nonconfigurable/nonenumerable. W1 reads once per take. |
| `window.__obedGrant(token,value,ms)` | Nonwritable/nonconfigurable/nonenumerable function → boolean; wrong token false/no mutation. Correct token + invalid revokes, true. Unknown value or invalid lease revokes, false. |
| Knowledge mode | Only snap without ms grants indefinitely (same Chrome eligibility); frac or supplied ms invalid. No timer/probe on Chrome product. |
| Probe mode | snap/frac requires finite integer `0 < ms <= 15000`; store private `{value,leaseMs,expiresAt}` using a bound pre-page monotonic clock. Getter returns invalid at/after expiry, never trusts page time functions. |
| Installation/round trip | Install before navigation; mode immutable. Probe round trip uses ms=15000, synchronous grant/read/finally-revoke/read; commit original uniqueContextId only. No token in product JSON. |
| Renewal | Host timer every3s/pre-navigation, O4 fingerprint unchanged; deadline/lock budget below remaining lease. Miss → leaseLapsed, no delayed extension. Stop joins/cancels timer and calibration before releasing server/transport. |

Product JSON (W4 publishes; W5 types/passes through; `at`/`leaseExpiresAt` are Unix seconds, expiry is advisory only):

```typescript
type Placement = {
  state: "invalid" | "probing" | "valid";
  grant: "snap" | "frac" | null;
  reason: string | null;
  at: number | null;
  product: string | null;
  gpuCompositing: string | null;
  method: "knowledge" | "probe" | null;
  probeId: string | null;
  leaseMs: number | null;
  leaseExpiresAt: number | null;
  tone: { observed: "identity" | "gpu_analytic" | null; applied: "identity" };
  automaticProbesDisabled: boolean;
}; // output.placement; additive to existing output fields
```

`grant=null` is JSON invalid; state probing never advertises a grant. Knowledge lease fields null. Host timestamps never
prove document expiry; reconnect requires revoke/fresh context. `probeId` is latest scheduled run, retained on failure;
no source UUIDs, tokens or nonce pixels in product JSON. Detailed records are logs/W6 only.

| Event | Transition/action |
|---|---|
| First eligible managed context; reload/source refresh/reconnect/observed engine or GPU change | invalid → probing after revoke, subject to launch suppression; defer while player transition busy; allocate run ID once. |
| Valid result | Only same engine/context/connection + GPU eligible classifier + program.ok=true + isolation/cleanup/restore true + no errors/authoritative persistence failure → valid, lease commit. |
| Failed/cancelled/stale result; changed/unreadable fingerprint; expiry | → invalid, no old grant restoration. Reason published; late generation ignored. |
| Runtime moving/isolation failure | invalid + automaticProbesDisabled=true until new engine launch; record reason. |
| Operator recalibrate | invalid/valid → probing even when automatic probes disabled; duplicate probing request rejected; manual success does not clear suppression. |
| Stop | invalid, cancel/drain; late completion ignored. No new session status enum. |

Managed reason vocabulary: `not-calibrated|waiting-for-transition|calibrating|granted|unsupported|probe-failed|
program-disturbed|isolation-failed|cleanup-failed|persistence-failed|cancelled|stale-result|revoked-fingerprint|
leaseLapsed|disconnected|stopped|channel-compromised`. Existing Chrome reason strings remain unchanged.
W4 consumes W2 classify result after W3 future; logs result and every rejected commit. Script-only `placement_mode="probe"`
permits leased wrong-rule forcing on Chrome; it does not schedule a Chrome probe or enable recalibrate without adapter.

### 11.4 W5 ↔ W4: command and presenter

Existing wire/adapter contract: `web/live.py:48`, `:279`, `:301`; `live_session.py:32`, `:112`, `:128`, `:280`, `:379`;
`dashboard/src/live/api.ts:1`, `:29`, `:41`; presenter sender/status `LivePresenter.tsx:204`, `:215`, `:230`, `:305`.

```text
POST /api/live/{session_id}/commands
request  = {requestId:string, operation:"recalibrate"}   # no slide (null tolerated as existing default)
response = {requestId, outcome:"completed"|"rejected", reason?:string, state:LiveSnapshot}
capabilities.recalibrate = {supported:boolean, reason?:string}
host.execute("recalibrate", None) -> PlayerObservation
router managed-host construction: calibration=engine.calibration_adapter()  # existing managed engine instance
```

- `completed` acknowledges **scheduling**, not successful calibration; `state.output.placement.state="probing"` and probeId
  identify that run (possibly waiting for a transition). Return cached scheduling observation without waiting for capture.
  Preserve scene/build/visibility/player status; increment session revision for status publication. Never add to
  `pending_navigation`/`pending_visibility`; normal request-ID replay/conflict handling remains. Stop stays prompt.
- Capability supported only for owned ready managed OBS, live session, not already probing; automatic suppression does
  not disable manual recalibrate. Chrome/headless/external attach → false. Include key in loading/default/apply capability
  lists and TS `LiveOperation`. Do not add a route or change the `PlayerAdapter` protocol.
- Extend output with optional `placement?: Placement` for older snapshots. Button `Recalibrate output`; probing status
  `Calibrating…`; valid `Output calibrated`; initial invalid `Output not calibrated`; failed invalid
  `Calibration unavailable. Movies use the standard transition.`; suppressed `Calibration paused. Recalibrate output to retry.`
  Unsupported reason `Recalibration is available only for managed OBS output.`; probing rejection `Calibration is already running.`
  Deferred reason `Waiting for the current transition to finish.`; disconnected `Waiting for connection to output host`.
  Shared connection/session/Stop guards remain; disable recalibrate during its run, not navigation/Hide/Stop for 15 seconds.
  Scheduling completed does not set presenter awaiting-navigation state; observe status through existing polling.

### 11.5 W1 ← W4: take admission and rendering split

Verified seams: `live_runtime.py:74`, `:79`, `:120`, `:125`, `:141–156`, `:298`, `:324`, `:338`;
`tests/test_live_runtime.py:312`. No new Python public player arguments.

```text
input pl = window.__obedPlacement (one read)
shared = existing tuple Q / paint / visibility / layer / clip / translation guards AND kx=ky=1
snap = pl=="snap" AND DPR in {1,1.5,2} AND shared                 # existing snap draw unchanged
frac = pl=="frac" AND DPR==1 AND integer(R.left,R.top) AND shared
other = skip; still publish __obedTakeMs
frac draw = existing snapped underlay THEN drawImage(v,fx,fy,round(cw),round(ch2))
fx = dx+(r.left-R.left)+round(cx-r.left)-u0
fy = dy+(r.top-R.top)+round(cy-r.top)-v0
frac refuses (no holder) when any holder cell centre lies outside the quad: fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5
then whole-backing alpha==255 scan
frac then redraws only partially covered boundary rows/columns (and their intersections) from the video at the frac
  mapping's pixel centres, clamped to edge texels: sx=clamp((e+.5-fx)*vw/fw-.5,0,vw-1), likewise sy   # amended 2026-10-14
then existing foreground draw / D3 holder attach
patch_player(stock, mm_opacity=True) = rendering fidelity + freeze take/attachment + observation
patch_player(stock, mm_opacity=False) = existing byte-identical off variant
patch_rendering(stock) = rendering fidelity only (no observation, executable freeze take or D3 attachment entry)
```

W1 consumes no lease metadata, tone map, probe DOM or UA; getter is sole grant input. `SUPPORTED_PLAYERS[*][0]` and `[2]`
re-pin final bytes for both stock digests; `[1]` unchanged. Rendering/live-minus-hook-minus-take/attachment equivalence
is intentional. Crossfade/cut and non-freeze composition remain unchanged; no disk `main.js` edits or `html_preview.py` edit.

### 11.6 W6 ← W1–W5: evidence and gates

Consume W2 assets/page/capture/classifier; W3 adapter/guard-result/persistence API; W4 constructor/channel/status;
W5 recalibrate wire; W1 final pinned bytes. Chrome uses harness CDP and script-only mode, never product calibration.
Keep existing run/gate formats (`dissolve_probe.py:1267`, `:3774`, `:3916`; `managed_obs_qualify.py:2235`). Add:

```text
runs/<arm>/record.json.placementCalibration = {
  schemaVersion:1, backend:"cef"|"chrome-harness", placement:"preview"|"offcanvas"|null,
  obsVersion:string|null, engine:EngineIdentity|null, request:CalibrationRequest|null,
  assets:{manifestSha256,patternSha256,motionSha256}, player:{stockSha256,liveSha256,renderingSha256},
  input:ClassifierInput|null, classification:ProbeResult|null, transaction:CalibrationResult|null,
  events:[{at:number,event:string,placement:Placement}],
  persistence:{baseline:CollectionRef,nullBefore:CollectionRef,nullAfter:CollectionRef,cleanup:CollectionRef|null,
               quit:CollectionRef|null,backup:FileRef[],lastRemovalMtimeNs:number,checks:PersistenceCheck[]}|null,
  integrity:{recording:FileRef|null,rgba:FileRef[],telemetry:FileRef|null},
  gates:{[name]:{verdict:"PASS"|"FAIL"|"INCONCLUSIVE"|"REPORTED",problems:string[],detail:object}}
}
FileRef = {path:string,sha256:string}  # relative to run, full digest; no secrets/absolute credentials
CollectionRef = FileRef & {mtimeNs:number,savedByObs:boolean}  # original file metadata, not copied-file mtime
```

Dataclasses serialize recursively with snake_case fields/enum values; replace each `ProbeCapture.png` with FileRef to
raw lossless PNG, never stringify bytes. Non-null transaction `evidence` serializes as
`{"$ref":"#/placementCalibration/input"}`; offline reader resolves it to the same ClassifierInput.
`at` is Unix seconds; capture timing retains monotonic fields. Raw collection snapshots, manifest, code versions and
player digests are retained with hashes. No unsupported object via `default=str` in this new record.
Gate names are §5 names; each stores null/positive/candidate IDs in detail. Missing evidence → INCONCLUSIVE, never expected
FAIL. Feed gate results into existing verdict.json/DX-2 summary; offline rescore calls the same classifier/persistence API.
No new acceptance scope. Unpinned release data: W2's three asset digests and W1's new patched digests await generation;
configured-device preview-output behavior remains an explicit field-test qualification, not a guessed contract.

## 12. Implementation status (paused by the owner 2026-10-13 ~18:35)

Branch `claude/cef-obs-placement` (local only, not pushed). Commits: `bd7f354c` skeleton → `ecb1de98` W1–W6 (Codex GPT-5.6 Sol
high) → `ba3b9ff5` review r1 fold → `eb46413f` review r2 fold. Reviews: Opus 5.5 high, two reviewers (product / probe+harness).
Raw rounds, implementer briefs and reports: `.agents/reviews/cef-placement-2026-10-13/` (plan critiques under `plan/`).

| Round | Product | Probe + harness |
|---|---|---|
| r1 on `ecb1de98` | 1 major, 6 medium, 9 low | 1 blocker (content_box), 4 major, 8 medium, 5 low |
| r2 on `ba3b9ff5` | 0 major, 4 medium, 4 low (15/16 r1 closed) | 3 major, 4 medium, 7 low (7 fold regressions) |

W2 regenerated the pruned clip byte-for-byte (`7b7d66b582d1…`; identity with the pruned file corroborated by size + prefix
only, O3 not needed). Coordinator test run on `ba3b9ff5`: all touched files 1203 passed, 1 skipped, 3 known external census
reds (Stage T fixture). r2 fold `eb46413f`: implementer-reported W3 28/28, W4 348, W6 484 + 1 skipped.

**Resume in this order:** (1) coordinator re-run of all touched test files on `eb46413f` (not yet done: machine was loaded);
(2) review r3 (final round; same two reviewers, verify r2 closure); (3) full suites on 3.12 and the 3.10 floor + dashboard
`test:ui` (machine window); (4) live `managed_obs_qualify.py --arm placement` + DX-1 re-run arms (machine window, OBS);
(5) W7 docs (README, skill, handover); (6) owner check; (7) PR.

**Update 2026-10-14:** resumed, merged main, r3 (final) folded, full suites green on `4c5771b6`, three live qualification
runs (product bugs found live and fixed in `3eae0fde`/`ae1c0f63`, r4/r4b 0 major); that handover is superseded by
`.agents/handovers/cef-placement-2026-10-14.md`.

**Update 2026-10-14 (evening): live-qualified.** Pass 2A's INCONCLUSIVEs came from an inherited paused-animation validator
bug that masked harness defects (fixed `1638a085`). Live passes then found a frac top-edge residual (9 LSB, τ 4) — owner chose a
product fix: the §11.5 boundary redraw above (`2d64a25e`, Astra plan, Opus critique + reviews). Harness/scorer folds
`f8059380`/`398ddd1d`: DSK frame identity from the drawn VideoFrame, session-level DSK recapture on a sole coverage shortfall,
`m-fg-cef` as the CEF frozen_region positive control (a paused-capture control can never produce it), transient "unknown" OBS
ownership retried within the deadline, Chrome classifier rows read their own records. `cut` and `tone` are REPORTED for this PR
(owner; identity take). Final live run on `f8059380`/`398ddd1d`: 25 fps ×2 and 30 fps ×2, all valid; 30 fps PASS live, 25 fps
PASS on offline rescore with the Chrome-row fix (29/29 arms MATCH each). Evidence: `E/cef-placement-live-2026-10-14/`. Open items
and resume order: `.agents/handovers/cef-placement-2026-10-14.md`.
