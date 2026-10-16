# Pre-draw source geometry and draw-completion evidence — r3

## Goal

Exempt startup rider rows only when every **visible** decoder sample stayed within **1 authored px on all four edges** (owner, 2026-10-16, after Step 0) of its authored source slot, within the existing grace and stand-down bounds. Measure grace to a completed GL draw and prove separation with a startup-only moved-decoder control.

Plan only; no implementation or captures were run for this revision. Code citations refer to read-only base `7746df27631fee2e33b86689bf894ca7602cd6dc` in `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/funny-pasteur-751a72`. `MAIN:` means `/Users/anyhowclick/Desktop/work/obed-edom/`. The approved bounded rule and deferred geometry work are in `.agents/reviews/stage-b/alpha-placement/gate-record-2026-10-16-predraw.md:5-14,30-37`.

## Non-goals

No product behavior, core/feed bytes, SHA pins, warm-up implementation, stacking semantics, or continuity-scoring changes. Restrict implementation to instrument, probe configuration, producer contract, variants, minimal gate wiring, and tests. Match dense one-line `INSTRUMENT_JS` style; minimal NatSpec, no inline comments unless necessary (tests may explain cases). No new evidence framework, CI, OBS qualification, or full Stage B campaign.

## Step 0 — feasibility gate before the rest

Implement only the JS source-error helper/accumulator and the two authored-source probe configuration additions described below. Before changing Python scoring, the contract, controls, or tests, capture current-core Alpha and D7 once at **1920x1080 and 2560x1440**: four captures, approximately 15 minutes, heavy. Complete the environment setup under Coordination and evidence before these captures.

Make the two probe additions permanent in Step 0: add `authoredSrcRect=movie.src_rect.as_dict()` to carry specs and expose it as instrument-entry `srcRect` in `feed_specs_for` (`scripts/live_continuity_probe.py:1565-1575,1930-1940`). Continuity's existing `srcRect` stays unchanged; the contract's `_fields` ignores extra keys (`scripts/live_evidence_contract.py:115-120`). These configuration additions do not change scoring. Source rectangles are already required (`scripts/live_continuity_probe.py:1539-1544`).

Report the maximum visible-prefix `sourceRectError` for every sampled carry/visit, explicitly including Alpha b5to6 and b7to8-wa0121 and D7 b0to1 a/b. Require actual visible-prefix observations on those motivating carries; missing/unreadable measurements do not establish feasibility. **If any positive exceeds 1.0 px, stop all remaining implementation and take the measurements to the owner. Do not relax or reinterpret 1 px.** Resolve capture failures before proceeding; if feasibility cannot be established, stop with the data.

**Step 0 result and owner decision (2026-10-16):** Alpha b5to6 measured 1.042 CSS px at 2560 (0.781 at 1920). That is a fixed 0.781 authored-px offset between Keynote's exported layer and the plan `srcRect`, and it is present at rest on the source slide. The owner chose **1 authored px**: `sourceRectError` is reported in authored px (the CSS edge error divided by the live stage scale `s`), with the limit at 1.0. Record: `.agents/reviews/stage-b/predraw-geometry/step0-2026-10-16.md`.

The risk is real: `domRead.rectError` measures origin/size errors, whereas right/bottom edges combine them (`scripts/mm_feed_instrument.py:136`). Stored Alpha `closedDom` readings include 0.337–0.484 px (`MAIN:output/evidence/stage-b-2026-10-13/alpha-placement/alpha-fix.verdicts.json`); these are motivation, not source-edge proof. Step 0 gates every subsequent section. Its geometry-only captures are diagnostics, not final contract-qualified evidence.

## Design decisions

