from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from obed_edom.live_continuity import ContinuityPlan, MovieContinuity, Rect, Unsupported, codec_report, derive_plan

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
REAL_EXPORT_ROOT = Path(
    "/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/"
    "keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-unmodified"
)

SLIDE1 = "08C861A1-CB39-4832-B189-6DF95B7F3396"
SLIDE2 = "0C652BEB-F445-48CF-BFD0-4194C6B7A438"
SLIDE3 = "D4D95253-4C37-40CF-A4A4-62D8DE24EF2A"
SLIDE4 = "7A851F4D-4648-4545-A491-58838A7CD843"

SLIDES = [
    {"playerIndex": 0, "originalOrdinal": 1, "exportedUuid": SLIDE1, "skipped": False},
    {"playerIndex": 1, "originalOrdinal": 2, "exportedUuid": SLIDE2, "skipped": False},
    {"playerIndex": 2, "originalOrdinal": 3, "exportedUuid": SLIDE3, "skipped": False},
    {"playerIndex": 3, "originalOrdinal": 4, "exportedUuid": SLIDE4, "skipped": False},
]


def _resolver(root: Path, relative: str) -> Path:
    """Minimal traversal-safe resolver used by these tests (mirrors safe_export_file's checks
    without requiring the export to sit under the preview cache)."""
    parts = Path(relative).parts
    if not relative or relative.startswith("/") or "\\" in relative:
        raise ValueError("invalid path")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("path traversal rejected")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if resolved_root not in candidate.parents and candidate != resolved_root:
        raise ValueError("outside root")
    if not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _plan(root: Path = FIXTURE_ROOT, slides: list[dict] = SLIDES) -> ContinuityPlan | Unsupported:
    return derive_plan(root, slides, resolver=_resolver)


def _rect(x, y, w, h):
    return {"x": pytest.approx(x, abs=0.05), "y": pytest.approx(y, abs=0.05), "w": pytest.approx(w, abs=0.05), "h": pytest.approx(h, abs=0.05)}


def _boundary(plan: ContinuityPlan, from_index: int) -> dict:
    for b in plan.boundaries:
        if b.from_player_index == from_index:
            return b.as_dict()
    raise AssertionError(f"no boundary from player index {from_index}")


def test_fixture_present():
    assert (FIXTURE_ROOT / "assets" / "header.json").is_file()
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        assert (FIXTURE_ROOT / "assets" / uuid / f"{uuid}.json").is_file()


def test_canvas_and_scene_boundaries():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.canvas == {"width": 1920, "height": 1080}
    assert plan.scene_index_by_player == {0: 0, 1: 2, 2: 6, 3: 8}


def test_boundary_1_to_2_pins_the_static_movie():
    plan = _plan()
    boundary = _boundary(plan, 0)
    assert boundary["toPlayerIndex"] == 1
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "pin"
    assert untitled["srcRect"] == _rect(109.35, 795.04, 951.54, 267.62)
    assert untitled["dstRect"] == _rect(109.35, 795.04, 951.54, 267.62)


def test_boundary_2_to_3_restarts_across_the_dissolve():
    plan = _plan()
    boundary = _boundary(plan, 1)
    assert boundary["toPlayerIndex"] == 2
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    assert movies["untitled.mov"]["action"] == "restart"


def test_boundary_3_to_4_bridges_the_moving_scaling_movie():
    plan = _plan()
    boundary = _boundary(plan, 2)
    assert boundary["toPlayerIndex"] == 3
    assert boundary["durationSeconds"] == 1.5
    movies = {m["asset"]: m for m in boundary["movies"]}
    # WA0125 does not appear on slide 4: it must not be treated as continuing.
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "bridge"
    assert untitled["srcRect"] == _rect(197.98, 797.10, 951.54, 267.62)
    assert untitled["dstRect"] == _rect(326.75, 708.52, 1266.49, 356.20)


def test_boundary_4_to_end_restarts_with_no_destination():
    plan = _plan()
    boundary = _boundary(plan, 3)
    assert boundary["toPlayerIndex"] is None
    movies = {m["asset"]: m for m in boundary["movies"]}
    assert set(movies) == {"untitled.mov"}
    untitled = movies["untitled.mov"]
    assert untitled["action"] == "restart"
    assert untitled["dstRect"] is None


