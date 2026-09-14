APPROVE

1. No findings. The MINOR is closed at `src/obed_edom/dsk_assemble.py:1235`: storage text is normalized before `_word_count`. The regression test at `tests/test_dsk_assemble.py:1065` uses real `_all_group_child_records`, confirms 10 words plus `￼` is accepted, and 11 words is refused.

Static review found no regressions in the prior kind-bearing IDs or fixed-frame refusal paths. Tests were not run, as requested.