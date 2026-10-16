# Alpha Keynote live: one-shot movie warm-up at deck load

**Planning pass · 2026-10-15 · planner HIGH · implementation not started**

Read-only reviewed checkout: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`, HEAD `7a49aa25fa8e3d4d62b21b09e6e13014ebd6a704`. All source references below are relative to that checkout and refer to the lines read at this revision. This plan alone is written in the supplied scratch directory. Follow the owner's plan → critique → implement → review roster; this pass does not launch qualification or change product code.

## 1. Context and intended result

The owner approved a product warm-up on 2026-10-15, explicitly rejecting faststart remuxing (`.agents/handovers/f4-faststart-measure-2026-10-15.md:178–196`; whole handover read). The measured implementation is the single inline script in `output/evidence/stage-b-2026-10-13/f4-faststart/warm-load/index.html:1`: create a detached muted video at parse time, preload one referenced H.264 movie, and remove its source and call `load()` on `loadeddata`.

This moves the once-per-page media-pipeline initialization before the first player movie mounts. The evidence is **214 → 28 ms median** in the headless real player and **280 → 56 ms median** in a fresh managed-OBS first session (14 → approximately 3 not-decoded frames). Other H.264 files warm the same pipeline. The benefit survived three minutes after release; twenty minutes and other codec pipelines remain unmeasured. Warm-up itself took roughly 203–289 ms, asynchronously and off-screen. It does not eliminate the residual first-frame gap or fix the known Alpha later-boundary failures.

Ship a best-effort warm-up once per loaded Program document, including when continuity is off or unsupported. No export or movie bytes change; no player digest, runtime-plan signature, rendering-patch pin, or continuity qualification changes. A warm-up failure, missing source, or reporting failure must never make a session fail or wait for readiness.

## 2. Decisions and code grounding

### 2.1 Serve it in `program.html`, before continuity

Add a separate `movie_warmup_script` argument to `_AssetServer`; inject it in `_program_html()` as:

`overlay → movie warm-up → continuity plan → core → optional GL replay → optional MM feed → fit → existing player document`.

The insertion seam is `live_host.py:615–643`, currently `overlay + self.continuity_script + fit_script`. The host builds this page for **all four output modes** and navigates to it through the same `start()` path (`:1665–1700`). `_AssetServer.start()` returns its loopback `/program.html` URL (`:467–501`); ordinary media serving already supports Range (`:578–613`).

Do not make the warm-up part of `continuity_script`: that string is empty when no runtime plan derives (`:1689–1693`), while `_resolve_codecs()` is deliberately independent of continuity (`:1316–1332`). Do not use `Page.addScriptToEvaluateOnNewDocument`: the existing hook is for instruments and placement (`:1681–1682`, `:1741–1744`, reconnect at `:1880–1882`), and would also need document/origin scoping for calibration and later navigations. Served HTML gives a known media URL base and exactly the Program-document lifetime without new CDP installation/reconnect behavior.

**Ordering is a correctness requirement, not cosmetic.** Continuity replaces `Document.prototype.createElement` and tags newly created videos (`live_continuity_js.py:2563–2584`); it also intercepts `src` clears/removal and can stash detached videos (`:2359–2406`). Start the warm-up before those hooks and capture the original `removeAttribute` and `load` methods at that time. Cleanup later must call those captured methods on the warm element, rather than resolving methods through the now-patched prototypes. The warm element must never be pooled, tagged with a player object ID, supplied to a continuity/feed API, or exposed as a page-global reference. No continuity-core edit or instrument exemption is necessary.

### 2.2 Select the first eligible referenced movie, with an actual served file

Preserve authored slide order. Prepared `slides` follow the source/header order and increment `playerIndex` over non-skipped slides (`html_preview.py:590–619`). `_referenced_movies()` already walks that list, skips skipped/unreadable slides, traverses event movie nodes, and retains insertion order for normalized keys and each key's distinct per-slide files (`live_continuity.py:2702–2732`; traversal at `:1056–1066`).

Do **not** take `codec_report()[0]`: its output is alphabetically sorted, contains counts rather than URLs, and aggregates all copies of an asset (`:2735–2770`). Nor is a normalized key a relative file path: `_normalize_asset_key()` strips the slide path and trim suffix (`:1362–1363`).

Add one small selection helper alongside that census, reusing `_referenced_movies()` without changing its behavior or the report schema. Iterate keys in first-reference order, then each key's paths in encounter order. Select the first existing, in-root file whose **own bytes** identify an eligible family. This permits a later slide-folder copy when the first copy is missing, and avoids treating a mixed-codec aggregate as proof that a particular copy is playable. Mixed/unreadable census warnings and continuity refusal remain unchanged. Within one slide, the existing event traversal order breaks ties. If an earlier referenced logical movie has no eligible surviving copy, continue to the next movie.

The host computes eligible families using `_codec_supported(family, attach=..., headless=..., managed=...)` (`live_host.py:226–236`). Initial warm-up policy intersects that result with **`{"h264"}`**. H.264 is supported in every host mode; there is no output-mode exclusion for H.264. Do not broaden ordinary codec support as part of this change.

Derive the URL from the selected resolved path relative to `export_root.resolve()`, in POSIX form, and use `urllib.parse.quote(relative, safe="/")`. Validate/re-resolve that relative path through the supplied host resolver before emitting it, and require it still names a file. The default resolver rejects traversal, symlinks, non-cache roots and missing files (`html_preview.py:1201–1222`); `_AssetServer` URL-decodes the request before passing it to the same resolver (`live_host.py:475–491`). Do not concatenate the asset key, guess a slide UUID, double-unquote filenames, or emit a filesystem/remote URL. Encode spaces, literal `%`, `#`, `?`, quotes and Unicode correctly. Embed the resulting URL with JSON serialization and HTML-script-safe `<` escaping, matching the existing safe-script intent at `live_host.py:186–207`.

