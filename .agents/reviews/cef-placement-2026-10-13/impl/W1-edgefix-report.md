# W1 edge-fix implementation report

Implemented the owner-approved frac-only boundary redraw in the live runtime. No fallback was used. I edited only W1's two product/test files; the concurrent W6 changes in `scripts/dissolve_probe.py` and `tests/test_dissolve_probe.py` were not touched.

## Files changed

- `src/obed_edom/live_runtime.py`
  - Lines 11–20: re-pinned only the two live-on outputs.
  - Lines 158–167: retained the snapped underlay and fractional quad, added the pixel-centre containment refusal, kept the whole-backing alpha scan before repair, and added row → column → intersection redraws only for partially covered cells.
  - Lines 413–421: minimally updated the `patch_player` frac description.
- `tests/test_live_runtime.py`
  - Lines 301–349: recorded the previous live-on pins and pinned all live-on/off/rendering outputs.
  - Lines 640–664: byte-level assertions cover the unchanged snap draw, one placement read, exact containment guard, partial-cell predicates, and scan/repair/foreground ordering.
  - Lines 1877–1919: the independent geometry oracle now models containment and exact boundary source sampling. The saved live geometry produces holder `109,795,952,268` and exactly these three repair draws:
    - row: source `(0, 0.434535, 1920, 1)` → destination `(0.351707, 0, 952, 1)`;
    - column: source `(0, 0, 1, 540)` → destination `(0, 0.036194, 1, 268)`;
    - intersection: source `(0, 0.434535, 1, 1)` → destination `(0, 0, 1, 1)`.
  - Lines 1960 and 2171–2187: extended the existing Node table, without adding a test function, for recorded live geometry plus foreground, `fx=-0.47 / fw=951 / ww=952` refusal, frac alpha refusal, and the existing DPR 1/1.5/2 snap cases.
  - Lines 2449–2475: exact trace assertions require snapped → frac → whole scan → three repairs → foreground; alpha rejection stops after the scan with zero repair draws.

## Contract mapping

1. Edge brief item 1 / frozen §11.5 admission: `live_runtime.py:160` applies `if(fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5)return;` before the fractional draw. The recorded geometry passes; the two-cell exterior-centre geometry returns before holder creation while `finally` still publishes take time.
2. Edge brief item 2: `live_runtime.py:161–167` selects columns with `ei<fx||ei+1>fx+fw` and rows with `ei<fy||ei+1>fy+fh`; there are no unconditional first/last-ring terms. The live geometry performs three repair draws.
3. Edge brief item 3: the original snapped draw is unchanged at `live_runtime.py:158`; the fractional draw follows, the whole-backing scan remains at line 161, repairs follow the scan, and `Y.forEach` foreground remains last at line 167. The underlay-omission refusal therefore remains before repair. Existing snap DPR 1/1.5/2 rows remain unchanged.
4. Edge brief item 4: only `SUPPORTED_PLAYERS[*][0]` and `REAL_PATCHED_SHA256[*][True]` changed. The off `[1]` and rendering `[2]` digests stayed byte-identical and are asserted by the existing pin tables. The previous live-on prefixes `e57025c3…` / `bff8f5ae…` are retained in the pin-history comment.
5. Edge brief item 5: the existing Node trace/case table covers exact source coordinates, holder geometry, strict operation order, exterior pixel-centre refusal, alpha rejection with no repair, and existing snap paths. No dissolve-probe test was added or changed by W1.
6. Edge brief item 6: the frac sentence in `patch_player` now describes opacity validation followed by partial-boundary redraw.
7. Frozen §11.5 invariants retained: `pl` is still read once (`live_runtime.py:89`); snap/frac DPR and shared admission are unchanged (`:130`); `patch_player(..., True)` remains fidelity + freeze + observation; off remains hook-only; `patch_rendering` remains free of the executable freeze lifecycle; no player file is modified on disk.

## Pins

| Stock player | Live on `[0]` / `True` | Off `[1]` / `False` | Rendering `[2]` |
|---|---|---|---|
| `e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354` | `d3ddd770dae1cd4aeb67a68a7e6aa12ef3d890b5ce4cd1cb19db81ec5e709d54` | `7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de` | `8202717a2699a2e4691aac6848675e3636f5d26ac1336f9ae6faba0a48cc72dd` |
| `17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91` | `1036a8e26fae661c0cde23291f1726643bfb7aa0e781b7f95da1739c7cda3732` | `4f9fbffd95e4649543142b2e95586babd9d75f0a0d9a4974e21d6f33c8389e3b` | `c0faaa3c99c88705931f686d96d4e891a8d10b6b59aa2da62faae5cf56b2c4fc` |

The off and rendering values were recomputed from the final code and match their pre-change pins exactly.

## Deviations from frozen §11

One explicit, owner-directed deviation exists. Frozen §11.5 ended the frac path after the two draws and whole-backing scan. The edge-fix brief and approved critique supersede that sequence by adding the post-scan boundary repair and tightening admission when a holder pixel centre lies outside the frac quad. Evidence is W6 live4: interior residual 2, edge residual 9 at τ=4, with exactly 15 failures on row 795; the approved diagnosis attributes them to fractional quad coverage mixing against the snapped underlay. All other §11.5 behavior is retained. The edge brief also overrides §11.5's older instruction to re-pin rendering: because rendering excludes the freeze method, its final bytes and `[2]` pins are unchanged.

There were no unimplementable contracts and no other deviations.

## Tests

All test commands obeyed the W1 restriction and ran only `tests/test_live_runtime.py`.

1. `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider`
   - First run: **168 passed, 2 failed** in 8.96 s.
   - Both failures were the new exact-coordinate expectation rounding `fx/fy` before deriving the source coordinate. The product emitted the correct `0.434535`; the independent Python oracle was corrected to retain raw geometry until the trace boundary.
2. `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider -k 'freeze_stub'`
   - **2 passed** in 0.61 s.
3. `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider`
   - Final: **170 passed, 0 failed** in 5.65 s.

`git diff --check -- src/obed_edom/live_runtime.py tests/test_live_runtime.py` also passed with no whitespace errors.

## Open items for the coordinator

- Run W6's first managed CEF scratch qualification on these final pins. The product fix still needs live proof that the boundary residual is within τ=4 and the DSK take remains ≤50 ms; unit tests prove the algorithm and coordinates, not CEF's fractional one-pixel filtering or cost.
- Integrate W6's concurrent scorer/harness changes and keep its separately diagnosed nooffset-y and foreground-demix issues distinct from this product fix.
- No fallback is pre-authorized or present. If the live CEF qualification fails, stop for the owner's decision rather than disabling frac silently.
- The three known external census reds were not exercised because W1 ran only the required target file; the final W1 suite is green.