1. **Independent authored source.** Add `authoredSrcRect=movie.src_rect.as_dict()` to carry `add(...)` in `verdict_specs`; emit it as instrument-entry `srcRect` in `feed_specs_for`. Preserve continuity's existing `srcRect`, including the pin shortcut (`scripts/live_continuity_probe.py:1565-1575,1930-1940`): it also feeds continuity, source-placement, and paint-gap scoring (`:3752,3900-3901,3988`). Reject reading the runtime plan or falling back to destination/current decoder geometry: the independent probe facts must identify the source for every census entry. Configuration already deep-copies entry fields (`scripts/mm_feed_instrument.py:357`).
2. **Local source mapping.** Leave shared `stageMap`/`expectedBox` unchanged; they also feed `domRead` and hand-back (`scripts/mm_feed_instrument.py:122-136,339-342`). In the new source helper, reproduce the core's live map: both offset and bounding dimensions >1, positive scale, `abs(sx-sy)/avg <= 0.001`, scale `sx`, screen origin `left/top` (`src/obed_edom/live_continuity_js.py:369-384`). Reject non-finite inputs and invalid source/decoder dimensions. Map authored edges, then take `max(abs(actual.left-L), abs(actual.top-T), abs(actual.right-R), abs(actual.bottom-B)) / s` (authored px). No rounding, DPR multiplication, cached map, or origin/size substitute.
3. **Visible samples only.** Fold geometry before rider-row deduplication, but only when the decoder is visible. Hidden samples contribute nothing; emit 0 when no sample was visible. A visible sample with unreadable geometry contributes sticky `null`. Visibility already uses opacity-aware `checkVisibility` (`scripts/mm_feed_instrument.py:117-120`). This avoids rejecting a legitimate bridge after `finishDepartureHides` hides and moves it through `rideFrame` while the sampled frame remains open (`src/obed_edom/live_continuity_js.py:868-875,1325-1332,1436-1443`; `scripts/mm_feed_instrument.py:256,402`). Reject folding hidden geometry or changing the existing representative-row visibility semantics.
4. **First completed draw per context.** Stamp `firstDrawAt` once, immediately after the original draw returns, including the no-active-frame path; a thrown call does not stamp (`scripts/mm_feed_instrument.py:226,262-284`). Choose any context draw because the agreed prefix already ends at context-wide `draws > 0` (`:614-624`). The product waits for feed advancement/stand-down after the callback (`src/obed_edom/live_continuity_js.py:846-875`); this earlier context endpoint is conservative and does not claim compositor presentation. Reject a new per-entry timing protocol. Start grace at the first move-frame `t`, preserving the existing start event, rather than context creation. No current-scorer frame-time fallback.
5. **Visit-wide exemption.** One prefix error >1 or unreadable error disables the whole visit's exemption; score all rows. Reject per-frame exemptions. Geometry is an exemption prerequisite, not a new rider offense or coverage condition. Preserve `_rider_readable`, `_rider_offender`, ordinary coverage, and complete-stream checks (`scripts/mm_feed_instrument.py:630-632,762-769,918-931`). Do not add usable-context, lost-context, or attribution prerequisites to the `exempt` flag.

## File-by-file changes

### `scripts/mm_feed_instrument.py`

- Add `SOURCE_RECT_TOLERANCE_PX = 1.0` (authored px); retain `PRE_DRAW_GRACE_MS = 320.0` (`:8-21`). Add the local source-error helper above.
- Initialize private `F.srcErr = {}` at frame creation. At each `collectRiders`, resolve decoder, visibility, and bounding rect before dedupe; avoid full `decoderRead` on repeated samples. Retain the existing representative-row creation and opacity/intersection values. Missing decoder creates no row; a frame without a row still fails ordinary coverage. For an existing hidden decoder, do not require readable source geometry.
- Fold each visible measurement into the entry's maximum, with sticky null. Preserve `srcErr` when `finalizePixels` clears/recollects riders. In `finishFrame` only, copy each aggregate (default 0 for no visible sample) into `row.sourceRectError`, then delete private state. Every stored frame passes through that function (`:255-260,329-334,397-404,421`). Cover previous-frame clear, final draw, tick, and report collection; do not add another sampling loop.
- Initialize `contextRecord.firstDrawAt = null`; stamp after successful `O[name].apply`, before reference capture or other post-draw reads, on both draw paths. Preserve returns/exceptions and stamp immutability across subsequent calls (`:226,263,273-284`).
- In `_visit_record`, retain per-entry/serial selection and prefix discovery (`:516-524,612-619`). Compute `preDrawMs = move.firstDrawAt - move_frames[0].t` only with finite, ordered times and a drawn frame; otherwise `None`. A timestamp before the first drawn frame's clear cannot establish this prefix and grants no exemption.
- Set `exempt` only for a nonempty zero-draw prefix followed by a drawn frame, `0 <= preDrawMs <= 320`, no accepted visit stand-down at/before `firstDrawAt`, and exactly one finite nonnegative `sourceRectError <= 1.0` per entry in every prefix frame. Preserve the separate coverage computation; a later unreadable frame remains inconclusive independently. Keep the first drawn frame fully scored and never-draw visits inconclusive. Preserve `preDrawFrames`, `preDrawMs`, `exempt`, and `exemptedVisibleSamples`; the last counts exempted offending representative rows, not collection calls (`:621-632,749-751`).

