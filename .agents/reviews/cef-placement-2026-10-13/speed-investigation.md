**Yes: a development run can plausibly fall below 10 minutes. Halving the full run requires restructuring repeated evidence collection and owner approval; launch reuse or shorter deadlines will not achieve it.**

This investigation was read-only, against `dd8c8753`. No applications, tests, or gates were run.

References below abbreviate [managed_obs_qualify.py as Q](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/managed_obs_qualify.py), [dissolve_probe.py as D](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py), [managed_obs.py as M](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/managed_obs.py), and the [rev-3.3 plan as P](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/plans/keynote_live_cef_placement.plan.md).

**Measured budget**

Live4 A took **2,691.70 s**, B **2,687.03 s**: approximately **44.8 minutes** each. Sources: `runA.log:23`, `runB.log:23`, four `out/runs/placement-*.json` files, session records/telemetry, and matching `output/.html-preview/live-logs` timestamps.

| Per-rate budget, seconds | 25 fps, A / B | 30 fps, A / B |
|---|---:|---:|
| OBS launch | 2.29 / 1.14 | 1.03 / 1.38 |
| 38 placement arms: recorded `script` sum | 1,091.33 / 1,088.89 | 1,093.20 / 1,089.09 |
| Seven control sessions, two Chrome probes, other overhead¹ | 53.60 / 54.02 | 53.38 / 53.64 |
| OBS quit | 0.29 / 0.29 | 0.24 / 0.23 |
| After-quit persistence, retirement, scoring¹ | 193.91 / 195.95 | 202.43 / 202.40 |
| **Total** | **1,341.42 / 1,340.29** | **1,350.28 / 1,346.74** |

¹ Derived using the authoritative quit-file timestamp and final artifact timestamp; these are phase brackets, not function-level profiling.

**OBS already launches once per rate**, enclosing all 47 sessions (`Q:3552–3597`). All four lifecycle records show clean exits and unchanged user configuration/sentinel.

The ten principal measured costs below include nested components; **do not add these rows**.

| Cost | Seconds/rate across A/B | Evidence and implementation |
|---|---:|---|
| 1. Calibration completion → measured advance | **321–322** | Record events + `dump.timeOrigin/advanceAt`; navigation, preparation, fixed waits: `D:4328–4369` |
| 2. Actual calibration transactions | **218–224** | `transaction.finished_s−started_s`; `M:1363`, `Q:1088` |
| 3. Repeated preflight controls/setup | **203–205** | `calibration-start` → probing event; **5.26–5.49/session**, `Q:2078–2089` |
| 4. Post-quit work | **194–202** | Persistence/retirement roughly **81–91**, subsequent scoring/reporting **111–115**; `Q:3954`, `3100` |
| 5. Mandatory probe paint waits | **80.6–80.7** | 266 captures × ≥300 ms; input capture timestamps; `P:629–633` |
| 6. Recording-stop fixed sleeps | **76** | Two recordings × 38 sessions × 1 s; `Q:1553–1556`. Candidate tails measured **38.28–38.32** total |
| 7. Probe capture calls | **56.6–57.1** | Capture start/finish timestamps; includes guarded sampling, so overlaps row 8 |
| 8. Transaction RGBA sampling | **47.9–48.8** | `telemetry.sampleCosts`; `Q:1062–1070`, `1195` |
| 9. Timed arm screenshot bursts | **46.9–47.5** | 383–387 screenshots; `shots.t0/t1`; `D:4255–4309` |
| 10. Paused-reference advance → perfect-ready | **43.3–43.9** | Reference timestamps; excludes final perfect captures/collection; `D:4190–4245` |

Additional attribution:

- Host start → calibration preflight is **19.47–19.57 s/rate**, about 0.51 s/session, including serving/navigation/readiness. `await_input` contributes another **8.04–8.13 s** inside preflight.
- DSK costs **71.2–72.2 s**, versus roughly 27–28 s normally. Its scratch preparation/transcode window is **24.1–24.9 s**; its calibration-complete → advance interval is **26.2–26.4 s**, versus about 7.9 s for P2.
- Preflight positive-control recordings occupy **72.5–73.1 s/rate**, including their stop sleeps. Program-guard controls add **64.6 s of explicit sleeps**: 38 × `(1 + .35 + .35)` (`Q:1733`).
- Driver fixed waits include **57 s** for `SETTLE_S`, **19 s** final settling, **3.8 s** live-pair gaps, plus paused-frame waits (`D:4340–4377`).
- OBS input creation/removal and cleanup polling are contained in preflight/transaction totals; no individual request durations were retained. **There is no AK.json persistence wait loop**: cleanup reads immediately; clean quit is authoritative (`M:1353`, P O5).
- `decode: 0` is misleading: placement decoding happens inside `analyze_program_recording`, then recordings are decoded again for retirement framemd5 (`Q:861`, `3915`). Encode/analysis CPU time is not separately measured.
- Placement passes no screencast callback: capture is paced OBS screenshots, not output-rate screencasting. There is no placement load/quiet wait. D’s standalone load check is a refusal, not a sleep.
- The 35 s host, 15 s measurement, 5 s cleanup, and 30 s readiness limits are ceilings. Actual transactions take **4.78–6.03 s**; lowering ceilings saves essentially **zero** successful-run time.

Live3’s 25-fps run was similarly slow, **1,377 s**. Its 30-fps run slept and is unsuitable for wall-clock comparison.

