# Chrome-major re-qualification plan (rev 2)

Status: Astra (GPT-6 high) plan r0 → Opus 5.5 high critique r1 (13 findings, folded) → Astra r1 → Opus critique r2 (no blocker/major; 3 folded below). Awaiting owner review.

## Owner decisions

- **OWNER CALL — planned default: 28 arms**, comprising 14 core arms, seven DPR-1 cells and their twins. Budget approximately **8 minutes on an idle machine**, longer with load waits.
- Alternative: retain all **62 arms**, approximately **35 minutes** based on the measured 155 run. The additional 32 high-DPR arms and two production raw/preview arms supply no required qualification reading.
- Document the reduced re-qualification scope in §13; high-DPR and production raw/preview coverage remains in full DX-1. Do not add a matrix-selection CLI option.

## Resolved disagreement
- `m-raw` uses `RawHost`, which saves no product (`dissolve_probe.py:4620`; `run_arm` copies only `mmOpacity, continuity, page, indexSha256, placement`, :4744).
- Do not change `RawHost`. `m-raw` is excluded from the product check: it launches from the same `d.CHROME` via `start_chrome`, and the plist version must be unchanged before and after capture. Probe edits are limited to `FIXTURES` and `chrome_path=CHROME`.

## Files and scope

- Add `scripts/chrome_requal.py`: CLI, constants, pacing/resume, scoring, qualification and printed result; aim for roughly 100 lines without compressing clarity.
- Update `scripts/dissolve_probe.py`: import `main_checkout`; derive `FIXTURES` from it; pass `chrome_path=CHROME` to `LiveOutputHost`.
- Add `tests/test_chrome_requal.py`: one parametrized pure qualification test.
- Update existing grant-matrix rows and version-specific wording in `tests/test_live_host.py`.
- Update `.agents/plans/keynote_live_dissolve_crossfade.plan.md` §13 and `.agents/skills/obed-edom/SKILL.md`.
- Add `.agents/reviews/chrome-requal-script/gates-r1.md`.
- Keep production admission code and `QUALIFIED_SNAP_MAJORS` unchanged. Reuse existing helpers and dependencies; minimal docstrings, no unnecessary inline comments.

## CLI, inputs and storage

```text
chrome_requal.py --chrome BINARY --out DIRECTORY [--decision Q0B_JSON]
```

- Resolve `out.expanduser().resolve()` and refuse any case-insensitive `output` path component before creating files. No descendant scanning or manifest machinery.
- Write captures to `<out>/runs`, generated assets to `<out>/scratch`, host logs to `<out>/host`, and the unmodified score to `<out>/verdict.json`.
- Set `OBED_EDOM_OUTPUT_ROOT=<out>/host` in-process before host construction, replacing any inherited value. Keep logs, caches and generated evidence outside every `output/`.
- Change the probe to `FIXTURES = main_checkout() / "output" / "fixtures"`; existing `DECKS` and `DSK_COUNTER_MOVIE` then derive correctly. Any worktree uses the main checkout’s fixtures without symlinks or `--fixtures`.
- Existing fixtures and decision files under `output/` are read-only inputs. Report missing-input failures clearly; add no asset-prevalidation framework.
- Default `--decision` to `main_checkout()/output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json`.
- Pin `DECISION_SHA256 = "26c4c3e6790218233a8d6b3920920ead5d2ff3e4741d7082bb7faf487cf8c13c"`; refuse missing, malformed or mismatching input. An explicit path must contain the same bytes.
- This record contains `L: "analytic"`, `counterEncoding: "h264-bt709"` and no `lPath`. Do not describe its `L` field as identity.

## Browser selection and temporary admission

- Validate the selected executable; read `CFBundleShortVersionString` from `chrome.parents[1]/Info.plist` before capture and again afterward, following `detach_experiment.py`.
- Set `d.CHROME` to that binary. Existing `start_chrome`, `RawHost` and `run_chrome_placement_probe` use it; the explicit host argument closes the remaining Stable fallback.
- Beta path: `/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta`. Validate actual recorded products against `Chrome/<version>` or `HeadlessChrome/<version>`; do not expect a `Beta/` prefix.
- Around the arm loop only, use `mock.patch.object(live_host, "QUALIFIED_SNAP_MAJORS", tuple(sorted({*original, major})))`.
- **No admission environment variable and no production override interface.** The patch affects this script’s process and restores automatically on exceptions; importing the script has no side effects.
- This admission matters for the three launch/channel arms. Attached arms retain the existing token-driven harness grant and production attach refusal.
- Require a product for every selected non-raw arm (27), twins included. Missing products, mixed versions or a changed final plist version make qualification INCONCLUSIVE.

## Arm selection, pacing and resume

```text
CORE_ARMS =
grant-chrome, grant-attach, channel-predefined, life-grant-reload,
opaque-off, off, noblend, on, on2, m-paused, m-off, m-on, m-hold, m-raw

SNAP_CELLS =
m-snap, m-snap-clipx, m-snap-clipy,
m-snap-lbfrac, m-snap-lbfrac-clipx, m-snap-lbfrac-clipy, m-snap-shift
```

