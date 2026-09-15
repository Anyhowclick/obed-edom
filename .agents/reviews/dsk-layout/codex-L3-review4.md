REVISE

1. **MAJOR — Multi-box slot splits still use legacy bottom stacking and omit badge verification.**  
   [dsk_assemble.py:2008](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2008), [dsk_assemble.py:2011](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2011), [dsk_assemble.py:2140](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2140)  
   When several slot-eligible boxes cannot fit jointly but fit individually, the generic per-box split calls `_stacked_text_rects` without `top_anchor=True` and `_short_row_rects` without `pinned_ids`. Because `used_slot_layout_name` is also never set on this branch, `slot_badge_ids` is omitted. The resulting parts are bottom-aligned despite carrying a slot layout; staged verification will reject their text, while the displaced badge is not checked.  
   **Fix:** route this branch through the same slot-part helper/state as the char-window split, or pass `top_anchor=slot_layout_name is not None`, pin the selected badge, set the slot band/t, and record `slot_badge_ids`. Add a multi-box slot-split fixture; GW 17 currently covers only the unsplit outcome.

2. **MAJOR — Group build identity validation does not require the badge child itself to remain exact.**  
   [dsk_assemble.py:457](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:457), [dsk_assemble.py:3927](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:3927), [test_dsk_assemble.py:7022](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:7022)  
   `_identity_is_narrowed_slice` accepts any one changed child when it is a substring of its corresponding source child. Thus `("group", "Matthew\n<full verse>")` is accepted against `("group", "Matthew 18\n<full verse>")`: the badge narrowed while the verse remained unchanged. This is weaker than “badge exact; designated split child contiguous slice.” The test rejects a wholly different badge but misses this substring corruption.  
   **Fix:** identify the actual split child when matching the source group build and permit narrowing only at that child index; require every other child to match exactly. Also select the source build by its source owner, not merely `(kind, effect, animationType)`. Add a truncated-badge negative test.

3. **MINOR — The claimed one-part/GW 38 regression coverage is incomplete.**  
   [test_dsk_assemble.py:378](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:378), [test_dsk_assemble.py:9903](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:9903), [test_dsk_assemble.py:10031](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/tests/test_dsk_assemble.py:10031)  
   There is still no end-to-end `plan_assembly` fixture that deliberately reaches the one-part fallback; the only one-part test stops at `_pack_split_lines`. The GW 38 test pins windows and badge x/y, but not the badge’s literal width/height, measurement keys, complete per-part delete order, or zero build multiplicity. Its band assertion is recomputed through `_slot_band(slot.verse)` rather than pinned literally.  
   **Fix:** add a synthetic planning fixture that reaches `len(chunks) == 1`, and pin GW 38 to literal band `Band(1043.4, 177.0, 53.6, 1852.6, …)`, badge `(63.1, 785.8, 933.1, 82.1)`, keys `text:1:1`–`text:1:4`, all four delete sequences, and zero builds.

Review-3 status:

- Finding 1: closed for ordinary unsplit and char-window split paths; still open for generic multi-box slot splits.
- Finding 2: closed for char-window and one-part branches; still open for generic multi-box slot splits.
- Finding 3: closed for the reviewed char-window/one-part state.
- Finding 4: partially closed; child-wise comparison landed, but it does not constrain which child may narrow.
- Finding 5: closed via per-ordinal staged saved-geometry containment. A missing group-child rect refuses at [dsk_assemble.py:2614](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2614).
- Finding 6: only partially closed because the one-part and full literal GW 38 assertions remain absent.

GW 38 re-trace succeeds through the implemented main path: windows are `1–91`, `93–185`, `187–271`, `273–296`; every part uses verse `(53.6, 866.4, 1799, 177)` and badge `(63.1, 785.8, 933.1, 82.1)`. Verse writes are width → 45/50pt ranges → tail delete → head delete → position. In an isolated plan, offline keys become `text:1:1` through `text:1:4`; the Standard band is recorded, and the source has zero builds.

GW 5 reaches the group-child path, emits child width → sizes → deletes → position, and staged verification reads each ordinal’s saved composed child height, requiring top `866.4` and height ≤179pt. Missing geometry refuses. Its group dissolve is cloned per part, but finding 2 prevents accepting the build-identity verification as fully safe.

The new top anchoring is gated to recorded slot layouts; legacy non-slot planning retains bottom stacking. Static review only; tests were not run.