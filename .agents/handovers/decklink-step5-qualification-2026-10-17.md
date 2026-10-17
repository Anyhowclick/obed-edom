# DeckLink field test — step 5 managed-OBS qualification (handover, 2026-10-17)

Runbook: `.agents/handovers/decklink-field-test-runbook.md`, checklist step 5 (also "Home dry run — 2026-10-17"). Steps 1,
2, 3, 3b, 4, 6 and 7 are done (#300). Step 5 has **not** started: the previous session stopped before launching anything.

## State
- Field build: main `76452a91`, worktree `W=/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/decklink-field-2026-10-17`
  (detached, clean, `.venv` synced). Do not move it to a newer main: the field build was picked on 2026-10-17.
- `PY=$W/.venv/bin/python`, always with `PYTHONPATH=$W/src`. OBS 32.2.2 in `/Applications`; Desktop Video 16.4 with its DExt
  enabled. Fixtures resolve from the main checkout (`output/fixtures/p2-binary`, `p2-loop`).
- **Temporary symlink, keep it:** `~/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key` →
  main checkout `output/source-decks/Minimal Alpha_DSK.key` (#299 moved the deck; `76452a91` still reads the old path).

## Run (owner's go per launch — each arm launches a hidden OBS)
Fresh `--out` per run, outside `output/` (scratchpad), then copy result JSON/logs to the main checkout
`output/evidence/decklink-step5-<date>/`. The harness refuses while any OBS runs or `OBED_LIVE_GL_REPLAY` /
`OBED_LIVE_MM_OPACITY` is set; it never drives the DeckLink. AC power; it keeps the Mac awake itself.
```
cd $W; F=/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/p2-binary
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm both --rate 25 --takes 2 --out <dir>
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm g2 --rate 25 --takes 2 --fixture $F --out <dir>
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm failsafe --fixture $F --out <dir>
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm placement --out <dir>          # one 25+30 pair, no --rate
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm soak --precheck --out <dir>
PYTHONPATH=$W/src $PY scripts/managed_obs_qualify.py --arm soak --soak-minutes 20 --out <dir>
```
Each must end `SUMMARY PASS` (placement: qualified). Run long ones in the background; one at a time.

## Machine coordination
One heavy job machine-wide. Ask the "Stage B architecture handover" session for windows before starting (it agreed on
2026-10-17 to three back-to-back windows: ~45 min `both`/`g2`/`failsafe`/`soak --precheck`, ~20 min `placement`, ~25 min
soak) and send it "done" after each. Start only at 1-min load < 3; on 2026-10-17 the load spiked to 10 after trashing many
files and settled within minutes. If blocked > 1 min, print the top CPU users and escalate rather than wait silently.

## Expect
- **`placement` will likely fail on `76452a91`** with `persistence-failed`: OBS's first save now adds
  `/modules/decklink_captions` (Desktop Video installed), which the persistence allowlist predates. Root cause and fix A:
  branch `claude/placement-decklink-captions-allowlist` (`e775fd88`, D2 session; full suites, live check and PR still owed).
  A placement fail with that reason confirms D2; report it, do not patch the field build.
- `both` at 30 fps on the grey fixture is report-only for cadence; with `--fixture $F` it is gated at both rates.

## Record
Tick step 5 in the runbook with each arm's `SUMMARY` line, the run dirs and anything that needed a retry; commit on a branch
and open a PR (owner merges).