### `scripts/live_continuity_probe.py`

The authored-source configuration changes land in Step 0. After that gate passes, add `startup-moved-decoder` to `feed_fixture_required` and register `{"labelsOverFeed": True}` in `MM_FEED_GATE_EXPECTATIONS` (`:361-378,1172-1179`).

Extend `mm_feed_control_aggregate_problems` using the intermittent-control pattern (`:1182-1203`): require every row's `noRiderAboveCanvas` verdict to be readable and at least one False row with an offender whose `sourceRectError` is finite and >1.0. Missing geometry does not prove the control. Offenders retain raw rider fields (`scripts/mm_feed_instrument.py:929-931`). No target-ID resolver or per-target gate logic.

### Contract, variants, and runner

Implement the producer-only contract and red control below. In `scripts/run_gates.sh`, add only these two `MM_FEED_ARMS` entries; leave its checking heredoc unchanged. The existing checker already calls the aggregate function and enforces registered leaf expectations (`:100-128,765-788`).

```text
Alpha_DSK startup-moved-decoder --core-variant startup-moved-decoder
D7 startup-moved-decoder --core-variant startup-moved-decoder
```

## Contract changes

In `scripts/live_evidence_contract.py`, require these producer keys using existing `_fields`/`_finite` checks (`:628-633,701-712,786-795`). No normalized-rider schema additions (`:1001-1006`).

| Producer field | Rule |
|---|---|
| Rider `sourceRectError` (authored px) | Explicit null or finite nonnegative number; missing, boolean, string, NaN/Infinity, or negative is invalid. Null means a visible geometry measurement failed; no visible samples means 0. |
| Context `firstDrawAt` | Explicit null or finite number >= `createdAt`; null means no completed draw observed. |

Keep the existing v1/v2 branching and require both new keys in every version. This refuses every real v1 file and every older v2 file, because neither producer emits them. Keep the current producer at version 2. Required-field tightening without a version bump has precedent in `9bf912b6:scripts/live_evidence_contract.py:675-695` and `51ee3be2:scripts/live_evidence_contract.py:675-700`; the alternative, a new version with compatibility gating, was used for hand-back in `1df31c33` (current version branches at `scripts/live_evidence_contract.py:688-733`). Choose strict refusal of missing fields because current rescoring rebuilds records from producers; accepting absence would certify geometry never measured (`scripts/live_continuity_probe.py:4636-4655`). Producer refusal makes the **whole under-artwork carry verdict None**, not merely the rider leaf (`:4355-4373`).

Assuming otherwise valid timing, coverage, and a drawn suffix:

| Prefix observation | Exempt | Rider verdict |
|---|---|---|
| Visible samples all <=1; suffix clean | True | True |
| Hidden throughout (error 0); suffix clean | True | True; 0 exempted visible samples |
| Error >1 or null; visible overlapping offender | False | False |
| Error null; representative rows all nonoffending | False | True |
| Missing row/unreadable draws, or no draw ever | No qualification | None |
| Missing required producer key, in either version | Contract refusal | Whole affected carry None |

## Red control

Add `startup-moved-decoder` to `VARIANTS` and `_TRANSFORMS`, retaining exact-once anchor validation and SHA generation (`scripts/continuity_core_variants.py:24-36,171-201`). Replace the complete hold block at `src/obed_edom/live_continuity_js.py:1406-1409`, retaining its guard and pending departure hide.

**Revised after the first control capture (2026-10-16):** a decoder reparented to `#body` escapes Keynote's source-layer hide at the first GL draw. It stays visible through the first drawn frame, so the pre-geometry scorer already reds it, and the control would not isolate geometry. The stimulus therefore keeps the decoder in its parent. Before opacity 1/return, set `v.style.translate = '8px 0px'`; the core never writes the CSS `translate` property. A second exact-once anchor in `finishDepartureHides` clears it (`v.style.translate = ''`) where the decoder is hidden and handed to `rideFrame`. Keynote's layer hide still applies at the first draw, so only the zero-draw prefix carries the displaced, visible decoder.

