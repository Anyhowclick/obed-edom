# Alpha Keynote: CEF/OBS placement calibration and the fractional movie freeze

**rev 1 — 2026-10-13; implementation proposal, not approved.** Base: `claude/cef-obs-placement-plan` @ `eb1fb6d2`.
Plan only: one new file; no product edits, commit, OBS, Chrome or Keynote run.
Parent: `keynote_live_dissolve_crossfade.plan.md` **rev 17**, landed #262; its §12 decisions 1–16 govern except where
today's explicit follow-up request restores probe work. Earlier probe design: `git show 41ef609b:.agents/plans/keynote_live_dissolve_crossfade.plan.md`,
§3.3 and §9. Handover: `.agents/handovers/keynote-live-dissolve-crossfade-followups.md`, items 1–5, r13 and W5.
All repository anchors below were read at this base; proposed names and behavior are design, not claims of existing code.

## 0. Summary

Extend the private placement channel with a compositor-measured `frac` grant. Probe a dedicated `AK-Probe` browser source
in **hidden Studio Mode preview of `AK-Calibrate`**, outside the program graph. If preview cannot be qualified, use an
enabled off-canvas nested calibration scene on `AK`, installed disabled → positioned → read back → enabled. Passive
off-program scenes, disabled items and hiding behind `Program` are rejected by the owner and measured evidence (§1.2).

Fresh host challenges visible in OBS screenshots and changing video pixels must establish a live source before the paused
two-pose classifier runs. A successful, isolated, cleaned-up transaction grants a context-bound lease; every uncertainty
means no freeze. The player draws the snapped underlay plus CEF's fractional quad, only at DPR 1 and integer stage origin.
W5 records the tone-path map; the take remains identity-tone. r13 #1 and #3 are explicit scope decisions (§4, §8), not
silently included fixes. No acceptance result is claimed by this plan.

## 1. Facts

### 1.1 Verified code seams

| ID | Fact and verified anchor |
|---|---|
| F1 | The take reads `window.__obedPlacement`, admits only `snap`, retains the DPR/translation/paint guards, draws once, scans the whole backing for opacity, then redraws foreground. D3 attaches holders to the transition wrapper. `src/obed_edom/live_runtime.py:74`, `:79`, `:113`, `:140`, `:145`, `:154`. |
| F2 | Both supported stock players have output pins; `patch_player` applies count-checked rendering replacements plus the observation hook; `patch_rendering` uses the same rendering replacements without the hook. Thus the rendering-only variant contains the executable take today. `src/obed_edom/live_runtime.py:11`, `:298`, `:324`, `:338`. |
| F3 | The first-run private getter/updater currently accepts only `snap`, without expiry. Installation precedes navigation; attached hosts install the channel but never grant. Eligible launched Chrome is major 154 with readable enabled GPU compositing; the round trip revokes in `finally`, and commit targets a unique context. `src/obed_edom/live_host.py:53`, `:110`, `:1198`, `:1222`, `:1265`. |
| F4 | CDP events are consumed while waiting for replies; default contexts are tracked, and `evaluate_in` uses `uniqueContextId`. Browser-target calls use a separate socket for launched Chrome. `observe()` synchronizes placement; fingerprint failure revokes an existing grant. These are not autonomous reconnect/probe machinery. `src/obed_edom/live_host.py:653`, `:676`, `:704`, `:727`, `:1280`, `:1402`. |
| F5 | `ManagedObs` serializes jobs on its worker and owns the private credentials. Its seed contains `Program` in `AK`; hidden launch and readiness identify the managed target. Calibration must not contaminate that target lookup. `src/obed_edom/managed_obs.py:96`, `:333`, `:586`, `:607`, `:872`, `:938`, `:953`. |
| F6 | The WebSocket client documents read-only product use, subscribes to no events, skips unrelated responses and has absolute request deadlines; its message cap is 4 MiB. Mutating calibration requests are a deliberate new product capability, not an existing screenshot API. `src/obed_edom/obs_websocket.py:1`, `:21`, `:75`, `:93`, `:121`. |
| F7 | The router passes the managed endpoint, target and bridge to `LiveOutputHost`, but no calibration adapter. `CommandBody` and session validation accept advance/goTo/hide/show/stop. Capabilities enumerate the first four; non-navigation commands currently enter `pending_visibility`. Recalibrate cannot simply use that branch. `src/obed_edom/web/live.py:48`, `:279`, `:302`; `src/obed_edom/live_session.py:112`, `:280`, `:293`, `:379`. |
| F8 | The presenter has the same operation union, output metadata without placement typing, capability-based disabling and a shared command sender. `dashboard/src/live/api.ts:1`, `:29`, `:41`; `dashboard/src/live/LivePresenter.tsx:204`, `:215`, `:305`. |
| F9 | DX-2 captures `AK`, unpremultiplies OBS RGB for the dissolve scorer, and currently enforces `attached`/no holders on every dissolve session. The harness can make lossless recordings. `scripts/managed_obs_qualify.py:288`, `:297`, `:526`, `:722`, `:1558`; `src/obed_edom/managed_obs.py:132`. |
| F10 | Holder scoring already requires a verified foreground mask and tests interior and edge band separately; reference capture and scope/grant checks are distinct. Reuse these rather than creating a second pixel oracle. `scripts/dissolve_probe.py:1760`, `:1790`, `:1814`, `:1829`, `:2427`, `:3317`. |
| F11 | Packaging currently includes YAML/JS, NE data and JPG, not MP4. A source-tree-only fixture would not ship. `pyproject.toml:57`. |

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

