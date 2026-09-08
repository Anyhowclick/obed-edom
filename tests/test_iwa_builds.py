"""Pure-function tests for obed_edom.iwa_builds -- no Keynote, no deck I/O.

build_identity/plan_build_patch/verify_builds operate on already-decoded per-slide
dicts (the shape deck_builds returns), so these tests build that shape by hand. A
real-deck read-through of deck_builds itself is exercised in test_iwa_write.py's
patch_slide_builds tests (via _build_builds_deck) and test_iwa_runs.py's
attach_slide_builds test.

``_build``'s ``chunk_order``/``chunk_referent`` default to an all-zero, all-True
degenerate chunk (one per chunk id) for fixtures that don't care about render
order -- the sort's stable secondary key (source ``builds`` index) then reproduces
pre-D8 ordering, so tests that predate the chunk-order fix keep their expectations
unchanged.
"""
from __future__ import annotations

from obed_edom.iwa_builds import build_identity, plan_build_patch, verify_builds


def _build(
    build_id,
    effect,
    kind="shape",
    kind_index=0,
    animation_type="In",
    identity=None,
    chunk_ids=None,
    chunk_order=None,
    chunk_referent=None,
):
    ids = chunk_ids if chunk_ids is not None else [f"c{build_id}"]
    return {
        "buildId": build_id,
        "chunkIds": ids,
        "chunkOrder": chunk_order if chunk_order is not None else [0] * len(ids),
        "chunkReferent": chunk_referent if chunk_referent is not None else [True] * len(ids),
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


def test_plan_build_patch_orders_survivors_by_source_chunk_order():
    # Source's builds array is [dissolve(idx0), wipe(idx1)], but its OWN
    # buildChunks positions disagree -- wipe sits at chunk 0, dissolve at chunk 1.
    # D8: buildChunks is Keynote's render timeline, builds an unordered owning
    # set; real source slides disagree like this 84% of the time (38/45 SRC).
    # Output is paste-scrambled (dissolve first, arbitrary chunk ids).
    src = {
        1: {
            "builds": [
                _build(
                    "s_dissolve", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_cd"], chunk_order=[1], chunk_referent=[False],
                ),
                _build(
                    "s_wipe", "apple:wipe-iris", identity=("image", "B"),
                    chunk_ids=["s_cw"], chunk_order=[0], chunk_referent=[True],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                _build("o_dissolve", "apple:dissolve", identity=("text", "A"), chunk_ids=["cd"]),
                _build("o_wipe", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cw"]),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    assert plan["builds"] == ["o_wipe", "o_dissolve"]
    assert plan["buildChunks"] == ["cw", "cd"]
    # This is exactly the shipped defect: ordering by source BUILDS index instead
    # of source CHUNK position produced ["cd", "cw"] in production. Must not recur.
    assert plan["buildChunks"] != ["cd", "cw"]


def test_plan_build_patch_orders_a_duplicate_key_shortfall_survivor_by_chunk_order():
    """Gate-integrity nit F1: when a key has >=2 source occurrences (duplicate
    identity/effect/animationType) and the output only partially survived, zip()
    paired survivors by BUILDS-array order, not chunk order -- so it could pick a
    DIFFERENT survivor than verify_builds' _restricted (which always keeps the
    chunk-order-earliest occurrences of a duplicate key). That mismatch lets the
    post-write order gate raise on a slide that was actually written correctly.
    Fixture: source builds array is [A@chunk2, B@chunk1, A@chunk0] -- duplicate key
    A, with the correct/earliest-chunk-order A LAST in the builds array; output
    legitimately lost one A (only one A survives the paste)."""
    src = {
        1: {
            "builds": [
                _build(
                    "s_a_late", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca_late"], chunk_order=[2], chunk_referent=[False],
                ),
                _build(
                    "s_b", "apple:wipe-iris", identity=("image", "B"),
                    chunk_ids=["s_cb"], chunk_order=[1], chunk_referent=[False],
                ),
                _build(
                    "s_a_early", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca_early"], chunk_order=[0], chunk_referent=[True],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                _build("o_a", "apple:dissolve", identity=("text", "A"), chunk_ids=["ca"]),
                _build("o_b", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cb"]),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    # Correct: o_a is matched against the chunk-order-EARLIEST source A (chunk 0),
    # so it sorts before o_b (chunk 1) -- agreeing with verify_builds' _restricted.
    assert plan["builds"] == ["o_a", "o_b"]
    # Pre-fix: zip() paired by builds-array order (s_a_late, index 0) instead, whose
    # chunkOrder is 2 -- sorting on that put o_b (chunk 1) first, disagreeing with
    # _restricted and raising the post-write order gate on a correct write.
    assert plan["builds"] != ["o_b", "o_a"]


def test_plan_build_patch_writes_the_builds_array_in_the_same_order_as_buildchunks():
    # Same disagreeing fixture: the builds array must mirror buildChunks' emission
    # order (first-appearance order of chunk owners), NOT the source's own builds
    # order [dissolve, wipe] -- that mismatch is an expected, correct consequence
    # of the fix (any builds-array census will now call these slides "reordered").
    src = {
        1: {
            "builds": [
                _build(
                    "s_dissolve", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_cd"], chunk_order=[1], chunk_referent=[False],
                ),
                _build(
                    "s_wipe", "apple:wipe-iris", identity=("image", "B"),
                    chunk_ids=["s_cw"], chunk_order=[0], chunk_referent=[True],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                _build("o_dissolve", "apple:dissolve", identity=("text", "A"), chunk_ids=["cd"]),
                _build("o_wipe", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cw"]),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    assert plan["builds"] == ["o_wipe", "o_dissolve"]
    assert plan["builds"] != ["o_dissolve", "o_wipe"]


def test_plan_build_patch_reports_a_headless_chain_when_the_source_head_is_missing():
    # Source's chunk 0 (a referent chain head) belongs to build s_a; the output
    # never got a partner for it (only s_b survived the paste). Ordering cannot
    # repair this -- it WARNs via "chainHeadless", it never halts the plan.
    src = {
        1: {
            "builds": [
                _build(
                    "s_a", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca"], chunk_order=[0], chunk_referent=[True],
                ),
                _build(
                    "s_b", "apple:wipe-iris", identity=("image", "B"),
                    chunk_ids=["s_cb"], chunk_order=[1], chunk_referent=[False],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o_b", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cb"])],
            "transition": None,
        }
    }
    result = plan_build_patch(src, out, [1])
    assert result["report"][0]["chainHeadless"] == "survivors"
    assert result["plans"]["sid1"]["builds"] == ["o_b"]


def test_plan_build_patch_reports_a_headless_chain_the_source_itself_has():
    # The source's own chunk 0 is non-referent -- the source starts mid-chain, so
    # nothing our patch does can be right or wrong here; it just WARNs why.
    src = {
        1: {
            "builds": [
                _build(
                    "s_a", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca"], chunk_order=[0], chunk_referent=[False],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o_a", "apple:dissolve", identity=("text", "A"), chunk_ids=["ca"])],
            "transition": None,
        }
    }
    result = plan_build_patch(src, out, [1])
    assert result["report"][0]["chainHeadless"] == "source"
    assert result["plans"]["sid1"]["builds"] == ["o_a"]


def test_plan_build_patch_reports_a_headless_chain_when_the_emitted_fields_disagree():
    # The source's chunk-0 build IS a referent chain head and it DID survive the
    # paste (matched_src_indices covers it) -- but the matched OUTPUT build's own
    # chunkReferent field says its first chunk is not a chain head. Neither
    # "source" nor "survivors" fits; this is the "fields" cause -- gate-integrity
    # nit F3.
    src = {
        1: {
            "builds": [
                _build(
                    "s_a", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca"], chunk_order=[0], chunk_referent=[True],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                _build(
                    "o_a", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["ca"], chunk_referent=[False],
                )
            ],
            "transition": None,
        }
    }
    result = plan_build_patch(src, out, [1])
    assert result["report"][0]["chainHeadless"] == "fields"
    assert result["plans"]["sid1"]["builds"] == ["o_a"]


def test_plan_build_patch_reports_a_headless_chain_when_the_head_owner_is_unresolved():
    # No source build claims chunk position 0 at all -- this models deck_builds
    # having dropped chunk 0's owner entirely (its drawable never resolved), a
    # silent blind spot before this branch existed. Chunk 1 IS claimed, so a
    # chunk-render system clearly exists on this slide; head_src_index staying
    # None here is a genuine "can't diagnose the head" case, not "no chunks at
    # all" -- gate-integrity wording nit on iwa_builds.py:227-233.
    src = {
        1: {
            "builds": [
                _build(
                    "s_b", "apple:wipe-iris", identity=("image", "B"),
                    chunk_ids=["s_cb"], chunk_order=[1], chunk_referent=[False],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o_b", "apple:wipe-iris", identity=("image", "B"), chunk_ids=["cb"])],
            "transition": None,
        }
    }
    result = plan_build_patch(src, out, [1])
    assert result["report"][0]["chainHeadless"] == "unresolved"


def test_plan_build_patch_does_not_flag_a_chain_it_actually_anchors():
    # Healthy path: source chunk 0 is a referent head, its build survived, and the
    # emitted first chunk is referent too -- no "chainHeadless" key at all (guards
    # against an always-on flag).
    src = {
        1: {
            "builds": [
                _build(
                    "s_a", "apple:dissolve", identity=("text", "A"),
                    chunk_ids=["s_ca"], chunk_order=[0], chunk_referent=[True],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o_a", "apple:dissolve", identity=("text", "A"), chunk_ids=["ca"])],
            "transition": None,
        }
    }
    report = plan_build_patch(src, out, [1])["report"][0]
    assert "chainHeadless" not in report


def test_plan_build_patch_reports_an_ambiguous_pairing_group():
    dup = ("shape", "dup")
    solo = ("text", "solo")
    src = {
        1: {
            "builds": [
                _build("s1", "apple:bc-drop", identity=dup, chunk_order=[0], chunk_referent=[True]),
                _build("s2", "apple:bc-drop", identity=dup, chunk_order=[1], chunk_referent=[False]),
                _build("s3", "apple:dissolve", identity=solo, chunk_order=[2], chunk_referent=[False]),
                _build("s4", "apple:dissolve", identity=solo, chunk_order=[3], chunk_referent=[False]),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                # dup: 2 source / 2 output -- genuinely ambiguous, counts.
                _build("o1", "apple:bc-drop", identity=dup, chunk_ids=["c1"]),
                _build("o2", "apple:bc-drop", identity=dup, chunk_ids=["c2"]),
                # solo: 2 source / 1 output -- not ambiguous, zip() has only one
                # choice, must NOT count.
                _build("o3", "apple:dissolve", identity=solo, chunk_ids=["c3"]),
            ],
            "transition": None,
        }
    }
    report = plan_build_patch(src, out, [1])["report"][0]
    assert report["ambiguousPairs"] == 1


def test_plan_build_patch_keeps_a_multi_chunk_builds_chunks_together():
    # o_multi owns two chunks; they must stay adjacent in the emitted buildChunks,
    # never interleaved with o_single's chunk in between.
    src = {
        1: {
            "builds": [
                _build(
                    "s_multi", "apple:bc-zoom-big", identity=("group", "X"),
                    chunk_ids=["s_c0", "s_c1"], chunk_order=[0, 1], chunk_referent=[True, False],
                ),
                _build(
                    "s_single", "apple:dissolve", identity=("text", "Y"),
                    chunk_ids=["s_c2"], chunk_order=[2], chunk_referent=[False],
                ),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "slideId": "sid1",
            "builds": [
                # paste-scrambled: single-chunk build listed first in the output
                _build("o_single", "apple:dissolve", identity=("text", "Y"), chunk_ids=["cy"]),
                _build("o_multi", "apple:bc-zoom-big", identity=("group", "X"), chunk_ids=["cx0", "cx1"]),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out, [1])["plans"]["sid1"]
    assert plan["builds"] == ["o_multi", "o_single"]
    assert plan["buildChunks"] == ["cx0", "cx1", "cy"]


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


def test_plan_build_patch_keeps_a_sparkle_that_arrives_with_the_paste():
    """plan-sparkle-hide.md Sec.1: once a coincident build-twin is planned as a paste
    (map_remap.coincident_duplicate_ids's build exemption), its build key is distinct
    from the base copy's (different effect, same identity) -- both survive with no
    build-creation capability needed. If the paste never carries the twin (output has
    only the base copy), no KLNSparkle is invented for it."""
    identity = ("group", "183\nCHC Churches")
    src = {
        1: {
            "builds": [
                _build("s1", "apple:bc-zoom-big", kind="group", kind_index=0, identity=identity),
                _build("s2", "com.apple.iWork.Keynote.KLNSparkle", kind="group", kind_index=5, identity=identity),
            ],
            "transition": None,
        }
    }
    out_both = {
        1: {
            "slideId": "sid1",
            # scrambled vs. source builds order -- both source builds share a
            # degenerate chunk order (untested here), so the sort falls back to
            # source builds-array index; ordering must come from the source, not
            # the paste
            "builds": [
                _build("o2", "com.apple.iWork.Keynote.KLNSparkle", kind="group", kind_index=5, identity=identity),
                _build("o1", "apple:bc-zoom-big", kind="group", kind_index=0, identity=identity),
            ],
            "transition": None,
        }
    }
    plan = plan_build_patch(src, out_both, [1])["plans"]["sid1"]
    assert plan["builds"] == ["o1", "o2"]  # both kept, source builds order (chunk order ties)

    out_base_only = {
        1: {
            "slideId": "sid1",
            "builds": [_build("o1", "apple:bc-zoom-big", kind="group", kind_index=0, identity=identity)],
            "transition": None,
        }
    }
    plan2 = plan_build_patch(src, out_base_only, [1])["plans"]["sid1"]
    assert plan2["builds"] == ["o1"]  # no KLNSparkle invented for the missing paste


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


def test_verify_builds_flags_a_reveal_order_difference():
    # Same multiset (dissolve/A, wipe/B) on both sides, but the output's chunk
    # order is swapped relative to the source's.
    src = {
        1: {
            "builds": [
                _build("s1", "apple:dissolve", identity=("text", "A"), chunk_order=[0], chunk_referent=[True]),
                _build("s2", "apple:wipe-iris", identity=("image", "B"), chunk_order=[1], chunk_referent=[False]),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "builds": [
                _build("o1", "apple:dissolve", identity=("text", "A"), chunk_order=[1], chunk_referent=[False]),
                _build("o2", "apple:wipe-iris", identity=("image", "B"), chunk_order=[0], chunk_referent=[True]),
            ],
            "transition": None,
        }
    }
    result = verify_builds(src, out, [1])
    assert result["surplus"] == []
    assert result["order"] == [
        {
            "slide": 1, "at": 0,
            "source": ("apple:dissolve", "In", ("text", "A")),
            "output": ("apple:wipe-iris", "In", ("image", "B")),
        }
    ]


def test_verify_builds_order_ignores_a_pure_shortfall():
    # Source has three builds in chunk order dissolve/A, wipe/B, bc-drop/C.
    # Output only has dissolve/A and bc-drop/C (wipe/B legitimately deleted) --
    # the surviving relative order still matches the source, so this is a pure
    # shortfall, not a reorder, and must stay silent in "order" (this is the
    # false-positive guard keeping slides 122/134/144 quiet).
    src = {
        1: {
            "builds": [
                _build("s1", "apple:dissolve", identity=("text", "A"), chunk_order=[0], chunk_referent=[True]),
                _build("s2", "apple:wipe-iris", identity=("image", "B"), chunk_order=[1], chunk_referent=[False]),
                _build("s3", "apple:bc-drop", identity=("shape", "C"), chunk_order=[2], chunk_referent=[False]),
            ],
            "transition": None,
        }
    }
    out = {
        1: {
            "builds": [
                _build("o1", "apple:dissolve", identity=("text", "A"), chunk_order=[0], chunk_referent=[True]),
                _build("o3", "apple:bc-drop", identity=("shape", "C"), chunk_order=[1], chunk_referent=[False]),
            ],
            "transition": None,
        }
    }
    result = verify_builds(src, out, [1])
    assert result["order"] == []
    assert result["missing"] == [
        {"slide": 1, "effect": "apple:wipe-iris", "animationType": "In", "identity": ("image", "B"), "count": 1},
    ]
