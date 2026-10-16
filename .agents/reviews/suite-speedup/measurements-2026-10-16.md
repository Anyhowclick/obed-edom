# Suite speed-up: Step 1 measurements (suite-speedup session, 2026-10-16)

Raw data: scratchpad `prof/` (junit, -v logs, --durations=0, /usr/bin/time -l), `cprof/*.prof`, `gates/*.txt`
(/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-distracted-cartwright-b450e1/44760fdd-4542-49d1-8447-86644444e3ee/scratchpad).
Peer data: `suite-profile-f4/` here, from the F4 branch at 39b32de9, measured at load 26–48 (Backblaze).

## Python full suite: clean window, 10 workers, load 3.3 at start
| run | wall | user CPU | sys CPU | tests | summed test time |
|---|---|---|---|---|---|
| origin/main 163ec812, 3.13 | 262 s | 1486 s | 324 s | 11044 passed / 38 skipped | 2427 s |
| origin/main, 3.10 floor | 314 s | 1714 s | 436 s | same | 2758 s |
| stage-b-arch 1a56be4c, 3.13 | 350 s | 1839 s | 453 s | 11245 passed / 38 skipped | 2910 s |
| F4 39b32de9, 3.13 / 3.10, loaded | 313 / 395 s | | | 11257 passed + 1 flake | 2877 s |

- The 1-minute load reached **~106** during our own run, which started at 3.3. The suite overloads the machine by itself: 10
  xdist workers, plus `test_run_gates` rounds that each spawn about 170 processes, plus the bracket sweep's own 10-process
  pool.
- xdist worksteal is balanced: per-worker busy time is within ~5% of the mean (243 s mean vs 262 s wall on main 3.13).
  **Wall ≈ summed test time / 10 + ~15 s.** Every second cut from the summed time is ~0.1 s of wall. Rebalancing
  the distribution gains nothing; we have to cut work.
- Setup + teardown is only ~45 s summed. The cost is in test calls.

### Summed time by file (main 3.13 / 3.10 / stage-b 3.13)
| file | main313 | main310 | stageb313 | n |
|---|---|---|---|---|
| test_run_gates | 1057 s (43.5%) | 1084 s | 1621 s (55.7%) | 120/121 |
| test_dissolve_probe | 373 s | 416 s | 334 s | 322 |
| test_p2_adversarial | 269 s | 377 s | 232 s | 750 |
| test_managed_obs_qualify | 161 s | 195 s | 151 s | 202/209 |
| test_dsk_pill | 54 s | 69 s | 54 s | 68 |
| test_dsk_assemble | 48 s | 48 s | 41 s | 526 |
| test_live_continuity_probe | 45 s | 48 s | 46 s | 1802/1878 |
| test_mm_handback_probe | 38 s | 67 s | 36 s | 74 |
| everything else | ~380 s | | | ~7.2k |

## Root causes found
1. **test_run_gates: ~one full stub round per test.**
   - A full-tier stub round launches 85 queued runs; each launch is python → zsh → python stub. It then runs ~85
     per-arm checks, each a fresh `$PY -` heredoc.
   - Alone at low load a round takes 6–8 s (traced at GATE_JOBS=1: queue 2.9 s, `expect` 1.4 s at ~0.18 s each
     because it imports p2_verdict at 0.34 s, check_host_red 1.2 s, paint_report 0.9 s).
   - Inside the suite the same test takes 22–40 s: the rounds compete with 10 workers.
   - Round counts: the carry-cover known-bad test is 15 cases × 2 rounds = 30 rounds; the broken-instrument test is one
     round per case; many order/matrix tests run the identical default round. The refusal tests (exit 2 before
     launch) are cheap.
   - The script is shell, so coverage.py cannot see it. A 0-loss line+branch diff says nothing about run_gates.sh
     behaviour; merging its tests needs an assertion-preservation argument.
2. **P2 bracket sweep (`_bracket_sweep`, test_p2_adversarial): cold on every run we measured.**
   - A cold run takes 56 s wall alone and 144–210 s in-suite. It uses a `ProcessPoolExecutor(max_workers=os.cpu_count())`,
     so it adds 10 more busy processes under xdist; `test_bracket_sweep_allowlist_has_no_dead_entries` (52–117 s)
     mostly waits on the sweep's file lock.
   - The cache stores ONE file per sweep name (`.cache/test-sweeps/bracket.json`). Its key hashes `sys.version`, every
     installed distribution, **every** `src/obed_edom/**/*.py`, the test file and conftest.
     - A 3.13 run and a 3.10 run evict each other, so every two-interpreter pair recomputes both sweeps.
     - Any edit anywhere in `src/` also misses.
     - In practice the "cache" almost never hits during PR work.
