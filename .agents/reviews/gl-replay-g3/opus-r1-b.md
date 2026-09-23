# R-B review: GL-replay G3 P2 plan change + G4 host flag (round 1)

Reviewer: Opus (R-B), read-only. Branch `feat/gl-replay-g3g4`. Reviewed: `git diff e59927e4 959eb651` (P2),
`git diff 959eb651 2884e116` (host). Spec: `.agents/plans/keynote_live_gl_replay_g3g4.plan.md` rev 2 §3–§4 (OD-2/OD-3 defaults).

**Verdict: no BLOCKER, no MAJOR.** 3 MINOR, 6 NIT. The off path is clean and forced-tested. The auto fallbacks and the
injection order are correct. The P2 boundary is byte-exact to the derived flag-on plan. `refusedCarry1to2` is sound, with one
gap: it does not pin the fallback reason (F2).

Commands run:
- `uv run pytest tests/test_p2_adversarial.py tests/test_live_host.py tests/test_live_continuity.py -q -rs -n auto` gave 1019 passed and 0 skipped.
- `OBED_LIVE_GL_REPLAY=auto uv run pytest tests/test_live_host.py`: 179 passed, so the new env is hermetic for the suite.
- Mutation runs on a scratch copy (table in §5). The null control passed and 9 of 9 product mutations went RED.

## 1. Does `off` inject, import-execute or evaluate anything, or change a served byte?

- **Served bytes: no change beyond the sanctioned v5 core.**
  - Off derives with no kwarg (`live_host.py:832` → `_derive_runtime()` :852-862, `derive_plan(..., resolver=...)`).
  - It serves `_continuity_scripts(plan, canvas) + ""` (:1033). `self._gl_replay_script` is `""` unless `_resolve_gl_replay` returned `injected` (:879). That function is reached only when preference is `auto` (:830-831).
  - `_continuity_plan_script`, `_continuity_core_script`, `_continuity_scripts` and `_AssetServer._program_html` are untouched by the diff.
  - Continuity off (ctor or env) returns before any GL code (:826-827).
  - Inactive-HTML sha pins are untouched (`test_continuity_inactive_html_is_byte_identical_to_pre_i2`).
- **In-page: nothing.** No `obed-gl-replay` tag is served, and the v5 core's `GL` is null without a `glReplay` boundary (`live_continuity_js.py:459`).
- **Python: two things do run on off. Both are harmless.**
  - (a) `live_host.py:35-36` now imports `live_gl_replay_js` unconditionally. It is the first production importer. The module has no side effects: it only defines constants and functions (`live_gl_replay_js.py:25-34, 1182-1269`).
  - (b) `_gl_replay_info()` calls `gl_replay_js_sha256()` on every `output` read and in the `continuity` log (:961, :964-970, :1060). §4 "Surface" requires this (version and sha in every mode), but it contradicts the letter of §4 "Off path" ("nothing from `live_gl_replay_js` is called"). See N1.
- **Forced, not grepped: yes.**
  - `forbid_gl_module` replaces `live_host.gl_replay_script`, `live_gl_replay_js.gl_replay_script` and `validate_gl_replay_entry` with raisers.
  - `spy_real_derive_plan` records the kwargs of every call.
  - The test runs over 6 off routes × core v4/v5 (`test_live_host.py` G4 block, `test_gl_replay_off_never_touches_the_module_and_serves_todays_recipe`).
  - Mutations M2 (off passes `gl_replay=False`) and M6 (unset env → auto) go RED.

## 2. `auto`

| Case | Code | Result | Test (forced) |
|---|---|---|---|
| attach | `live_host.py:867-868` (first check) | `unavailable`, "attach output not qualified", flag-off plan + `transparentBackground` | `..._in_attach_mode_is_not_injected` (module forbidden); M5 RED |
| core < 5 | :869-870 | `unavailable`, flag-off plan | `..._with_a_v4_core_serves_the_off_plan` (monkeypatched 4); M4 RED |
| Unsupported (derive or `to_runtime`) | :871-873 | `unavailable` + reason, re-derive off | `..._unsupported_flag_on_plan_falls_back_to_off` ×2 |
| no entry | :874-875 | `notApplicable`, re-derive off, bytes == off | `..._without_an_entry_...byte_identical_to_off` (real derive) |
| empty script / invalid entry | :876-878 | `unavailable`, re-derive off | `..._empty_module_script_...`, `..._real_invalid_entry_...`; M7 RED |
| codec refusal after acceptance | :844-846 | `unavailable`, "continuity unsupported"; no plan served (:1032-1035) | `..._codec_refuses_continuity`; M1 RED (weak assert, N4) |

