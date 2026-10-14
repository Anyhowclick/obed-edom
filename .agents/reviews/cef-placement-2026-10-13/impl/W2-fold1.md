# W2 review round 1 fold

## Outcome

All assigned W2 findings were folded. None was refuted. No §11 contract deviation was introduced.

## Files changed

- `src/obed_edom/placement_probe.py`
  - Corrected the classifier's expected `content_box` to the page's 1920×540 contain-fit geometry.
  - Applied the requested 1/256 px comparison tolerance to `rect` and `content_box`.
  - Removed the unreachable comparison of candidate inner-pixel counts.
- `tests/test_placement_probe.py`
  - Corrected the synthetic geometry helper to the same contain-fit calculation.
  - Added the page-JavaScript geometry evaluation and all requested classifier negative/ambiguous rows to the existing parametrized test.
  - Replaced the local `math_ceil` implementation with `math.ceil`.

Inspected but unchanged: `scripts/generate_placement_probe.py`, `pyproject.toml`, and the three generated placement data files. Review finding #16 identified no generator or package-data defect; the package-data entries remain correct and the generator remains reproducible.

## Findings

### Probe #1 — folded

`_expected_geometry` now computes:

`f = min(width / 1920, height / 540)`, `cw = 1920 * f`, `ch = 540 * f`, then `(x + (width - cw) / 2, y + (height - ch) / 2, cw, ch)`.

The exact corrected values W4 and W6 must use in their owned test helpers are:

- Pose 0: `rect=(10.352, 10.036, 480.53125, 135.140625)`, `content_box=(10.367625, 10.036, 480.5, 135.140625)`, `box=(10, 10, 482, 137)`.
- Pose 1: `rect=(10.73, 10.41, 480.53125, 135.140625)`, `content_box=(10.745625, 10.41, 480.5, 135.140625)`, `box=(10, 10, 483, 137)`.

The W2 parametrized test now extracts the actual `geometry()` function from `render_probe_page`, evaluates it in Node for both poses with `videoWidth=1920` and `videoHeight=540`, checks those exact contain-fit values, and passes each result through `_same_geometry` against `_expected_geometry`. W4/W6 files were not edited because they are outside W2 ownership.

### Probe #13 — folded

The existing single parametrized classifier test now includes:

- repeated motion pixels and binary counter with a fresh nonce → `UNKNOWN/stale-capture`;
- 299 ms paint-to-capture settle → `UNKNOWN/invalid-evidence`;
- 199 ms capture pacing → `UNKNOWN/invalid-evidence`;
- 1919×1080 PNG → `UNKNOWN/invalid-evidence`;
- mismatched capture `context_id` → `UNKNOWN/invalid-evidence`;
- `video=111`, `snap=111`, `frac=100`, causing identity/SNAP and GPU/FRAC disagreement → `UNKNOWN/ambiguous`.

### Probe #15 — folded

Required evidence wording for handover and commit text:

> Regenerated; byte-reproducible; matches the retained 144,100 B / `7b7d66b5` prefix (corroboration).

This does not claim full identity with the old pruned file, and requalification is not inherited. A fresh scratch regeneration produced the committed pattern digest `7b7d66b582d1b0df0c27c11bd945c1606d11ad4d34f5031b726ee22319d19870`, motion digest `e4640a667bbbdfca47dbde5942455d262c69a4e80c031b22cada0753763b3bfe`, manifest digest `c804288b674507df28c6d165f09634d6483458cb4f40fb74ff73c98ec29d0bcf`, and a 144,100-byte pattern file; all three regenerated files compared byte-equal to the committed regeneration. This proves reproducibility of the current generated artifacts, not full identity with the unavailable pruned source.

### Probe #16 — folded

- Removed `inner_pixels != other_pixels`; `_share` already rejects unequal shapes before both counts can differ.
- Removed the custom test `math_ceil` and used `math.ceil`.
- No finding #16 change applied to `generate_placement_probe.py` or `pyproject.toml` because the review names no defect in those files.

## Contract mapping

- §11.1 expected geometry: `_expected_geometry`, `_same_geometry`, and the page-JavaScript geometry row.
- §11.1 freshness/identity/timing validity: repeated motion, settle, pacing, size, and context-mismatch rows.
- §2.4/§11.1 map arbitration: the identity-SNAP/GPU-FRAC disagreement row returns `ambiguous`.
- §2.4/O3 artifact provenance: reproducible current generation is recorded separately from retained-file prefix/size corroboration; qualification inheritance is explicitly denied.

## Verification

Command, run twice after the fold (the second run followed the final context-mismatch adjustment):

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_placement_probe.py -q -n 2 -p no:cacheprovider
```

- First run: 21 passed, 0 failed, 0 skipped in 2.96 s.
- Final run: 21 passed, 0 failed, 0 skipped in 1.92 s.
- `git diff --check` for all W2-owned text files: clean.

No known external reds were encountered because only the required targeted W2 test file was run.

## Coordinator open items

- W4 and W6 must replace their `contentBox=list(rect)` test evidence with the exact contain-fit values above, preferably derived with the same formula.
- Use the finding #15 wording verbatim or equivalently narrowly in handover/commit text; do not describe the full old pruned-file digest as recovered and do not claim inherited requalification.
