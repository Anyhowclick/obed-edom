"""Pure-function tests for obed_edom.iwa_builds -- no Keynote, no deck I/O.

build_identity/plan_build_patch/verify_builds operate on already-decoded per-slide
dicts (the shape deck_builds returns), so these tests build that shape by hand. A
real-deck read-through of deck_builds itself is exercised in test_iwa_write.py's
patch_slide_builds tests (via _build_builds_deck) and test_iwa_runs.py's
attach_slide_builds test.
"""
from __future__ import annotations

from obed_edom.iwa_builds import build_identity, plan_build_patch, verify_builds


def _build(build_id, effect, kind="shape", kind_index=0, animation_type="In", identity=None, chunk_ids=None):
    return {
        "buildId": build_id,
        "chunkIds": chunk_ids if chunk_ids is not None else [f"c{build_id}"],
        "kind": kind,
        "kindIndex": kind_index,
        "effect": effect,
        "animationType": animation_type,
        "identity": identity if identity is not None else (kind, f"id{kind_index}"),
    }


def test_build_identity_is_geometry_free_per_kind():
    assert build_identity("text", "  Hello   World  ", None, None) == ("text", "Hello World")
    assert build_identity("shape", "Hello", None, None) == ("shape", "Hello")
    assert build_identity("image", None, "photo.png", None) == ("image", "photo.png")
    assert build_identity("movie", None, "clip.mov", None) == ("movie", "clip.mov")
    assert build_identity("group", None, None, "183\nAffiliate") == ("group", "183\nAffiliate")
    assert build_identity("line", None, None, None) == ("line",)
    # Absent identity inputs degrade to an empty string, never None/crash.
    assert build_identity("image", None, None, None) == ("image", "")
    assert build_identity("group", None, None, None) == ("group", "")


def test_plan_build_patch_keeps_min_of_source_and_output_per_key():
    # Source has ONE "bc-drop"/shape build; output (post-paste) has THREE identical
    # (degenerate-identity) copies -- keep exactly 1, drop 2.
    src = {1: {"builds": [_build("s1", "apple:bc-drop")], "transition": None}}
    out = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o1", "apple:bc-drop"), _build("o2", "apple:bc-drop"), _build("o3", "apple:bc-drop")],
            "transition": None,
        }
    }
    result = plan_build_patch(src, out, [1])
    plan = result["plans"]["sid1"]
    assert len(plan["builds"]) == 1
    assert plan["builds"][0] in ("o1", "o2", "o3")
    report = result["report"][0]
    # src's transition is None -- reported and excluded from the write, not guessed.
    assert report == {
        "slide": 1, "kept": 1, "dropped": 2, "retimed": False, "transitionSkipped": "source has none",
    }


def test_plan_build_patch_drops_every_key_absent_from_source():
    # The donor's whole build set (a key the source never had) is dropped entirely.
    src = {1: {"builds": [], "transition": None}}
    out = {1: {"slideId": "sid1", "builds": [_build("o1", "apple:bc-drop")], "transition": None}}
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    assert plan["builds"] == []
    assert plan["buildChunks"] == []


