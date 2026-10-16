# Movie warm-up acceptance record (2026-10-16)

Implementation `41800609` (Codex GPT-5.6 Sol high, plan r3) + review r1 folds `39b32de9` (Opus 5.5 high: APPROVE,
5 LOW folded). Base `claude/stage-b-arch` `c7bd7cbd`. Every run used `39b32de9` (pinned gate worktree for A5).

Evidence: `output/evidence/stage-b-2026-10-13/f4-faststart/acceptance-39b32de9/`.
- Per-mount cold starts: `coldstart.jsonl` / `compare.jsonl` per arm. Raw run JSONs were not kept.
- `movieWarmup` host-log records.
- OBS run summaries, gate logs, `uptime.log` and the batch script.

Machine: one heavy job machine-wide with the linked sessions; load-guarded start (1-min < 4). The macOS update and a
Backblaze upload had settled before the timed runs.

## A1: unit tests (pass)
`uv run pytest tests/test_live_host.py tests/test_live_continuity.py tests/test_live_runtime.py tests/test_live_api.py`:
1012 passed, 0 skipped (the Node lifecycle test ran), before and after the review folds.

## A2: headless real player, Alpha, feed off, 5 + 5 interleaved (pass)
Probe at `39b32de9`, `NO_PREMOVE_CAPTURE=1` wrapper, unwarmed original index; `OBED_LIVE_MOVIE_WARMUP=off|auto`.

| slide-4 Untitled entry | off | auto |
|---|---|---|
| mount → readyState ≥ 2, ms | 212, 215, 207, 200, 216 (median 212) | 33, 17, 17, 17, 17 (median **17**) |
| not-decoded frames | 12–13 | 1–2 |

- Later mounts: 33–52 ms in both arms.
- Per-boundary verdicts identical across all 10 runs; only the known b5to6..b7to8 fails.
- The host log has `movieWarmup` `{state:"ready"}` in every auto session (ready 183–269 ms after load), and one
  `reason:"off"` record per off session.

## A3: feed-on paint verdict (not scorable on this base; substitute evidence recorded)
- Same loop with `--mm-feed on`.
- The b3to4 paint check passes with 0 unpainted frames in **both** arms. The reason is `47bc3698` (WIP, "UNREVIEWED,
  DO NOT MERGE AS IS", in the `claude/stage-b-arch` history), which changed `paint_start` to begin at the first
  decoded row. Its own message says the slide-entry poster exposure "now goes unscored". Off run: scoring window
  21724, paint window 21807 = decode time; mount 21623.
- Substitute evidence, from the same feed-on runs' sample rows:
  - **off:** 183 ms median (11 frames);
  - **auto:** 18 ms (1–2 frames).
- Verdicts are identical across arms.
- Scoring the entry needs F3 `entryColdStart` or a revisit of `47bc3698`. That is the restructure's call
  (refactor-owned file).

## A4: managed OBS 32.2.2, hidden launch, 4 + 4 alternating (pass; owner go 2026-10-16)

| first session (`feed`), id1 entry | off | auto |
|---|---|---|
| ms | 292, 272, 293, 255 (median 282) | 40, 60, 60, 70 (median **60**, max 70) |
| not-decoded frames | 13–15 | 2–4 |

- The second session (`feed-off`, reported separately) was 48.5 / 66.5 ms.
- OBS quit after every run.
- Gate checks: 16 always fail in both arms. The only arm difference is `feed-off … posterHold`, which flakes in
  both arms (3 of 4 off runs today, both arms last night).

## A5: gates, then full suites
Two complete full rounds at `GATE_JOBS=3` from a worktree pinned to `39b32de9`: default-on (1412 s), then
`OBED_LIVE_MOVIE_WARMUP=off`. An earlier default-on round was stopped mid-run at the owner's request and is
discarded.

- **auto:** `failed=25`, **off:** `failed=26`. All 25 auto failures also fail in off. Off-only: `D7 interim-delay` (a
  red control that missed its exposure in that run).
- **The 25 are pre-existing on the base,** all MM-FEED (D7, D7s, Alpha) plus `HOST red D3 --strip bridge@6`:
  - `feedLive None`: counter reads `coveredByLaterDraw`, with `callbackCostP95Ms` ~128 ms from the stock
    pre-move-capture instrument (F1 not yet done);
  - `noRiderAboveCanvas False` at D7 b0to1: the open departure-interim lead, A/B'd by the alpha-placement session;
  - Alpha b5to6..b7to8 unreadable or failing: the hand-back placement fix `838eeedf` is not yet merged.
- **One mismatch-level difference:** `D7 attach-once` b1to2 `handbackContinuity None` / `posterHold False` in auto
  only. A 3 + 3 repeat of that exact gate gives auto all-True and one off run with the same `posterHold` /
  `handbackContinuity False`. It is a flake, not the warm-up.

**Full suites** (in the worktree, after the gates, with the suite-speedup session's reporting-only profiling flags;
profiles in that session's `suite-profile-f4/` notes):

| interpreter | result | time |
|---|---|---|
| 3.13.11 | 11257 passed, 38 skipped, 1 xfailed, **1 failed** | 313 s |
| 3.10.10 floor (`UV_PROJECT_ENVIRONMENT` venv) | 11257 passed, 38 skipped, 1 xfailed, **1 failed** | 393 s |

- The one failure, the same in both, is `tests/test_run_gates.py::test_the_settle_wait_never_sleeps_past_its_deadline`
  ("round took 6.0 s", wall-clock limit 4.5 s).
- It passes alone on both interpreters, even at load ~33.
- This branch changes nothing under `scripts/` or in that test (refactor-owned). It is a wall-clock flake under
  `-n auto` contention, handed to the suite-speedup session.
- The 38 skips are the usual Keynote and live-cache skips.