3. **dissolve_probe image maths.**
   - `scripts/dissolve_probe.py:premul` takes 86 s of the file's 180 s single-process (19,356 calls, ~4.4 ms each). It
     does `np.asarray(img, dtype=float32).copy()`: two full-frame copies when one would do. It is also called again and
     again on the same unchanged A/B images, from `fit_frame` / `over` / `far_mask`.
   - `fit_frame` takes 39 s, `over` 28 s, the test helper `unpremul` 24 s and `strip_frame` 3.6 s.
   - The same functions dominate `test_placement_rescore_launch_matrix_and_dev_relocation` (42 s alone, 80 s in-suite):
     premul 12 s, PNG encode 5.6 s.
4. **pytest tmp retention.** Each full run leaves ~50k files in `pytest-of-$USER/pytest-N`. The next session's
   cleanup costs ~6 s (49k unlink + 33k rmdir seen in single-process profiles).
5. Smaller items:
   - test_dsk_pill (54 s): file I/O, copyfile and pickle loads.
   - test_golden_plan: a 20 s test, plus 9 skipped.
   - test_binary_counter_movie: 16–24 s setup.
   - test_mm_handback_probe: 37–67 s.
6. **Load flake.** `test_the_settle_wait_never_sleeps_past_its_deadline` failed on F4 under load; it is already fixed on
   stage-b-arch at 1a56be4c.

## Gate rounds (F4 branch 39b32de9, GATE_JOBS=3, two full rounds, timings from log birth time / .rc mtime)
- **Wall:** 1412 s and 1415 s per round. 85 runs, 3681 s of run time; 3681 / 3 = 1227 s ideal vs a 1385 s span.
- **Where the tail goes:** ~160 s is queue-tail idle. The two slowest P2 arms (`--wait-profile fast` and
  `--gl-replay auto`, 117–122 s, the only arms that run the freeze bracket) launch last.
- **Run time by group:**
  - mm-feed (F4/Stage B only) 27 runs, 1210 s
  - Pass G 7 runs, 811 s (86–135 s each)
  - host red 30 runs, 537 s
  - P2 8 runs, 521 s
  - host 3 runs, 286 s
  - carry-cover 6 runs, 142 s
  - Pass G red 1 run, 135 s
  - paint control 3 runs, 39 s
- **Prewarm and settle:** the H.264 prewarm is a cache hit (46 s of pattern), and the start-load guard did not wait.

## Not yet measured
- Dashboard npm suites (test:ui / test:maps / test:perf): queued for the next window.
- Collection/import time on its own: wall minus worker busy time puts it at ≤ ~15–20 s.

## Pass G / host-gate phase profile (cProfile wall, main 163ec812, idle, 12:21–12:25)
Pass G D2 139 s (121 s in time.sleep):
- capture_burst 62 s: 16 go-to legs + 3 advance destinations, 8 screenshots over G_BURST_OFFSETS_MS 0–3180 ms (liveness).
  This IS measurement; the sampler span I used earlier misses it, so "117 s outside sampling" was wrong.
- run_goto_destination: fixed POST_ADVANCE_SETTLE_S 1.8 s after each go-to = 29 s.
- run_advance_leg 17 s (sampled advances); score_static_control 9.6 s (6.5 s of sleeps).
- Chrome DevTools port wait 5.6 s; warm_up_for_screenshots 3 s; settle polls ~8 s.
Host 1920 137 s (110 s sleep):
- advance_until_original_slide 54 s (30 advances × 1.8 s settle); drive_and_sample dwells 23 s; capture_burst 23 s; attach arm 21 s.
Conclusion: ~85–90% of gate run time is deliberate pacing or measurement (bursts, dwells, settle). The only fixed wait that
could become event-driven is POST_ADVANCE_SETTLE_S (1.8 s per advance/go-to: ~29 s per Pass G run, ~54 s per host run).
That changes when bursts/samples start relative to arrival, so it is a measurement change: owner call + re-qualification.