### 2.3 Non-H.264 policy

**Skip until measured.** VP9 playback qualification does not establish that a detached WebM preload warms subsequent movie starts. `_codec_supported` admits VP9 for headful launch and managed OBS, but not headless/external attach; HEVC is headful-only (`live_host.py:226–236`). The handover explicitly leaves WebM warm-up open. This increment also skips HEVC-only and other non-H.264 decks. A mixed deck warms its first eligible H.264 reference even if an earlier reference is VP9.

Run the bounded WebM experiment in §5 before closing acceptance, record its result, and retain the skip default for this implementation. A positive result can support a separately reviewed policy expansion; a headless harness measurement alone must not grant headless VP9 playback support. No synthetic fallback H.264 download for decks with no H.264 reference.

### 2.4 Control and reporting

Use the environment-only switch **`OBED_LIVE_MOVIE_WARMUP=off|auto`**, default `auto`, resolved once at host start. `off` disables it independently of continuity, opacity, GL replay and feed. Trim whitespace and lowercase, like the neighboring controls (`live_host.py:1625–1649`). Empty/unset means `auto`. For an invalid value, disable warm-up and log `invalid-preference`; do not raise. This deliberate difference from GL replay's strict configuration errors honors the requirement that this optimization never fail the session. No new UI, route request field or constructor option is needed.

Session log events named `movieWarmup` record preference, mode (`scheduled`, `off`, `skipped`, then page `loading`/terminal status when observed), reason, normalized asset, relative served URL, codec family, and explicit output mode (`headless`, `headful`, `managed-obs`, `external-attach`). A scheduled event means injected, not decoded. Skip reasons distinguish disabled/invalid preference, no eligible source, and selection failure; diagnostics must not change existing codec warnings.

The script exposes **scalar diagnostics only** in `window.__obedMovieWarmup`: state, page time origin, started-at time, ready-at time and elapsed readiness time (milliseconds from warm-up start), terminal reason, release result. No video, callback, decoder or DOM object appears there. Copy its known scalar fields into a private `__obedMovieWarmup` field of `_LIVE_SNAPSHOT_EXPR`, with its own `try/catch`, alongside the existing private feed entries (`live_host.py:102–107`). Consume this in `observe()` (`:2791–2804`) to log state changes once per page origin/state. Missing or malformed diagnostics are ignored. Log readiness only when reported; never infer it from elapsed wall time. This costs no additional CDP call, polling timer, runtime-player schema change, evidence-contract field, or operator warning. A session that ends before reporting completion may have only `scheduled`/`loading` in its log.