**Options and evidence consequences**

Savings below are standalone estimates per rate unless stated otherwise.

| Option | Estimated saving | Validity risk / contract consequence |
|---|---:|---|
| One OBS launch/rate or group | **0** | Already implemented. More groups add launches. |
| Parallel scenes/sources | No defensible estimate | Shared Program, preview, recording and GPU invalidate independence; §11.2 explicitly rejects concurrent transactions (`P:709`). Reject for qualification. |
| Run invariant flash/audio/leak/toggle controls once per rate | **175–185 s** | Retain per-session readiness, baseline and absence checks. Medium risk: shared controls must match launch/configuration. §5 evidence mapping and §11.6 references need review. |
| Share a calibration across new documents | Envelope available: **≈12.2 s/arm** | **Cannot reuse a product grant across contexts**: §11.3/O4 bind context/connection/launch. Same-context reuse is valid only while fingerprint/lease remain valid. |
| Separate renderer arms from product calibration qualification | **≈420 s** with three full anchors retained | Owner-approved redesign described below; renderer rows must explicitly identify harness-injected grants. Changes §5/§11.6 evidence composition. |
| Drop twins | **246–248 s gross** | Reject simple deletion: nine twins establish mask/foreground/rule-specific comparisons (`D:435–467`, P §5). Paired capture redesign needs equivalence evidence and sign-off. |
| Faster positioning before the measured transition | **≈130–160 s** | `D.navigate/drive`: use go-to plus necessary builds. Preserve target state, movie identity and measured transition; warm-path equivalence must be demonstrated. |
| Replace generous fixed sleeps with verified readiness | **≈100–125 s**, before overlap | Preserve stable reference pairs, recording coverage and 300 ms probe waits. Medium risk; deadlines themselves offer no saving. |
| Cache generated movies/transcodes/PDF stripping across rates | **≈24 s** DSK alone; other gains unmeasured | Existing cache is scratch-per-rate (`D:1181–1235`). Use content/toolchain/encoding hashes; preserve provenance. No acceptance relaxation. |
| Score offline | Moves **194–202 s** after OBS release | Does not remove time-to-verdict. Avoid double decoding/repeated classification separately; exact saving needs instrumentation. §5 already permits offline scoring. |
| Skip recordings for renderer-only rows | Included in ≈420 s envelope saving | Allowed only after separating evidence roles. Every product transaction retained for wire qualification still needs recording; §5 forbids silently dropping it. |
| One rate | **≈1,345 s/invocation** gross | Explicitly changes §5 (`P:362`). Appropriate for dev, not current qualification. |

Rate reduction is not presently justified for full qualification. Timed dissolve/cut, moving/frozen-frame, foreground and DSK-cost arms depend on scheduling. Paused clip/rule/tone/twin/geometry arms test largely spatial properties, but source cadence can affect capture settling and engagement. Chrome classifier arms are independent of OBS output rate, yet §5 separately requires two fresh Chrome launches; removing one invocation loses that repetition.

**Recommended implementation plan**

**Fast tier: target 8–10 minutes.** Add `--tier dev|full` and explicit rate selection in `Q.main/sessions_for/placement_gates`; add a dependency-complete development profile in D.

At 25 fps retain seven control sessions, two Chrome probes, and these fourteen renderer arms:

`opaque-off`, `off`, `noblend`, `on2`, `on`, `opaque-on`, `m-snap-cef`, its twin, `wrongrule-cef`, its twin, `perfect-shift`, `m-tone-cef`, its twin, `m-tone-raw-cef`.

Their measured script sum is **387.8–388.3 s**. Add **54 s** surrounding acquisition and a provisional **75–100 s** scoring allowance: **517–542 s**. Scoring for this subset remains unmeasured.

This preserves basic fade controls, one complete holder/reference/mask case, wrong-rule/shift detection and tone observation. It excludes clip-matrix, DSK, broader foreground/geometry and second-rate qualification. Emit **DEV**, never qualification PASS. [run_gates.sh:4](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/run_gates.sh:4) already establishes this distinction and uses exit 10 for dev success.

**Full tier: target approximately 21–22 minutes, conditional on owner approval.** Retain both rates and all logical renderer arms. In `Q.placement_session` separate:

- Three genuine calibration/integrity anchors: off-canvas, sampled preview, and product-timing preview; retain existing lifecycle/freshness controls.
- Remaining renderer rows: fresh harness channels, explicitly injected measured-rule grants immediately before the take via D’s privileged grant mechanism. Never relabel copied calibration as fresh context-bound product evidence.

Update `Q.placement_gates`, offline rescoring and §11.6 records to reference anchor evidence explicitly. Preserve all twins and pixel thresholds. Product grant/renewal behavior remains exercised by genuine anchors.

Planning arithmetic per rate: **1,345 − 420** repeated envelopes **− 140** positioning **− 24** cached preparation **− 100–120** remaining driver waits = **641–661 s**, or **21.4–22.0 minutes** for both rates. These are estimates tied to measured budgets, not demonstrated results; analysis savings receive no additional credit.

Owner sign-off must explicitly accept factored product/renderer evidence and revise §5/§11.6. Without that approval, retain fresh per-context calibration and the current qualifying matrix; the evidence does **not** support promising a halved run. All live4 invocations currently fail, so neither faster tier should convert existing failures or inconclusives into passes.