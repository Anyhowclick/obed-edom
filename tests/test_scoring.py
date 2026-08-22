"""Scoring a remap against a human-made CG deck, and leaving hidden slides alone."""

from obed_edom.map_remap import (
    plan_payload_transforms,
    score_against_gold,
)


def _item(**kwargs):
    rec = {
        "index": 0,
        "kind": "shape",
        "x": 0,
        "y": 0,
        "w": 10,
        "h": 10,
        "text": "",
        "fileName": "",
        "locked": False,
    }
    rec.update(kwargs)
    return rec


def _pin(x, y, **kwargs):
    return _item(kind="movie", fileName="PIN DROP WAVE-1.mov", x=x, y=y, w=50, h=50, **kwargs)


def _map(x, y, w, h, **kwargs):
    return _item(kind="image", fileName="pasted-image.pdf", x=x, y=y, w=w, h=h, **kwargs)


def _identity_recipe():
    frame = {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}
    return {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(frame),
        "mapDst": dict(frame),
        "groups": [{"s": 1.0, "tx": 0.0, "ty": 0.0, "src": dict(frame), "dst": dict(frame)}],
    }


def _wall(slides):
    return {"slideWidth": 1920.0, "slideHeight": 1080.0, "slides": slides}


def test_matching_the_gold_layout_scores_zero():
    """The wall gives an exact correspondence, so an identical layout scores 0."""
    slide = {
        "number": 1,
        "items": [
            _map(0, 0, 1000, 600, kindIndex=0),
            _pin(100, 100, kindIndex=0),
            _pin(400, 300, kindIndex=1),
        ],
    }
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    # Gold used the same 1:1 transform, so its objects sit where ours do.
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100), _pin(400, 300)]}
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    assert score["slides"][1]["pin"]["goldRmse"] == 0.0
    assert score["slides"][1]["_goldAffine"]["s"] == 1.0


def test_a_different_layout_choice_shows_up_as_error():
    """Our template shrank the map; the gold kept it full size."""
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(500, 300, kindIndex=0)],
    }
    wall = _wall([slide])
    # Recipe scales everything to half size.
    recipe = _identity_recipe()
    half = {"x": 0.0, "y": 0.0, "w": 500.0, "h": 300.0}
    recipe["mapDst"] = dict(half)
    recipe["groups"] = [{"s": 0.5, "tx": 0.0, "ty": 0.0, "src": recipe["mapSrc"], "dst": half}]
    transforms = plan_payload_transforms(wall, recipe)
    gold = {"slides": [{"number": 1, "items": [_map(0, 0, 1000, 600), _pin(500, 300)]}]}
    score = score_against_gold(transforms, gold, wall=wall)
    assert score["slides"][1]["_goldAffine"]["s"] == 1.0
    # The pin centre sits at (525,325) for gold and (262,162) for us.
    assert score["slides"][1]["pin"]["goldRmse"] > 250


def test_dense_pins_are_compared_by_identity_not_proximity():
    """Dense pins plus a systematic offset defeat nearest-neighbour matching.

    On the real deck 138 pins share ~886px, about 6px apart, while the layout
    difference offsets everything by up to 190px — so each pin matches one about
    thirty places away. Identity matching reports the true offset; proximity
    matching reports something else entirely, sometimes smaller and sometimes
    larger depending on how the cloud is shaped, which is why it cannot be used
    to judge a change.
    """
    pins = [_pin(1000 + i * 6, 500, kindIndex=i) for i in range(40)]
    slide = {"number": 1, "items": [_map(0, 0, 1900, 1000, kindIndex=0), *pins]}
    wall = _wall([slide])
    recipe = _identity_recipe()
    shifted = {"x": 150.0, "y": 0.0, "w": 1900.0, "h": 1000.0}
    recipe["groups"] = [{"s": 1.0, "tx": 150.0, "ty": 0.0, "src": recipe["mapSrc"], "dst": shifted}]
    recipe["mapDst"] = dict(shifted)
    transforms = plan_payload_transforms(wall, recipe)
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1900, 1000), *[_pin(1000 + i * 6, 500) for i in range(40)]]}
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    row = score["slides"][1]["pin"]
    # The truth: we shifted every pin 150px right of where gold has it.
    assert abs(row["goldRmse"] - 150.0) < 1.0
    # Proximity matching does not recover that, so it must not be trusted.
    assert abs(row["nearestRmse"] - 150.0) > 20.0


def test_count_mismatch_is_visible():
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(100, 100, kindIndex=0), _pin(400, 300, kindIndex=1)],
    }
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    gold = {"slides": [{"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100)]}]}
    score = score_against_gold(transforms, gold, wall=wall)
    row = score["slides"][1]["pin"]
    assert row["predicted"] == 2
    assert row["gold"] == 1


def test_skipped_gold_slides_are_not_scored():
    """Hidden alternates held 21% of the items on a real gold CG deck."""
    slide = {"number": 1, "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(100, 100, kindIndex=0)]}
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100)]},
            {"number": 2, "skipped": True, "items": [_pin(9, 9) for _ in range(50)]},
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    assert set(score["slides"]) == {1}


def test_skipped_wall_slides_are_not_planned():
    slides = [
        {"number": 1, "items": [_pin(100, 100, kindIndex=0)]},
        {"number": 2, "skipped": True, "items": [_pin(200, 200, kindIndex=0)]},
        {"number": 3, "items": [_pin(300, 300, kindIndex=0)]},
    ]
    hidden: list[int] = []
    transforms = plan_payload_transforms(_wall(slides), _identity_recipe(), skipped_slides=hidden)
    assert hidden == [2]
    assert sorted({t.slide_number for t in transforms}) == [1, 3]
