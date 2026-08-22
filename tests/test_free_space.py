from PIL import Image, ImageDraw

from obed_edom.free_space import (
    Box,
    FreeSpace,
    background_colour,
    occupancy_from_image,
    place_boxes,
)

NAVY = (13, 27, 58)
ORANGE = (244, 164, 60)


def _slide(width=1920, height=1080, bg=NAVY):
    return Image.new("RGB", (width, height), bg)


def _grid(occupied_cells, cols=10, rows=10, cell=8):
    occupied = [False] * (cols * rows)
    for c, r in occupied_cells:
        occupied[r * cols + c] = True
    return FreeSpace(cols, rows, occupied, cell)


def test_background_colour_picks_the_dominant_flat_tone():
    im = _slide()
    # A landmass over a third of the slide must not outvote the background.
    im.paste(ORANGE, (0, 0, 1920, 380))
    r, g, b = background_colour(im)
    assert abs(r - NAVY[0]) < 30
    assert abs(g - NAVY[1]) < 30
    assert abs(b - NAVY[2]) < 30


def test_empty_slide_is_entirely_free():
    space = occupancy_from_image(_slide(), slide_w=1920, slide_h=1080)
    assert space.free_fraction > 0.99


def test_artwork_marks_cells_occupied():
    im = _slide()
    im.paste(ORANGE, (0, 0, 960, 1080))
    space = occupancy_from_image(im, slide_w=1920, slide_h=1080, bg=NAVY)
    assert 0.4 < space.free_fraction < 0.6
    assert not space.is_free(Box(100, 100, 200, 200))
    assert space.is_free(Box(1200, 100, 200, 200))


def test_fit_test_respects_slide_edges():
    space = _grid([])
    assert space.is_free(Box(0, 0, 80, 80))
    assert not space.is_free(Box(-8, 0, 80, 80))
    assert not space.is_free(Box(8, 8, 80, 80))


def test_boxes_stack_into_a_column_then_step_left():
    space = _grid([], cols=40, rows=40, cell=8)
    boxes = [Box(0, 0, 60, 80)] * 4
    placed = [p.box for p in place_boxes(space, boxes, gap=8, margin=16)]
    # Same column, descending.
    assert placed[0].x == placed[1].x == placed[2].x
    assert placed[0].y < placed[1].y < placed[2].y
    # Column starts at the right edge, since that is where the wall keeps them.
    assert placed[0].x + placed[0].w <= 320 - 16
    assert placed[0].x + placed[0].w > 320 - 16 - 8


def test_boxes_avoid_artwork_and_each_other():
    im = _slide()
    # Landmass down the middle; the only free space is the two side gutters.
    im.paste(ORANGE, (400, 0, 1500, 1080))
    space = occupancy_from_image(im, slide_w=1920, slide_h=1080, bg=NAVY)
    boxes = [Box(0, 0, 120, 300), Box(0, 0, 120, 300), Box(0, 0, 120, 300)]
    placed = place_boxes(space, boxes, gap=10, margin=16)
    assert all(p.clean for p in placed)
    for p in placed:
        # Nothing may land on the landmass.
        assert p.box.x + p.box.w <= 400 or p.box.x >= 1500
    # And they must not overlap one another.
    for i, a in enumerate(p.box for p in placed):
        for b in [p.box for p in placed][i + 1 :]:
            assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


def test_content_is_never_dropped_when_there_is_no_clean_gap():
    """A church missing from the slide is worse than a crowded slide."""
    im = _slide()
    im.paste(ORANGE, (0, 0, 1920, 1080))
    space = occupancy_from_image(im, slide_w=1920, slide_h=1080, bg=NAVY)
    placed = place_boxes(space, [Box(0, 0, 200, 200)], gap=10, margin=16)
    assert len(placed) == 1
    assert not placed[0].clean
    assert placed[0].overlap > 0.9
    # Still inside the frame, so the operator can see and move it.
    box = placed[0].box
    assert 0 <= box.x and box.x + box.w <= 1920
    assert 0 <= box.y and box.y + box.h <= 1080


def test_crowded_box_picks_the_emptiest_spot_available():
    im = _slide()
    # Solid on the left, sparse speckle on the right: the box belongs right.
    im.paste(ORANGE, (0, 0, 900, 1080))
    draw = ImageDraw.Draw(im)
    for x in range(1000, 1900, 120):
        draw.rectangle([x, 400, x + 8, 420], fill=ORANGE)
    space = occupancy_from_image(im, slide_w=1920, slide_h=1080, bg=NAVY)
    placed = place_boxes(space, [Box(0, 0, 860, 900)], gap=10, margin=16)
    assert placed[0].box.x > 900


def test_scaled_down_map_does_not_poison_the_background_estimate():
    """A shrunk template map makes the CG frame map back past the wall's edge.

    Cropping there pads with black, black then wins the background vote, and the
    real navy background reads as content — which showed up as free space
    collapsing from 81% to 38%.
    """
    from obed_edom.free_space import predict_cg_raster

    wall = Image.new("RGB", (7680, 1080), NAVY)
    wall.paste(ORANGE, (3052, 18, 4300, 789))
    frame, bg = predict_cg_raster(
        wall,
        wall_w=7680,
        wall_h=1080,
        scale=0.8547,
        tx=-2597.65,
        ty=28.26,
        dest_w=1920,
        dest_h=1080,
    )
    assert frame.size == (1920, 1080)
    # Background must be the deck's navy, not the padding.
    assert abs(bg[0] - NAVY[0]) < 30 and abs(bg[2] - NAVY[2]) < 30
    space = occupancy_from_image(frame, slide_w=1920, slide_h=1080, bg=bg)
    # The map covers roughly 1067x659 of 1920x1080, so most of the frame is free.
    assert space.free_fraction > 0.6


def test_zero_sized_box_is_left_alone():
    space = _grid([], cols=40, rows=40)
    placed = place_boxes(space, [Box(5, 5, 0, 40)])
    assert placed[0].box == Box(5, 5, 0, 40)
    assert placed[0].clean