- **Order.** plan < core < `obed-gl-replay` < fit < `#stage` < `main.js`. `continuity_script` is plan + core + gl (:80-81, :1033), and the body inject is overlay + continuity + fit (:431). The real `_AssetServer._program_html` pins this with a strict index chain (`..._injects_the_flag_on_plan_and_the_module_after_the_core`). M3 (gl before core) goes RED.
- **A `glReplay` plan with a v4 core: impossible in the host.** The :869 guard catches it. In P2, a v4 core would treat `glReplay` as a non-retire (carry). It would then emit no `glreplay-zone` note, and `refusedCarry1to2` fails "glReplay zone never fell back to retire" (`p2_verdict.py:850-851`). Both paths fail closed.
- **A `glReplay` plan without the module.** The host never does this: `injected` requires a non-empty script, and every other outcome re-derives off. P2 does it on purpose. The v5 core resolves `pending` to `retired` with reason `moduleAbsent`, and `pending` refuses like retire (`live_continuity_js.py:472-478, 515-525`). G-P2 on 2884e116 measured this path as safe.
- **Observation, no finding.** If the page-side stage gate later turns continuity `unsupported` (:926-955), `glReplay.mode` stays `injected`. That is truthful, because the tag was served, and G2 stands down on `disabled` (plan R8). The codec path differs because there nothing was served.

## 3. Parsing, precedence, messages, surface, downstream

- **Ctor.** An exact `"auto"`/`"off"` wins; anything else, including `None` and `""`, raises "GL replay must be auto or off." (:751-752). This matches the `continuity` ctor (:749-750) and the `_UNSET` precedent of `attach_endpoint`.
- **Env.** It is read in `start()` only when the ctor argument is unset, via `strip().lower()`. `""`/`off` → off, `auto` → auto; anything else raises "OBED_LIVE_GL_REPLAY must be off or auto." before any resource is created (:1004-1010). This mirrors ADVANCE (:1001-1003). Tests pin precedence, including ctor `auto` + env `bogus` → `injected`, and assert that nothing starts on an invalid env.
- **Surface.** `output()["continuity"]["glReplay"] = {mode, reason?, version, sha256}` (:964-970). The `continuity` log record carries the same dict (:1060). Both are pinned equal in `test_gl_replay_output_shape_before_and_after_start`.
- **Downstream: no change needed.**
  - `web/live.py:132` passes only `continuity`, so the flag comes from the env.
  - `web/live.py:138` snapshots `host.output` before `start()`, so `mode: "off"` there. That is truthful for "not yet resolved" and matches continuity's own pre-start `off`.
  - `LiveContinuity` (`dashboard/src/live/api.ts:8`) is a parsed-JSON type, so the extra field is inert.
  - `LivePresenter.tsx:13-22` reads only `mode`, `reason`, `scale` and `notCarried`.
  - `notCarried` is unchanged under `auto`: the flag-on plan keeps `movie.refusal` (`live_continuity.py:1492-1498`), and `_not_carried` projects the same four keys. This is OD-3-consistent.
  - `scripts/live_continuity_probe.py` reads only `continuity.mode`.

## 4. P2

- **Byte-exact: yes.**
  - `plan_signature(build_continuity_plan(True) − transparentBackground)` = `6a0596da…` = `plan_signature(derive_plan(FIXTURE, gl_replay=True).to_runtime())` (measured). The signature is sorted-key JSON, so equal digests mean an identical canonical serialisation.
  - The sorted JSON of boundary 0 is identical (measured).
  - `test_injected_plan_matches_the_derived_flag_on_runtime_plan` pins `==`, same-order `json.dumps` and allowlist membership. `test_gl_replay_flag_on_runtime_plan_is_pinned_and_qualified` pins the derived side to `6a0596…`.
- **Can a live carry pass?** No, on three independent grounds:
  - Any `armed`/`released` zone note fails (`p2_verdict.py:815-817`; M9 RED).
  - Any `glreplay-live` fails (:818-819; M8 RED).
  - The pre-existing census, lingering, frozen-composite and hash clauses are unchanged.
