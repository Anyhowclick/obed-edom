# W1 player implementation report

## Outcome

Implemented the W1 player stream for CEF fractional placement and the O1 rendering/freeze split in the two authorized files. No §11 contract deviations were required.

## Files changed

- `src/obed_edom/live_runtime.py`
  - Added `frac` admission and the fdrawu two-pass draw.
  - Split the rendering-only replacement table from the live freeze lifecycle.
  - Re-pinned live-on and rendering outputs for both supported stock players.
  - Strengthened every applied replacement check to require one anchor before replacement, zero afterward, and one replacement afterward.
- `tests/test_live_runtime.py`
  - Rewrote the rendering/live equivalence to remove the observation hook plus freeze methods and D3/D4 call sites.
  - Extended existing parameterized anchor and Node tables; no new test function was added for frac coverage.
  - Added independent frac geometry expectations, grant-read counts, forbidden-geometry cases, pin checks, and byte-order checks.

## Contract mapping

### §11.5 take admission and drawing

- `pl=window.__obedPlacement` remains the sole grant input and is evaluated once per take. Node rows count one getter invocation for `snap`, `frac`, and `invalid`.
- Shared admission retains the qualified color tuple, paint/visibility/layer/clip/translation rules, integral computed scene `left`/`top`, and `kx == ky == 1`.
- `snap` retains DPR `{1, 1.5, 2}`. Its existing snapped geometry and first `drawImage(v,dx,dy,dw,dh)` bytes remain in place.
- `frac` requires DPR 1 and integral `R.left`/`R.top`. It first executes the unchanged snapped draw, then executes:
  - `fx = dx + (r.left - R.left) + Math.round(cx - r.left) - u0`
  - `fy = dy + (r.top - R.top) + Math.round(cy - r.top) - v0`
  - width `Math.round(cw)`, height `Math.round(ch2)`
- Near-side clipping retains `dx`/`dy`; the test table covers fractional x/y with left/top clipping.
- The whole-backing alpha read follows both video draws, and foreground canvases still draw only after the alpha scan. The byte-order assertion and Node traces enforce snapped draw → frac draw → whole readback → foreground.
- `invalid`, absent, unknown-case grants, frac at DPR 1.5/2, fractional stage origins, non-unit base geometry, and fractional scene positions skip while still publishing take cost.

### §2.6 and O1 (§8.1)

- `patch_player(stock, mm_opacity=True)` applies all rendering replacements, executable freeze take/attachment, and the observation hook.
- `patch_player(stock, mm_opacity=False)` remains byte-identical to the prior hook-only variant. Its two digests are unchanged:
  - e9b2fad4… → `7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de`
  - 17c0c938… → `4f9fbffd95e4649543142b2e95586babd9d75f0a0d9a4974e21d6f33c8389e3b`
- `patch_rendering(stock)` retains Magic Move opacity/hand-back and Dissolve/cut construction, but contains no observation hook, `__obedFreezeTake`, `__obedFreeze`, D3 attachment call, or D4 take call.
- Rendering equivalence is tested as live output minus the hook, freeze methods, D3 call, and D4 call.
- `RUNTIME_VERSION` remains 2. No on-disk `main.js` was edited.

## Final player pins

| Stock player | live on `[0]` | off `[1]` | rendering `[2]` |
|---|---|---|---|
| e9b2fad4… | `63c328b21fb3b5a57a0b89a4498f07c0f8e146da7088b6f292d051de33dfb8d4` | `7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de` | `a117b3ee37da8d85bb230977f99d5013d05a6fe118af58c4ba04ee4e8bfe6fa1` |
| 17c0c938… | `7b0af74970a3e94b6ac7971e9181519e0b5ffc612a1cdc23ff011901588cf09d` | `4f9fbffd95e4649543142b2e95586babd9d75f0a0d9a4974e21d6f33c8389e3b` | `2432c819d914468a2471cfc9f52bbe0e7a0e8722eaee480109f3634c6c79648e` |

## Tests

Required targeted file:

`env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider`

- Result: **116 passed, 3 failed**.
- All three failures are the coordinator-declared external fixture reds:
  - `test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_across_real_exports`: the new main-checkout fixture adds `(False, 4)`, `(False, 6)`, and `(False, 10)`.
  - `test_dissolve_real_patched_methods_on_node[*-census]` ×2: the new main-checkout fixture raises the census from expected 133 to 143.

Same targeted file with exactly those three known rows deselected:

`env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_runtime.py -q -n 2 -p no:cacheprovider --deselect tests/test_live_runtime.py::test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_across_real_exports --deselect 'tests/test_live_runtime.py::test_dissolve_real_patched_methods_on_node[e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354-census]' --deselect 'tests/test_live_runtime.py::test_dissolve_real_patched_methods_on_node[17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91-census]'`

- Result: **116 passed, 0 failed**.
- Both supported live-on/off/rendering players pass Node syntax checks inside the suite.
- `git diff --check -- src/obed_edom/live_runtime.py tests/test_live_runtime.py`: pass.

## Deviations from §11

None.

## Open items for the coordinator

- Keep the three declared main-checkout fixture census failures separate from W1; no expectations or fixtures were changed.
- Integrate W4's `snap|frac|invalid` getter contract and W6's raw/preview forgery plus CEF pixel gates against these final pins.
- Other streams were actively modifying disjoint files in the shared worktree; W1 touched only its two authorized files and made no commit.
