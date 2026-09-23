1. **BLOCKER — new class** — `src/obed_edom/remap_keynote.js:690-717`  
   The `attrs` timer surrounds the entire geometry branch. On the `as` path it therefore attributes `runSlideGeomScript` to `attrs`, although the specification defines this stage as the sum of `applyTransforms` calls. This can falsely trigger the attrs optimization gate.  
   **Exact fix:** “Time and accumulate `attrs` immediately around each `applyTransforms(...)` call, including both JXA passes, but excluding `runSlideGeomScript` and the outer phase `_trec` calls; preserve call order and applied/missed semantics.”

2. **SHOULD-FIX — edge case** — `src/obed_edom/remap_keynote.js:718-721`  
   With `OBED_WRITE_TIMING` enabled, `hides` includes the phase `_trec` bookkeeping, making the always-on stage dependent on the opt-in profiler.  
   **Exact fix:** “Record `_stage("hides", _td)` immediately after `deleteHides` and before the phase `_trec`, without changing the `_trec` bucket name or output.”

3. **SHOULD-FIX — edge case** — `src/obed_edom/remap_keynote.js:761-777`  
   Template stages are recorded only after success. A caught failure in open/import/apply/delete omits the attempted stage’s elapsed time and inflates R1, even though `run()` continues and returns timing.  
   **Exact fix:** “Record each attempted template stage in a `finally` around that individual operation, retaining the existing outer catch and its short-circuit behavior.”

4. **SHOULD-FIX — new class** — `tests/pass1_stages.test.js:90-120`  
   Tests exercise only the attrs-only path, so they do not catch the AppleScript misattribution or prove that both JXA apply passes contribute.  
   **Exact fix:** “Add AS- and JXA-path regression fixtures proving AppleScript work is excluded from `STAGES.attrs`, both JXA apply passes contribute, and applied/missed plus hide ordering remain unchanged.”

No additional Standards findings. Save→retry→close behavior, abort semantics, hide deletion order, Python signatures, and existing `_trec` output structure remain intact.

fix-then-ship