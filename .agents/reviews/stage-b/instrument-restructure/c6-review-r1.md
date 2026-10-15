# C6 code review r1 (Opus 5.5 high; three/two lenses, each finding adversarially verified by Opus 5.5 high)

Confirmed 25, refuted 0. Implementer: Codex GPT-5.6 Sol high. All confirmed findings were folded (fold report summarised in the C6 gate record).

## major · spec · OBS feed-off now scores continuousExpected=False, which removes the feedLive red the feed gate requires
`scripts/managed_obs_qualify.py:4689` · class: new class

**Scenario.** feed-off runs with mm_feed_qualify_once=True, so the module reports mode 'once'. With feed_script(False), verdict_records stamps continuousExpected=False. score_under_artwork's once branch adds feedLive only when continuousExpected is True (probe :3828), so feedLive is never produced. feed_gates (:4986) requires 'feed-off <id> feedLive is False', reads None, and the OBS feed gate can never pass. Pre-C6, feed_script(True) gave the explicit red that test_feed_gate_requires_..._with_continuous_red and plan §C5 ('Feed-off feedLive False/False, keep explicit red') depend on. The change also gets ahead of the owner's retained decision that feed-off host expectations are settled in C5.

**Fix.** Restore `run_session("feed-off", feed_script(True), ...)` at `scripts/managed_obs_qualify.py:4689`. That keeps the session's existing value, now passed into `capture_arm` instead of mutated after normalization. In `tests/test_managed_obs_qualify.py`, switch the interface test to `feed_script(True)` for feed-off (or add a parametrized case for it) and assert `continuousExpected is True`. Ideally also assert that a feed-off once-mode record yields a `feedLive` verdict row, so the explicit red the gate requires is covered.

## major · spec · score_arm leaves sampleSpace='screen' on rows it already converted, so replaying any fresh C6 artifact converts twice
`scripts/live_continuity_probe.py:8593` · class: new class

**Scenario.** capture_arm sets sampleSpace='screen' (:4690). score_arm deep-copies the capture into result and replaces samples with authored rows, but never updates sampleSpace. run_arm/run_attach_arm/OBS therefore persist authored rows tagged 'screen'. On rescore, capture.setdefault('sampleSpace','authored') does nothing, and _capture_samples runs convert_samples_to_authored a second time. Any non-identity stage map (a --viewport other than the canvas, or a letterboxed deck) maps the rects twice and overwrites rectScreen and the pre-paint stageBoxScreen with authored values, so replayed verdicts diverge. The stored attempt-3 replay could not catch this because those files have no sampleSpace key.

**Fix.** In `score_arm`, set `result["sampleSpace"] = "authored"` next to `result["samples"] = samples`; this one key covers the `sampleRows` alias too. Add one interface test: with a valid non-identity stage map (e.g. s=0.5, ox=100), `score_arm(score_arm(capture, facts, stage), facts, stage)` must give the same samples and verdicts as the first pass. Alternatively, run it through `rescore_generated` on a freshly scored arm.

## medium · spec · _continuous_expected infers the expectation from the product's observed mode
`scripts/live_continuity_probe.py:4573` · class: new class

**Scenario.** A historical capture with no top-level continuousExpected, where the product module reports every entry as 'once', gets continuousExpected=False. That is the observed outcome standing in for the expectation. Example: an attempt-3 OBS feed-off session (stored records carry continuousExpected=True) has its feedLive row dropped, so the expected False becomes None, which is one source of the 'became unknown' outcomes. A feed-on capture whose product fell back to once would likewise be scored as if once were expected (feedLive omitted rather than False). The plan says 'Normalize from this field'.

**Fix.** Remove the producer-mode inference in `_continuous_expected`:
- Return `capture['continuousExpected']` when it is a bool.
- Otherwise, if every stored `feedEvidence.verdicts` record carries the same bool `continuousExpected`, use that value.
- Else return None, so the outcome is unknown (fail closed).