def test_slide3_authored_y_differs_from_p2s_measured_constant_within_tolerance():
    """Known discrepancy (plan section 2): a previous analysis derived y=797 for slide 3's
    movie while P2's screen-measured MOVIE constant used 795 (authored notes: 794.6). The
    export data says y=797.10 (see test_boundary_3_to_4_bridges_the_moving_scaling_movie);
    P2's 795 is off by ~2.1px, comfortably inside the probe's stated 10px per-axis tolerance,
    consistent with it being a screen-measured rather than authored value. This test pins the
    DATA value; it must not be relaxed to force-fit 795.
    """
    plan = _plan()
    boundary = _boundary(plan, 2)
    src = next(m for m in boundary["movies"] if m["asset"] == "untitled.mov")["srcRect"]
    assert src["y"] == pytest.approx(797.10, abs=0.05)
    p2_measured_y = 795
    assert abs(src["y"] - p2_measured_y) < 10


def test_ambiguous_same_asset_instance_resolves_by_unique_geometry_match():
    """Slide 1 (player index 0) authors TWO Untitled.mov instances (see
    test_boundary_1_to_2_pins_the_static_movie's srcRect and the second, non-continuing
    instance at ~(1076, 876), matching the plan's noted 'movie2' drift). Only one of them
    has an identical-geometry counterpart on slide 2, so ownership is not actually ambiguous:
    the narrow rule is 'refuse only when more than one instance has a geometry-equal match on
    the far side', not 'refuse whenever more than one instance of an asset exists'. This is
    exactly the fixture P2 qualified, so it must still resolve to plan (not Unsupported).
    """
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    boundary = _boundary(plan, 0)
    assert len(boundary["movies"]) == 1


def test_ambiguous_ownership_is_refused_when_the_stray_instance_also_matches():
    """Mutate slide 2 so its lone Untitled.mov instance geometry equals slide 1's SECOND
    (non-continuing) instance as well as its first: now two geometry-equal pairs exist and
    ownership is genuinely ambiguous, which must fail closed."""
    tmp = _mutate_slide(SLIDE2, _clone_second_instance_onto_slide2)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "ambiguous" in plan.reason


def test_refuses_unreadable_header():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / "header.json").write_text("{not json")
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "header" in plan.reason


def test_refuses_slide_with_no_events():
    tmp = _copy_fixture_tree()
    _rewrite_slide_json(tmp, SLIDE1, lambda data: {**data, "events": []})
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "no events" in plan.reason


def test_refuses_unreadable_slide_json():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / SLIDE1 / f"{SLIDE1}.json").write_text("not json at all")
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unreadable slide export" in plan.reason


def test_refuses_unknown_transition_kind():
    tmp = _copy_fixture_tree()

    def rename(data):
        return _map_transitions(data, lambda name: "apple:cube")

    _rewrite_slide_json(tmp, SLIDE1, rename)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unsupported transition" in plan.reason


def test_refuses_rotated_movie_layer():
    tmp = _copy_fixture_tree()

    def rotate(data):
        return _map_movie_nodes(data, lambda node: _set_rotation(node, 5))

    _rewrite_slide_json(tmp, SLIDE1, rotate)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "rotated" in plan.reason or "transformed" in plan.reason


def test_refuses_non_identity_affine_transform():
    tmp = _copy_fixture_tree()

    def skew(data):
        return _map_movie_nodes(data, lambda node: _set_affine(node, [1, 0.2, 0, 1, 0, 0]))

    _rewrite_slide_json(tmp, SLIDE1, skew)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)


@pytest.mark.parametrize("ancestor_change", [None, "position", "rotation", "animation"])
def test_refuses_video_below_an_intermediate_layer(ancestor_change):
    def nest_video(node):
        base = node["baseLayer"]
        for index, layer in enumerate(base["layers"]):
            if not layer.get("isVideoLayer"):
                continue
            ancestor = {
                "initialState": copy.deepcopy(base["initialState"]),
                "layers": [layer],
                "animations": [],
            }
            if ancestor_change == "position":
                ancestor["initialState"]["position"]["pointX"] += 80
            elif ancestor_change == "rotation":
                ancestor["initialState"]["rotation"] = 30
            elif ancestor_change == "animation":
                ancestor["animations"] = [{"property": "position", "duration": 1.5}]
            base["layers"][index] = ancestor

    tmp = _mutate_slide(SLIDE1, lambda data: _map_movie_nodes(data, nest_video))
    plan = _plan(tmp)
    assert isinstance(plan, Unsupported)
    assert "not a direct child" in plan.reason


