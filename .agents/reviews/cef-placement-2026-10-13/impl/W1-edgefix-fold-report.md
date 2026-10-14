# W1 edge-fix fold report

## Outcome

Folded review finding M1 into the existing W1 Node freeze-stub table. The new row exercises `vrect=[108.7,794.7,952,268]` (`fx=fy=-0.3`) against both supported real players. It passed without exposing a product bug, so this fold makes no product-code change.

## Changes

- `tests/test_live_runtime.py:1920-1931`: added a literal expected holder/trace for the edge geometry. The trace proves:
  - no top-row or left-column repair is emitted;
  - bottom row 267 is repaired from source row `vh-1 = 539`;
  - right column 951 is repaired from source column `vw-1 = 1919`;
  - intersection `(951,267)` is repaired from source `(1919,539)`.
- `tests/test_live_runtime.py:1972`: incremented the frozen case-table cardinality from 285 to 286.
- `tests/test_live_runtime.py:2188-2190`: added `fracRightBottomRepair` to the existing parameter table with the exact literal trace above.
- `tests/test_live_runtime.py:2483-2484`: asserted the repair ordering is snapped draw, fractional draw, whole-backing alpha read, bottom repair, right repair, intersection repair (`vvgvvv`).
- `src/obed_edom/live_runtime.py`: no edge-fix change; the existing uncommitted W1 product implementation already produced the required repair trace.

## Frozen-contract mapping

- §11.5 fractional draw: the row uses the existing snapped underlay followed by the fractional overlay at `fx=fy=-0.3`.
- §11.5 whole-backing alpha scan: the expected trace requires the full `952x268` read before any repair draw.
- Review M1: the previously uncovered `ei+1>fx+fw` right/bottom branches now execute, including the `vw-1`/`vh-1` source clamps and the corner intersection; exact trace equality also proves the top/left branches do not execute for this geometry.
- Sha-pinned in-memory replacement rule: exercised through `patch_player` on both supported real player hashes; no on-disk Keynote export was edited.

## Deviations

None. No §11 contract was redesigned or approximated. The row exposed no product defect.

## Verification

Command:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider
```

Result: **170 passed, 0 failed, 0 skipped in 5.83s**.

Additional check: `git diff --check -- src/obed_edom/live_runtime.py tests/test_live_runtime.py` passed with no output.

## Coordinator open items

- Fold this test-only M1 delta with the existing W1 uncommitted implementation.
- W6-owned blocker B1 and all W6 files remain untouched by W1.
- The listed external census reds were not encountered; the permitted target completed green.