### 2.5 Lifecycle, modes and other features

The standalone IIFE must:

1. Return immediately if its per-document scalar sentinel already exists; otherwise publish `loading` and start exactly one attempt. A full reload/new deck document starts a new attempt; show/hide, slide jumps, continuity resets and CDP reconnect within the same document do not.
2. Capture release methods before continuity installs; create one detached `<video>`, set `muted=true`, `defaultMuted=true`, `preload="auto"`, and register listeners before setting `src` and calling the captured `load()`. Never append it, call `play()`, seek it, attach a source child, or use an off-screen/shadow DOM holder.
3. On `loadeddata` (readyState ≥ 2), record readiness and release immediately. On `error`, synchronous setup failure, a **5-second cleanup timeout**, or `pagehide`, release and record the corresponding terminal reason. The timeout is resource cleanup, not a host readiness deadline. No retry or alternate-file attempt after page execution starts.
4. Use one idempotent finish path: clear the timer, remove the event/pagehide listeners, remove `src` and call the captured `load()` in separately guarded operations, then drop the closure's element reference. Do not call `pause()` unnecessarily: it was never played, and the feed instrument wraps media pause/play (`scripts/mm_feed_instrument.py:69–109`). Cleanup and telemetry exceptions must not escape; report a cleanup failure if possible rather than claiming successful release. Timers can be throttled, so `pagehide` is the additional lifecycle cleanup, not a hard wall-clock guarantee in a suspended renderer.

| Output/surface | Treatment |
|---|---|
| Headless launch | Common served script, H.264 admitted. A2 measures real-player benefit. |
| Headful launch / Screen | Same path, H.264 admitted; smoke-check silent decode, cleanup and unchanged display behavior. |
| Managed OBS / CEF | Same served alpha page; identified by attached endpoint plus `bridge="obs-managed"` (`live_host.py:1227–1233`). A4 requires a fresh engine and owner go per session. |
| External attach | Same `goto(program.html)` path and H.264 policy; no placement/feed qualification is granted. Smoke-check a separately controlled attach browser. |
| Live presenter dashboard monitor | It renders `<Still slide={current}/>` (`dashboard/src/live/LivePresenter.tsx:415–425`), not a second live player. The actual output is `LiveOutputHost` via `web/live.py:291–305`, so it receives the warm-up once. |
| Build Preview / raw export | Excluded: `/api/html-preview/.../player` serves its own index/diagnostics and `preview_player` (`web/app.py:987–1017`), not `LiveOutputHost._program_html`. No preview-route change. |

Poster holds, `mm_feed` and `gl_replay` retain their plans, ordering relative to each other, eligibility, clocks, texture upload behavior and release semantics. The warm element performs no canvas/WebGL operation. Since it is detached throughout and created before core hooks, it is absent from `document.querySelectorAll('video')`, the player DOM, continuity's DOM scans (`live_continuity_js.py:328`, `:2615`), probe sample rows (`scripts/live_continuity_probe.py:442`, `:477`, `:582`), and paint scans (`scripts/paint_instrument.py:177`, `:230`). Pre-navigation instrument hooks still install normally; no sampler filtering or new instrument note is introduced. Verify that the first player mount remains the sampler's first mount, and that no warm decoder enters carry/feed state.

## 3. Exact implementation inventory

### `src/obed_edom/live_continuity.py`

Add beside `_referenced_movies`:

```python
def first_referenced_movie(
    export_root: Path,
    slides: list[dict[str, Any]],
    *,
    families: set[str],
    resolver: Callable[[Path, str], Path] = safe_export_file,
    probe: Callable[[Path], str | None] = movie_codec,
) -> tuple[str, Path, str] | None:
    ...
```

Return `(normalized_asset, resolved_file, family)` using the order/existence/per-file policy in §2.2. Check root containment and resolver round-trip before accepting a file; catch per-file failures and continue. Reuse `codec_family`, already used by `codec_report`, and stop probing after the first eligible file. The host catches any whole-enumeration failure. Do not rename/refactor `_referenced_movies`, alter `codec_report`'s signature/schema/sorting, or derive a continuity plan just for warm-up. The small extra metadata read is preferable to adding path/order fields to every public census entry.