Update the D7-missing-sampler parameter so it expects None, or a value taken from stored records, instead of a value inferred from producer mode. Separately, have stream O restore `feed_script(True)` for the `feed-off` session, per plan §238/§275.

## medium · spec · OBS environment records configured rates as 'observed' and takes 'during' before driving starts
`scripts/managed_obs_qualify.py:2335` · class: new class

**Scenario.** outputRate.observedHz is canvas_fps(GetVideoSettings), and browserSourceRate.observedHz is GetInputSettings.fps. Both read back configuration. A host that drops to 20 Hz still records observed=30, so C2 environment validity would compare configured against configured and could never fail. observations['during'] is taken at :2270, after show but before capture_arm drives the deck, so it is a second 'before'.

**Fix.** Set outputRate.observedHz from the raw GetVideoSettings value: fpsNumerator/fpsDenominator when both are positive ints, otherwise None. Do not use canvas_fps, which falls back to the configured rate and is meant for decoding. Keep browserSourceRate.observedHz as the GetInputSettings fps read-back; it is the actual setting the plan asks for. For 'during', take the reading inside the drive. One way is a single optional mid-capture hook in capture_arm, which the plan already lets the caller supply as environment context. Otherwise leave 'during' absent (None) instead of storing a pre-drive reading under that name. Add one test that feeds a mismatched or missing videoSettings and asserts observedHz is not the configured value.

## low · spec · chrome_process_counts double-counts Chrome and hard-codes owned=0
`scripts/managed_obs_qualify.py:2291` · class: edge case

**Scenario.** pgrep -f 'Google Chrome' matches chrome_crashpad_handler (its path is inside 'Google Chrome Framework' and it has no --type=) and any process whose command line contains the string. Verified on this machine: one headless Chrome 155 counts as 2 'foreign' roots. 'owned' is the literal 0, not an observation. The before/during/after foreign/owned counts in environment are therefore wrong whenever any Chrome is running.

**Fix.** Filter roots by executable rather than by substring. A pid counts as a Chrome root only when its argv[0] ends in "/Contents/MacOS/Google Chrome" (or the Chrome for Testing equivalent), which leaves out crashpad and the Helper apps. Take one `ps -A -o pid=,ppid=,command=` snapshot instead of running pgrep plus a ps call per pid. Derive owned from roots that descend from os.getpid(), the same walk check_no_leftover_chrome uses, and set foreign = roots - owned. Return None for both on any ps failure, never a constant. Update the test fixtures only if the shape changes. The keys stay {owned, foreign}.

## medium · spec · Headless/attach captures never receive an environment (always {})
`scripts/live_continuity_probe.py:4730` · class: new class

**Scenario.** run_arm and run_attach_arm accept environment, but no caller passes one (run_cli A/B/C/attach, red arm, paint control, detach). capture_arm therefore records environment={} for every fresh headless and attach capture, with no Chrome build, git head, load/uptime or Chrome counts. Only OBS fills the §2 environment contract, and the plan says the caller supplies it. C2 will see every headless capture as environment-unproven, and §10's 'uptime/load/browser identity recorded' is not met.

**Fix.** Move the environment observation helper into the probe (P-owned), then have managed_obs_qualify import it instead of keeping `environment_observation` / `chrome_process_counts` privately. The helper records load, uptime and owned/foreign Chrome counts.

Inside `run_arm` and `run_attach_arm`, build the environment from the live transport:
- Browser.getVersion
- git head
- qualification identity for the host kind
- a "before" observation, a "during" observation after `show_output`, and an "after" observation added to `capture["environment"]` before `score_arm`

Doing this inside the two functions covers every caller (run_cli A/B/C, attach, the red arm, the paint control and detach) without changing call sites. Make the `environment` parameter internal or drop it.

For the test, add one interface-level assertion that a fake-transport headless capture records a non-empty environment with a browser version and before/after observations. Reuse an existing `run_arm` fake if one exists.