Do not execute a long calibration under the session adapter lock or from a CDP event callback. A bounded cancellable worker
does probe I/O through its own connection; short program-context operations use the existing serialized CDP transport.
OBS graph mutations remain serialized with managed restart/quit/setup. Stop cancels first, drains cleanup, and never waits
for a worker that needs a lock Stop holds. Observations expose progress; they do not recursively launch another probe.

### 2.2 OBS isolation, primary and fallback

Before any mutation, snapshot Studio Mode, preview scene, program scene, canvas dimensions, transition state and relevant
scene items/transforms/order. Require the owned ready engine and expected program `AK`; reject a transition already in
flight. Record identities as well as names. Never operate on a colliding object whose ownership is unproved.

**Primary:** create `AK-Calibrate` and its enabled `AK-Probe` without adding either to `AK`. Enable Studio Mode if needed,
select `AK-Calibrate` as preview, and verify program is unchanged, source active=false/showing=true, correct target and
visible probe document. Never call a transition-to-program operation. Keep OBS inactive with no on-screen window; do not
use `isHidden()` alone as proof (feasibility report, **Ranked product recommendation**). Use the program browser's source
FPS, source dimensions and measured DPR; initially qualify 1920×1080/DPR 1 in managed OBS.

**Fallback:** after verified primary cleanup, create the calibration scene reference in `AK` **disabled**, with the probe
still silent. Set a translation beyond the current canvas (positive margin), identity scale/rotation, no crop/bounds
surprises, no filters or show/hide transitions. Read back the complete effective bounds and prove their disjointness
from the canvas before enabling. Verify active/showing and freshness. A nested scene is preferred so one disabled
reference isolates the whole probe. Never briefly enable at the default origin. Recheck geometry/source size/canvas
and state before every capture; unexpected mutation aborts, disables the reference and invalidates the result.

Fallback is for unavailable/unqualified preview, not a retry after observed program contamination or unverifiable cleanup.
Do not implement zero-scale, full-crop, occlusion or projectors as additional choices. Both placements must be audio-silent:
no audio track, muted HTML video, OBS audio rerouted and muted, mixers disabled, monitoring off, each read back before use.

**Restoration, every exit:** revoke pending grants; disable any fallback reference first; restore the saved preview before
turning Studio Mode back off; remove owned scene references, inputs and scene; continue past verified already-absent errors;
poll enumerations for absence and read back Studio Mode/preview/program. Attempt remaining steps after each error. Never
transition `AK-Calibrate` to program. If an unexpected program change occurs, invalidate and report isolation failure;
restore the saved program directly only while managed ownership is still established. A transient leak still fails the gate.

