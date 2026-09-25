"""`noStrayVideo` -- the P2 DOM stray check (continuity generalisation plan S1, WS-H).

Synthetic sampler rows are built with every raw reading `MEDIA_PROBE_JS` records,
so the verdict's off-page re-derivation of `visible`/`hiddenBy` runs on them
exactly as it does on a live snapshot. Ground truth is the committed P2 fixture's
derived plan (4 slides: two movie1 instances on slide 1, one on slides 2 and 4,
movie1 + WA0125 on slide 3).
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

from obed_edom import p2_verdict as p2

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from test_live_continuity import FIXTURE_ROOT, SLIDES, _plan  # noqa: E402
from test_p2_adversarial_driver import p2 as drv  # noqa: E402

PLAN = _plan()
INSTANCES = PLAN.slide_instances
SCENES = PLAN.scene_index_by_player
SLIDE_HASH = {0: "#1?currentSlide=1", 1: "#2", 2: "#7", 3: "#9"}
STAGE_MAP = {"s": 1.0, "ox": 0.0, "oy": 0.0, "authoredWidth": 1920, "authoredHeight": 1080}


def _row(rect: dict, *, decoder: int, painting: bool = True, suppressed: bool = False,
         src: str = "assets/Untitled.mov-0.0000-46.0333.mov") -> dict:
    """A sampler row whose `visible`/`hiddenBy` re-derive from its raw readings:
    painting at full opacity, or held at opacity 0 (`hidden`) like the player's
    WebGL-composited layer tree and the runtime's suppressed restart element."""
    return {
        "index": decoder, "decoderId": decoder, "src": src,
        "visible": painting, "hiddenBy": None if painting else "hidden", "suppressed34": suppressed,
        "inDocument": True, "documentHidden": False, "display": "block", "visibility": "visible",
        "opacityProduct": 1.0 if painting else 0.0, "checkVisibility": painting,
        "clientRect": dict(rect), "viewport": {"w": 1920, "h": 1080}, "rect": dict(rect),
    }


def _snap(player: int, rows: list[dict]) -> dict:
    return {"hash": SLIDE_HASH[player], "stageMap": dict(STAGE_MAP), "videos": rows}


def _authored(player: int, asset: str = "untitled.mov", n: int = 1) -> dict:
    return dict(INSTANCES[player][asset][n - 1])


def _green_snapshots() -> list[dict]:
    """Today's healthy P2 run: slide 1 paints both movie1 instances; slide 2 is the
    player's WebGL composite (its element held at opacity 0); slide 3 paints movie1
    and WA0125; slide 4 paints the bridged decoder over the suppressed fresh element."""
    return [
        _snap(0, [_row(_authored(0, n=2), decoder=1), _row(_authored(0, n=1), decoder=2)]),
        _snap(1, [_row(_authored(1), decoder=3, painting=False)]),
        _snap(2, [
            _row(_authored(2), decoder=4),
            _row(_authored(2, "vid-20250608-wa0125.mp4"), decoder=5,
                 src="assets/VID-20250608-WA0125.mp4-0.0000-45.1381.mp4"),
        ]),
        _snap(3, [_row(_authored(3), decoder=6, painting=False, suppressed=True), _row(_authored(3), decoder=4)]),
    ]


def _score(snapshots: list[dict]) -> dict:
    return p2.noStrayVideo(snapshots, INSTANCES, SCENES)


def test_fixture_ground_truth_is_the_four_slide_p2_deck():
    assert SCENES == {0: 0, 1: 2, 2: 6, 3: 8}
    assert {k: {a: len(v) for a, v in d.items()} for k, d in INSTANCES.items()} == {
        0: {"untitled.mov": 2},
        1: {"untitled.mov": 1},
        2: {"untitled.mov": 1, "vid-20250608-wa0125.mp4": 1},
        3: {"untitled.mov": 1},
    }


@pytest.mark.parametrize("scene_hash, player", [
    ("#0", 0), ("#1?currentSlide=1", 0), ("#2", 1), ("#5", 1), ("#6", 2), ("#7", 2), ("#8", 3), ("#12", 3),
    ("#1junk", None), ("", None), (None, None),
])
def test_slide_of_hash_maps_scenes_to_player_indices(scene_hash, player):
    assert p2.slide_of_hash(SCENES, scene_hash) == player
    assert p2.slide_of_hash({str(k): v for k, v in SCENES.items()}, scene_hash) == player


def test_exact_match_on_every_settled_slide_is_true():
    verdict = _score(_green_snapshots())
    assert verdict["verdict"] == "pass", verdict["reason"]
    assert verdict["ok"] is True
    assert verdict["failingSlides"] == []
    assert [s["composited"] for s in verdict["slides"]] == [[], ["untitled.mov#1"], [], []]
    assert verdict["slides"][3]["claims"]["untitled.mov#1"][0]["decoderId"] == 4


def test_the_stash_any_stray_on_slide_4_is_false_naming_the_slide():
    """WA0125 pooled at the 3->4 detach and remounted at the movie1 fallback footprint
    (plan §4 red control): it overlaps the grown slide-4 rect by IoU ~0.39 only."""
    snaps = _green_snapshots()
    snaps[3]["videos"].append(_row({"x": 109, "y": 795, "w": 952, "h": 268}, decoder=5,
                                   src="assets/VID-20250608-WA0125.mp4-0.0000-45.1381.mp4"))
    verdict = _score(snaps)
    assert verdict["verdict"] == "fail"
    assert verdict["ok"] is False
    assert verdict["failingSlides"] == [3]
    assert "player index 3 (#9)" in verdict["reason"]
    assert "1 painting video(s) match no authored instance" in verdict["reason"]
    stray = verdict["slides"][3]["unexpected"][0]
    assert stray["decoderId"] == 5 and stray["bestLabel"] == "untitled.mov#1"
    assert 0.3 < stray["bestIou"] < 0.75