def test_plan_build_patch_orders_survivors_by_matched_source_index():
    # Source order: dissolve(idx0), wipe-iris(idx1). Output paste scrambled the order
    # (wipe-iris first): the kept output ids must come back in SOURCE order.
    src = {
        1: {
            "builds": [
                _build("s_dissolve", "apple:dissolve", identity=("text", "A")),
                _build("s_wipe", "apple:wipe-iris", identity=("image", "B")),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                _build("o_wipe", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cw"]),
                _build("o_dissolve", "apple:dissolve", identity=("text", "A"), chunk_ids=["cd"]),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    assert plan["builds"] == ["o_dissolve", "o_wipe"]
    assert plan["buildChunks"] == ["cd", "cw"]


def test_plan_build_patch_refuses_to_copy_a_referencing_transition():
    referencing = {"attributes": {"customImage": {"identifier": "777"}}}
    src = {1: {"builds": [], "transition": referencing}}
    out = {1: {"slideId": "sid1", "builds": [], "transition": None}}
    result = plan_build_patch(src, out, [1])
    assert result["plans"]["sid1"]["transition"] is None
    assert result["report"][0]["transitionSkipped"] == "holds a reference"


def test_plan_build_patch_reports_and_excludes_a_none_source_transition():
    # Source has no transition at all; the output's own must survive untouched,
    # and the report must say why, not leave a silent, unexplained mismatch.
    out_transition = {"attributes": {"animationAttributes": {"effect": "apple:dissolve", "duration": 0.5}}}
    src = {1: {"builds": [], "transition": None}}
    out = {1: {"slideId": "sid1", "builds": [], "transition": out_transition}}
    result = plan_build_patch(src, out, [1])
    assert result["plans"]["sid1"]["transition"] is None
    report = result["report"][0]
    assert report["transitionSkipped"] == "source has none"
    assert report["retimed"] is False


def test_plan_build_patch_reports_retimed_only_when_transition_actually_changes():
    same = {"attributes": {"animationAttributes": {"effect": "apple:dissolve", "duration": 0.5}}}
    src = {1: {"builds": [], "transition": same}}
    out = {1: {"slideId": "sid1", "builds": [], "transition": dict(same)}}
    report = plan_build_patch(src, out, [1])["report"][0]
    assert report["retimed"] is False

    different = {"attributes": {"animationAttributes": {"effect": "apple:magic-move-implied-motion-path", "duration": 1.2}}}
    src2 = {1: {"builds": [], "transition": different}}
    report2 = plan_build_patch(src2, out, [1])["report"][0]
    assert report2["retimed"] is True


def test_plan_build_patch_reports_a_missing_slide_without_crashing():
    report = plan_build_patch({}, {}, [5])["report"][0]
    assert report == {"slide": 5, "kept": 0, "dropped": 0, "retimed": False, "missing": True}


def test_verify_builds_flags_surplus_and_shortfall_separately():
    src = {
        1: {
            "builds": [_build("s1", "apple:dissolve", identity=("text", "A")), _build("s2", "apple:bc-drop", identity=("shape", "B"))],
            "transition": None,
        }
    }
    # Output is missing the "bc-drop" build (a legitimately deleted object) and has an
    # EXTRA "wipe-iris" build the source never had (a surplus -- would raise the run).
    out = {
        1: {
            "builds": [_build("o1", "apple:dissolve", identity=("text", "A")), _build("o2", "apple:wipe-iris", identity=("image", "C"))],
            "transition": None,
        }
    }
    result = verify_builds(src, out, [1])
    assert result["surplus"] == [{"slide": 1, "effect": "apple:wipe-iris", "animationType": "In", "identity": ("image", "C"), "count": 1}]
    assert result["missing"] == [{"slide": 1, "effect": "apple:bc-drop", "animationType": "In", "identity": ("shape", "B"), "count": 1}]
    assert result["transitions"] == []


def test_verify_builds_flags_transition_mismatch():
    src = {1: {"builds": [], "transition": {"attributes": {"animationAttributes": {"effect": "apple:dissolve", "duration": 0.5}}}}}
    out = {1: {"builds": [], "transition": {"attributes": {"animationAttributes": {"effect": "none", "duration": 1.0}}}}}
    result = verify_builds(src, out, [1])
    assert result["transitions"] == [{"slide": 1, "source": ("apple:dissolve", 0.5), "output": ("none", 1.0)}]


def test_verify_builds_defaults_to_every_slide_in_either_deck():
    src = {1: {"builds": [], "transition": None}, 2: {"builds": [_build("s1", "x")], "transition": None}}
    out = {1: {"builds": [], "transition": None}}
    result = verify_builds(src, out)  # no `slides` -- covers slide 2 even though out lacks it
    assert result["missing"] == [{"slide": 2, "effect": "x", "animationType": "In", "identity": ("shape", "id0"), "count": 1}]
