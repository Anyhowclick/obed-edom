REVISE

1. **MAJOR — Generic multi-box slot splits still abandon the slot’s 45pt/50pt typography contract.**  
   [dsk_assemble.py:2023](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2023), [dsk_assemble.py:2039](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2039), [test_dsk_assemble.py:10364](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:10364)  
   Geometry, badge pinning, band recording, and top anchoring are fixed, but each part is independently passed through `fit_text_stack([box], ...)`, which chooses any scale up to the source size. Its runs then go through `_run_size_ranges` without `_EMPHASIS_CAP_PT`. A forced or naturally overflowing GW17-shaped split can therefore emit lead text above or below 45pt and emphasis above the owner-approved 50pt cap while still passing staged geometry verification. The new GW17 test asserts only rects.  
   **Fix:** for a slot split, use the slot-authoritative scale (`45 / lead source size`) for every part, measure/refuse each box at that scale, and call `_run_size_ranges(..., cap=_EMPHASIS_CAP_PT)`. Add an emitted-script test with source runs that would exceed 50pt, pinning literal 45pt lead and 50pt emphasis.

2. **MINOR — The one-part fallback still does not use or test the ordinary slot-fit result path.**  
   [dsk_assemble.py:1953](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:1953), [test_dsk_assemble.py:10400](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:10400)  
   The ordinary path builds a top-anchored rect using the calculated wrapped height at lines 1777–1779; the fallback instead assigns the full 177pt `split_rect`. The test forces GW38’s four-part text into one chunk and compares the result only with slot constants—not with an actual direct-slot plan—so its “matches the direct slot fit” claim is tautological.  
   **Fix:** funnel both outcomes through one slot-fit finalizer, including calculated height, run sizes, badge, band, and `stack_t`; compare a forced-one-chunk plan against a separately produced direct-slot plan field-for-field.

GW38 otherwise retraces correctly: four windows `1–91`, `93–185`, `187–271`, `273–296`; 45/50pt runs; literal tail-then-head deletes; final position `(53.6, 866.4)`; badge `(63.1, 785.8, 933.1, 82.1)` on every part; keys `text:1:1`–`text:1:4`; band `Band(1043.4, 177.0, 53.6, 1852.6, 4)`; zero source builds.

GW5 also closes the prior blind-write and identity issues: the group-child is written width → sizes → deletes → position; each saved ordinal is checked through composed group-child geometry for exact top and height ≤179pt, with missing geometry refusing; the group dissolve is matched to its source owner, only text child index 1 may narrow, and the badge child must remain exact.

Legacy non-slot placement remains bottom-stacked: top anchoring is gated by a selected/recorded slot layout. Static review only; tests were not run.