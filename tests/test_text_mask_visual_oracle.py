from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from scripts.text_mask_visual_oracle import (
    autosize_left,
    autosize_top,
    changed_ratio,
    clipped_region,
    estimated_translation,
    region_oracle,
    text_translation_pass,
)


def _label_image(x: int) -> Image.Image:
    image = Image.new("RGBA", (80, 30), "white")
    ImageDraw.Draw(image).rectangle((x, 8, x + 20, 20), fill="black")
    return image


def test_clipped_region_unions_frames_and_clips_to_image():
    assert clipped_region(
        [(-2.2, 3.1, 10.0, 5.0), (70.0, 20.0, 20.0, 20.0)],
        (80, 30),
        padding=2,
    ) == (0, 1, 80, 30)
    assert clipped_region([(90.0, 2.0, 5.0, 5.0)], (80, 30), padding=2) is None


def test_changed_ratio_is_zero_for_null_and_nonzero_for_change():
    image = _label_image(10)
    assert changed_ratio(image, image.copy()) == 0.0
    assert changed_ratio(image, _label_image(11)) > 0.0


def test_region_oracle_accepts_subtle_shift_below_eight_pixel_control():
    image_a = _label_image(10)
    row = region_oracle(
        image_a, _label_image(11), image_a.copy(), (0, 0, 80, 30), control_shift=8
    )
    assert row["nullRatio"] == 0.0
    assert row["actualRatio"] < row["positiveRatio"]
    assert row["pass"] is True


def test_region_oracle_rejects_wholesale_visible_change():
    image_a = Image.new("RGBA", (80, 30), "white")
    image_b = Image.new("RGBA", (80, 30), "black")
    row = region_oracle(
        image_a, image_b, image_a.copy(), (0, 0, 80, 30), control_shift=8
    )
    assert row["actualRatio"] > row["positiveRatio"]
    assert row["pass"] is False


def test_region_oracle_rejects_small_label_moved_far_in_a_large_region():
    image_a = Image.new("RGBA", (1000, 100), "white")
    image_b = image_a.copy()
    ImageDraw.Draw(image_a).rectangle((10, 40, 20, 50), fill="black")
    ImageDraw.Draw(image_b).rectangle((60, 40, 70, 50), fill="black")
    row = region_oracle(
        image_a, image_b, image_a.copy(), (0, 0, 1000, 100), control_shift=8
    )
    assert row["actualRatio"] > row["positiveRatio"]
    assert row["pass"] is False


def test_region_oracle_rejects_noisy_null_export():
    image_a = _label_image(10)
    image_null = Image.new("RGBA", image_a.size, "black")
    row = region_oracle(
        image_a, _label_image(11), image_null, (0, 0, 80, 30), control_shift=8
    )
    assert row["nullRatio"] > row["positiveRatio"]
    assert row["pass"] is False


def test_region_oracle_accepts_identical_solid_region_as_visually_inert():
    image = Image.new("RGBA", (80, 30), "#123456")
    row = region_oracle(image, image.copy(), image.copy(), (0, 0, 80, 30), control_shift=8)
    assert row["positiveRatio"] == 0.0
    assert row["visualSpan"] == 0
    assert row["visuallyInert"] is True
    assert row["pass"] is True


def test_estimated_translation_rejects_a_large_realistic_text_shift():
    font = ImageFont.load_default()
    image_a = Image.new("RGBA", (500, 100), "white")
    image_b = image_a.copy()
    ImageDraw.Draw(image_a).text((40, 30), "MYANMAR CHURCH", font=font, fill="black")
    ImageDraw.Draw(image_b).text((60, 30), "MYANMAR CHURCH", font=font, fill="black")
    dx, dy, peak = estimated_translation(image_a, image_b, (0, 0, 500, 100))
    assert dx == 20
    assert dy == 0
    assert peak > 0.5


def test_fixed_translation_ceiling_overrides_a_relative_visual_pass():
    row = {"pass": True, "translationPx": 20}
    assert text_translation_pass(row, 8.0) is False
    row["translationPx"] = 8
    assert text_translation_pass(row, 8.0) is True


def test_autosize_visual_footprints_respect_alignment_anchors():
    assert autosize_left(100.0, 40.0, "TATvalue0") == 100.0
    assert autosize_left(100.0, 40.0, "TATvalue2") == 80.0
    assert autosize_left(100.0, 40.0, "TATvalue1") == 60.0
    assert autosize_top(100.0, 40.0, "kFrameAlignTop") == 100.0
    assert autosize_top(100.0, 40.0, "kFrameAlignMiddle") == 80.0
    assert autosize_top(100.0, 40.0, "kFrameAlignBottom") == 60.0
