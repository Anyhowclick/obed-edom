## Standards

No standards-only findings. No blocker findings or actionable code-smell violations.

## Spec

1. **Major — edge case** — [live_continuity_js.py:1479](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_continuity_js.py:1479)

   `objectOf()` treats a canvas’s immediate grandparent as Keynote object identity. It is only a generated layer/content wrapper. A group—or another parent layer—can contain two distinct coincident child objects beneath the same `layerNN-contents`. The branch then selects the later object’s canvas and inserts the decoder above it, potentially covering that sibling’s artwork.

   The effect extends to G2 at line 725: `releaseArmed()` can accept the wrong canvas twice and report a successful handoff. In the `bindFacade()` path at line 1900, the wrong canvas can cause removal of a valid stub or placement into a sibling object. The new test at line 1064 defines “same object” as “same grandparent,” so it cannot detect this distinction.

   **Exact fix:** “Before removing a fresh destination stub, capture and stamp its actual authored layer on the decoder. Resolve tied canvases only through an exact stamped-layer match; without that identity—including G2 hand-back—retain ambiguity and retire/fail safely. Add grouped-sibling, G2 hand-back, and `bindFacade` collision tests.”

2. **Major — edge case** — [live_mm_feed_js.py:288](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_mm_feed_js.py:288)

   Missing tracking means “not observed since wrapping,” not necessarily “never set.” If a reused context’s active program had `mixFactor = 0.5` before the module later wrapped that context, `programValues` is empty and the draw is treated as zero. A from-only feed then replaces unit 0 while the shader is still blending unit 1.

   WebGL uniforms do default to zero after linking, and a `WebGLProgram` cannot be reused across contexts; those facts do not cover program state established before wrapping within the same context. Relinking also resets actual uniforms without clearing this cache.

   **Exact fix:** “Read the active program’s actual `mixFactor` using cached `getUniformLocation` plus `getUniform` at the target draw, normalize it to a scalar, and feed only when it is absent or exactly zero. Add pre-wrap-nonzero and relink-reset tests.”

3. **Medium — edge case** — [live_mm_feed_js.py:474](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_mm_feed_js.py:474)

   `uniform1fv(location, new Float32Array([0]))` stores the array itself. Because that array is not strictly equal to numeric zero, a valid zero-valued from-only draw stands down as `binding-mismatch`. The new test covers only `uniform1f`.

   **Exact fix:** “Normalize `uniform1fv` to its first finite scalar before storing or comparing it; reject empty/non-finite payloads. Parameterize zero and nonzero cases across `uniform1f` and `uniform1fv`.”

4. **Low — new class** — [test_live_mm_feed_js.py:350](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_mm_feed_js.py:350), [test_live_continuity_probe.py:11992](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_continuity_probe.py:11992)

   The instrument tests still use identically cased fact, plan, seam, and decoder IDs. Therefore the regression that previously produced null entry IDs and unresolved decoders is not pinned. The artwork test at line 12342 likewise uses matching lowercase IDs.

   **Exact fix:** “Run the existing realistic instrument test with lowercase fact IDs and uppercase plan/seam/decoder IDs, asserting decoder resolution plus claim/serial attribution. Give the existing artwork fact an uppercase row ID, and assert a missing plan row remains explicitly inconclusive.”

## No further findings

- **Instrument implementation:** no further exact-ID defect found. The remaining Python object-ID comparisons are fallbacks for contract-invalid rows; valid producer rows require `entryId`. A missing/ambiguous plan row yields `feed = null`, no bound reads, and an inconclusive verdict.
- **Closed classes:** no regressions found in `idleAtSource`, the real-snapshot harness, or `sampleRows`.
- **Repins:** core and feed SHA pins are consistent.
- **Covered tests:** the unset and `uniform1f(0)` assertions are non-vacuous; their missing cases are identified above.
- **Known suite failure:** the isolated passing deadline test appears load-sensitive and unrelated to this diff.

**Summary:** Standards: 0 findings. Spec: 4 findings; worst severity: major.