def test_an_extra_painting_video_on_an_authored_rect_is_a_duplicate():
    snaps = _green_snapshots()
    snaps[1]["videos"].append(_row(_authored(1), decoder=9))
    snaps[1]["videos"].append(_row(_authored(1), decoder=10))
    verdict = _score(snaps)
    assert verdict["verdict"] == "fail"
    assert verdict["failingSlides"] == [1]
    assert verdict["slides"][1]["duplicates"] == ["untitled.mov#1"]
    assert "painted more than once" in verdict["reason"]


def test_a_missing_authored_instance_is_false():
    snaps = _green_snapshots()
    snaps[2]["videos"] = [r for r in snaps[2]["videos"] if r["decoderId"] != 5]
    verdict = _score(snaps)
    assert verdict["verdict"] == "fail"
    assert verdict["failingSlides"] == [2]
    assert verdict["slides"][2]["missing"] == ["vid-20250608-wa0125.mp4#1"]


def test_a_suppressed_element_alone_does_not_account_for_its_instance():
    """The runtime's own suppressed restart element is not the player's composite:
    with the bridged decoder gone, slide 4's instance is missing."""
    snaps = _green_snapshots()
    snaps[3]["videos"] = [r for r in snaps[3]["videos"] if r["suppressed34"]]
    verdict = _score(snaps)
    assert verdict["verdict"] == "fail"
    assert verdict["slides"][3]["missing"] == ["untitled.mov#1"]


def test_a_suppressed_painting_element_is_not_a_painter():
    snaps = _green_snapshots()
    snaps[3]["videos"] = [
        _row(_authored(3), decoder=6, suppressed=True),
        _row(_authored(3), decoder=4),
    ]
    assert _score(snaps)["verdict"] == "pass"


def test_preserve_pool_rows_are_not_dom_videos():
    snaps = _green_snapshots()
    snaps[0]["videos"].append({"decoderId": 7, "fromPreservePool": True, "visible": False,
                               "hiddenBy": "detached", "rect": None})
    assert _score(snaps)["verdict"] == "pass"


def _broken(mutate) -> dict:
    snaps = _green_snapshots()
    mutate(snaps)
    return _score(snaps)


@pytest.mark.parametrize("name, mutate", [
    ("no snapshots", lambda s: s.clear()),
    ("snapshot not a dict", lambda s: s.__setitem__(0, None)),
    ("no stage map", lambda s: s[0].__setitem__("stageMap", None)),
    ("videos not a list", lambda s: s[1].__setitem__("videos", None)),
    ("hash off the deck", lambda s: s[2].__setitem__("hash", "#junk")),
    ("row missing suppressed34", lambda s: s[0]["videos"][0].pop("suppressed34")),
    ("row not a dict", lambda s: s[0]["videos"].append("video")),
    ("non-boolean visible", lambda s: s[0]["videos"][0].__setitem__("visible", 1)),
    ("page-computed visible disagrees with the raw readings",
     lambda s: s[1]["videos"][0].__setitem__("visible", True)),
    ("raw readings absent", lambda s: s[0]["videos"][0].pop("clientRect")),
    ("page hidden", lambda s: s[0]["videos"][0].__setitem__("documentHidden", True)),
    ("painting row without an authored rect", lambda s: s[0]["videos"][0].__setitem__("rect", None)),
    ("a slide never sampled", lambda s: s.pop(1)),
])
def test_malformed_rows_are_inconclusive(name, mutate):
    verdict = _broken(mutate)
    assert verdict["verdict"] == "inconclusive", name
    assert verdict["ok"] is False
    assert verdict["reason"]


def test_missing_ground_truth_is_inconclusive():
    for instances, scenes in (({}, SCENES), (INSTANCES, {}), (None, SCENES)):
        assert p2.noStrayVideo(_green_snapshots(), instances, scenes)["verdict"] == "inconclusive"
    bad = copy.deepcopy(INSTANCES)
    bad[3]["untitled.mov"][0] = {"x": 1, "y": 2}
    assert p2.noStrayVideo(_green_snapshots(), bad, SCENES)["verdict"] == "inconclusive"


def test_harness_ground_truth_derives_the_fixture_plan(tmp_path):
    """`_p2_ground_truth` reads the export's own slide list; the trimmed fixture is
    given exactly the four P2 slides the real export lists."""
    root = tmp_path / "export"
    shutil.copytree(FIXTURE_ROOT, root)
    header_path = root / "assets" / "header.json"
    header = json.loads(header_path.read_text())
    header["slideList"] = [s["exportedUuid"] for s in SLIDES]
    header_path.write_text(json.dumps(header))
    plan = drv._p2_ground_truth(root)
    assert plan.slide_instances == INSTANCES
    assert plan.scene_index_by_player == SCENES


def test_harness_ground_truth_refuses_an_export_that_does_not_derive():
    """The six-slide copy's two same-rect movie1 pairs are whole-deck ambiguous today."""
    with pytest.raises(SystemExit, match="does not derive"):
        drv._p2_ground_truth(FIXTURE_ROOT / "minimal_alpha_dsk")