### `src/obed_edom/live_host.py`

- Add `MOVIE_WARMUP_ENV = "OBED_LIVE_MOVIE_WARMUP"` near `CONTINUITY_ENV`, and `_movie_warmup_script(url: str) -> str` near the existing script builders. Keep the bounded standalone JS here, consistent with small overlay/fit injections; no new runtime module/framework or SHA pin for HTML injection.
- Extend `_AssetServer.__init__(..., *, alpha: bool = False, continuity_script: str = "", movie_warmup_script: str = "") -> None`; store the new argument. The empty default preserves direct server callers. Change only the injection concatenation in `_program_html()` as §2.1 specifies.
- Initialize minimal private selection/log-dedup state in `LiveOutputHost.__init__`; keep its public signature unchanged.
- Add `_resolve_movie_warmup(self) -> str`: resolve preference, derive eligible families through `_codec_supported`, call `first_referenced_movie`, form the escaped served URL and script, and emit selection/skip diagnostics. Catch optional-work failures and return `""`; logging is best effort. Do not put discovery or codec probing inside the HTTP request handler.
- In `start()`, immediately after the codec census (`:1665–1666`) resolve the warm-up once, independently of `_resolve_continuity_static()`. Pass the resulting script as the new named server argument at `:1694–1697`. Keep `patch_player` and `goto` unchanged and never wait for warm-up readiness.
- Extend `_LIVE_SNAPSHOT_EXPR` with guarded scalar diagnostic copying. Add `_log_movie_warmup(self, value: Any) -> None` and call it from `observe()` after validating the normal snapshot. Validate finite, non-boolean numeric times and allowed state strings before logging; malformed optional data must not affect a `PlayerObservation`. Use a page-origin/state dedup key; no retention of page objects and no new public `output` fields.

### `tests/test_live_host.py` and `tests/test_live_continuity.py`

Use the few parameterized tests described in §4. Update `FakeServer.__init__` (`test_live_host.py:155–159`) to accept/store `movie_warmup_script`. Any helper reconstructing the real server from a fake must forward it, notably `:1936` and `_program_document` around `:2641`. `test_live_api.py:351–354` already accepts arbitrary server keywords, so it needs no automatic signature edit; verify with its existing tests.

The historical inactive-continuity HTML hash test (`test_live_host.py:1920–1937`) asserts pre-I2 bytes for a deck that contains H.264. Its premise changes under default-on warm-up. Rename/scope it explicitly to **warm-up disabled**, set the new environment switch to `off`, forward the new server argument, and keep the old expected hashes. Add positive inactive-continuity coverage to the injection matrix. Do not regenerate historical hashes to hide a regression or let the reconstruction silently omit the new script.

### `README.md`

Add a short paragraph in the live movie-continuity area (`README.md:98`, existing controls around `:261–284`): one attempt at deck load, H.264-only initial policy, independent of continuity, default `auto`, `OBED_LIVE_MOVIE_WARMUP=off`, errors skip optimization, no change to Build Preview. Mention the diagnostic event and that the residual gap is not zero. Avoid promising an exact latency for every deck or engine.

### Deliberately unchanged code

`live_runtime.py` remains untouched: `patch_player()` recognizes SHA-pinned player inputs and verifies its in-memory outputs (`:413–451`), and `patch_rendering()` is the separate preview path. Never modify `main.js` on disk. No continuity/GL/feed JS changes, codec-parser changes, frontend changes, manifest changes, media conversion or asset writes. No edits to repo rule/skill files.

## 4. Tests: maximum useful coverage with few additions

Use **three parameterized test groups**, plus extensions to existing tests/fakes; no new large fixture or instrument framework.