## high · spec · OBS session artifact serialises the sample rows twice (samples and sampleRows)
`scripts/managed_obs_qualify.py:2286` · class: edge case

**Scenario.** scored['sampleRows'] = scored['samples'] followed by s.out.update(scored) means json.dump writes both keys in full. For Alpha feed/feed-off that is about 1,891/1,329 rows written twice per session, doubling the largest payload in each take artifact. Pre-C6 OBS stored only sampleRows.

**Fix.** Store only one copy in the OBS session, under the existing key `sampleRows`, e.g. `scored["sampleRows"] = scored.pop("samples")` before `s.out.update(scored)`. Or have score_arm emit `samples` only when the input used `samples`, and `sampleRows` only when it used `sampleRows`, never both. Then any `samples` key in a managed session stays the precheck schema the contract expects, and the payload is no longer doubled. Change tests/test_managed_obs_qualify.py:1419/1483 to assert that `samples` is absent and that `sampleRows` equals the headless rows. Add one assertion that `q.contract_problem({"sessions": [session.out]})` is None, so a live feed session is checked against the producer contract.

## low · spec · Unused CAPTURE_FIELDS constant and an unused, duplicated facts['fixtureIdentity']
`scripts/live_continuity_probe.py:360` · class: edge case

**Scenario.** CAPTURE_FIELDS has no reader. complete_facts computes feed_fixture_identity (reading every slide JSON) into facts['fixtureIdentity'], but no probe path reads it: run_cli and the red arm still call require_feed_fixture separately, and feed_fixture_facts calls require_feed_fixture and then overwrites the value. This is speculative generality that fails the deletion test.

**Fix.** Delete `CAPTURE_FIELDS`. Then pick one of two options.
- Simplest: drop the fixtureIdentity line from `complete_facts`, and remove `feed_fixture_identity` from the test's monkeypatch and its `seen`/assert expectations.
- Alternative: have `complete_facts` call `require_feed_fixture` once. Then make run_cli (9538), the red arm (7667) and managed_obs `feed_fixture_facts` read `facts["fixtureIdentity"]` instead of re-deriving it. This must keep the `feed_fixture_required(args)` gating and the refusal-before-launch ordering.

## major · correctness · Feed-off now captures with continuousExpected=False, so feedLive is never scored and the feed gate can never pass
`scripts/managed_obs_qualify.py:4689` · class: new class

**Scenario.** Before this change, sessions_for registered feed-off with feed_script(True). It now uses feed_script(False). In departure, once or standDown mode, score_under_artwork only computes results["feedLive"] when record.continuousExpected is True (live_continuity_probe.py, the once-mode branch). With False, underArtwork has no feedLive key. feed_gates (managed_obs_qualify.py ~4980) requires feed-off feedLive `is False`, so it reads None and fails for every under-artwork spec on every fresh take. The plan's C5 table also says 'Feed-off feedLive | False | Keep explicit red'. I reproduced this on stored D7 feed-20261015-150032 feed-off through score_arm with sampler schema 2: with continuousExpected=True all 6 specs have feedLive=False (mode departure); with False all 6 have no feedLive (None). The new test test_feed_capture_scores_both_retirements_with_final_environment asserts the False value, so it locks the regression in. This fails closed, but it makes Q7 attempt 4's feed gate impossible to pass and deletes the explicit red control. Report-O also says 'No implementation deviations', yet this is one.

**Fix.** In scripts/managed_obs_qualify.py sessions_for, restore `run_session("feed-off", feed_script(True), ctx, gl_replay="off", mm_feed="off", mm_feed_qualify_once=True)`, because True is that session's registered value. Keep removing the post-normalisation mutation, since capture_arm now supplies continuousExpected. In tests/test_managed_obs_qualify.py, change the retirement test to drive feed_script(True) for the feed-off-shaped session, or make the registration test assert the value each session passes. Ideally, also feed the scored feed-off output into feed_gates so the explicit feedLive=False red is checked through the interface.

