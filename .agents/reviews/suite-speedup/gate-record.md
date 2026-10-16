# Suite speed-up gate record (2026-10-16)

Branch `claude/suite-speedup` off origin/main 163ec812. Roster:
- Plan: Codex GPT-6 Astra high (r0–r2).
- Plan critiques: Opus 5.5 high (2 rounds).
- Implementers: Codex GPT-5.6 Sol high (streams A, A3, B, C, D, F and the review folds).
- Code reviews: Opus 5.5 high (r1 B/C/D, r1 A/F, r2 A3 + fold). No BLOCKER or MAJOR in any round; every MEDIUM and LOW
  was folded except two lows accepted on r1 B/C/D: L7 (no flock timeout) and L8 (lock-file accumulation).

## Full Python suites (-n auto --dist worksteal, 10 workers)
| Run | 3.13 | 3.10 |
|---|---|---|
| Baseline 163ec812 (cold sweep, the PR-typical case) | 285 s | 317 s |
| HEAD, warm sweep cache | **120 s** | **140 s** |
| HEAD, cold sweep (scorer manifest changed) | 185 s | 219 s |

- HEAD tally: 11054 passed, 38 skipped, 1 xfailed on both interpreters; the baseline had 11044 passed with the same skips.
- Load at start ranged 4–47; each run started as the previous one ended (one heavy job at a time).
- Raw data: session scratchpad `final/`, `final2/`, `final3/`.

## Coverage (owner rule: drops/merges must lose 0 line+branch)
- The only file with dropped Python tests is `tests/test_p2_adversarial.py`: 2 removed, 9 added.
- Measured before/after with `coverage run --branch --source=src/obed_edom,scripts`, serial, on 3.13: 3422 lines /
  586 branches executed both sides, **0 files with any lost line or branch** (122 files compared).
- `test_run_gates.py` exercises zsh, which coverage.py cannot see. It is gated instead by an assertion-preservation map
  (session scratchpad `impl/AFfix/assertion-map.md`), reviewed in r1/r2.
  - Every prior assertion is either kept or replaced by an approved stricter oracle (exact launch sequence, P2 launch
    lists, dev producer, settle anchor).
  - Mutants that must fail, and do: settle fixed `sleep 5`, fixed `sleep 4`, doubled deadline; oldest-PID wait
    (refill); cross-wired multi-fault check.

## Equivalence evidence
- dissolve_probe: one-off old-vs-new differential on both interpreters. Arrays, scorer dicts (NaN-aware), CASES
  verdicts, managed records and PNG bytes are all identical.
- P2 sweep: 52,130 indexed-path→bool entries byte-identical cold/warm/cache-off on both interpreters
  (sha af132e39…447b).
- run_gates.sh: at GATE_JOBS 1/3/5 a stub round launches all 58 arms exactly once, with the same argv multiset as
  HEAD~ and a concurrency cap that held.

## Owner A/B: multi-fault rounds (3270041b), kept
- test_run_gates.py at -n 4 (3.13, alternating ×3): 87.6 → 47.7 s.
- Summed test time: 337 → 187 s.
- Runner invocations: 113 → 87.

## Found along the way
- `test_live_host.py::test_managed_probe_state_machine_renews_suppresses_and_stops`: load race in the test (it never
  joined the cancelled probe thread). Fixed in 9736ca86; reproduced deterministically with a 0.3 s probe-thread delay.
- Reverted the tmp-retention trial (26644ec2): `tmp_path_retention_count=1` pruned other sessions' live basetemps
  under the shared `pytest-of-$USER` root.

## Open
- Live gate scheduling (b592eef5) needs one paired real full round at GATE_JOBS=3 to confirm verdicts and timing.
  - Simulated main queue span: 1002 → 829 s.
  - Pass G option A (approved; after Stage B merges) would take it to ~724 s.
- Dashboard npm suites: unchanged, 17 s total.