No seed entries, persisted calibration grant, fixture URL or temporary objects may survive in the scene collection or
backup. Verify the live graph and persisted collection after cleanup/clean exit; recover only positively owned leftovers
before the next session. Do not rewrite live OBS JSON or copy the scratch report's post-exit restoration into the product.
OBS autosave/non-persistence must be established on the exact transaction: an acknowledgement or eventual clean shutdown
does not prove the owner's “nothing persisted” rule. If temporary objects are saved during a transaction and the available
API cannot prevent it, report a blocking feasibility gap; do not quietly redefine the requirement as eventual cleanup.

### 2.3 Chrome isolation and runtime verification

For host-launched Chrome, use a second target of the same browser, away from the output display, with matching actual DPR.
Do not use device-metrics emulation to impersonate a DPR. Keep program DOM, videos, viewport, focus and visibility untouched.
Close the target and its connection in the same transaction-finally path. A second target that cannot be isolated means
no probe grant. The proposed migration of the existing Chrome fast grant is the explicit O2 decision (§8).

For either backend, verify target identity, program scene/graph and source geometry before/during/after measurement, and
sample program captures for a known static program. The **release gate** in §5 additionally records the actual OBS program
continuously. `GetSourceScreenshot(AK)` is not a recording of the program wire (§1.2).

On-air calibration must not pause a live program to manufacture a static reference. With natural program motion, compare
structural isolation invariants and record captures as diagnostic, not a false byte-equality PASS. Permit on-air operation
only for the placement/backend whose full static RGB+RGBA qualification has passed; defer starting while a transition is
in flight. No qualified isolation implementation means invalid placement and stock movie behavior.

### 2.4 Freshness, clip provenance and classifier

**Assets.** During implementation, promote the retained `hidpi/scripts/genvid.py` recipe into a reproducible generator.
Generate `p2like` at 1920×540, seed 7, three seconds/30 fps, libx264 High, QP 1, yuv420p, TV-range BT.709 with the exact
retained scale/tags/x264/faststart arguments. Record generator, NumPy/Pillow, FFmpeg and encoder versions, generated PNG
digest, MP4 byte count, full sha256 and decoded-frame/color metadata. Regenerate twice in the pinned toolchain. Recover
the old full digest if possible; the prefix and byte count are corroboration, **not a cryptographic pin**. If exact recovery
fails, use O3: qualify the newly full-pinned clip through both engines and all controls before shipping; never invent the
missing suffix or claim the regenerated file is the old artifact. Ship `data/placement_probe.mp4` and a provenance manifest,
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
These are deadlines to qualify, not a claim that the old “about 1.5 s” estimate holds. Timeout, cancellation, wrong PNG size,
DPR mismatch, unreadable state or insufficient fresh captures aborts without a grant. Size the screenshot message limit
explicitly for full-size PNG/base64 plus envelope; the existing 4 MiB cap (F6) must not truncate valid captures or become unlimited.

**Classifier, host only.** For each pose and candidate `c ∈ {snap, frac}`, over the box eroded by **3×DPR device pixels**:

`share(c, M) = count(max(|V.R−M[C.R]|, |V.G−M[C.G]|, |V.B−M[C.B]|) > 4) / inner_pixel_count`.

Use pixel-center inclusion for fractional erosion distances (including DPR 1.5), not the prototype's `3*int(DPR)` shortcut.
`M` is identity or the fixed analytic GPU table `round(255·sRGB((i/255)^1.961))`. A map qualifies a pose only if exactly one
rule has share ≤2% and the other ≥20%. Require one consistent map/rule across **both** poses; reject contradictory maps,
disagreeing poses, intermediate shares, empty masks and malformed evidence. Only a GPU-map classification can grant;
record identity/software results but leave invalid until their holder pixels are separately qualified. Do not infer `frac`
from a CEF UA. Record all shares, map, tuple, readiness, DPR, geometry, identity, hashes and capture timings.

### 2.5 Grant lifecycle and operator command

Restore rev 16's **invalid → probing → valid** lifecycle for probe-derived grants. `valid` means a successful classifier,
verified isolation and completed cleanup, all for the same engine/connection/program context. Revoke before starting every
probe. Commit only to its original `uniqueContextId`, after rechecking generation/fingerprint; late completion never grants
into a replacement page. A failed re-probe never restores the previous result. Reload, source refresh, reconnect, engine
restart, observed GPU change, DPR/canvas/source change and lost calibration placement invalidate the active transaction.