1. **Selection (`test_live_continuity.py`)**: construct tiny slide JSONs and reuse existing minimal movie-byte helpers/census fixture patterns (`:1956–2076`). Cover slide order opposed to alphabetical key order; skipped/unreadable slides; multiple movie nodes; same-key duplicate files; missing first copy with surviving second copy; mixed H.264/unsupported copies selected by actual bytes; no eligible file, unsupported-only, VP9-only; and resolver failure/out-of-root candidates. Verify first-reference priority and existing-file choice. Existing `codec_report` assertions must remain exactly valid.
2. **Host-to-served-HTML/logging (`test_live_host.py`)**: extend injection-order coverage at `:1745–1763` and reuse `host_with_continuity` (`:1414–1444`). A compact case table covers default-on H.264 across headless/headful/managed/external attach, continuity off/unsupported, environment off/invalid, no movie/unsupported-only, and selection exception. Assert script presence/absence, encoded actual URL, one tag before core and player, mode/asset logs, and successful host start on warm-up failure. Include a hostile filename/`</script>` builder input to prove safe embedding. Feed/GL script bytes and relative order remain unchanged. Extend fake-snapshot cases to cover loading→ready once, timeout/error, malformed/missing diagnostics, and a fresh-document origin; no extra CDP evaluation should be required.
3. **Executed JS lifecycle (`test_live_host.py`)**: follow the existing Node subprocess testing pattern at `:3613–3636`, using one small media/event/timer stub and table-driven terminal paths. Test muted-before-src, no `play`/seek/DOM insertion, one attempt even if script evaluated twice, ready/error/timeout/pagehide/setup-failure cleanup, timer/listener removal, late duplicate event no-op, scalar-only global state, and source-free `load()` on release. After script start, replace prototype release methods with throwing/pooling spies, then deliver `loadeddata`: cleanup must call the captured originals. Assert no unhandled exception for cleanup failure. Run with Node available; a skipped JS test is not sufficient completion evidence. Real-browser A2/A4 and the mode smoke checks remain necessary; stubs do not prove decoder release or silence in CEF.

Existing API, census, player pin, continuity plan SHA, GL/feed and full-suite tests cover integration beyond these groups. New tests must not assert every line of JS text. Keep implementation comments minimal; one short comment explaining the captured-method requirement is warranted. Tests may explain behavioral contracts.

## 5. Acceptance and reproducible commands

Commands below are for the later implementation checkout, **not instructions to mutate or run tests in this read-only planning checkout**. Choose `WT` to point to that checkout. Keep measurements serial, on an idle machine, with fresh profiles and separate outputs. Record commit, environment, Chrome/CEF/OBS builds, argv, fixture identity, plan SHA, raw samples, logs, exits and per-verdict comparisons. Do not discard failed/inconclusive runs. Historical raw run JSONs were not retained, so reproduce a contemporaneous disabled control, rather than comparing only with the published median.

### Common setup and wrapper boundary

```bash
WT=/absolute/path/to/implementation-checkout
SRC=/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f
EVID="$SRC/output/evidence/stage-b-2026-10-13/f4-faststart"
RUN=$(mktemp -d /private/tmp/obed-movie-warmup.XXXXXX)
FX="$HOME/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/Alpha"
PY="$WT/.venv/bin/python"
mkdir -p "$RUN/tools" "$RUN/headless" "$RUN/paint" "$RUN/obs"
cp "$EVID/tools/run_probe_ab.py" "$EVID/tools/run_obs_ab.py" \
   "$EVID/tools/coldstart.py" "$EVID/tools/obs_coldstart.py" "$RUN/tools/"
```

Check that `FX/html-player` and `FX/html-unmodified/index.html` exist and are the measured Alpha fixture. Use the same **unwarmed** original index in both arms. The product supplies the injection; do not use `warm-load/index.html` on top of it. The copied wrappers take `PROBE_WT` (and the probe wrapper optionally `PROBE_SRC_WT`); their import assertions prevent testing an unintended checkout. `NO_PREMOVE_CAPTURE=1` changes the exact `mm_feed_instrument.INSTRUMENT_JS` guard from `if(!size||!(current===e.atScene-1||moveLive))return;` to `if(!size||!moveLive)return;`, with an exact one-match assertion (`scripts/mm_feed_instrument.py:109`). Preserve that assertion. If the parallel refactor changes the seam, adapt only the **outside-repo wrapper** to the equivalent import-time seam and document the change. Do not weaken the scorer or patch in-product JS to make a measurement pass.