For observed control reds, verify a visible overlapping prefix offender with finite error >1 and `exempt=False`; record timing and subsequent restoration. The fresh-producer old/new comparison below must show True→False on those rows. This verifies geometry separation without permanent target/suffix checks or a synthetic counterfactual. Other carries may remain green; all must be readable and labels must pass.

## Grace re-look gate

Ancestry inspection returned exit 1 for `git merge-base --is-ancestor 41800609 7746df27`: F4 has not landed. Record ancestry again at capture time. **Keep 320 ms in this change**; tightening is a follow-up after F4 lands, based on measured completion-time distributions and run-to-run headroom, with a new value justified by data.

From final captures record per entry/visit: viewport, prefix geometry maximum/nulls, `createdAt`, first move `t`, first drawn-frame `t`, `firstDrawAt`, `firstDrawAt - move_frames[0].t`, `firstDrawAt - first_draw.t`, stand-downs, exemption, and verdict. Preserve hashes, load, errors, and callback cost (`scripts/mm_feed_instrument.py:421-425`). If accurate timing makes positives exceed 320, report unresolved validation and take any requested budget change to the owner; do not widen or restore fallback. No grace-confirmation capture matrix in this revision.

## Tests (minimal, after Step 0)

Extend existing fixtures/parametrizations rather than adding a parallel suite.

1. `test_rider_pre_draw_exemption` (`tests/test_live_continuity_probe.py:12316-12383`): retain existing cases; add 1/exceeds-1, one bad frame among two, visible null, hidden zero, duration boundary, null/out-of-order timing, and stand-down between clear and completion. Preserve repeated-visit isolation and separate coverage assertions. Malformed field types belong in contract tests.
2. Extend the JS harness (`tests/test_live_continuity_probe.py:12542-12637`) with accumulator lifecycle checks: move-away/return, hidden post-hide movement ignored, reset/recollect preservation, next-frame reset, and entry isolation. Geometry cases: offset plus one non-unit scale, nonuniform map, sticky null, and right-edge dx+dw. Timestamp cases: framed draw, no-frame draw, thrown draw; assert completion ordering and once-only stamping. Do not duplicate drawArrays/drawElements cases or rework fake GL dispatch (`:12604`).
3. Extend `test_feed_instrument_is_registered_before_navigation` (`:12725-12736`): assert `feed_specs_for` supplies actual authored sources for all scored pin/bridge carries, including a pin with unequal source/destination. Keep continuity `srcRect` assertions unchanged.
4. Extend `test_mm_feed_contract_rejects_required_field_and_generation_breaks` (`tests/test_live_evidence_contract.py:421-434`) for new-key deletion/type/range, legal null/finite values, and `firstDrawAt < createdAt` rejected. Add the two new keys to the existing producer fixtures wherever contexts/riders are present, preserve their versions, and assert that deleting either key is refused. A null `firstDrawAt` remains contract-valid even with positive frame draw counts: those counts increment before the draw returns (`scripts/mm_feed_instrument.py:264,273`). Extend `test_score_verdicts_validates_feed_contract_per_entry` (`tests/test_live_continuity_probe.py:12513-12539`) to prove old-key absence nulls the whole affected carry despite cached success. No duplicate historical test or normalized-schema fixture churn.
5. Extend variant-name/anchor tests (`tests/test_continuity_core_variants.py:26-55`) and registration test (`tests/test_live_continuity_probe.py:12864-12885`). Add one restoration behavior test using `_departure_hide` (`tests/test_live_continuity_js.py:3971-4076`). Extend the existing aggregate test (`tests/test_live_continuity_probe.py:12064-12079`) with one geometry-red case and one red-without-geometry failure.

## Validation runs

### Coordination and evidence

All captures, dependency installs, full Python suites, and dashboard suites are heavy. Coordinator sends a separate `need window` before each heavy block, including each interpreter run, and `done` afterwards. One heavy job machine-wide; captures serial, never more than three headless Chromes. Do not launch the full gate driver.

Working captures, environments, scripts, and logs stay in the **session scratchpad**. Only at the end copy the finished evidence bundle (including failed attempts and diagnostic captures) to `MAIN:output/evidence/stage-b-2026-10-13/predraw-geometry/<run-id>/`. Do not retain evidence in `/private/tmp`, and do not copy virtualenvs or temporary exports into retained evidence.

