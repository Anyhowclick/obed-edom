"""``offline_write_ab.py --slides`` accepts the CLI's slide spec (lists and ranges), not only ``A-B``.

The 2026-09-13 runner gate had to run three single-slide A/B passes because the gate script
only parsed one contiguous range; the remap side already took a frozenset.
"""

import pytest

from scripts.offline_write_ab import slide_selection


def test_blank_means_whole_deck():
    assert slide_selection(None) is None
    assert slide_selection("") is None


def test_single_slide_and_contiguous_range_keep_working():
    assert slide_selection("47") == frozenset({47})
    assert slide_selection("47-49") == frozenset({47, 48, 49})


def test_non_contiguous_list_mixed_with_ranges():
    assert slide_selection("47,113,82") == frozenset({47, 82, 113})
    assert slide_selection("47, 82,110-113") == frozenset({47, 82, 110, 111, 112, 113})


def test_invalid_spec_raises_value_error():
    with pytest.raises(ValueError):
        slide_selection("47-x")
    with pytest.raises(ValueError):
        slide_selection("0")