- **Can a retired-by-fallback run fail?** Only if the `glreplay-zone` note is not fetched. The core's `events` array is unbounded (`live_continuity_js.py:690-693`), and the script's kind filter now keeps `glreplay-zone` (`scripts/p2_recovery_html_adversarial.py:3242`). The gate passed.
- **`glReplayFallback`** = the `reason` of the first `to == "retired"` note, and only for a `glReplay` plan (:869). `retired` is terminal (`live_continuity_js.py:49-52`, single `setZone('retired')` at :543), so in practice there is at most one such note. The verdict does not require that reason to be `moduleAbsent` (F2).
- **Other findings vs the shape change.** Only `refusedCarry1to2` reads `action` (grep: `p2_verdict.py:800-808`). The script uses `continuity_plan["boundaries"]` only as detail (:3519). `neverPooledEvidence` is blind to the armed-zone pool (N3); this is masked and unreachable in P2.
- **Is the server-side filter complete for what the verdict reads?**
  - It now holds everything read by the new and the refusal clauses (`preserve-refused`, `retire-boundary`, `glreplay-zone`, `glreplay-live`).
  - `bridge-3to4` is fetched separately (:2599, :3437).
  - Of `CARRY_EVENT_KINDS` (`p2_verdict.py:127-136`), `remount-scheduled`, `remount-authored-parent`, `remount-into-authored-layer` and `remount-footprint-rect` are **not** kept, and `remount-done` is sliced (:3246-3248). So the local `carryEvents` belt is partly blind. This is a CLOSED CLASS: the authoritative in-page census counts the full log over the full kind set (`CARRY_CENSUS_JS`, :203-243). The enumeration itself is unpinned (F1).

## 5. Test quality (mutations on a scratch copy; null control 38 + 43 passed)

| Mutation | Result |
|---|---|
| M1 drop codec reset (:845) | RED |
| M2 off derives with `gl_replay=False` | RED |
| M3 gl tag before core | RED |
| M4 guard `< 4` | RED |
| M5 drop attach guard | RED |
| M6 unset env → auto | RED |
| M7 drop empty-script guard | RED |
| M8 drop `not went_live` | RED |
| M9 accept `released` | RED |

The one tautology is in the new `test_live_continuity.py` test (F3).

## Findings

### F1: MINOR, NEW CLASS: the P2 fetch filter is a hand enumeration, unpinned against the kinds the verdict reads

- **Evidence.** The plan's F10 said "no script change is needed". It was wrong, and only the live gate caught it: the `keep` list at `scripts/p2_recovery_html_adversarial.py:3227-3243` is a JS literal. No test ties it to the kinds that `refusalEvents`, `refusedCarry1to2` and future verdicts read (`p2_verdict.py:524, 809-818`). This is the memory's "schema-not-enumeration" lesson recurring.
- **Failure scenario.** A later edit drops `glreplay-live` from the list. The `went_live` absence clause then becomes silently vacuous: it fails open, not closed. Dropping `glreplay-zone` would fail closed.
- **Fix, exact wording.**
  - "Move the kept kinds into `p2_verdict.PRESERVE_EVENT_KEEP_KINDS` (a sorted tuple). Substitute it into the fetch JS with `json.dumps` exactly as `__CARRY_KINDS__` is (`:240`).
  - Add a test in `tests/test_p2_adversarial.py` asserting `{"preserve-refused", "retire-boundary", "glreplay-zone", "glreplay-live"} <= set(p2.PRESERVE_EVENT_KEEP_KINDS)`, and that the script source contains the placeholder, not a literal list.
  - Prove the test RED by removing `glreplay-live` from the constant."
- **Ownership.** `scripts/**` is outside Stream B; the coordinator owns it.

### F2: MINOR, EDGE CASE: `refusedCarry1to2` accepts any `pending→retired` reason; G-P2's `moduleAbsent` is only reported

- **Evidence.**
  - `zone_fell_back` requires only `to == "retired"` (`p2_verdict.py:814-817`).
  - `glReplayFallback` is the first reason (:869).
  - `output/gates-g3/summarise_gates.py:63` copies it into the gate record without asserting it.
  - Plan §6 G-P2 requires "`glReplayFallback` = `moduleAbsent`".
