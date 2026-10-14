# W6 live3 fold 5

## Changes

- `scripts/dissolve_probe.py:236-237,3191-3224` removes the fixed three-frame DSK spacing constant and retains each decoder's first non-preroll rVFC presentation/media times.
- `scripts/dissolve_probe.py:3266-3351` derives holder-strip spacing tolerance as `round(DSK_COUNTER_TIME_TOLERANCE_S * counter_fps)` and includes both base and `#t=5` first-rVFC presentation/media tuples in a spacing failure.
- `tests/test_dissolve_probe.py:1079-1109,1627-1628` updates the existing DSK identity table row: the derived eight-frame boundary is accepted, nine frames is rejected, and the rejection carries both timestamp tuples.

## Tests

`env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

Result: **500 passed, 1 skipped in 103.04s (0:01:43)**.