## medium · correctness · OBS environment records configured rates as observedHz, and the canvas_fps fallback hides a contradicting rate
`scripts/managed_obs_qualify.py:2335` · class: new class

**Scenario.** outputRate.observedHz comes from ctx['canvasFps'] = canvas_fps(videoSettings, rate). canvas_fps returns the configured RATES label whenever GetVideoSettings is unreadable or differs from the configured rate by more than 0.2. Example: OBS left at 60/1 by a stale profile while configured for 30 gives observedHz=30, matching configuredHz. browserSourceRate.observedHz is source_settings['fps'], which is OBS's stored input setting (GetInputSettings), not a measured cadence. C2's run_validity will consume these fields as the 'configured and observed' rate pair. A configured value labelled as observed would let a rate check pass with no observation, or against contrary evidence, so missing evidence would turn green.

**Fix.** In feed_environment, set outputRate.observedHz straight from the raw ctx["videoSettings"] fpsNumerator/fpsDenominator, with the same int and >0 guards. Use None when that is unreadable, and never call canvas_fps here. Leave canvas_fps unchanged for the recording timing it already serves. Add one test through the feed_script interface for videoSettings that are mismatched or missing. It should assert that observedHz is the raw value or None, not the configured rate. For the browser source, keeping the read-back of the OBS setting is fine under the plan. Optionally rename the key to settingHz so C2 does not treat it as a measured cadence.

## medium · correctness · The 'during' environment observation is taken before the deck is driven
`scripts/managed_obs_qualify.py:2270` · class: new class