Extend the existing `__obedGrant` channel to `snap | frac | invalid`, private state and non-writable/non-configurable
properties. Probe grants have a maximum **15 s lease**, using a bound clock captured before page code runs. Retain token
secrecy and eligibility-before-round-trip (r13 #2, F3): one context-bound synchronous set/read/revoke/read evaluation with
revocation in `finally`, then a separate verified commit. Test forcing uses this privileged channel, never page assignment.

Renew every 3 s and immediately before advance/goTo only on the same connection/context/engine identity, after reading the
fingerprint. A timer tick alone cannot renew. A changed or previously readable-now-unreadable fingerprint revokes; explicit
GPU reset signals trigger re-probe. Treat unavailable CEF browser-target `SystemInfo` as a declared backend limitation,
not as “GPU enabled”: require the measured GPU tone path and available managed identity/settings, record capability absence,
and do not blindly renew a lease from no observations. Do not broaden the launched Chrome browser-target API by guessing an
attached endpoint. Qualify an OBS-supported fingerprint route or expire and re-probe; report the unchanged-fingerprint
residual under O2. Keep-alive is grant maintenance, not screenshot acquisition or keeping a probe scene installed.

On CDP/OBS connection loss, drop host state immediately and cancel renewal. Reconnect first revokes in the old document,
then re-probes before another valid grant. If revocation cannot be delivered, navigation waits until successful revocation
or a conservatively proven expiry; use the upper bound on any in-flight renewal, not merely its last acknowledgement.
Test renderer suspension/sleep before relying on elapsed host time to prove page-clock expiry; absent proof, require a
fresh invalid context. Internal automatic transitions can still run; a lease bounds some stale windows, never eliminates
all GPU fallback races (§4). Hide and Stop remain usable.

`recalibrate` is a capability and command end to end (F7–F8). Add it to the API and session validation/capabilities, without
a slide argument. It acknowledges scheduling and exposes the run state; it must not enter `pending_visibility`, change
`outputVisible`, advance the slide or wait for a navigation revision. Duplicate request IDs do not schedule twice. Keep
Stop prompt; reject/coalesce another recalibration while probing, and discard results for a stopped/superseded session.
The presenter offers **Recalibrate output**, “Calibrating…”, valid, or a concise unavailable reason. Disable only according
to capability/connection/run state; do not expose tokens, source UUIDs or classifier internals in operator copy.

Extend `output.placement` compatibly: `state`, `grant`, `reason`, `at`, existing product/GPU fields, `method`, `probeId`,
lease expiry and `tone: {observed, applied: "identity"}`. Detailed capture/classifier/cleanup evidence belongs in logs.
Channel compromise retains the existing hide/refuse-show rule (F3); ordinary unqualified placement keeps the presentation
usable with the baked-frame jump. Update engine/host reasons without turning an ordinary probe failure into session error.

### 2.6 Fractional take and immutable player rules

Make changes only through **sha-pinned, count-checked in-memory `patch_player` replacements** (F1–F2); never edit an
export's `main.js` on disk. Preserve `mm_opacity=off`, `RUNTIME_VERSION=2`, D1/D2 cross-fade/cut semantics, the scene/paint
allowlists and add-only D4/D3 lifecycle. Minimal code comments. Re-pin both supported players and every intentionally
changed rendering variant; prove unrelated replacement composition and anchors remain intact.

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
color patches and skin tones; two fresh launches each of headless GPU/software and managed OBS acceleration on/off;
same tagged tuple, plus CEF hevc10 and Keynote-HEVC. Record unsupported decoding explicitly. Verify repeatability,
GPU/software discrimination and invalidation on GPU loss/reset/acceleration change. The feasibility test's video ROI
differences are freshness evidence, not tone qualification (§1.2).

Non-identity application requires W5 go, owner approval of the player-boundary change, and parent decision 5's bars:
each measured encoding in the qualified tuple fits within 2/255, two CEF launches agree within 1, analytic vs measured
table within 1 or use the measured table. Requalify geometry, foreground and cost on the exact tone-writing bytes.
Until then `Q` and identity `L` stay unchanged, tone gates report only, Q5 stays open. G2 use of a qualified map is a
separate follow-up; no adjustment of `EXPECTED_STATS` to accommodate an unexplained change.

## 3. Scope

Implement handover items 2–5 on today's settled item-1 isolation: probe/fixture, leased channel, reconnect/recalibrate,
`frac`, OBS/Chrome harnesses, report/UI and docs. Product mutations are limited to owned calibration resources and their
temporary preview state; OBS lifetime remains explicit Take/Release output. Do not seed calibration into the collection.

Recommended but **scope-gated by O1/O2**: host-only executable freeze variant; migrate launched Chrome from the rev-17
knowledge grant to the shared probe lease. Do not mix an indefinite `snap` fallback into the new probe path when it fails.
If O2 retains the old Chrome policy, keep its legacy grant branch explicitly labeled/tested and apply leases to probe
grants only; that does not claim to close r13 #3. If O1 is deferred, do not add `frac` to the non-host executable variant
and retain an explicit failing raw/preview-forgery record.

## 4. Interplay

| Area | Contract |
|---|---|
| r13 #1, raw/preview forgery | **Open, not fixed by a stronger host channel.** Rendering-only pages contain the take today (F2). Recommend a host-only freeze variant: non-host rendering keeps cross-fade/cut but has no executable D4/D3 freeze entry point. Production raw/preview controls forge both assignment and non-configurable getters (`snap`, and `frac` if exposed), and must bind no holder. O1 decides inclusion; adjust the existing rendering-equals-live-minus-hook test intentionally, not by weakening its assertion. |
| r13 #3, stale GPU fallback | **Open, with CDP connected too.** Current revocation waits for observation (F4); the handover corrects rev 17's narrower residual. New probe leases are requested here, but decision 16 kept the old Chrome lease dropped. O2 explicitly decides migration. Even with a lease, unobserved/unchanged-fingerprint fallback can be renewed indefinitely unless renewal has independent path evidence; no claim that timers or tagged tuples solve it. |
| r13 #2 | Already addressed by eligibility-first, synchronous round-trip revocation and context-bound commit (F3). Preserve this ordering for probe eligibility and cancellation. |
| D1/D2, MM opacity, hand-back | No arithmetic/switch changes. Extend only admission/draw and any O1 variant split; both stock pins, off bytes, anchor non-overlap and composition remain gates (F1–F2). |
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
| `probe-*` | Two fresh launches: qualified Chrome → snap, CEF → frac, both poses and GPU map. Stable paused ROI pair passes. Software identity, undecodable/mismatched clip → no grant/no next holder. | Cold dormant, warmed dormant/disabled, frozen-video with live rAF, repeated/replayed challenges, delayed prior-run PNG, wrong source/context/DPR/size → invalid. Synthetic boundary rows: 2% passes, 2%+ε refuses; 20% passes, 20%−ε refuses; both-low/high, channel-only mismatch, pose/map conflict → unknown. |
| `iso-hdmi`, `iso-obs-preview`, `iso-obs-offcanvas` | Static program, no-probe null and candidate: full-frame RGBA unchanged before/install/run/cleanup/restore; program identity unchanged. Exercise startup and failed on-air recalibration. OBS remains inactive/no on-screen windows. | `iso-leak`: instrument deliberately puts probe at visible origin/on program; detector must FAIL. Behind-transparent-Program must FAIL. A source that never paints is INCONCLUSIVE, not isolated success. |
| Program-wire integrity | Continuous **lossless actual program recording**, started before install and stopped after verified cleanup/restoration: every decoded frame byte-identical to the static baseline; all PCM samples silent. Run both placements, success, failure and cancellation. | One-frame visible flash and brief audio injection detected. A missing/truncated recording, uncovered transaction interval or encoder mismatch is INCONCLUSIVE. Compare decoded frame bytes, not container-file hashes. |
| Alpha integrity | Separate transparent and half-transparent program baseline; raw OBS RGBA screenshots equal in **all four channels**, zero tolerance, including during mutation and cleanup. This supplements the recording, which may not preserve alpha. | Behind-Program alpha leak and injected alpha-only change detected; RGB-only comparison cannot satisfy this gate. Preserve raw PNGs; do not unpremultiply for exact isolation equality. |
| `life-cal-*`, channel | Valid grant → next take engages. Reload/source refresh/reconnect/reprobe failure/fingerprint change/expiry/cancel/Stop → invalid until successful fresh probe. Both preexisting Studio modes/preview selections restore. | Navigation between measurement/round-trip/commit, late result, lost renewal reply, delayed callback, tampered clock/updater/token/getter, disconnect before revoke, sleep/suspension and failed restore. No wrong-context grant; expiry never assumed from an unproved clock bound. Repeat cleanup; already-absent and delayed-delete rows must still verify complete absence. |
| `m-snap-cef[clip]` | DPR1/integer origin, P2 paused current frame: none, near/far fractional x and y clips, foreground crossing; DSK 7→8 two holders. Each cell has browser-rendered live reference, stable pairs, `perfect`, same-frame omit twin, verified mask, interior **and edge** scoring. | `m-snap-cef-nooffset[x|y]` on near-side clips → RGB FAIL with opaque backing; far-side nooffset is not a meaningful red. `wrongrule-cef`/`wrongrule-chrome`, forced through privileged channel → pixel FAIL. Shifted holder/`perfect-shift` → FAIL. Fractional-only underlay-omission → alpha refusal. |
| Geometry/foreground | Re-run Chrome's 18-cell DPR×origin×clip matrix with real launch DSF; require engagement, opaque cover and foreground preservation in each admitted cell. Frac translation-only/int-origin positives pass. | Frac DPR1.5/2, fractional origin; either rule at scaled stage/nested scale/mismatched base/fractional scene left/top → published take/no holder. Transparent last backing row/column skips; foreground omit/swap controls fail. Do not waive prior DPR1.5 mask INCONCLUSIVEs. |
| DX-2/DX-1 fidelity and cost | Existing dissolve/cut/opaque/frozen-frame/foreground gates, with calibrated CEF grant; real CEF DSK 7→8 total take ≤50 ms including extra draw, two holders, plus all measured DSK transitions and Chrome DSF2. | Off/baked-frame, hold-at-full-strength, no-blend and 50 ms+ε controls. `cef-skip` becomes a deliberate invalid-probe/unsupported-geometry control, not a blanket attached expectation (F9). |
| Raw/preview scope | Real production raw/export and Build Preview keep cross-fade/cut and stock movie behavior, no host script. O1 adds adversarial forgery no-holder gates. | O1 known-bad current rendering variant exposes the forgery. Do not substitute a harness-installed channel for production-path coverage. If O1 is deferred, mark this defect open rather than green. |
| W5 | GPU/software maps recorded across §2.7 matrix; identity take remains unchanged. | Raw/uncompensated tone, unknown tuple/map, insufficient ramp/patch coverage and reset/invalidation controls. Non-identity application is blocked until its separate qualification. |

Keep DX-2's existing unclamped calibration: `n` from `opaque-off`; τ=`max(4,ceil(n)+1)`, complement=`2+ceil(n)`,
no-dip=`252−ceil(n)`; caps 8/6/248, hence n>4 invalid (`scripts/managed_obs_qualify.py:669`). These holder/fade limits
do **not** replace the classifier's fixed 4-LSB / 2% / 20% rules or isolation's zero tolerance. Keep capture/reference
coverage, tone compensation only on exposed video, mask missed=0/excess≤1%, and `perfect` instrument gate (F10).

Run at 25 and 30 output fps with matching source rates, hidden OBS, two fresh launches for classification/tone. Record
load; serialize Chrome and OBS; use AC/no Low Power Mode and reject Sleep/Wake runs. Qualification may use a static test
program, never mutate an operator's live show. CEF screenshots are paced measurements, not a claimed output-rate capture.
Owner visual check: current movie frame freezes/fades with foreground intact, no flash/leak during recalibration; compare
`mm_opacity=off`, explicitly show the retained identity-tone step. DeckLink/physical keyer integrity is not proven by recording.

## 6. Tests

Prefer table rows in existing functions; **at most three new test functions**: one pure probe/fixture table, one OBS
transaction/fault table, one presenter calibration interaction table. Avoid duplicate implementation-mirror tests.

- Extend `test_dissolve_real_patched_methods_on_node` (`tests/test_live_runtime.py:1820`) on both players with frac geometry,
  two draws/offsets, whole-alpha scan, forbidden geometry and cleanup rows. Extend anchor/pin/composition/parse functions
  (`:297`, `:306`, `:312`, `:541`, `:630`), including O1 host/non-host distinctions if approved. Off remains byte-identical.
- New `tests/test_placement_probe.py`: one parameterized function for known-pixel classifier boundaries, maps, inner mask,
  max-over-channels, nonce replay/freshness, capture stability/identity/size and shipped full-digest validation. Use crafted
  inputs whose correct result is independently specified, including edge-only vs inner defects.
- Extend host placement tests (`tests/test_live_host.py:3223`, `:3263`, `:3305`, `:3325`, `:3356`, `:3431`) with fake clocks,
  transport/context generations, lease cap/expiry, cancellation races, connected GPU fallback and reconnect/reprobe. Node
  exercises the real channel against assignment/delete/getters/wrong-token/clock changes and both grant values.
- Add one parameterized managed transaction test in `tests/test_managed_obs.py` for preview/fallback sequences and every
  partial-failure boundary, wrong ownership, absent object, delayed disappearance, persistence/readback, audio and Stop.
  Extend seed/lifetime tests (`:108`, `:126`, `:1322`) to forbid seeded leftovers and prove cleanup before quit. Extend
  WebSocket tests (`tests/test_obs_websocket.py:113`, `:135`, `:144`, `:163`) for bounded image size/timeouts/errors without
  credential leakage; do not add another generic client.
- Extend session/API command tests (`tests/test_live_session.py:382`, `:435`, `:590`, `:785`;
  `tests/test_live_api.py:232`, `:566`) for recalibrate idempotency, capability propagation, no visibility/navigation ack,
  cancellation, stale completion and engine-adapter injection. Add one UI table alongside existing delayed-command/Stop
  tests (`dashboard/tests-ui/live-presenter.ui.test.tsx:205`, `:273`, `:350`) for states, error reason and retry.
- Extend the single scorer table (`tests/test_dissolve_probe.py:1235`) with all new controls and evidence omissions. Extend
  DX-2 arm/gate tests (`tests/test_managed_obs_qualify.py:98`, `:180`) for per-arm grants, positive holder expectations,
  program recording+RGBA coverage and no-OBS rescore. Diagnose failures before changing expected values.

Implementation checks: targeted rows first, then full Python suite
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`; Python 3.10 compatibility; dashboard
`npm install`, `npm run build`, `npm run test:maps`, `npm run test:ui`. Verify wheel-installed probe assets/hash as part of
the fixture table. Then §5 gates and parent regression: `run_gates.sh` full tier, `mm_opacity_probe.py`, `mm_handback_probe.py`,
managed `mmo`, `g2`, `mmo-cef`. A plan-only change runs none of these product/browser gates.

## 7. Work streams

Implementation only: **Codex GPT-5.6 Sol high, one implementer per stream; disjoint files; only the coordinator commits.**
No implementers are launched by this planning task. Coordinator settles O1/O2 and freezes adapter/result/schema contracts
before parallel work; ownership transfers are explicit, never concurrent edits to a shared file.

| Stream | Exclusive files | Deliverable |
|---|---|---|
| W1 player | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | Frac draw/guards/pins; O1 variant split only if accepted. |
| W2 probe | new `src/obed_edom/placement_probe.py`, `src/obed_edom/data/placement_probe.mp4`, `placement_motion.mp4`, `placement_probe.json` (all under `data/`), new `scripts/generate_placement_probe.py`, `tests/test_placement_probe.py`; `pyproject.toml` | Reproducible assets, freshness protocol, pure classifier, schema, packaging; W5 map observation. |
| W3 OBS | `src/obed_edom/managed_obs.py`, `src/obed_edom/obs_websocket.py`, `tests/test_managed_obs.py`, `tests/test_obs_websocket.py` | Owned transaction, preview/fallback, capture budgets, restore/cleanup/persistence verification, narrow adapter. |
| W4 host | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | Isolated Chrome target, channel/lease/state machine, worker cancellation, context/connection binding and report. Implement O2 policy explicitly. |
| W5 command/UI | `src/obed_edom/web/live.py`, `src/obed_edom/live_session.py`, `tests/test_live_api.py`, `tests/test_live_session.py`, `dashboard/src/live/api.ts`, `dashboard/src/live/LivePresenter.tsx`, `dashboard/tests-ui/live-presenter.ui.test.tsx` | Adapter wiring and recalibrate lifecycle/capabilities/status, no visibility misrouting. This stream label is distinct from the parent W5 tone investigation. |
| W6 qualification | `scripts/dissolve_probe.py`, `scripts/managed_obs_qualify.py`, `tests/test_dissolve_probe.py`, `tests/test_managed_obs_qualify.py` | Freshness/isolation/lifecycle/rule controls, continuous recording+RGBA, CEF clips/tone/cost and offline rescoring. |
| W7 docs/coordinator | `README.md`, `.agents/skills/obed-edom/SKILL.md`, `.agents/handovers/keynote-live-dissolve-crossfade-followups.md`, this plan | Operator behavior, residuals, gate evidence/owner dispositions. Update skill under its writing rules during implementation. |

Order: decisions/contracts → W1–W6 (within available concurrency) → asset/probe/cleanup feasibility on exact adapters →
integration and review → targeted/full suites → controls-first DX-1 → CEF preflight and DX-2 → regressions/owner check →
coordinator's PR. A non-persistence or isolation failure blocks that placement before on-air qualification. W5 tone
observation can run during these captures; a failed tone-application gate does not block identity-tone placement.

## 8. Owner questions

No question reopens today's preview/fallback/freshness/restore decisions. These are scope choices to record before
dependent implementation; this non-interactive planning task does not request a reply.

1. **O1 — r13 #1:** include the bounded host-only freeze variant and raw/preview forgery controls here, or leave them in
   a separate PR? **Recommend include**, explicitly, because the shared rendering variant otherwise retains the known
   bypass while `frac` is added. If separate, do not expand its executable non-host freeze or claim the bypass fixed.
2. **O2 — r13 #3 / decision 16:** may this follow-up replace launched Chrome's indefinite knowledge grant with the shared
   probe lease, as parent decision 13 originally intended? **Recommend yes for uniform lifecycle**, explicitly superseding
   decision 16 only for that path. This does not close unchanged-fingerprint GPU fallback; owner must accept the stated
   residual or commission stronger path-change detection. If no, preserve and label the legacy Chrome path/residual;
   new probe-derived grants still require the requested lease.
3. **O3 — conditional clip provenance:** if the pruned `7b7d66b5…` artifact cannot be recovered/reproduced exactly, accept
   a newly full-pinned regeneration after both-engine requalification? **Recommend yes after the full controls pass**;
   otherwise asset recovery blocks release. Prefix matching alone cannot qualify the asset.

## 9. Risks / out of scope

- The feasibility work did not prove live cleanup absence or non-persistence; its post-exit restoration cannot be borrowed
  as product evidence. OBS collection autosave is a blocking implementation investigation (§2.2), not permission to relax
  the owner's rule. A disconnected/crashed engine may prevent immediate cleanup; never report clean until verified.
- Preview and program source compositors may diverge after a GPU change. Challenge freshness proves a live probe, not
  equivalence of every program video path. Final holder gates and explicit fallback residuals remain necessary.
- Screenshot cost/load can exceed the old probe estimate. Deadlines fail closed; no overlapping screenshot burst or
  recurring scene installation every three seconds disguised as cheap lease renewal.
- No scaled-stage/nested-scale model, software holder qualification, arbitrary external attach, F2 transitions, bridge/held
  decoder changes, new G2 tone behavior or physical DeckLink/keyer proof. Identity-tone step and parent Q5 remain open.
- The raw/preview bypass and stale connected-CDP fallback retain their own dispositions; passing CEF placement does not
  close either automatically. Keep unsupported geometry and ambiguous maps as skips, never broaden tolerances to pass.

## 10. Critique log

| Round | Reviewer / revision | Finding | Disposition |
|---|---|---|---|
