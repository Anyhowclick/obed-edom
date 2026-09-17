Overall: not clean—three correctness issues remain, and one new test masks an invalid geometry state.

### Verdicts 1–6

1. **FAIL** — The slot-height gate uses uncapped typography, applies no three-line check, and incorrectly falls back to shrinking below 45pt when the slot budget fails.
2. **PASS** — `box.runs` is `tuple[Run, ...]`; attribute access is valid.
3. **PASS** — `cap=` only lowers resolved sizes. Gap/unresolved detection is unchanged, although capped mixed sizes can legitimately collapse to a scalar.
4. **FAIL** — No downstream code requires an exact 177pt rect, but the new one-part finalizer measures uncapped text and its revised test blesses an impossible over-slot rect.
5. **FAIL** — `stack_t` is consumed by the post-save shrink fallback, which assumes one scale for every split part and can also remove the 50pt cap.
6. **MIXED** — The new GW17 test genuinely fails pre-fix code, but its aggregate assertions do not prove every part was sized correctly. The GW38 test hides a real defect.

## Findings

1. **MAJOR — The slot eligibility gate evaluates different typography from what it emits and uses the wrong fallback.**  
   [dsk_assemble.py:2175](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:2175), [dsk_assemble.py:2185](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:2185), [dsk_assemble.py:2198](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:2198)

   `box_slot_h` is calculated with raw `r.size * box_slot_t`, while the emitted runs are subsequently capped at 50pt. For a 70pt lead/85pt emphasis box, eligibility measures emphasis at 54.64pt, but output would use 50pt. A box that fits only after the mandated cap therefore falls into `fit_text_stack`, shrinks below the authoritative 45pt lead, and loses the cap.

   There are two additional boundary failures:

   - Exactly three 45pt lines estimate to `3 × 1.157 × 45 + 21 = 177.195pt` at [dsk_plan.py:1077](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_plan.py:1077). The strict `> 177` gate rejects this even though `_pack_split_lines` deliberately allows the 2pt tolerance. `fit_text_stack` then additionally charges 15pt safety and can shrink the lead to roughly 40pt.
   - The inverse is possible: four lines composed of smaller runs can total less than 177pt, so this path accepts more than three lines because it never counts spans.

   The same uncapped eligibility problem exists in the joint slot fit at [dsk_assemble.py:1838](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:1838), potentially splitting a multi-box slide whose final capped typography would fit jointly.

   **Fix:** Build capped `Run` objects first and use them for both wrapping and emitted sizes. Validate through the same line-span/height-budget logic as `_pack_split_lines`, including the three-line limit and tolerance. Separate the fallback causes:

   - `slot_t < minimum`: legacy fallback is defensible for an explicit `--min-text-pt > 45`.
   - 45pt typography exceeds the slot: do not silently shrink; split according to policy or refuse if splitting inside that box is forbidden.

   The cap’s slot-only scoping is otherwise correct: §2:72 ties it specifically to the 45pt slot lead. Off-slot `DEFAULT_BAND` fits should remain uncapped.

2. **MAJOR — The one-part fallback measures uncapped text, and the revised GW38 test explicitly accepts a 430pt rect in a 177pt slot.**  
   [dsk_assemble.py:2091](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:2091), [test_dsk_assemble.py:11088](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/tests/test_dsk_assemble.py:11088)

   `_pack_split_lines` wraps and budgets using capped `run_table`, but `one_h` immediately returns to uncapped `split_box.runs`. Thus a box can reach `len(chunks) == 1` because the capped output fits, then receive an uncapped wrapped height that exceeds the slot.

   The GW38 test makes this worse by mocking a genuinely four-part passage into one chunk. On the real fixture:

   - uncapped `expected_h`: **430.08pt**
   - capped full-text height: **408.60pt**
   - slot height: **177pt**

   The updated assertion at [test_dsk_assemble.py:11100](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/tests/test_dsk_assemble.py:11100) therefore blesses an impossible plan that staged verification would later reject at [dsk_assemble.py:3131](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:3131).

   **Fix:** Use a shared slot finalizer based on the capped emitted runs and reject any supposedly one-part result exceeding the slot or three-line budget. Replace GW38’s impossible monkeypatch fixture with a synthetic passage that naturally becomes one part after the cap, and assert `rect.h <= slot.h`.

   No downstream consumer needs `rect == slot.verse`: `resolve_slide_layouts` ignores body height, the pill pass only reads the badge, and refit/verification benefit from the accurate wrapped-height budget.

3. **MAJOR — Post-save shrink can use another part’s scale and re-expand capped emphasis above 50pt.**  
   [dsk_assemble.py:2212](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:2212), [dsk_assemble.py:5427](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:5427), [dsk_assemble.py:5484](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:5484), [dsk_assemble.py:5490](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:5490)

   Only the first box’s `t` is stored in `stack_t`. The shrink fallback later uses that slide-wide value for every split part. With source leads of 60pt and 70pt, the correct scales are respectively 0.75 and 0.643. If the 70pt part overflows after staging but inherits 0.75, a modest 3% reduction still emits about a 51pt lead.

   Independently, the shrink fallback calls `_run_size_ranges` without `cap=50`. A part initially emitted with a 50pt emphasis run can therefore be rewritten above 50pt during `--text-fit shrink`.

   **Fix:** Store the initial scale per split part/item, preferably on `SplitPart`, and key refit state by `(slide, part, item_id)`. Preserve the slot cap whenever rewriting a slot-derived part.

4. **MINOR — The new GW17 test is a real regression guard but does not verify each part.**  
   [test_dsk_assemble.py:11051](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/tests/test_dsk_assemble.py:11051), [test_dsk_assemble.py:11054](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/tests/test_dsk_assemble.py:11054)

   It would fail pre-fix code: the old `stack_t` was not `45/70`, and the emitted 66.3pt run violates `max <= 50`.

   However, it aggregates all size writes across both parts. A regression where part 1 writes 45pt while part 2 receives no size write and remains at its 70pt source size can still pass: the unwritten 70pt value never enters `all_sizes`. Flattening all emphasis to 45pt would also pass because the test never requires a 50pt emphasis run.

   **Fix:** Assert per `SplitPart`/long-box ID that each part emits its 45pt lead, that the known emphasized run is exactly 50pt, and that every long box has a size write.

The `Run` attribute concern is clean: `_box_with_runs` constructs actual `Run` dataclass instances at [dsk_assemble.py:5013](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/beautiful-khorana-439e7f/src/obed_edom/dsk_assemble.py:5013). The `cap=` addition also leaves unresolved/gap detection intact.

I could not run pytest because the read-only environment provides no writable temporary directory, but direct read-only planning confirmed GW17 now produces `t = 45/70` and capped 50pt runs, and confirmed the GW38 mocked one-part expected height is 430.08pt.