### A1 — unit behavior

```bash
cd "$WT"
env -u PYTHONDONTWRITEBYTECODE uv run --python 3.13 --extra test pytest \
  tests/test_live_host.py tests/test_live_continuity.py \
  tests/test_live_runtime.py tests/test_live_api.py -q
```

Required: served HTML contains exactly one warm-up for eligible H.264; absent when disabled or without an eligible movie; ordered selection and fallback copy are right; all four modes inject; continuity off/unsupported still injects; safe URL round-trip; failure never blocks; cleanup remains independent of continuity hooks; historical disabled HTML/player pins unchanged. Fixture skips must be explained/restored, not treated as coverage.

### A2 — headless real player, feed off, five matched runs per arm

After common setup, run in `bash` or `zsh` (without fail-fast shell behavior; expected existing red verdicts can produce exit 1):

```bash
for i in 1 2 3 4 5; do
  order="off auto"
  if (( i % 2 == 0 )); then order="auto off"; fi
  for mode in $(printf '%s' "$order"); do
    env PROBE_WT="$WT" PROBE_SRC_WT="$WT" NO_PREMOVE_CAPTURE=1 \
      OBED_LIVE_MOVIE_WARMUP="$mode" \
      "$PY" "$RUN/tools/run_probe_ab.py" \
      --fixture "$FX/html-player" --original-index "$FX/html-unmodified/index.html" \
      --skip-arms B,C,V,Voff,attach --mm-feed off \
      --artifact "$RUN/headless/$mode-$i.json" \
      > "$RUN/headless/$mode-$i.log" 2>&1
    printf '%s\n' "$?" > "$RUN/headless/$mode-$i.exit"
  done
done
"$PY" "$RUN/tools/coldstart.py" "$RUN"/headless/*.json > "$RUN/headless/coldstart.jsonl"
```

Score the actual slide-4 first movie mount (historically sampler id1 / scene 4), not the hidden warm-up. Require **≤ approximately 50 ms median over the five auto runs**, against a disabled baseline reproducing roughly 214 ms. Retain all five values and maxima and compare later mounts. All per-boundary verdicts must be unchanged between arms; known b5to6…b7to8 failures remain visible. Missing samples/readiness or a non-reproducing control is inconclusive, not a zero-time success. Verify warm-up readiness/release precedes entry, no extra sampled video, and unchanged plan SHA. The no-pre-move wrapper is required even with feed off.

### A3 — feed-on paint verdict, observer effect removed

Repeat the A2 loop into `$RUN/paint`, changing only `--mm-feed off` to **`--mm-feed on`** and its artifact/log paths. Retain `NO_PREMOVE_CAPTURE=1`. The wrapper keeps in-move capture and the paint oracle enabled; do not replace it with a feed-off result.

Required: b3to4's **paint classification `not-decoded` frames drops from approximately 12 to ≤3** in each valid warm run; report median/max as well. Use raw sampler rows to corroborate, but distinguish `coldstart.py`'s readyState row count from the paint oracle's classification. Read all boundary/check verdicts, preserving known later failures and positive/null/red controls. If removing the observer effect makes a dependent evidence field unavailable, retain INCONCLUSIVE and investigate the outside-repo wrapper; do not waive producer validation or change protected tests. The expected entry metric improvement does not authorize unrelated verdict changes.

### A4 — managed OBS, fresh engine first-session comparison

**Owner go is required per OBS session; planning is not permission to launch OBS.** Follow the pinned 32.2.2 managed lifetime/isolation/clean-quit rules (`.agents/skills/obed-edom/SKILL.md:831–889`), never the user's OBS profile, never SIGKILL. The original handover's prior go applies to its historical sessions only.

After owner go for a run, use this exact single-run template (set `mode=off|auto`, `i=1..4`):

```bash
env PROBE_WT="$WT" OBED_LIVE_MOVIE_WARMUP="$mode" \
  "$PY" "$RUN/tools/run_obs_ab.py" --arm feed --launch hidden \
  --fixture "$FX" --out "$RUN/obs/$mode-$i" --home "$RUN/obs-home" \
  > "$RUN/obs/$mode-$i.log" 2>&1
printf '%s\n' "$?" > "$RUN/obs/$mode-$i.exit"
```