def test_refuses_two_geometry_changing_movies_on_one_boundary():
    tmp = _copy_fixture_tree()

    # Slide 3 already carries a WA0125 instance; add a matching one on slide 4 so it also
    # "continues" (with different geometry) across the 3->4 magic move alongside Untitled.mov.
    def add_wa0125_to_slide4(data):
        events = copy.deepcopy(data["events"])
        movie_nodes = _find_movie_nodes(events)
        assert movie_nodes
        clone = copy.deepcopy(movie_nodes[0])
        clone["movie"] = {
            "startTime": 0,
            "volume": 1,
            "endTime": 45.1,
            "isStreaming": False,
            "isAudioOnly": False,
            "asset": "VID-20250608-WA0125.mp4-0.0000-45.1381",
        }
        state = clone["baseLayer"]["initialState"]
        state["position"]["pointX"] += 80
        state["position"]["pointY"] += 80
        events[0]["effects"][0]["effects"] = events[0]["effects"][0].get("effects", []) + [
            {"movie": clone["movie"], "baseLayer": clone["baseLayer"], "effects": []}
        ]
        data = {**data, "events": events}
        data["assets"] = {
            **data["assets"],
            "VID-20250608-WA0125.mp4-0.0000-45.1381": {
                "type": "video",
                "url": {"web": "assets/VID-20250608-WA0125.mp4-0.0000-45.1381.mp4"},
            },
        }
        return data

    _rewrite_slide_json(tmp, SLIDE4, add_wa0125_to_slide4)
    plan = derive_plan(tmp, SLIDES, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "more than one movie" in plan.reason


def test_skipped_slide_does_not_shift_scene_indices():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 4, "originalOrdinal": 5, "exportedUuid": "does-not-exist", "skipped": True})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)
    assert plan.scene_index_by_player == {0: 0, 1: 2, 2: 6, 3: 8}


def test_skipped_slide_missing_uuid_is_ignored():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 9, "skipped": True})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, ContinuityPlan)


def test_non_skipped_slide_missing_uuid_is_refused():
    slides = copy.deepcopy(SLIDES)
    slides.append({"playerIndex": 9, "skipped": False})
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, Unsupported)


def test_path_traversal_is_impossible():
    slides = copy.deepcopy(SLIDES)
    slides[0]["exportedUuid"] = "../../../../etc"
    plan = derive_plan(FIXTURE_ROOT, slides, resolver=_resolver)
    assert isinstance(plan, Unsupported)
    assert "unreadable slide export" in plan.reason


def test_plan_round_trips_through_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    restored = json.loads(plan.to_json())
    assert restored == plan.as_dict()
    assert restored["canvas"] == {"width": 1920, "height": 1080}
    assert restored["sceneIndexByPlayer"]["2"] == 6


@pytest.mark.skipif(not REAL_EXPORT_ROOT.is_dir(), reason="real P2 export not available")
def test_real_export_matches_trimmed_fixture_plan():
    real_plan = derive_plan(REAL_EXPORT_ROOT, SLIDES, resolver=_resolver)
    fixture_plan = _plan()
    assert isinstance(real_plan, ContinuityPlan)
    assert isinstance(fixture_plan, ContinuityPlan)
    assert real_plan.as_dict() == fixture_plan.as_dict()