Set these task variables before running; `PREDRAW_SCRATCH` is the session scratchpad, `PREDRAW_NODE_BIN` the installed bundled Node's bin directory. Before Step 0, run the 3.12 sync and dashboard install below as one heavy setup block (approximately 5–15 minutes, longer with cold caches), then verify Python 3.12. Test/xdist and IWA dependencies are optional extras (`pyproject.toml:32-49`); dashboard tests require TypeScript (`dashboard/package.json:9-12,29`). Keep the Python environment in scratch via `UV_PROJECT_ENVIRONMENT`.

```sh
PREDRAW_REPO=/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/funny-pasteur-751a72
PREDRAW_FIXTURES='/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures'
PREDRAW_OUT="$PREDRAW_SCRATCH/predraw-geometry"
mkdir -p "$PREDRAW_OUT"
export PATH="$PREDRAW_NODE_BIN:$PATH"
cd "$PREDRAW_REPO"
UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv312" uv sync --frozen --all-extras --all-groups --python 3.12
(cd dashboard && npm ci)
UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv312" uv run python --version
```

The fixture/driver paths are verified in `MAIN:output/evidence/stage-b-2026-10-13/norider-ab/repro/run.sh:4-14`. Use the direct probe, not that historical shell script with its pinned worktree.

```sh
UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv312" uv run python scripts/live_continuity_probe.py \
  --fixture "$PREDRAW_FIXTURES/$PREDRAW_DECK/html-player" \
  --original-index "$PREDRAW_FIXTURES/$PREDRAW_DECK/html-unmodified/index.html" \
  --mm-feed on --viewport "$PREDRAW_VIEWPORT" --skip-arms B,C,V,Voff,attach \
  --artifact "$PREDRAW_OUT/$PREDRAW_DECK-positive-$PREDRAW_VIEWPORT-$PREDRAW_TAKE.json"
```

After Step 0 and implementation, run **six fresh positives**: Alpha and D7, each 1920x1080 ×2 and 2560x1440 ×1. Run **four controls**, once each at 1920: Alpha overlay-ride, D7 departure-early-hide, and startup-moved-decoder on both decks. For controls replace `--skip-arms ...` with `--core-variant "$PREDRAW_CONTROL"` and use distinct artifact names; combining these flags is forbidden (`scripts/live_continuity_probe.py:1047-1057`).

Final ten captures cost approximately 35–50 minutes; Step 0 adds four diagnostics/about 15 minutes. Do not count geometry-only diagnostics as final timestamp/contract evidence. No extra viewport/repeat/grace matrix. Retain invalid attempts and explicitly label retakes.

| Final arm | Required rider result |
|---|---|
| Alpha positives, including b5to6/b7to8-wa0121 | True; visible prefix <=1 and exempt when timing bounds hold |
| D7 positives, including b0to1 a/b | Same |
| Alpha overlay-ride | False; drawn-frame offenders; labels True |
| D7 departure-early-hide | True; 0 exempted visible samples; exempt True when the timing bounds hold |
| Moved decoder, each deck | Aggregate passes: all rider leaves readable, at least one geometry-backed False with exempt False; labels True |

Check contracts and relevant registered expectations, not process exit alone; the gate checker accepts normal 0/1 exits only with matching evidence (`scripts/run_gates.sh:725-727,785-791`). Investigate unrelated leaf changes without changing thresholds.

### Fresh-producer null comparison

```sh
git show 7746df27:scripts/mm_feed_instrument.py > "$PREDRAW_OUT/mm_feed_instrument_7746df27.py"
```

A scratch script imports that module and calls `verdict_records` directly, bypassing the current contract, on **every final fresh producer** with the same entry config/continuous expectation. Compare `score_no_rider_above_canvas` per entry/visit against current scoring. Expect positives, departure-early-hide, and overlay-ride verdicts unchanged; moved-decoder red rows True→False. Keep scripts, hashes, and diffs. Unexpected differences require diagnosis. This replaces stored-D7 replay and synthetic geometry mutation; missing-old-fields refusal is covered by tests. Stored Alpha cannot provide full replay because its frames were trimmed (`.agents/reviews/stage-b/alpha-placement/gate-record-2026-10-16-predraw.md:24-28`).

