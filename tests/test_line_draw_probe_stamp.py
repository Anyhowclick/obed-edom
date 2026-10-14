import importlib.util
from pathlib import Path

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "line_draw_probe.py"
SPEC = importlib.util.spec_from_file_location("line_draw_probe", SCRIPT)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


@pytest.mark.parametrize(
    ("milliseconds", "corrupt"),
    [(0.0, False), (16.67, False), (42_000_000.0, False), (1234.56, True)],
)
def test_frame_stamp_round_trip_integrity_and_mask(milliseconds: float, corrupt: bool) -> None:
    ticks = round(milliseconds * PROBE.STAMP_TICKS_PER_MS)
    payload = PROBE.encode_stamp_ticks(ticks)
    image = np.full((12, PROBE.STAMP_WIDTH + 8, 4), 17, dtype=np.uint8)
    image[:, :, 3] = 255
    x0, y0, width, height = PROBE.stamp_mask_rect(image.shape)
    assert (x0, y0, width, height) == (0, 10, PROBE.STAMP_WIDTH, PROBE.STAMP_HEIGHT)
    for index in range(PROBE.STAMP_BITS):
        bit = payload[index // 8] >> (7 - index % 8) & 1
        value = 255 if bit else 0
        image[y0:y0 + height, x0 + index * PROBE.STAMP_CELL:x0 + (index + 1) * PROBE.STAMP_CELL, :3] = value
    if corrupt:
        index = 16
        cell = image[y0:y0 + height,
                     x0 + index * PROBE.STAMP_CELL:x0 + (index + 1) * PROBE.STAMP_CELL, :3]
        cell[:] = 255 - cell
        with pytest.raises(ValueError, match="CRC-8 mismatch"):
            PROBE.decode_frame_stamp(image)
    else:
        assert PROBE.decode_frame_stamp(image) == ticks / PROBE.STAMP_TICKS_PER_MS
    masked = PROBE.mask_frame_stamp(image)
    assert np.count_nonzero(masked[y0:y0 + height, x0:x0 + width]) == 0
    assert np.array_equal(masked[:y0], image[:y0])