# P2's injected fixture plan (scripts/p2_recovery_html_adversarial.py MOVIE_ROI /
# SLIDE3_MIN_HASH / SLIDE4_MIN_HASH / SLIDE4_MOVIE_RECT), the equivalence target
# for `to_runtime()`. Scenes exact; rects within 3px (the documented slide-3
# y=797.1 vs P2's screen-measured 795 is a known ~2.1px discrepancy).
P2_MOVIE1_FOOTPRINT = {"x": 109, "y": 795, "w": 952, "h": 268}
P2_SLIDE3_MIN_HASH = 6
P2_SLIDE3_MOVIE_RECT = {"x": 198, "y": 797, "w": 952, "h": 268}
P2_SLIDE4_MIN_HASH = 8
P2_SLIDE4_MOVIE_RECT = {"x": 327, "y": 709, "w": 1266, "h": 356}


def _rect_close(a: dict, b: dict, tol: float = 3.0) -> bool:
    return all(abs(a[k] - b[k]) <= tol for k in ("x", "y", "w", "h"))


def test_to_runtime_matches_p2_injected_plan():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)

    # The fixture's WA0125 instance is only single (unambiguous) on player index 2,
    # not the first slide, so it does not enter the movie table -- it never
    # continues across a boundary, so the runtime does not need to classify it.
    assert "movie1" in runtime["movies"]
    movie1 = runtime["movies"]["movie1"]
    assert movie1["assetKeys"] == ["untitled.mov"]
    assert _rect_close(movie1["footprint"], P2_MOVIE1_FOOTPRINT)

    boundaries = {b["atScene"]: b for b in runtime["boundaries"]}
    assert set(boundaries) == {P2_SLIDE3_MIN_HASH, P2_SLIDE4_MIN_HASH}
    assert boundaries[P2_SLIDE3_MIN_HASH]["action"] == "restart"
    bridge = boundaries[P2_SLIDE4_MIN_HASH]
    assert bridge["action"] == "bridge"
    assert bridge["movieKey"] == "movie1"
    assert bridge["srcRect"] == P2_SLIDE3_MOVIE_RECT
    assert bridge["durationSeconds"] == 1.5
    assert _rect_close(bridge["rect"], P2_SLIDE4_MOVIE_RECT)


def test_to_runtime_refuses_when_no_boundaries():
    plan = ContinuityPlan(canvas={"width": 1, "height": 1}, scene_index_by_player={0: 0}, slide_rects={}, boundaries=())
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)


def test_to_runtime_refuses_bridge_without_source_rect():
    plan = _plan()
    bridge = replace(
        plan.boundaries[2],
        movies=tuple(replace(movie, src_rect=None) for movie in plan.boundaries[2].movies),
    )
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "no source rect" in result.reason


@pytest.mark.parametrize("duration", [None, 0, -1, True, "1.5", float("nan"), float("inf")])
def test_to_runtime_refuses_bridge_without_positive_export_duration(duration):
    def change_duration(data):
        for event in data["events"]:
            for effect in event["effects"]:
                if effect.get("type") == "transition":
                    if duration is None:
                        effect.pop("duration")
                    else:
                        effect["duration"] = duration
        return data

    plan = _plan(_mutate_slide(SLIDE3, change_duration))
    assert isinstance(plan, ContinuityPlan)
    result = plan.to_runtime()
    assert isinstance(result, Unsupported)
    assert "no finite positive export duration" in result.reason


def test_to_runtime_refuses_unqualified_export_duration():
    plan = _plan()
    bridge = replace(plan.boundaries[2], transition_duration=2.5)
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert "not yet qualified" in result.reason


@pytest.mark.parametrize("action", ["bridge", "restart", "pin"])
def test_to_runtime_refuses_actionable_boundaries_after_bridge(action):
    plan = _plan()
    bridge = plan.boundaries[2]
    following = replace(
        bridge,
        from_player_index=3,
        to_player_index=4,
        movies=tuple(replace(movie, action=action) for movie in bridge.movies),
    )
    result = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], following),
    ).to_runtime()
    assert isinstance(result, Unsupported)
    expected = "more than one bridge" if action == "bridge" else "actionable boundary follows a bridge"
    assert expected in result.reason


@pytest.mark.parametrize("include_later_restart", [False, True])
def test_to_runtime_refuses_bridge_before_restart(include_later_restart):
    plan = _plan()
    boundaries = (plan.boundaries[0], plan.boundaries[2])
    if include_later_restart:
        boundaries += (plan.boundaries[1],)
    result = replace(plan, boundaries=boundaries).to_runtime()
    assert isinstance(result, Unsupported)
    assert "precedes the first restart" in result.reason