- **Failure scenario.** A G3 core change makes `glEntryValid` (`live_continuity_js.py:497-500`) reject the P2 entry, which the Python validator accepts. The zone then retires `entryInvalid`, P2 stays fully green, and G-P2 no longer qualifies the path it claims to (module absent on a valid entry). A duplicate `retired` note (impossible today, since `retired` is terminal) would also pass silently.
- **Fix, exact wording.**
  - "Add keyword `expected_gl_fallback: str = "moduleAbsent"` to `refusedCarry1to2`. For a `glReplay` plan, `zone_fell_back` additionally requires `zone_retired == [expected_gl_fallback]`.
  - Otherwise append the reason `f"glReplay fell back for {zone_retired!r}, expected [{expected_gl_fallback!r}]"`.
  - Add a RED-first test with `_zone_note(reason="entryInvalid")` in place of the default note ⇒ `ok is False`.
  - Change `test_refused_carry_reports_the_first_retired_zone_reason_as_the_fallback` to expect `ok is False` for two `retired` notes."

### F3: MINOR, CLOSED CLASS: a tautological tail in `test_gl_replay_instance_rect_selects_exactly_one_source_slide_instance`

- **Evidence** (`tests/test_live_continuity.py:2969-2971`):
  - The last assert counts matches over `(*source, dict(matches[0]))`. That only tests the test's own `within` helper: an appended copy of a match matches.
  - The `shifted` (+1.01 px) assert is implied by `assert matches[0] == target` two lines earlier.
  - Neither exercises product code, and neither can go RED under any product mutation.
- **Fix, exact wording.** "Delete the `shifted = …` line and the two asserts after it; the selection claim is fully carried by `len(matches) == 1`, `matches[0] == target` and the sibling distance > 900."

### N1: NIT: the off-path docstrings overclaim

- **Evidence.** The `forbid_gl_module` and `test_gl_replay_off_never_touches_the_module_and_serves_todays_recipe` docstrings say the off path "never call[s] into `live_gl_replay_js`". But `gl_replay_js_sha256()` runs on every `output` read and log (`live_host.py:969`), and the module is imported unconditionally (:35-36). Both are side-effect-free and required by §4 "Surface".
- **Fix.** "Reword to: off never builds, validates or injects the GL module; only its version and sha are reported."

### N2: NIT: `went_live` is whole-run, but the reason says "inside the refused zone"

- **Evidence.** `p2_verdict.py:818, 853`. This fails closed.
- **Fix.** "Reason text: `glReplay went live`." Alternatively, scope the check to `sceneHash < restart_scene`.

### N3: NIT, EDGE CASE: `neverPooledEvidence` ignores the glReplay `armed` pool

- **Evidence.** `armed` pools the carried decoder (`__obedGlPooled`, `live_continuity_js.py:52-53, 738-739`). `neverPooledEvidence` (`p2_verdict.py:884-913`) does not look at zone notes. This is masked in P2, because `refusedCarry1to2` fails on any `armed` note, and it is unreachable there because no module is loaded.
- **Fix.** "Also fail `neverPooledEvidence` when any `glreplay-zone` note has `to in ("armed", "released")`."

### N4: NIT: the codec test's assertion is weak

- **Evidence.** `mode != "injected"` would also accept `off`.
- **Fix.** "Assert `== {"mode": "unavailable", "reason": "continuity unsupported", "version": …, "sha256": …}`."

### N5: NIT, CLOSED CLASS: `_derive_runtime` guards `derive_plan` but not `plan.to_runtime()`

- **Evidence.** `live_host.py:853-859`. Under `auto`, the new `glReplay` branch of `to_runtime` (`live_continuity.py:787-822`) runs unguarded, so a raise there would abort `start()` instead of falling back to off. The branch looks total today, and the class predates this diff.
- **Fix.** "Move `runtime = plan.to_runtime()` inside the `try`."

### N6: NIT: the `start` log does not record the requested GL preference

- **Evidence.** `advanceMode` and `goToAutoplayMode` are logged (`live_host.py:1019-1020`). Under continuity off or attach, the log cannot show that `auto` was requested.
- **Fix.** "Add `glReplayPreference=self._gl_replay_preference` to the `start` log record."
