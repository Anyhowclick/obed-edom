REVISE

1. **HIGH — mandatory detector refusals are missing.** [src/obed_edom/dsk_assemble.py:469](/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom/b0fe5f66-5d53-46a1-ad2a-6074e9f6ea03/scratchpad/wt-d1b/src/obed_edom/dsk_assemble.py:469)

   `_heading_cluster` only requires `long_text_ids` to be non-empty. It therefore accepts multiple long boxes. It also never rejects an unrelated short top-level text item, contrary to §3.

   Concrete fix: require exactly one long box, explicitly identify the allowable verse badge, and return `None` if any other kept short top-level text remains. Add regression tests for both refusal cases.

2. **HIGH — the circle and numeral are not sufficiently identified.** [src/obed_edom/dsk_assemble.py:474](/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom/b0fe5f66-5d53-46a1-ad2a-6074e9f6ea03/scratchpad/wt-d1b/src/obed_edom/dsk_assemble.py:474)

   The shape check verifies only `kind`, empty text, and exact 81×81 geometry. Consequently:

   - A filled 81×81 textless shape is accepted, despite the unfilled requirement.
   - A text-bearing 81×81 circle is correctly rejected.
   - There is no geometric association between the numeral and circle.
   - A verse-badge text `"3"` is treated as a point-number candidate. With a real point number it safely causes refusal; without one it can substitute for the missing numeral.
   - A number-only slide is correctly rejected because it has no long text.
   - Two digit texts are correctly rejected through the cardinality check.

   The offline payload currently exposes no fill-style field, so the docstring’s “unfilled circle” claim is not implemented. Concrete fix: expose a reliable fill/no-fill property from inspection, require no fill, and pair the numeral to the circle by geometry. Add synthetic tests for filled and text-bearing circles, digit-only verse badges, missing numerals, and two point numbers.

3. **MEDIUM — fractional `min_pt` can be violated.** [src/obed_edom/dsk_plan.py:1068](/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom/b0fe5f66-5d53-46a1-ad2a-6074e9f6ea03/scratchpad/wt-d1b/src/obed_edom/dsk_plan.py:1068)

   `int(min_pt)` floors the lower bound. For example, `min_pt=24.5` can return `24.0`; I reproduced this directly. Use `math.floor(max_pt)` and `math.ceil(min_pt)` for the integer search bounds, with a fractional-bound regression test.

Other checks:

- The block-cap subtraction is correct: `wrapped_height` is exactly `n_lines × 1.157 × size + 21`, so subtracting `_BOX_PADDING_PT` implements §4 exactly. The 60pt two-line and 80pt one-line results are not coincidental.
- `longest_line_width` uses the same font size, oversampling, margin, and `_wrap_lines` call as `wrapped_height`, then divides by the oversampling factor to return real points.
- Heading/number/circle candidates are taken only from `cls.kept`; `long_text_ids` originates from kept content during classification.
- The gold-size tests and hard-coded deck fired set are meaningful, though the width test partly verifies one new helper with another. The missing refusal cases above are the larger coverage gap.
- `plan_assembly` remains unwired and therefore unchanged.
- House style is acceptable.
- The requested pytest command could not start because the read-only sandbox has no writable temporary directory; even `-s` was blocked by `tests/conftest.py` calling `tempfile.mkdtemp`. Static review and direct read-only helper probes were completed.