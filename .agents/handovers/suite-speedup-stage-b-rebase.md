# Suite speed-up → Stage B rebase notes (2026-10-16)

Done: ported onto 15fa7c41 as `claude/stage-b-arch-speedup` (6adaa752 + fcd2b2ef); Stage B fast-forwards to it.

For the Stage B session rebasing `claude/stage-b-arch` onto main after the suite speed-up PR merges. Plan:
`.agents/plans/suite_speedup.plan.md`. Conflict hot spots: `scripts/run_gates.sh` and `tests/test_run_gates.py`. The
other files the speed-up touches don't conflict with Stage B as of 7746df27:
- `tests/test_p2_adversarial.py`
- `tests/test_dissolve_probe.py` and `scripts/dissolve_probe.py`
- `tests/test_managed_obs_qualify.py`: Stage B has its own changes here, but they are in other hunks.
- `tests/test_mm_handback_probe.py`

## scripts/run_gates.sh

- **Queue.** `queue()` no longer keeps a `PIDS` array or waits on the oldest PID. It polls the running-job count
  `N=${#${(M)${(v)jobstates}:#running:*}}` in the current shell, with `zselect -t 1`, until `N < GATE_JOBS`.
  - Keep the count as an assignment. Inside `(( ))` or double quotes it returns a string length, and the queue
    silently becomes serial.
  - Never fork `sleep` in the queue: the tests' PATH `sleep` stub records every sleep.
  - `stop_jobs`, the traps, the process groups and the atomic `.rc` writes are unchanged.
- **One launch section.** Every `queue` call now sits in a single block, just before the checks (~lines 616–626 on main).
  The fixed group order is:
  1. positive freeze-bracket P2 arms (no `--skip-freeze-bracket`)
  2. Pass G
  3. host gates
  4. Pass G red
  5. remaining P2 arms
  6. host red (P2 host reds, then deck arms)
  7. carry-cover
  8. paint control
- **Checks.** They keep their old order, in the block after the final `wait`.
- **Your mm-feed arms.** Add one launch line, `for A in "${MM_FEED_ARMS[@]}"; do run_mm_feed ${=A}; done`, between
  Pass G red and the remaining P2 arms (the coordinator's simulation placed mm-feed there; the Alpha arms run ~49–123 s).
  Keep `check_mm_feed` in your check position.
- **Your staging.** Keep the qualification-fixture staging (D7/D7s/Alpha) before the prewarm, as on your branch.

## tests/test_run_gates.py

- **Fixture.** `gates` is now built by `_make_gates(root)` with cleanup in `_cleanup_gates(root)`. A session fixture,
  `_gate_rounds`, shares completed stub rounds across xdist workers:
  - flock under `getbasetemp().parent`, keyed on (script, args, sorted explicit overrides);
  - errors are published as a record;
  - cleanup is round-local.

  Tests opt in explicitly with `gates["shared"](*args, **overrides)`, which returns the CompletedProcess and binds that
  round's `out`/`events`. Add your `QUAL_B_SOURCE` env and staging to `_make_gates`.
- **Shared rounds.**
  - R1 is `gates["shared"](GATE_JOBS="1")`: the order and matrix tests, `fresh_round[1]` and `warns[1]`.
  - R2 is `gates["shared"]("--tier", "full")`: the carry-cover and Pass G good controls, explicit-full and
    `warns[None]`.
- **Dev-tier producers** (assertions unchanged):
  - `warns[3,4,5]`
  - the four load positive controls
  - load-stays-low
  - empty-outdir accepted
  - the prewarm test's second (cache-hit) run
  - Exception on Stage B: the empty-outdir control stays full tier, because it also checks the mm-feed staging, which
    only a full-tier round launches (ported as fcd2b2ef on `claude/stage-b-arch-speedup`).
- **Launch-order oracles.**
  - `_full_launch_stems()` is the exact full-round launch sequence; Stage B must add its mm-feed stems there.
  - `FULL_P2_LAUNCH_ARMS` and `DEV_P2_LAUNCH_ARMS` hold the P2 launch order.
  - Check-order assertions are unchanged.
- **Multi-fault rounds.** `_multi_fault_rounds()` and `MULTI_FAULT_SLOTS` pack the 33 known-bad carry-cover,
  instrument and errored-Pass-G cases into seven shared rounds, one fault per stem per round. If you add known-bad
  cases, give each a stem that is unused in its round.
- **Settle test.** Your 1a56be4c test is already on main (SLEEP_STUB, `gates["sleeps"]`), adapted so the patch anchors
  on `GATE_SETTLE_S=${GATE_SETTLE_S:-300}` with `typeset -F SECONDS`. Main has no staging between the deadline and the
  loop. Mutants that must fail:
  - fixed `sleep 5`
  - fixed `sleep 4`
  - doubled deadline

  If your staging sits between the deadline and the loop again, re-check the anchor.
- **Added test.** A `refills-any-slot` parameter on the queue-owner test.

## Not in this PR (Stage B owns or gates them)

- **Pass G null-control subset (option A, owner-approved).** Edits `scripts/live_continuity_probe.py` and
  `tests/test_live_continuity_probe.py` after Stage B merges, with your agreement; see plan §F.
- **Feed-dwell scoping.** Yours, after merge; see plan §F.