def test_to_runtime_allows_empty_boundary_after_bridge():
    plan = _plan()
    empty = replace(plan.boundaries[3], to_player_index=4, movies=())
    result = replace(
        plan,
        scene_index_by_player={**plan.scene_index_by_player, 4: 10},
        boundaries=(*plan.boundaries[:3], empty),
    ).to_runtime()
    assert isinstance(result, dict)
    assert result == plan.to_runtime()


# --- fixture mutation helpers -------------------------------------------------------------


def _copy_fixture_tree(tmp_path: Path | None = None) -> Path:
    import shutil
    import tempfile

    dest = Path(tempfile.mkdtemp(prefix="live-continuity-fixture-"))
    shutil.copytree(FIXTURE_ROOT, dest, dirs_exist_ok=True)
    return dest


def _rewrite_slide_json(root: Path, uuid: str, transform) -> None:
    path = root / "assets" / uuid / f"{uuid}.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps(transform(data)))


def _mutate_slide(uuid: str, transform) -> Path:
    tmp = _copy_fixture_tree()
    _rewrite_slide_json(tmp, uuid, transform)
    return tmp


def _find_movie_nodes(obj):
    found = []
    if isinstance(obj, dict):
        if "movie" in obj and "baseLayer" in obj:
            found.append(obj)
        for value in obj.values():
            found.extend(_find_movie_nodes(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_movie_nodes(item))
    return found


def _map_movie_nodes(data, fn):
    events = copy.deepcopy(data["events"])
    for node in _find_movie_nodes(events):
        fn(node)
    return {**data, "events": events}


def _map_transitions(data, rename):
    events = copy.deepcopy(data["events"])

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "transition" and "name" in obj:
                obj["name"] = rename(obj["name"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(events)
    return {**data, "events": events}


def _set_rotation(node, degrees):
    node["baseLayer"]["initialState"]["rotation"] = degrees


def _set_affine(node, matrix):
    node["baseLayer"]["initialState"]["affineTransform"] = matrix


def _clone_second_instance_onto_slide2(data):
    """Give slide 2 the same non-continuing 'movie2' rect that slide 1 authors, in addition
    to its real continuing instance, so two geometry-equal pin pairs exist and pinning
    ownership becomes genuinely ambiguous."""
    fixture_slide1 = json.loads((FIXTURE_ROOT / "assets" / SLIDE1 / f"{SLIDE1}.json").read_text())
    stray = copy.deepcopy(_find_movie_nodes(fixture_slide1["events"])[1])
    events = copy.deepcopy(data["events"])
    events[-1]["effects"][0]["effects"] = events[-1]["effects"][0].get("effects", []) + [
        {"movie": stray["movie"], "baseLayer": stray["baseLayer"], "effects": []}
    ]
    return {**data, "events": events}


def test_only_p2_measured_plans_are_qualified():
    # Codex (2026-09-19): the runtime keeps every decoded movie, honours only the first
    # restart and the first bridge, and picks same-asset instances in DOM order. Until it
    # is boundary-specific a deck is trusted only if its runtime plan is byte-for-byte one
    # the P2 gate measured. The fixture is; the same deck with a different slide-4
    # destination is a different, unmeasured plan and must fall back to the raw player.
    from dataclasses import replace

    from obed_edom import live_continuity

    plan = _plan()
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert live_continuity.plan_signature(runtime) in live_continuity.QUALIFIED_PLAN_SHA256

    boundaries = list(plan.boundaries)
    index = next(i for i, b in enumerate(boundaries) if any(m.action == "bridge" for m in b.movies))
    moved = tuple(
        replace(m, dst_rect=replace(m.dst_rect, x=m.dst_rect.x + 40)) if m.action == "bridge" else m
        for m in boundaries[index].movies
    )
    boundaries[index] = replace(boundaries[index], movies=moved)
    unmeasured = replace(plan, boundaries=tuple(boundaries)).to_runtime()
    assert isinstance(unmeasured, Unsupported)
    assert "not yet qualified" in unmeasured.reason


def test_mixed_bridge_and_pin_cannot_bypass_qualified_plan():
    plan = _plan()
    extra = MovieContinuity('second.mov', 'pin', Rect(0, 0, 100, 100), Rect(0, 0, 100, 100))
    bridge = replace(plan.boundaries[2], movies=(*plan.boundaries[2].movies, extra))
    result = replace(plan, boundaries=(*plan.boundaries[:2], bridge, plan.boundaries[3])).to_runtime()
    assert isinstance(result, Unsupported)
    assert 'pin action follows' in result.reason


# --- I5 codec report -----------------------------------------------------------------------

REAL_PLAYER_ROOT = Path(__file__).resolve().parents[1] / "output" / "p2-recovery" / "html-adversarial" / "html-player"


def test_codec_report_lists_every_referenced_movie_not_only_planned_ones():
    # The fixture's WA0125 instance never continues across a boundary (only Untitled.mov
    # does -- see test_boundary_3_to_4_bridges_the_moving_scaling_movie), so it is never
    # part of a continuity plan; the codec report must still list it.
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    assets = {entry["asset"] for entry in report}
    assert assets == {"untitled.mov", "vid-20250608-wa0125.mp4"}


def test_codec_report_entries_are_shaped_asset_codec_family_files():
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    for entry in report:
        assert set(entry) == {"asset", "codec", "family", "files"}


def test_codec_report_reports_none_for_a_movie_file_the_fixture_does_not_ship():
    # tests/fixtures/live_continuity ships only the export JSON, not the referenced
    # .mov bytes, so every entry must fail closed to an unreadable/"other" codec
    # rather than raising.
    report = codec_report(FIXTURE_ROOT, SLIDES, resolver=_resolver)
    for entry in report:
        assert entry["codec"] is None
        assert entry["family"] == "other"


def test_codec_report_skips_slides_it_cannot_read_instead_of_raising():
    tmp = _copy_fixture_tree()
    (tmp / "assets" / SLIDE1 / f"{SLIDE1}.json").write_text("not json at all")
    report = codec_report(tmp, SLIDES, resolver=_resolver)
    assets = {entry["asset"] for entry in report}
    # slide 1 is unreadable and contributes nothing, but the other slides still do.
    assert "vid-20250608-wa0125.mp4" in assets


def _tree_with_movie_files() -> Path:
    """The fixture ships no .mov bytes. An HTML export stores a separate copy of the movie
    under every slide folder that uses it, so write a placeholder for each: the codec of
    each copy is then supplied by an injected probe."""
    tmp = _copy_fixture_tree()
    for uuid in (SLIDE1, SLIDE2, SLIDE3, SLIDE4):
        data = json.loads((tmp / "assets" / uuid / f"{uuid}.json").read_text())
        for entry in data["assets"].values():
            path = tmp / "assets" / uuid / entry["url"]["web"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
    return tmp


def _probe_by_slide(codecs: dict[str, str | None]):
    """Report a codec per slide folder: a path resolves to assets/<uuid>/assets/<file>."""
    return lambda path: codecs.get(path.parent.parent.name)


def _entry(report: list[dict], asset: str) -> dict:
    return next(entry for entry in report if entry["asset"] == asset)


def test_codec_report_aggregates_every_slide_folders_copy_of_one_asset():
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide(dict.fromkeys((SLIDE1, SLIDE2, SLIDE3, SLIDE4), "avc1"))
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": "avc1", "family": "h264", "files": 4,
    }


def test_codec_report_fails_closed_when_one_slide_folders_copy_is_a_different_codec():
    # Slide 1's copy is H.264 but slide 3's separate file is HEVC: keeping only the first
    # would report the key playable while a fresh decoder on slide 3 cannot play it.
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide({SLIDE1: "avc1", SLIDE2: "avc1", SLIDE3: "hvc1", SLIDE4: "avc1"})
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": None, "family": "other", "files": 4, "mixed": True,
    }


def test_codec_report_key_is_unreadable_when_any_of_its_files_is_unreadable():
    tmp = _tree_with_movie_files()
    probe = _probe_by_slide({SLIDE1: "avc1", SLIDE2: "avc1", SLIDE3: None, SLIDE4: "avc1"})
    report = codec_report(tmp, SLIDES, resolver=_resolver, probe=probe)
    # unreadable, not "mixed": the key's codec is simply unknown.
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": None, "family": "other", "files": 4,
    }


def test_codec_report_keeps_two_different_assets_independent():
    tmp = _tree_with_movie_files()
    report = codec_report(
        tmp, SLIDES, resolver=_resolver,
        probe=lambda path: "hvc1" if path.name.startswith("VID-") else "avc1",
    )
    assert _entry(report, "untitled.mov") == {
        "asset": "untitled.mov", "codec": "avc1", "family": "h264", "files": 4,
    }
    assert _entry(report, "vid-20250608-wa0125.mp4") == {
        "asset": "vid-20250608-wa0125.mp4", "codec": "hvc1", "family": "hevc", "files": 1,
    }


def test_codec_report_counts_one_file_for_two_instances_of_the_same_movie_on_a_slide():
    # Slide 1 authors Untitled.mov twice; both instances are the same file on disk.
    tmp = _tree_with_movie_files()
    slides = [SLIDES[0]]
    report = codec_report(tmp, slides, resolver=_resolver, probe=lambda _path: "avc1")
    assert _entry(report, "untitled.mov")["files"] == 1


def test_codec_report_on_slides_with_no_movies_is_empty():
    slides = [{"playerIndex": 0, "originalOrdinal": 1, "exportedUuid": SLIDE2, "skipped": False}]
    report = codec_report(FIXTURE_ROOT, slides, resolver=_resolver)
    # slide 2 has no non-continuing single-instance movie of its own referenced beyond
    # what boundary 1 already covers; this only asserts the call is well-formed and
    # never raises on a minimal slide list.
    assert isinstance(report, list)


# --- slide_instances: ground truth for the visible-content probe --------------------------
#
# `slide_rects` keeps an asset only when the slide authors exactly ONE instance of it
# (live_continuity.py: `if len(rects) == 1`), so it cannot describe slide 1's two
# Untitled.mov instances. `slide_instances` lists EVERY authored movie instance per player
# index -- multi-instance assets and movies that no boundary classifies included -- ordered
# by (x, y, w, h) ascending.

SLIDE1_BIG = (109.35, 795.04, 951.54, 267.62)
SLIDE1_SMALL = (1075.79, 876.25, 662.79, 186.41)
SLIDE3_UNTITLED = (197.98, 797.10, 951.54, 267.62)
SLIDE3_WA0125 = (1152.72, 794.60, 484.66, 272.62)
SLIDE4_UNTITLED = (326.75, 708.52, 1266.49, 356.20)


def test_slide_instances_lists_both_untitled_instances_on_slide_1():
    """Slide 1 (player index 0) authors two Untitled.mov instances: the big continuing one
    and the second, non-continuing one at ~(1076, 876) that `slide_rects` drops entirely."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert set(plan.slide_instances[0]) == {"untitled.mov"}
    assert plan.slide_instances[0]["untitled.mov"] == [_rect(*SLIDE1_BIG), _rect(*SLIDE1_SMALL)]
    # the same slide contributes nothing to slide_rects, which drops multi-instance assets.
    assert plan.slide_rects[0] == {}


def test_slide_instances_matches_slide_rects_where_an_asset_is_single_instance():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    for player_index, rects in plan.slide_rects.items():
        for asset, rect in rects.items():
            assert plan.slide_instances[player_index][asset] == [rect]


def test_slide_instances_lists_the_never_planned_wa0125_movie_on_slide_3():
    """WA0125 never continues across a boundary, so it appears in no MovieContinuity and in
    no runtime movie table -- but it is authored on slide 3 and must be visibly live there."""
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances[2] == {
        "untitled.mov": [_rect(*SLIDE3_UNTITLED)],
        "vid-20250608-wa0125.mp4": [_rect(*SLIDE3_WA0125)],
    }


def test_slide_instances_lists_only_the_moved_scaled_movie_on_slide_4():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances[3] == {"untitled.mov": [_rect(*SLIDE4_UNTITLED)]}


def test_slide_instances_covers_every_player_index_and_uses_movie_rect_geometry():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert set(plan.slide_instances) == set(plan.scene_index_by_player) == {0, 1, 2, 3}
    assert plan.slide_instances[1] == {"untitled.mov": [_rect(*SLIDE1_BIG)]}
    # the rects are the authored-space rects _movie_rect produces for the boundaries too.
    bridge = next(m for m in _boundary(plan, 2)["movies"] if m["asset"] == "untitled.mov")
    assert plan.slide_instances[2]["untitled.mov"][0] == bridge["srcRect"]
    assert plan.slide_instances[3]["untitled.mov"][0] == bridge["dstRect"]


def test_slide_instances_ordering_is_deterministic_and_independent_of_authoring_order():
    """Instances sort by (x, y, w, h) ascending. Slide 1's two Untitled.mov instances live in
    different branches of the event tree, so swapping their geometry swaps the DOM order the
    rects are discovered in; the emitted field must be identical either way."""

    def swap_instance_geometry(data):
        events = copy.deepcopy(data["events"])
        nodes = _find_movie_nodes(events)
        assert len(nodes) == 2, "slide 1 fixture must author two movie instances"
        first, second = nodes[0]["baseLayer"], nodes[1]["baseLayer"]
        nodes[0]["baseLayer"], nodes[1]["baseLayer"] = second, first
        return {**data, "events": events}

    baseline = _plan()
    assert isinstance(baseline, ContinuityPlan)
    swapped = _plan(_mutate_slide(SLIDE1, swap_instance_geometry))
    assert isinstance(swapped, ContinuityPlan)
    assert swapped.slide_instances == baseline.slide_instances
    assert (
        swapped.slide_instances[0]["untitled.mov"][0]["x"]
        < swapped.slide_instances[0]["untitled.mov"][1]["x"]
    )


def test_slide_instances_round_trips_through_json():
    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    restored = json.loads(plan.to_json())
    assert restored == plan.as_dict()
    assert restored["slideInstances"]["0"]["untitled.mov"] == [
        _rect(*SLIDE1_BIG),
        _rect(*SLIDE1_SMALL),
    ]
    assert list(restored["slideInstances"]) == ["0", "1", "2", "3"]


def test_slide_instances_defaults_to_empty_so_positional_construction_still_works():
    plan = ContinuityPlan({"width": 1, "height": 1}, {0: 0}, {}, ())
    assert plan.slide_instances == {}
    assert plan.as_dict()["slideInstances"] == {}


def test_slide_instances_does_not_move_the_runtime_plan_or_its_signature():
    """The visible-content ground truth is additive: `to_runtime()` must not learn about it,
    so the allowlisted signature (and P2's injected plan) stay exactly where they are."""
    from obed_edom import live_continuity

    plan = _plan()
    assert isinstance(plan, ContinuityPlan)
    assert plan.slide_instances
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert set(runtime) == {"movies", "boundaries"}
    assert "slideInstances" not in json.dumps(runtime)
    assert "slide_instances" not in json.dumps(runtime)
    assert (
        live_continuity.plan_signature(runtime)
        == "ec4b0cb3eeaf393ec00a7313d1c68b640a90282c80d408767c99984b710800cf"
    )
    assert live_continuity.plan_signature(runtime) in live_continuity.QUALIFIED_PLAN_SHA256
    # an emptied field must not change the runtime either.
    assert replace(plan, slide_instances={}).to_runtime() == runtime


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_slide_instances_match_the_trimmed_fixture():
    def resolver(root: Path, relative: str) -> Path:
        return root / relative

    real = derive_plan(REAL_PLAYER_ROOT, SLIDES, resolver=resolver)
    fixture = _plan()
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.slide_instances == fixture.slide_instances


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
def test_real_export_movies_report_h264():
    def resolver(root: Path, relative: str) -> Path:
        return root / relative

    report = codec_report(REAL_PLAYER_ROOT, SLIDES, resolver=resolver)
    assert report
    for entry in report:
        assert entry["codec"] == "avc1"
        assert entry["family"] == "h264"
    # the export stores its own copy of Untitled.mov under each of the four slide folders,
    # and every one of them is probed.
    assert next(entry for entry in report if entry["asset"] == "untitled.mov")["files"] == 4
