"""W2 piece 3: knob, suppression, eligibility/orchestration wiring. Keynote-free."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from obed_edom import remap_keynote as rk
from obed_edom.keynote import _build_stat_finalize_script
from test_remap_keynote import _payloads, _touch_paths


def test_zorder_write_mode_default_off():
    assert rk.zorder_write_mode("", offline_mode="on") == "off"


def test_zorder_write_mode_on():
    assert rk.zorder_write_mode("on", offline_mode="on") == "on"


def test_zorder_write_mode_verify():
    assert rk.zorder_write_mode("verify", offline_mode="on") == "verify"


def test_zorder_write_mode_garbage_falls_back_off():
    assert rk.zorder_write_mode("bogus", offline_mode="on") == "off"


def test_zorder_write_mode_forced_off_without_iwa_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name in {"keynote_parser", "obed_edom.iwa_write"}:
            raise ImportError("no iwa extra")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert rk.zorder_write_mode("on", offline_mode="on") == "off"


def test_zorder_write_mode_forced_off_when_offline_write_off():
    assert rk.zorder_write_mode("on", offline_mode="off") == "off"


def _jobs():
    return [{"slide": 1, "childSig": "s1", "groupIndex": 1, "captionPt": 10.0}]


def _badges():
    return [{"slide": 2, "kind": "shape", "index": 1, "x": 0, "y": 0, "w": 10, "h": 10}]


def test_suppress_raises_drops_obed_raise_and_badge_lines(tmp_path):
    dest = tmp_path / "out.key"
    baseline = _build_stat_finalize_script(dest, _jobs(), {}, badge_raises=_badges())
    suppressed = _build_stat_finalize_script(
        dest, _jobs(), {}, badge_raises=_badges(), suppress_raises={1, 2},
    )
    assert "my obedRaiseSlide(1)" in baseline
    assert "my obedBadgeSlide(2," in baseline
    assert "my obedRaiseSlide(1)" not in suppressed
    assert "my obedBadgeSlide(2," not in suppressed


def test_suppress_raises_empty_is_character_identical(tmp_path):
    dest = tmp_path / "out.key"
    a = _build_stat_finalize_script(dest, _jobs(), {}, badge_raises=_badges())
    b = _build_stat_finalize_script(dest, _jobs(), {}, badge_raises=_badges(), suppress_raises=set())
    assert a == b


def test_suppress_raises_partial_leaves_other_slide_lines(tmp_path):
    dest = tmp_path / "out.key"
    jobs = [
        {"slide": 1, "childSig": "s1", "groupIndex": 1, "captionPt": 10.0},
        {"slide": 3, "childSig": "s3", "groupIndex": 1, "captionPt": 10.0},
    ]
    script = _build_stat_finalize_script(dest, jobs, {}, suppress_raises={1})
    assert "my obedRaiseSlide(1)" not in script
    assert "my obedRaiseSlide(3)" in script


def test_suppress_raises_does_not_touch_font_or_dedup_lines(tmp_path):
    dest = tmp_path / "out.key"
    a = _build_stat_finalize_script(dest, _jobs(), {})
    b = _build_stat_finalize_script(dest, _jobs(), {}, suppress_raises={1})
    stat_job_lines_a = [l for l in a.splitlines() if "obedStatJob(" in l]
    stat_job_lines_b = [l for l in b.splitlines() if "obedStatJob(" in l]
    assert stat_job_lines_a == stat_job_lines_b


def test_close_emits_closed_token_after_close_statement():
    script = _build_stat_finalize_script(Path("out.key"), _jobs(), {})
    close_idx = script.index("close theDoc saving yes")
    closed_idx = script.index("set closedOK to 1")
    assert close_idx < closed_idx
    assert '" closed=" & closedOK' in script


@pytest.fixture
def zorder_deck(tmp_path):
    pytest.importorskip("keynote_parser")
    from test_iwa_write import _arch, _member, _shape_super  # noqa: PLC0415

    def _groups(child_a, gid_a, child_b, gid_b, text_a="a", text_b="b"):
        st_a, st_b = child_a * 100, child_b * 100
        return [
            _arch(child_a, "TSWP.ShapeInfoArchive", {
                "isTextBox": False, "super": _shape_super(0, 0, 30, 30),
                "ownedStorage": {"identifier": st_a},
            }),
            _arch(st_a, "TSWP.StorageArchive", {"text": [text_a]}),
            _arch(gid_a, "TSD.GroupArchive", {"super": _shape_super(0, 0, 0, 0)["super"], "children": [{"identifier": child_a}]}),
            _arch(child_b, "TSWP.ShapeInfoArchive", {
                "isTextBox": False, "super": _shape_super(0, 0, 30, 30),
                "ownedStorage": {"identifier": st_b},
            }),
            _arch(st_b, "TSWP.StorageArchive", {"text": [text_b]}),
            _arch(gid_b, "TSD.GroupArchive", {"super": _shape_super(0, 0, 0, 0)["super"], "children": [{"identifier": child_b}]}),
        ]

    slide1_groups = _groups(301, 300, 303, 302)
    slide2_groups = _groups(401, 400, 403, 402)
    slide1 = _arch(100, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": i} for i in [300, 302]],
        "ownedDrawables": [{"identifier": i} for i in [300, 302]],
    })
    slide2 = _arch(110, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": i} for i in [400, 402]],
        "ownedDrawables": [{"identifier": i} for i in [400, 402]],
    })
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 20}]}})
    node1 = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    node2 = _arch(20, "KN.SlideNodeArchive", {"slide": {"identifier": 110}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node1, node2]))
        z.writestr("Index/Slide-100.iwa", _member([slide1, *slide1_groups]))
        z.writestr("Index/Slide-110.iwa", _member([slide2, *slide2_groups]))
    deck = tmp_path / "elig.key"
    deck.write_bytes(buf.getvalue())
    return deck


def test_zorder_eligible_slides_off_mode_returns_empty(zorder_deck):
    from obed_edom import offline_write

    said = []
    result, counts = offline_write.zorder_eligible_slides(
        zorder_deck, "off", {1, 2}, set(),
        [{"slide": 1, "groupIndex": 1, "childSig": "a"}], [], [], said.append,
    )
    assert result == {}
    assert counts["zorderGui"] == []


def test_zorder_eligible_slides_eligible_and_refused_and_unresolved_and_ambiguous(zorder_deck):
    from obed_edom import offline_write

    said = []
    stat_jobs = [
        {"slide": 1, "groupIndex": 1, "childSig": "a"},
        {"slide": 2, "groupIndex": 1, "childSig": "dup"},
        {"slide": 2, "groupIndex": 2, "childSig": "dup"},
    ]
    result, counts = offline_write.zorder_eligible_slides(
        zorder_deck, "on", {1, 2}, set(), stat_jobs, [], [], said.append,
    )
    assert list(result.keys()) == [1]
    assert result[1]["stat"] == ["300"]
    assert counts["zorderGui"] == [2]
    assert counts["zorderUnresolved"] == 2
    assert any("ambiguous" in s for s in said)


def test_zorder_eligible_slides_unresolved_group_index(zorder_deck):
    from obed_edom import offline_write

    said = []
    stat_jobs = [{"slide": 1, "groupIndex": 9, "childSig": "a"}]
    result, counts = offline_write.zorder_eligible_slides(
        zorder_deck, "on", {1}, set(), stat_jobs, [], [], said.append,
    )
    assert result == {}
    assert counts["zorderGui"] == [1]
    assert any("zorderUnresolved" in s for s in said)


def test_zorder_eligible_slides_childsig_mismatch_is_unresolved(zorder_deck):
    from obed_edom import offline_write

    said = []
    stat_jobs = [{"slide": 1, "groupIndex": 1, "childSig": "z"}]
    result, counts = offline_write.zorder_eligible_slides(
        zorder_deck, "on", {1}, set(), stat_jobs, [], [], said.append,
    )
    assert result == {}
    assert counts["zorderGui"] == [1]
    assert any("mismatch" in s for s in said)


def test_zorder_eligible_slides_no_targets_skipped(zorder_deck):
    from obed_edom import offline_write

    said = []
    result, counts = offline_write.zorder_eligible_slides(
        zorder_deck, "on", {1}, set(), [], [], [], said.append,
    )
    assert result == {}
    assert counts["zorderGui"] == []


def test_run_offline_zorder_patches_and_reports_counts(zorder_deck):
    from obed_edom import offline_write

    said = []
    targets = {1: {"stat": ["300"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "on", targets, said.append)
    assert result["zorderSlides"] == 1
    assert result["slides"] == [1]
    assert result["zorderStatRaised"] == 1
    assert result["zorderRefused"] == 0
    assert result["zorderLost"] == 0
    from obed_edom.iwa_write import read_slide_zorder
    z, owned = read_slide_zorder(zorder_deck, 1)
    assert z == ["302", "300"]
    assert owned == z


def test_run_offline_zorder_lost_id_reports_failure_without_raising(zorder_deck):
    from obed_edom import offline_write

    said = []
    targets = {1: {"stat": ["999"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "on", targets, said.append)
    assert result["zorderLost"] == 1
    assert result["failures"] == [(1, "lost id(s) ['999']")]
    assert any("zorderLost(s=1,id=999)" in s for s in said)


def test_run_offline_zorder_lost_counts_one_token_per_missing_id(zorder_deck):
    from obed_edom import offline_write

    said = []
    targets = {1: {"stat": ["997", "998"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "on", targets, said.append)
    assert result["zorderLost"] == 2
    tokens = [s for s in said if s.startswith("zorderLost(")]
    assert len(tokens) == 2


def test_run_offline_zorder_off_mode_is_noop(zorder_deck):
    from obed_edom import offline_write

    said = []
    result = offline_write.run_offline_zorder(zorder_deck, "off", {1: {"stat": ["300"], "badge": []}}, said.append)
    assert result is None


def test_run_offline_zorder_patch_readback_mismatch_reports_failure_without_raising(zorder_deck, monkeypatch):
    from obed_edom import iwa_zorder, offline_write

    monkeypatch.setattr(iwa_zorder, "read_slide_zorder", lambda deck, n: (["bogus"], ["bogus"]))
    said = []
    targets = {1: {"stat": ["300"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "on", targets, said.append)
    assert result["zorderSlides"] == 0
    assert result["zorderRefused"] == 1
    assert len(result["failures"]) == 1
    n, reason = result["failures"][0]
    assert n == 1
    assert "read-back" in reason
    assert any("zorderRefused(s=1" in s for s in said)


def test_run_offline_zorder_verify_mismatch_reports_failure_without_raising(zorder_deck, monkeypatch):
    from obed_edom import iwa_write, offline_write

    monkeypatch.setattr(iwa_write, "read_slide_zorder", lambda deck, n: (["bogus"], ["bogus"]))
    said = []
    targets = {1: {"stat": ["300"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "verify", targets, said.append)
    assert result["zorderSlides"] == 0
    assert result["zorderRefused"] == 1
    assert len(result["failures"]) == 1
    n, reason = result["failures"][0]
    assert n == 1
    assert "verify mismatch" in reason
    assert any("zorderRefused(s=1" in s for s in said)


def test_run_offline_zorder_verify_read_raises_reports_failure_without_raising(zorder_deck, monkeypatch):
    from obed_edom import iwa_write, offline_write

    def raising_read(deck, n):
        raise ValueError("slide index out of range")

    monkeypatch.setattr(iwa_write, "read_slide_zorder", raising_read)
    said = []
    targets = {1: {"stat": ["300"], "badge": []}}
    result = offline_write.run_offline_zorder(zorder_deck, "verify", targets, said.append)
    assert result["zorderSlides"] == 0
    assert result["zorderRefused"] == 1
    assert len(result["failures"]) == 1
    n, reason = result["failures"][0]
    assert n == 1
    assert "verify read failed" in reason
    assert any("zorderRefused(s=1" in s for s in said)


def _wire_zorder_remap(
    monkeypatch, rk, *, child_resize, badge_raises, stat_finalize_ok=True, stat_finalize_closed=True,
):
    """Stubs the Keynote-facing calls so `rk.remap_keynote` runs its real orchestration
    (suppression, export_dir threading, the pass-2 ok+closed gate) without Keynote."""
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.setenv("OBED_AS_GEOMETRY", "on")

    def fake_plan(*a, **k):
        report = k.get("child_resize_report")
        if report is not None:
            report.extend(child_resize)
        badges = k.get("badge_raise_report")
        if badges is not None:
            badges.extend(badge_raises)
        return []

    monkeypatch.setattr(rk, "plan_payload_transforms", fake_plan)
    monkeypatch.setattr(
        rk, "recipe_for",
        lambda wall, template: {
            "source": "test", "mapSrc": "src", "mapDst": "dst",
            "destWidth": 1920, "destHeight": 1080, "characterStyles": [],
        },
    )
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 0, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0})
    monkeypatch.setattr(rk, "read_template_stat_sizes", lambda *a, **k: {})
    monkeypatch.setattr(rk.offline_write, "_offline_write_slides", lambda *a, **k: {1})
    monkeypatch.setattr(rk.offline_write, "run_offline_write", lambda *a, **k: {"refused": []})

    def fake_eligible(dest, mode, offline_slides, refused, stat_jobs, badge_rows, transform_dicts, say):
        counts = {"zorderUnresolved": 0, "zorderRefused": 0, "zorderGui": []}
        if mode == "off":
            return {}, counts
        targets: dict[int, dict[str, list[str]]] = {}
        for j in stat_jobs:
            targets.setdefault(int(j["slide"]), {"stat": [], "badge": []})["stat"].append("statX")
        for r in badge_rows:
            targets.setdefault(int(r["slide"]), {"stat": [], "badge": []})["badge"].append("badgeX")
        return targets, counts

    def fake_run_offline_zorder(dest, mode, targets_by_slide, say):
        if mode == "off" or not targets_by_slide:
            return None
        return {
            "mode": mode, "slides": sorted(targets_by_slide), "zorderSlides": len(targets_by_slide),
            "zorderStatRaised": 0, "zorderBadgeRaised": 0, "zorderNoop": 0,
            "zorderRefused": 0, "zorderLost": 0, "failures": [],
        }

    monkeypatch.setattr(rk.offline_write, "zorder_eligible_slides", fake_eligible)
    monkeypatch.setattr(rk.offline_write, "run_offline_zorder", fake_run_offline_zorder)

    stat_finalize_calls = []

    def fake_stat_finalize(dest, jobs, size_map, export_dir=None, group_removes=None,
                            badge_raises=None, suppress_raises=None):
        stat_finalize_calls.append(
            {"export_dir": export_dir, "suppress_raises": suppress_raises}
        )
        return {
            "ok": stat_finalize_ok, "closed": stat_finalize_closed,
            "done": 0, "jobs": 0, "exported": False,
        }

    monkeypatch.setattr(rk, "_run_stat_finalize", fake_stat_finalize)
    return stat_finalize_calls


def test_orchestration_suppress_raises_equals_slides_patched(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    stat_finalize_calls = _wire_zorder_remap(monkeypatch, rk, child_resize=child_resize, badge_raises=[])
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    info = rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload, log=lambda m: None,
    )

    assert stat_finalize_calls[0]["suppress_raises"] == set(info["zorderWrite"]["slides"])
    assert stat_finalize_calls[0]["export_dir"] is None


def test_orchestration_export_dir_threaded_iff_knob_on(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "off")
    stat_finalize_calls = _wire_zorder_remap(monkeypatch, rk, child_resize=[], badge_raises=[{
        "slide": 1, "kind": "shape", "index": 1, "x": 0, "y": 0, "w": 1, "h": 1,
    }])
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        export_dir=tmp_path / "previews", log=lambda m: None,
    )

    assert stat_finalize_calls[0]["export_dir"] == (tmp_path / "previews").expanduser().resolve()


def test_orchestration_export_dir_folded_to_none_when_knob_on(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    stat_finalize_calls = _wire_zorder_remap(monkeypatch, rk, child_resize=child_resize, badge_raises=[])
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        export_dir=tmp_path / "previews", log=lambda m: None,
    )

    assert stat_finalize_calls[0]["export_dir"] is None


def test_orchestration_post_pass2_refusal_raises(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    _wire_zorder_remap(monkeypatch, rk, child_resize=child_resize, badge_raises=[])
    monkeypatch.setattr(
        rk.offline_write, "zorder_eligible_slides",
        lambda *a, **k: ({1: {"stat": ["x"], "badge": []}}, {
            "zorderUnresolved": 0, "zorderRefused": 0, "zorderGui": [],
        }),
    )

    def fake_run_offline_zorder(dest, mode, targets_by_slide, say):
        return {
            "mode": "on", "slides": [], "zorderSlides": 0, "zorderStatRaised": 0,
            "zorderBadgeRaised": 0, "zorderNoop": 0, "zorderRefused": 1, "zorderLost": 0,
            "failures": [(1, "slide archive not decoded post-pass-2")],
        }

    monkeypatch.setattr(rk.offline_write, "run_offline_zorder", fake_run_offline_zorder)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()
    said = []

    with pytest.raises(RuntimeError, match="suppressed slide"):
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload, log=said.append,
        )

    detail_lines = [s for s in said if s.startswith("Stat zorder detail:")]
    assert len(detail_lines) == 1


def test_orchestration_two_lost_ids_emits_detail_then_raises(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    _wire_zorder_remap(monkeypatch, rk, child_resize=child_resize, badge_raises=[])
    monkeypatch.setattr(
        rk.offline_write, "zorder_eligible_slides",
        lambda *a, **k: ({1: {"stat": ["997", "998"], "badge": []}}, {
            "zorderUnresolved": 0, "zorderRefused": 0, "zorderGui": [],
        }),
    )
    monkeypatch.setattr(
        rk.offline_write, "run_offline_zorder",
        lambda *a, **k: {
            "mode": "on", "slides": [], "zorderSlides": 0, "zorderStatRaised": 0,
            "zorderBadgeRaised": 0, "zorderNoop": 0, "zorderRefused": 1, "zorderLost": 2,
            "failures": [(1, "lost id(s) ['997', '998']")],
        },
    )
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()
    said = []

    with pytest.raises(RuntimeError, match="suppressed slide"):
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload, log=said.append,
        )

    detail_lines = [s for s in said if s.startswith("Stat zorder detail:")]
    assert len(detail_lines) == 1
    assert "zorderLost=2" in detail_lines[0]


def test_orchestration_pass2_failure_skips_patch(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    _wire_zorder_remap(
        monkeypatch, rk, child_resize=child_resize, badge_raises=[], stat_finalize_ok=False,
    )
    patch_calls = []
    monkeypatch.setattr(
        rk.offline_write, "run_offline_zorder",
        lambda *a, **k: patch_calls.append(a) or None,
    )
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    with pytest.raises(RuntimeError, match="pass 2"):
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload, log=lambda m: None,
        )
    assert patch_calls == []


def test_orchestration_ok_but_not_closed_skips_patch_and_raises(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    _wire_zorder_remap(
        monkeypatch, rk, child_resize=child_resize, badge_raises=[],
        stat_finalize_ok=True, stat_finalize_closed=False,
    )
    patch_calls = []
    monkeypatch.setattr(
        rk.offline_write, "run_offline_zorder",
        lambda *a, **k: patch_calls.append(a) or None,
    )
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    with pytest.raises(RuntimeError, match="pass 2"):
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload, log=lambda m: None,
        )
    assert patch_calls == []


def test_orchestration_emits_single_merged_stat_zorder_detail_line(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.setenv("OBED_ZORDER_WRITE", "on")
    child_resize = [{"slide": 1, "groupIndex": 1, "childSig": "a"}]
    _wire_zorder_remap(monkeypatch, rk, child_resize=child_resize, badge_raises=[])
    monkeypatch.setattr(
        rk.offline_write, "zorder_eligible_slides",
        lambda *a, **k: ({1: {"stat": ["statX"], "badge": []}}, {
            "zorderUnresolved": 0, "zorderRefused": 1, "zorderGui": [],
        }),
    )
    monkeypatch.setattr(
        rk.offline_write, "run_offline_zorder",
        lambda *a, **k: {
            "mode": "on", "slides": [1], "zorderSlides": 1, "zorderStatRaised": 1,
            "zorderBadgeRaised": 0, "zorderNoop": 0, "zorderRefused": 0, "zorderLost": 0,
        },
    )
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()
    said = []

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload, log=said.append,
    )

    detail_lines = [s for s in said if s.startswith("Stat zorder detail:")]
    assert len(detail_lines) == 1
    assert "zorderRefused=1" in detail_lines[0]