Use four disabled and four warm runs, alternating order; verify OBS exits cleanly after every run, so each `feed` session starts in a fresh CEF process. The harness also runs `feed-off` in the same engine; keep that evidence but **never pool it with the first-session timings**. The copied OBS wrapper applies the same pre-move capture guard automatically. Aggregate completed run directories with:

```bash
"$PY" "$RUN/tools/obs_coldstart.py" \
  "$RUN/obs/off-1" "$RUN/obs/auto-1" "$RUN/obs/off-2" "$RUN/obs/auto-2" \
  "$RUN/obs/off-3" "$RUN/obs/auto-3" "$RUN/obs/off-4" "$RUN/obs/auto-4" \
  > "$RUN/obs/coldstart.jsonl"
```

Require first-session entry **≤ approximately 80 ms on all four warm runs**, reporting median/max, versus approximately 280 ms disabled. Gate verdicts must remain unchanged apart from the specified entry metric improvement; the handover's 16/17 known-failure counts are context, not an equality oracle. Compare named checks, retain artifacts, and diagnose noise rather than editing thresholds. Capture mode/readiness/release diagnostics and verify no warm-up visual/audio output. A withheld owner go leaves A4 outstanding, not passed.

### A5 — Alpha/D7/D7s gates and full local suites

Run the unedited full gate runner; Stage B registrations include Alpha_DSK, D7 and D7s (`scripts/run_gates.sh:100–129`), source staging/plan signatures (`:336–391`) and named verdict comparisons (`:725–808`). It requires a fresh output directory. Use matched off/default-on runs to identify any new verdict changes:

```bash
env OBED_LIVE_MOVIE_WARMUP=off GATE_JOBS=1 \
  QUAL_B_SOURCE="$HOME/Desktop/Convert wall to 16x9 CGs/Continuity" \
  zsh "$WT/scripts/run_gates.sh" "$WT" "$RUN/gates-off" --tier full
env OBED_LIVE_MOVIE_WARMUP=auto GATE_JOBS=1 \
  QUAL_B_SOURCE="$HOME/Desktop/Convert wall to 16x9 CGs/Continuity" \
  zsh "$WT/scripts/run_gates.sh" "$WT" "$RUN/gates-auto" --tier full
```

These stock-instrument gates complement, and do not replace, A2/A3's observer-effect-controlled measurements. Do not add `--allow-record` or launch managed-OBS qualification implicitly. Compare the Alpha/D7/D7s registered expectations and named statuses; **no new verdict changes**. Existing red arms must stay red for the same reasons. If warm-up moves a hard-coded expectation, report and resolve with the gate owner; protected gate code/tests are not editable in this task. Do not declare a new failure harmless solely because it was an expected-red deck.

```bash
cd "$WT"
env -u PYTHONDONTWRITEBYTECODE uv run --python 3.13 --extra test \
  pytest tests/ -n auto --dist worksteal
env -u PYTHONDONTWRITEBYTECODE uv run --python 3.10 --extra test \
  pytest tests/ -n auto --dist worksteal
cd "$WT/dashboard"
npm run test:maps
npm run test:ui
```

Both Python full suites must pass locally (no CI; repo skill `:49–59`), with expected fixtures available and interpreter versions recorded. Avoid concurrently recreating `.venv` for different Python versions. Run dashboard test scripts as required by the repo skill; no frontend build is needed without a frontend edit. Investigate root causes before changing tests.

### Additional bounded qualification: non-H.264 and mode/lifecycle smoke checks

Copy the existing `gap/run_gap.py` and `gap/harness.html` into `$RUN/gap-tools` and adapt **only those outside-repo copies**. Existing CLI:

```bash
"$PY" "$RUN/gap-tools/run_gap.py" "$WEBM_FIXTURE_ROOT" \
  "$RUN/gap-tools/harness.html" "$RUN/webm-gap.jsonl" \
  '[["c1","",20],["w1","u",20],["w2","u",20],["c2","",20],["c3","",20],["w3","u",20]]'
```