### Local suites and finish

Use the project skill's full-suite/xdist and dashboard commands (`.agents/skills/obed-edom/SKILL.md:43-50`) and the specified isolated 3.10 floor setup. Each command runs sequentially in its heavy window. Warm Python runs are approximately 1–3 minutes each; allow dependency/cold-cache time. Dashboard budget: 5–15 minutes.

Run pytest with `-rs` and report skip counts for both interpreters. A fresh worktree can skip about 70 extra tests unless the main checkout's git-ignored fixtures are linked; this is the recorded environment baseline, not a predicted count for this revision (`/Users/anyhowclick/.claude/projects/-Users-anyhowclick-Desktop-work-obed-edom/memory/worktree-env-setup.md:19-22`). Inspect the actual skip reasons and link the needed main-checkout fixtures before treating the suites as complete; fixture absence explicitly skips tests (`tests/test_live_continuity_probe.py:3462-3472`; ignored paths: `.gitignore:7-8,16-18`).

```sh
env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv312" uv run pytest tests/ -n auto --dist worksteal -rs
UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv310" uv sync --frozen --all-extras --all-groups --python 3.10
env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv310" uv run --frozen --python 3.10 pytest tests/ -n auto --dist worksteal -rs
cd "$PREDRAW_REPO/dashboard"
npm run test:ui
npm run test:maps
```

Run focused affected tests first as needed. Diagnose failures before editing expectations. Finally verify scope and unchanged product bytes; assemble full raw producers, configuration/hashes, commands/logs, feasibility table, timing table, null diff, and the 320-ms rationale. Copy only this finished bundle to the retained evidence destination above, including a stopped-gate bundle if Step 0 fails.

## Risks and owner decisions

Only measured failure to meet 1 px, or positive completion times beyond 320 ms, can require an owner threshold/product decision. Neither is pre-authorized. Missing measurements cannot establish a pass. The guarantee covers collection points, not unobserved mutations between callbacks; context completion is not compositor presentation. No other design approval is pending.

## r3 changes

r1 findings were folded in r2; N3 completes D3, and N2 corrects the L4 overshoot.

All six r2 findings were verified against code and folded; none refuted.

- **N1:** Removed the recorded-draw/finite-timestamp contract inference; Test 4 now rejects `firstDrawAt < createdAt` and permits null after a thrown draw. The scorer still grants no exemption for null/out-of-order completion. Frame counts increment before the original call (`scripts/mm_feed_instrument.py:264,273`), and producer failure affects every under-artwork carry (`scripts/live_continuity_probe.py:4355-4373`).
- **N2:** Preserved v1/v2 branching and fixture versions; require both new keys in either version and test deletion. This avoids unrelated v2 hand-back requirements (`scripts/live_evidence_contract.py:688-733,901-911,947-952`; v1 fixtures: `tests/test_live_continuity_probe.py:12295,12524`, `tests/test_live_evidence_contract.py:347`).
- **N3:** Added a heavy 3.12 all-extras/all-groups sync plus dashboard `npm ci` before Step 0, kept Python environments in scratch, and added `-rs`/skip-count reporting for both suites. Verified optional test/IWA dependencies and dashboard TypeScript requirements (`pyproject.toml:32-49`; `dashboard/package.json:9-12,29`); fixture skips are explicit (`tests/test_live_continuity_probe.py:3462-3472`).
- **L-a:** Moved the two permanent authored-source probe additions into Step 0 and removed the scratch-wrapper instructions; continuity `srcRect` remains unchanged, and extra fields are ignored by `_fields` (`scripts/live_continuity_probe.py:1565-1575,1930-1940`; `scripts/live_evidence_contract.py:115-120`).
- **L-b:** Qualified departure-early-hide's exemption by timing bounds while retaining True and zero exempted visible samples: the variant hides immediately, but the exemption still checks grace (`scripts/continuity_core_variants.py:103-112`; `scripts/mm_feed_instrument.py:621-626`).
- **r3 low (coordinator fold):** `UV_PROJECT_ENVIRONMENT` set inline on every 3.12 command; shell state does not persist across agent Bash calls.
- **L-c:** Corrected the suite-command citation to `.agents/skills/obed-edom/SKILL.md:43-50` (dashboard commands at 43–46; xdist at 50).
