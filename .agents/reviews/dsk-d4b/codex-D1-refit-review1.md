REVISE

1. Major — `src/obed_edom/dsk_assemble.py:783`: `GroupChildId` omits the child kind even though `kindIndex` is per-kind. A `shape 1` badge and `text item 1` verse therefore both become `("groupchild", g, 0)`; the badge is mistaken for the long child and receives no short-row placement. Use a distinct kind-bearing ID for short children, or refuse collisions explicitly.

2. Major — `src/obed_edom/dsk_plan.py:163`: non-autosize grouped text is silently excluded from text-slide classification. `_all_group_child_records` labels text-bearing fixed shapes as `shape` (`src/obed_edom/dsk_assemble.py:1168`), while `_is_text_slide_kept` accepts only `kind == "text"` and `attach_group_child_runs` similarly skips them (`src/obed_edom/iwa_runs.py:775`). Consequently, a long fixed-frame verse group follows the affine content path and retains slide media. Preserve the child’s text membership/index separately, attach its runs, classify it as grouped text, and carry `autosize` into the emitter so height is written only for fixed-frame children; otherwise refuse explicitly.

Tests could not start because the sandbox had no writable temporary directory.