- Build `ARMS` from the 14 core arms, seven cells and each cell’s existing `d.ARMS[cell].twin`: **28 captures**. The full non-CEF snap matrix has 46 arms, making the alternative recipe 62.
- Reuse the paced runner’s five-second polling, waiting up to 300 seconds for zero headless Chromes and load below 3.5; immediately before launching, require zero headless Chromes and load below `d.MAX_LOAD` (4.0).
- Run serially, one Chrome per arm. The zero-before-launch guard is stricter than the three-browser ceiling and matches scorer requirements; never terminate another session’s browser.
- Reuse `run_arm`, `save_run`, `load_runs`, and `score_runs`. Guard refusal exits 2 and preserves completed captures.
- Use one output directory per full candidate version. Skip an arm when `runs/<arm>/record.json` exists: `save_run` writes images first and this record last.
- Remove a record-less partial arm directory before recapturing. Existing malformed saved records produce INCONCLUSIVE rather than silently triggering a retry.
- No fingerprints or resume manifest. Re-score saved captures and verify all products on every invocation.

## Baseline, functions and verdict

```python
def chrome_version(chrome: Path) -> str: ...
def qualify(verdict: dict, products: dict[str, str | None],
            version: str) -> tuple[str, list[str]]: ...
def main(argv: list[str] | None = None) -> int: ...
```

- Use script constants `GATES`, `CORE_ARMS`, `SNAP_CELLS: dict[str, tuple[str, ...]]`, `ARMS`, and `DECISION_SHA256`; add only a small pacing helper if useful.
- The constants are the committed baseline summary. Retain `.agents/reviews/chrome155-requal/dx1-verdict.json` as the measured 155 positive control for the 154/155 qualification bar; create no duplicate baseline JSON.
- `products` maps every selected non-raw arm (27) to its recorded product; a missing key detects an absent capture, twins included. `m-raw`'s presence is checked through `verdict['detail']`.
- Save and report the original DX-1 verdict. Its overall INCONCLUSIVE is expected and does not determine qualification.

**PASS requires all of the following:**

- Complete, matching browser identity and usable evidence for all 28 captures.
- Gates `handoff`, `frozen_frame`, `frozen_region`, `cost`, `grant`, and `cvc` PASS.
- Every core arm has outcome MATCH and empty arm-level `problems`; expected negative-control FAIL readings remain valid.
- Every snap cell has reference and mask PASS, empty arm-level problems, and geometry PASS except `m-snap-shift`, which has no geometry check.
- Each snap cell’s `holder_pixels` is INCONCLUSIVE with exactly `["no L_path for the arm's compositing path"]`. Do not generalize this exemption.

**FAIL:** a trustworthy required PASS reading becomes FAIL, or a core arm becomes MISMATCH. Preserve a valid failure alongside unrelated inconclusive evidence; do not classify expected negative-control FAIL readings as regressions.

**INCONCLUSIVE:** missing/malformed evidence, identity mismatch, load/headless or capture problems, unresolved admission, unexpected limitation changes, or any other unmet requirement without a trustworthy failure. Existing scorer problems already invalidate affected captures.

- Exit codes: PASS `0`, FAIL `1`, INCONCLUSIVE/input refusal `2`.
- Only PASS prints the exact sorted, deduplicated `QUALIFIED_SNAP_MAJORS = (...)` proposal; print “already qualified” when applicable. Never modify the constant.
- Print non-conforming arms and reasons. For an eligible INCONCLUSIVE capture, print shell-quoted commands to delete only its saved arm directory and rerun the same command.
- Never automatically retry FAIL/MISMATCH. After two consecutive INCONCLUSIVE attempts on an idle machine, stop, diagnose and escalate; do not add the major. No persistent retry subsystem.

## Tests and documentation

- One parametrized `qualify` test uses the committed 155 verdict plus matching product inputs: PASS; gate/cell regressions; core MISMATCH; expected negative controls; missing arm/twin/non-raw product; `products` without `m-raw` still PASS; version mismatch; capture problems; exact holder exemption; unexpected holder problems; shift without geometry; FAIL precedence.
- Derive the grant-matrix newest-qualified row from `max(QUALIFIED_SNAP_MAJORS)` and the refused row from that value plus one; retain literal 153/154 cases.
- Reword the nearby comment, test docstring and SKILL paragraph around “a `QUALIFIED_SNAP_MAJORS` major.” No environment-variable test or harness-boundary fake suite.
- Document the command, 28-arm scope, override isolation, resume/retry procedure, exit meanings and manual constant update. Preserve high-DPR, tone, headed-Chrome and CEF limitations.
- Run focused tests, then repo-required full Python and dashboard `test:maps`/`test:ui` suites. Investigate failures before changing expectations; keep all generated test artifacts outside `output/`.

## Acceptance and delivery

On AC power with Low Power Mode off, from the implementation worktree:

```bash
/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python scripts/chrome_requal.py \
  --chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --out "$HOME/.cache/obed-edom/chrome-requal-155.0.8059.79-r1"
```

- Require one real **155.0.8059.79 PASS**, printing `QUALIFIED_SNAP_MAJORS = (154, 155)` and “already qualified”; record actual wall time.
- Invoke identically again and verify all captures are skipped and scoring still PASSes.
- Commit the script’s printed result and score log in the gate record, with command, version, evidence location and suite results. Keep captures outside the repo; do not commit the hundreds of megabytes of images.
- Deliver a PR implemented by Codex GPT-5.6 Sol high and reviewed by Opus 5.5 high. Review binary routing, temporary admission, verdict scope and acceptance evidence.
- Subsequent release PRs need the constant change plus a short gate record containing script output. Main risks remain silent browser updates, load-sensitive captures and overly broad exemptions.