**Scenario.** feed_script records observations['before'] in feed_environment, calls show, records observations['during'], and only then calls capture_arm, which drives and samples the whole deck. 'during' is therefore a second pre-drive sample. Suppose a foreign Chrome (for example another session's headless measurement) starts, or load spikes, partway through the drive and ends before 'after'. All three observations miss it, and C2's before/during/after health check passes on load it never saw during the run.

**Fix.** Take `during` while the deck is actually being driven. In feed_script, run a small daemon thread around the `capture_arm` call that calls environment_observation() every few seconds until capture returns. Write `capture["environment"]["observations"]["during"]` as the worst case across those samples (max loadAverage per component, max foreign count), or store the list of samples. Write it after the deep copy, the same way `after` is written. If any sample fails (chromeCounts None), the merged value should be None, so the result fails closed. A simpler option is to drop the pre-drive `during` write so C2 sees the observation as missing (None) rather than mislabelled. Either way, change the test so the fake drive_and_sample asserts that a `during` observation is taken while it runs (for example, the fake observation iterator is advanced inside `drive`), not just that the key order is right.

## low · correctness · For historical captures, score_arm infers continuousExpected from the observed producer modes and ignores the recorded expectation
`scripts/live_continuity_probe.py:4573` · class: new class

**Scenario.** When a capture has no top-level continuousExpected (every stored artifact, including rescore_generated replays), _continuous_expected derives the expectation from the observed producer entry modes. That makes the expected value depend on the observed behaviour. Historical OBS feed-off sessions (modes 'departure') give None, so the stored feed producer is dropped completely even though every stored feedEvidence.verdicts record carries the session's continuousExpected. A historical attach arm, recorded with expectation False, whose producer ran in 'continuous' mode is inferred as True. score_feed_live then applies the coverage and inter-feed-gap requirements that the arm was never held to, and can return False for behaviour that was never contrary to its expectation.

**Fix.** Change `_continuous_expected` so it never reads producer modes:
1. Return the capture's boolean `continuousExpected` if present.
2. Otherwise, use the stored per-record `feedEvidence.verdicts[*].continuousExpected` (including `visits[*]` when present), but only if every record holds the same boolean value.
3. Otherwise return None (and leave the producer un-normalized, as the code already does).

This keeps all 48 reproduced attempt-3 outcomes:
- feed records stay True.
- feed-off becomes True, as recorded, and only adds a non-applicable `feedLive` row.

Add one interface test through `score_arm`: a capture with no top-level field, a 'continuous' producer and recorded per-record `continuousExpected=False` must not apply the coverage/gap checks. A variant with no recorded expectation must give None.

Correct the finding text: feed-off infers False, not None, and is not dropped.

## low · correctness · run_advance_leg hard-codes hostKind 'headless Chrome' and continuousExpected True even when Pass G runs on attach
`scripts/live_continuity_probe.py:6589` · class: edge case

**Scenario.** run_pass_g supports --attach (attach_chrome at ~6778), but every advance-leg capture is built with hostKind=HOST_HEADLESS_CHROME and continuousExpected=True. The plan makes hostKind the explicit qualification key and says it is never guessed. Once C2 makes score_arm call run_validity(capture, qualification[hostKind]), an attach advance leg will be validated against headless qualification constants, so the wrong budget can mark it valid.

**Fix.** Thread the host through from run_pass_g rather than using literals. Choose the pair once from args.attach: (HOST_QUALIFIED_CHROME_ATTACH, False) when attaching, else (HOST_HEADLESS_CHROME, True). Pass it through _run_goto_arm and run_goto_destination as keyword arguments host_kind and continuous_expected. Use them in the capture in run_advance_leg at line 6589. One alternative is to read the pair from the existing env (ATTACH_ENV present), but explicit parameters fit the plan's "never inferred" rule better. Don't add a new test unless an existing Pass G attach test already builds this capture; if C2's validity integration lands, cover it there.

## low · correctness · Fresh headless and attach captures always ship environment={} because no caller supplies one
`scripts/live_continuity_probe.py:4730` · class: edge case

**Scenario.** run_arm and run_attach_arm gained `environment: Mapping | None = None` and pass `environment or {}`. None of the callers (run_cli arms A/B/C and attach, red/paint-control/forced-fail, detach_experiment) passes one. Every fresh Chrome capture therefore lacks the frozen-contract fields: browser version, git head, qualification identity, and before/during/after load and Chrome counts. This fails closed, but under C2 every headless and attach run becomes invalid. The plan said the capture contract would be frozen and complete before parallel C2 work.

**Fix.** Move the OBS environment_observation helper (load, uptime, owned and foreign Chrome counts) out of managed_obs_qualify.py and into the probe, since the OBS qualifier already depends on the probe. Then have run_arm, run_attach_arm and the advance-leg capture each build a finalized environment before score_arm: browser version from Browser.getVersion on the player's transport, git head, a qualification-identity placeholder, and the before/during/after observations. That would let the callers drop the `environment or {}` default and the hard-coded `{}` at line 6589. If this is deliberately deferred instead, the C6 hand-off must say that P's C2 integration owns populating environment for headless, attach and advance-leg captures, and that those captures carry `{}` until then.

## low · correctness · chrome_process_counts counts chrome_crashpad_handler as a Chrome root, and one vanished PID nulls the whole count
`scripts/managed_obs_qualify.py:2305` · class: edge case

**Scenario.** `pgrep -f "Google Chrome"` also matches `.../Google Chrome Framework.framework/.../chrome_crashpad_handler --monitor-self-annotation=...`, which has no `--type=`. Each Chrome instance is therefore counted twice; I confirmed this on this Mac with the other session's headless Chrome running. Separately, if any matched helper exits between pgrep and `ps -p` (renderers come and go constantly), ps returns 1 and the function returns {owned: None, foreign: None} for the whole observation, which C2 will read as unproven health.

**Fix.** Take one `ps -axo pid=,command=` snapshot instead of pgrep followed by a ps call per PID, so a vanished PID cannot fail the read. Count a process as a root only when its executable path ends in `/Contents/MacOS/Google Chrome` (the main browser binary) and it has no `--type=`; this excludes chrome_crashpad_handler and the Helper apps. Return None only when the snapshot itself fails. In tests/test_managed_obs_qualify.py, add one fake snapshot through the existing interface that contains a main process, a crashpad handler and a --type= helper, and assert foreign == 1.

## low · correctness · Replay explained: all 12 'became unknown' outcomes are a missing sampler record; with a schema-2 control, C6 matches the pre-C6 baseline
`scripts/live_continuity_probe.py:4625` · class: edge case

**Scenario.** All 12 cases have the same cause: 'evidence contract: rows:schema at samples (sampler schema None)'. They are Alpha feed b3to4/b4to5, Alpha feed-off b3to4/b4to5, D7 feed-off b2to3 a/b in each of the 3 runs, and D7s feed-off b1to2 a/b. The stored OBS sessions have no `sampler` key because the old writer hard-coded schema=2, so this is genuinely missing evidence and None is correct under the plan. Positive control (replay script at /private/tmp/claude-501/peer-scratch/c6-correctness/): giving score_arm sampler schema 2 yields exactly the same 12 differences from stored verdicts as baseline d898f445 score_verdicts on producer-re-derived records. So C6 introduces no scoring or plumbing regression. Those residual differences come from pre-C6 WIP 47bc3698 drift after capture head 03a35b28, not from C6: Alpha feed b3to4 goes False to True; Alpha feed b6to7/b7to8 x2 go None to False; D7/D7s feed-off last carry goes False to None, handbackContinuity unreadable. The replay's '0 contrary / 0 fabricated' result is therefore vacuous for those 12. They are masked by the missing schema and must not be cited as evidence that observed reds survive.

**Fix.** C6 needs no code change. In the C6 gate record:
- State that all 12 "became unknown" verdicts come from the missing stored sampler schema. The attempt-3 sessions have no `sampler` key because the old writer hard-coded schema=2.
- Add the schema-2 null control: C6 score_arm with sampler schema 2 gives the same 12 differences as score_verdicts at d898f445.
- Say that "0 contrary / 0 fabricated" does not cover those 12.

Send the pre-C6 drift since capture head 03a35b28 to the C3 "no later failure disappears" review:
- Alpha feed b3to4 goes False to True.
- Three Alpha feed verdicts go None to False.
- Eight D7/D7s feed-off carries go False to None ("handbackContinuity unreadable"), not six as the finding says.

Attribute this drift to the post-03a35b28 changes (likely 47bc3698), unless someone bisects it.

## major · standards · score_arm saves authored samples labelled sampleSpace="screen", so replaying a C6 artifact converts the samples a second time
`scripts/live_continuity_probe.py:4594` · class: new class

**Scenario.** score_arm starts from result = deepcopy(capture), which copies capture_arm's "sampleSpace": "screen". It then replaces result["samples"] with AUTHORED rows and never updates sampleSpace. run_arm, run_attach_arm and OBS feed_script persist this result, so every new artifact pairs authored samples with sampleSpace "screen". rescore_generated (:8593) calls setdefault("sampleSpace", "authored"), which leaves the stored "screen" in place, so _capture_samples converts the rows again. I checked this in a scratch run with LETTERBOXED_STAGE_MAP_5_6: screen rect {x:100,y:150,w:500,h:250} becomes {120,120,600,300} on the first score and {144,84,720,360} on replay. The replay also overwrites rectScreen with the authored rect. Every --rescore or offline replay of a non-identity-stage C6 artifact scores wrong geometry. The new TestArmInterface only feeds sampleSpace="authored", so it cannot catch this.

**Fix.** In score_arm, set result["sampleSpace"] = "authored" right after result["samples"] = samples, so the stored label matches the rows. Do not add a new test. Extend the existing score_arm test in TestArmInterface with one round-trip assertion: for a screen-space capture using LETTERBOXED_STAGE_MAP_5_6, score_arm(json round-trip of score_arm(capture))["samples"] must equal score_arm(capture)["samples"].

## medium · standards · The feed-off continuousExpected fix (feed_script(True) to feed_script(False)) is not covered by any test
`scripts/managed_obs_qualify.py:4689` · class: new class

**Scenario.** In sessions_for, C6 changes the feed-off session from feed_script(True) to feed_script(False); this is the behaviour change the plan requires ("OBS receives the session's value"). test_feed_arm_registers_continuous_and_qualification_only_once_sessions uses captured_sessions, whose run_session stub throws away the `script` argument. The new tests call q.feed_script(False) directly. Reverting line 4689 to feed_script(True) therefore leaves every test green, and the bug that made attempt-3 feed-off records claim continuousExpected=True could come back silently.

**Fix.** Make the smallest change to the existing feed-arm registration test and add no new test. In captured_sessions, keep the script: calls.append({"name": name, "script": script, **kw}). In test_feed_arm_registers_continuous_and_qualification_only_once_sessions, run monkeypatch.setattr(q, "feed_script", lambda continuous_expected: continuous_expected) before captured_sessions, then assert calls[0]["script"] is True and calls[1]["script"] is False. Do not add a flag-exposing attribute to feed_script, since that would be speculative interface growth.

## medium · standards · The environment observation labelled "during" is taken before driving starts
`scripts/managed_obs_qualify.py:2270` · class: new class

**Scenario.** feed_script records environment["observations"]["during"] right after s.host.execute("show") and before capture_arm calls drive_and_sample. That is a second "before" sample under a name that tells C2 it measured load and foreign-Chrome counts mid-capture. A load spike or a foreign Chrome that starts during the take will not appear in "during". test_feed_capture_scores_both_retirements_with_final_environment only checks the key order [before, during, after], so it accepts the mislabelled timing.

**Fix.** Simplest fail-closed fix: stop writing a "during" observation at line 2270, and make "during" absent/None until a real mid-drive hook exists. Note it in report-O so that C2 treats a missing "during" as unproven. If a real mid-run sample is wanted now, have the existing observer that capture_arm passes to drive_and_sample take an environment_observation at one mid-deck ordinal, rather than adding a new parameter. In the test, use a fake drive that triggers the observer and assert that the "during" observation is made inside drive (for example, record the call order of environment_observation and drive), instead of checking only key order.

## low · standards · CAPTURE_FIELDS is defined but never used
`scripts/live_continuity_probe.py:360` · class: edge case

**Scenario.** A grep over scripts/ and tests/ finds CAPTURE_FIELDS only at its definition. No code or test validates a capture against it, so the frozen-contract list it appears to enforce can drift without anything failing. This is speculative generality or dead code.

**Fix.** Delete CAPTURE_FIELDS from scripts/live_continuity_probe.py:360-363. The plan's §2 C6 table is already the frozen contract. C2 can add the constant together with the validity check that reads it. If the team wants the freeze enforced now instead, one existing capture_arm test could assert set(capture) >= set(CAPTURE_FIELDS) so the constant does something. Deletion is simpler and fits the owner rules better.

## low · standards · The new environment parameter on run_arm and run_attach_arm has no caller
`scripts/live_continuity_probe.py:4714` · class: edge case

**Scenario.** run_arm (:4714) and run_attach_arm (:4838) now take environment=None and pass environment or {}. None of the callers (run_cli :9555/:9563/:9571/:9633, run_red_arm, run_paint_control, detach_experiment :1514) pass it. Every headless and attach capture therefore stores environment: {}, the parameter has no effect, and it reads as if headless captures carry the plan's environment record when they don't.

**Fix.** Choose one:
(a) Fill in the environment for headless and attach in line with the C6 contract. Give stream P a small builder for browser version, git head, qualification identity and before/after observations, like `feed_environment`/`environment_observation` in stream O. Pass it from the run_cli A/B/C/attach call sites and from detach_experiment's `run_arm` call.
(b) Remove the `environment` kwarg from `run_arm` and `run_attach_arm` and pass `environment={}` directly to `capture_arm`. Drop the `environment` argument from the test at :8256-8263. Note in report-P that the headless/attach environment record is deferred to C2.

Do not keep a public parameter that no production code uses.

## low · standards · rescore_generated looks up an expected stage whose result is discarded
`scripts/live_continuity_probe.py:8595` · class: edge case

**Scenario.** rescore_generated reads stageFit.expected from the stored entry, falling back to result attachExpectedStage or expectedStage, and passes it to score_arm. score_arm uses expected_stage only for result["stageFit"]. rescore_generated keeps only arm[spec_id] and never reads stageFit. The lookup (which also reads a saved derived field) has no effect on the output.

**Fix.** In rescore_generated, delete the two-step stage lookup at lines 8595-8597 and call `arm = score_arm(capture, arm_facts, {})`. stageFit then reports "expected stage fit is unavailable", which nothing in the rescore output reads.

## low · standards · The four-deck score_arm parametrization does not cover D7, D7s or Alpha shapes
`tests/test_live_continuity_probe.py:8094` · class: edge case

**Scenario.** All four cases build _p2_facts() and only rename planSha256 to "D7", "D7s" or "Alpha". score_verdicts, verdict_records and arm_paint_census are all monkeypatched. The ids ("D7-missing-sampler", "Alpha-runtime-not-installed") and report-P's claim of "P2, D7, D7s, and Alpha shapes" overstate what is covered: it is one fact shape exercised with a sampler, producer and continuity toggle. The test also branches internally (if producer is None / else, if stale_alias), so each case checks a different subset of assertions.

**Fix.** Rename the param ids and the `deck` argument to the evidence axis each case varies (complete, missing-sampler, missing-producer, runtime-not-installed). Drop the `planSha256` relabel, and use explicit per-case `aliases` and `retirement` params instead of deriving them from the deck string. Replace the `if producer is None` / `if stale_alias` branches with per-case expected values, so each case asserts the full interface contract. Correct report-P's claim that the family covers the D7, D7s and Alpha shapes. Alternatively, if the plan's wording "P2/D7/D7s/Alpha" is meant literally, build minimal deck-shaped facts for each deck, for example the two Alpha retirements, so the labels describe real shapes.

## low · standards · Most of the detach late-binding test asserts values that hold whatever capture_arm does
`tests/test_detach_experiment.py:200` · class: edge case

**Scenario.** The fake drive reads probe.SAMPLER_JS, probe.FEED_CONTROL and probe.FEED_DWELL_S from the module globals itself. capture_arm never passes those three, so the asserted values ('rafTs' present, {tamper: late}, 0.25) are true even if capture_arm captured them at import. The only part that would fail is sink["instrumentRead"], which proves drive_and_sample is resolved at call time.

**Fix.** In test_capture_arm_installs_the_observer_and_resolves_detach_hooks_at_invocation, make the fake drive record only ("drive",), with no SAMPLER_JS, FEED_CONTROL or FEED_DWELL_S reads. Remove the monkeypatches of probe.FEED_CONTROL and probe.FEED_DWELL_S and update the expected events list to match. Keep the observer-order, evidence/sampler/capture-key and sink["instrumentRead"] assertions. Optionally rename the test so it no longer claims to check all detach hooks, since only drive_and_sample late-binding is exercised through capture_arm.

## nit · standards · The fixture identity is computed twice, and feed_fixture_facts overwrites it with an identical value
`scripts/managed_obs_qualify.py:1938` · class: edge case

**Scenario.** complete_facts now sets facts["fixtureIdentity"] = feed_fixture_identity(...) whenever feed specs exist. feed_fixture_facts has already computed the same identity through require_feed_fixture and assigns it again at :1938. run_cli likewise calls require_feed_fixture, which hashes every slide JSON a second time. That is duplicated work, and there are two places that decide fixtureIdentity.

**Fix.** No change needed. If cleanup is wanted, keep feed_fixture_facts' assignment at managed_obs_qualify.py:1938, because it is the refusal-checked identity and covers the under-artwork-without-feed case. Do not delete it. Leave run_session's require_feed_fixture as it is (separate per-session export).