Before that command, select an existing referenced, verified VP9-alpha WebM from a prepared deck and set `WEBM_FIXTURE_ROOT`; replace the harness's visible `U` and runner's `UNTITLED` with that real relative URL, and fix its suffix-only MIME assumption for WebM (including WebM retained under `.mov`). Add bounded error/timeout reporting so a decode failure cannot become a missing result masquerading as success. No product-policy change or instrument-repo change is needed. First measure **WebM→same WebM** control/warm at 20 seconds, fresh profiles, three per arm; if effective, repeat at 180 seconds and then confirm a different referenced WebM target to distinguish pipeline from file caching. The existing runner hardcodes headless Chrome: an outside-repo adaptation must repeat in headful Chrome, and managed CEF requires its own owner-authorized session. Record engine, successful decoded target frame, warm release, cold time and not-decoded frames. A headless finding is exploratory because host VP9 headless support is currently unqualified. Mixed H.264→VP9 cross-codec claims remain unproven unless explicitly measured. Default remains skip for non-H.264 in this increment.

Also run one headful-launch and one controlled external-attach H.264 smoke session through the real `LiveOutputHost` using an outside-repo driver or existing host probe seam, checking served injection, unchanged visible output, mute, ready/release log, and zero warm-element entries in DOM samplers/carry pools. Add ready/error/timeout and early navigation smoke observations to the headless session, plus show/hide and reconnect without a second attempt. A full document reload must make exactly one new attempt. Do not infer CEF success from Chrome; A4 supplies CEF evidence.

## 6. Risks and completion criteria

- **Prototype hooks can retain the decoder.** Required mitigation is pre-core creation plus captured release methods; executed lifecycle tests and real-player sample/carry checks prove isolation.
- **Additional early fetch/decode may contend with page load or an immediately playing first slide.** There is no readiness barrier, forced delay or first-frame guarantee; test a deck with a first-slide movie and compare page settle/player behavior. The measured Alpha entry is approximately 21 seconds after warm-up.
- **No guarantee after an arbitrarily long idle.** Three minutes is measured; twenty minutes is not. No periodic warm-up/decoder retention is introduced to compensate.
- **Codec census order and asset aliases are misleading.** Reuse reference traversal, verify individual actual bytes and existing paths, and preserve all original census/continuity diagnostics.
- **Browser failure or suspension.** Best-effort setup/cleanup and missing telemetry must leave normal playback usable. Timeout is not a decoder-release timing SLA under suspended event loops.
- **Measurements can be polluted by instruments and process reuse.** Keep observer-effect wrappers outside the repo, separate first/second CEF sessions, run controls and warm arms serially, and retain raw results rather than only medians.
- **Parallel refactor ownership.** Rebase/re-read changed seams before implementing. Adapt external wrappers if needed; coordinate protected-gate expectation conflicts instead of editing their files.

Completion means implementation review plus A1–A5, recorded WebM experiment/default decision, and headful/external lifecycle smoke evidence. The plan is not a claim those checks already passed. Known later Alpha failures must remain explicitly reported, without lowering a gate to make this optimization appear green.

## 7. Not in scope

- Faststart remux, movie re-encode, `moov` relocation, media/manifest/hash changes, `main.js` writes or new player-patch anchors/pins.
- Per-slide/per-file warm-up, persistent hidden decoders, periodic refresh, awaiting warm-up before show, or feeding the warm decoder to the player.
- New VP9/HEVC playback or continuity admission, alpha/cadence/placement qualification, poster-hold redesign, MM feed/GL replay changes, or fixing Alpha b5to6…b7to8.
- Dashboard preview/Build Preview warm-up, new UI controls, public API/evidence schema changes, new warning gates or telemetry services.
- Any edit to `scripts/live_continuity_probe.py`, `scripts/mm_feed_instrument.py`, `scripts/live_evidence_contract.py`, `scripts/paint_instrument.py`, `scripts/managed_obs_qualify.py`, `scripts/run_gates.sh`, `scripts/binary_counter_movie.py`, `scripts/obs_cadence_decode.py`, **or any of their tests**. Acceptance may run them unedited and use import-time wrappers exclusively outside the repository.
- This planning pass does not implement, run suites, launch Chrome/OBS, alter the read-only checkout, commit, or publish anything.
