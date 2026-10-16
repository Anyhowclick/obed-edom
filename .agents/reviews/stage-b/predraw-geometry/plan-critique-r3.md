# Critique r3 (final): predraw-geometry.plan.md

**Verdict: READY.** 0 blocker, 0 major, 0 medium, 1 low.

I diffed predraw-geometry.plan.r2.md against the current plan. The changes are confined to the r2 findings, and every r2 finding is folded:

| r2 finding | What the plan now does |
|---|---|
| N1 | The rule "recorded draws imply a finite timestamp" is removed from the contract. Test 4 now checks that `firstDrawAt < createdAt` is rejected. A null `firstDrawAt` after a thrown draw is contract-valid. The scorer still grants no exemption for a null or out-of-order timestamp. |
| N2 | The v1/v2 branching and the fixture versions are kept. Both new keys are required in either version, and deleting either key is tested. There is no v2 fixture churn. |
| N3 | A 3.12 sync with `--all-extras --all-groups` and a dashboard `npm ci` now run as one heavy block before Step 0. Both suites run with `-rs`, and skip counts and reasons are reported. |
| L-a | The two permanent `authoredSrcRect` / `feed_specs_for` additions now land in Step 0. The wrapper is gone. |
| L-b | The departure-early-hide exemption is now qualified by the timing bounds. |
| L-c | The suite-command citation now reads `SKILL.md:43-50`. |

The new citations are accurate:
- `pyproject.toml:32-49` (the test and iwa extras)
- `tests/test_live_continuity_probe.py:3462-3472` (fixture skipifs)
- `continuity_core_variants.py:103-112`
- `mm_feed_instrument.py:264,273`

Nothing outside these edits changed.

## Low

**L-d. The `export UV_PROJECT_ENVIRONMENT=...venv312` line in the setup block may not reach later commands.**
- Shell exports are not reliable across separate tool calls: agent Bash calls reset shell state.
- If the variable is lost, the later Step 0, capture and 3.12 `uv run ... pytest` commands fall back to the worktree default environment. That environment would be built without the extras or xdist.

**Fix:** put `UV_PROJECT_ENVIRONMENT="$PREDRAW_SCRATCH/venv312"` inline on every 3.12 `uv run` command (the probe captures and the 3.12 pytest line), the same way the 3.10 lines already carry theirs. Alternatively, say that all commands run in one persistent shell.
