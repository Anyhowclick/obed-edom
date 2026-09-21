"""Tests for obed_edom.dsk_movie_export: pure helpers, the generated AppleScript, and
a faked live export path. No test may launch Keynote; the autouse fixture below
raises if subprocess.run/Popen is reached without an explicit monkeypatch of the
module's own `_run_osascript`/`_ffprobe`/`_keynote_running` seams.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import obed_edom.dsk_movie_export as dme
from obed_edom.dsk_plan import SlideClass
from obed_edom.map_remap import Rect


def _set(monkeypatch, name, value):
    """Patches `name` on both dsk_movie_export and dsk_live: the seam moved to dsk_live,
    but a caller still resident in dsk_movie_export (e.g. export_slide_clips) resolves it
    via dme's own globals, while a moved caller (e.g. _quit_and_wait_for_exit) resolves it
    via dsk_live's."""
    monkeypatch.setattr(dme, name, value)
    monkeypatch.setattr(dme.dsk_live, name, value)


_REAL_CHECK_LAYOUT_IMPORT_PRECONDITIONS = dme.dsk_live.check_layout_import_preconditions
_REAL_RESOLVE_BLACK_LAYOUT_NAME = dme._resolve_black_layout_name
_REAL_RESOLVE_BLACK_LAYOUT_DONOR = dme._resolve_black_layout_donor


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


@pytest.fixture(autouse=True)
def no_layout_precondition(monkeypatch):
    """`export_slide_clips` resolves and validates the black layout offline (against the
    real, on-disk `DEFAULT_LAYOUT_TEMPLATE`, and the fake FW deck bytes tests write)
    whenever a test omits `layout_template` -- no-ops here so tests that don't care about
    layout import aren't coupled to that file's contents or made to parse fake deck bytes:
    `_resolve_black_layout_name` reports nothing FW-owned (forcing the donor path), and the
    donor/precondition seams pick/accept the first candidate name unconditionally. Tests
    that DO exercise this restore the real functions via `_REAL_CHECK_LAYOUT_IMPORT_PRECONDITIONS`
    and `dme._resolve_black_layout_name`/`dme._resolve_black_layout_donor`."""
    monkeypatch.setattr(dme.dsk_live, "check_layout_import_preconditions", lambda *_a, **_k: None)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", lambda _fw, _candidates: None)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", lambda _tpl, candidates: candidates[0])


# --- ordinal_map -------------------------------------------------------------


def test_ordinal_map_ranks_kept_slides():
    assert dme.ordinal_map({17, 32, 33}) == {17: 1, 32: 2, 33: 3}


def test_ordinal_map_unaffected_by_deck_size():
    # slides {17, 32, 33} of a 63-slide deck map to ordinals {1, 2, 3}
    assert dme.ordinal_map({17, 32, 33}) == {17: 1, 32: 2, 33: 3}


# --- clip_name / require_m4v --------------------------------------------------


def test_clip_name_keyed_by_slide_number():
    assert dme.clip_name("Sermon_PK (GW)", 32) == "Sermon_PK (GW).032.mov"


def test_require_m4v_accepts_m4v():
    p = Path("/tmp/x.m4v")
    assert dme.require_m4v(p) == p


def test_require_m4v_rejects_mov():
    with pytest.raises(ValueError):
        dme.require_m4v(Path("/tmp/x.mov"))


def test_require_m4v_rejects_no_suffix():
    with pytest.raises(ValueError):
        dme.require_m4v(Path("/tmp/x"))


# --- crop_filter ---------------------------------------------------------


def test_crop_filter_basic():
    rect = Rect(100, 50, 800, 400)
    assert dme.crop_filter(rect, 1920, 1080) == "crop=800:400:100:50"


def test_crop_filter_full_frame_is_none():
    rect = Rect(0, 0, 1920, 1080)
    assert dme.crop_filter(rect, 1920, 1080) is None


def test_crop_filter_clamps_negative_origin():
    rect = Rect(-10, -5, 100, 50)
    assert dme.crop_filter(rect, 1920, 1080) == "crop=90:45:0:0"


def test_crop_filter_clamps_overflow():
    rect = Rect(1900, 1070, 100, 100)
    assert dme.crop_filter(rect, 1920, 1080) == "crop=20:10:1900:1070"


def test_crop_filter_degenerate_raises():
    rect = Rect(0, 0, 0, 500)
    with pytest.raises(ValueError, match="Degenerate"):
        dme.crop_filter(rect, 1920, 1080)


def test_crop_filter_explicit_degenerate_off_frame_raises():
    rect = Rect(5000, 5000, 100, 100)
    with pytest.raises(ValueError, match="Degenerate"):
        dme.crop_filter(rect, 1920, 1080)


def test_ffmpeg_process_centre_panel_crop_reaches_shipped_command(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (7680, 1080, 30.0, 8.0))
    captured = {}

    def fake_stage(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", fake_stage)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    w, h = dme._ffmpeg_process(
        raw, dest, crop_rect=dme.CENTRE_PANEL_RECT, wall_w=7680, wall_h=1080, codec="AppleProRes422LT"
    )
    assert (w, h) == (3840, 1080)
    assert "crop=3840:1080:1920:0" in captured["cmd"]


# --- fps_enum_name / CODECS --------------------------------------------------


def test_fps_enum_name_known_rates():
    assert dme.fps_enum_name(30) == "FPS30"
    assert dme.fps_enum_name(23.98) == "FPS2398"
    assert dme.fps_enum_name(59.94) == "FPS5994"


def test_fps_enum_name_rejects_unknown_rate():
    with pytest.raises(ValueError):
        dme.fps_enum_name(48)


def test_fps_rational_matches_named_ntsc_rates():
    assert dme.fps_rational(23.98) == pytest.approx(24000 / 1001)
    assert dme.fps_rational(29.97) == pytest.approx(30000 / 1001)
    assert dme.fps_rational(30) == pytest.approx(30.0)


def test_codecs_matches_sdef_enumerators():
    assert dme.CODECS == {
        "h264",
        "AppleProRes422",
        "AppleProRes422LT",
        "AppleProRes422HQ",
        "AppleProRes422Proxy",
        "AppleProRes4444",
        "HEVC",
    }


def test_expected_duration_removed():
    assert not hasattr(dme, "expected_duration")


# --- script snapshot -------------------------------------------------------


def _jobs():
    return [
        dme._SlideJob(17, 1, dme.CENTRE_PANEL_RECT, Path("/out/Sermon.017.m4v"), Path("/work/tmp.0017.m4v")),
        dme._SlideJob(
            32,
            2,
            dme.CENTRE_PANEL_RECT,
            Path("/out/Sermon.032.m4v"),
            Path("/work/tmp.0032.m4v"),
            delete_ids=(("image", 1),),
        ),
        dme._SlideJob(44, 3, Rect(0, 0, 7680, 1080), Path("/out/Sermon.044.m4v"), Path("/work/tmp.0044.m4v")),
    ]


def _sample_script():
    return dme._build_export_script(
        scratch_path=Path("/Users/x/Desktop/dsk-d3-work/.dsk-export-Sermon/Sermon.key"),
        stem="Sermon",
        layout_template=Path("/Users/x/Desktop/Default Templates/2026_Lower-Thirds (ENG).key"),
        per_slide=_jobs(),
        codec="AppleProRes422LT",
        fps=30,
    )


def test_script_uses_application_id_not_literal_name():
    script = _sample_script()
    assert 'application id "' in script
    assert '"Keynote"' not in script
    assert "tell application \"Keynote\"" not in script


def test_script_has_export_clause_for_each_slide():
    script = _sample_script()
    for job in _jobs():
        assert str(job.tmp) in script


def test_script_export_clause_has_m4v_destination_and_properties():
    script = _sample_script()
    assert "as QuickTime movie with properties" in script
    assert "movie format:native size" in script
    assert "movie codec:AppleProRes422LT" in script
    assert "movie framerate:FPS30" in script
    assert "skipped slides:false" in script
    assert ".m4v\"" in script


def test_script_closes_without_saving():
    script = _sample_script()
    assert "close theDoc saving no" in script


def test_script_has_timeout_clause():
    script = _sample_script()
    assert "with timeout of 3600 seconds" in script
    assert "end timeout" in script


def test_script_has_error_clause_for_exports():
    script = _sample_script()
    assert "on error errMsg number errNum" in script
    assert 'log ("ERR" & tab &' in script


def test_script_deletes_by_keep_list_membership():
    script = _sample_script()
    assert "set keepList to {17, 32, 44}" in script
    assert "if keepList does not contain i then delete slide i of theDoc" in script


def test_script_sets_base_layout_on_kept_slides():
    script = _sample_script()
    assert "set base layout of s to targetLayout" in script


def test_script_verifies_base_layout_before_deleting_donor():
    script = _sample_script()
    delete_donor_idx = script.index("delete donorSlide")
    verify_idx = script.index("base layout verify failed")
    assert delete_donor_idx < verify_idx


def test_script_never_resizes_document():
    # D0/B1: the coal-slide bug was a Keynote canvas resize that rescaled content while the
    # compensating translate stayed in unscaled wall points. The document is now always
    # exported at its own native size; ffmpeg does all cropping afterwards.
    script = _sample_script()
    assert "set width of theDoc" not in script
    assert "set height of theDoc" not in script


def test_script_deletes_non_content_drawables():
    # B2: the scratch slide keeps every drawable the classifier dropped unless the export
    # script deletes them too -- this is what stripped the GW-32 side panel from the clip.
    script = _sample_script()
    assert "      set theObj to image 2 of slide 2" in script
    assert "        if locked of theObj then set locked of theObj to false" in script
    assert "      delete theObj" in script
    delete_idx = script.index("image 2 of slide 2")
    export_idx = script.index("tmp.0032.m4v")
    assert delete_idx < export_idx


def test_script_deletes_route_through_title_body_placeholder_guard():
    # Same Keynote refusal as the assembly script (errNum -10003 on the shape bound as
    # the slide's default title/body item) -- the clip-export scratch script must hide it
    # via title/body showing too, not just log a DELETEFAIL and leave stale content in view.
    script = _sample_script()
    assert "if isTitle then" in script
    assert "is (default title item of slide 2)" in script
    assert "set title showing of slide 2 to false" in script
    assert "set body showing of slide 2 to false" in script


def test_script_raises_on_unaddressable_delete_kind():
    jobs = [
        dme._SlideJob(
            17,
            1,
            dme.CENTRE_PANEL_RECT,
            Path("/out/Sermon.017.m4v"),
            Path("/work/tmp.0017.m4v"),
            delete_ids=(("bogus-kind", 0),),
        )
    ]
    with pytest.raises(ValueError, match="bogus-kind"):
        dme._build_export_script(
            scratch_path=Path("/Users/x/Desktop/dsk-d3-work/.dsk-export-Sermon/Sermon.key"),
            stem="Sermon",
            layout_template=None,
            per_slide=jobs,
            codec="AppleProRes422LT",
            fps=30,
        )


def test_script_no_literal_mov_extension_used_for_export():
    script = _sample_script()
    for line in script.splitlines():
        if "export theDoc" in line:
            assert ".mov" not in line


def test_script_binds_scratch_document_by_stem_or_filename():
    script = _sample_script()
    assert 'name is "Sermon" or name is "Sermon.key"' in script
    assert "set theDoc to open theFile" in script
    assert "set theDoc to document 1" not in script


def test_script_black_layout_uses_explicit_approved_name_list():
    script = _sample_script()
    expected_list = dme._applescript_string_list(dme.DEFAULT_BLACK_LAYOUT_NAMES)
    assert f"set approvedBlackNames to {expected_list}" in script
    assert script.count("lname is in approvedBlackNames") == 2
    for name in dme.DEFAULT_BLACK_LAYOUT_NAMES:
        assert f'set wantLayoutName to "{name}"' in script
    assert "words of" not in script
    assert "begins with" not in script


def test_resolve_black_layout_name_accepts_blank_black_alias(monkeypatch, tmp_path):
    """"Blank Black" is a 2025-template-family alias for the alpha-safe black layout;
    an FW deck owning it exactly must resolve without any template donor/import."""
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    fw_objects = _layout_objects_multi(entries=[("Blank Black", [])])
    monkeypatch.setattr(dme.dsk_live, "_load_deck", lambda _path: (fw_objects, {}, {}))

    assert _REAL_RESOLVE_BLACK_LAYOUT_NAME(fw, dme.DEFAULT_BLACK_LAYOUT_NAMES) == "Blank Black"


def test_resolve_black_layout_name_rejects_non_alias_black_copy(monkeypatch, tmp_path):
    """"BLACK copy" is not one of the approved aliases; owning it alone must not resolve."""
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    fw_objects = _layout_objects_multi(entries=[("BLACK copy", [])])
    monkeypatch.setattr(dme.dsk_live, "_load_deck", lambda _path: (fw_objects, {}, {}))

    assert _REAL_RESOLVE_BLACK_LAYOUT_NAME(fw, dme.DEFAULT_BLACK_LAYOUT_NAMES) is None


def test_script_black_layout_approved_list_refuses_substring_match():
    script = dme._build_export_script(
        scratch_path=Path("/Users/x/Desktop/dsk-d3-work/.dsk-export-Sermon/Sermon.key"),
        stem="Sermon",
        layout_template=None,
        per_slide=_jobs(),
        codec="AppleProRes422LT",
        fps=30,
        black_layout_names=("Black",),
    )
    assert '"Black"' in script
    assert "Blackboard" not in script


# --- _build_dsk_export_script -------------------------------------------------


def _dsk_per_slide():
    return [
        (2, 1, Path("/work/tmp.0002.m4v")),
        (5, 2, Path("/work/tmp.0005.m4v")),
    ]


def _dsk_sample_script():
    return dme._build_dsk_export_script(
        scratch_path=Path("/Users/x/Desktop/dsk-d3-work/.dsk-export-Sermon_DSK/Sermon_DSK.key"),
        per_slide=_dsk_per_slide(),
        codec="AppleProRes422LT",
        fps=30,
    )


def test_dsk_script_uses_application_id_not_literal_name():
    script = _dsk_sample_script()
    assert 'application id "' in script
    assert '"Keynote"' not in script
    assert 'tell application "Keynote"' not in script


def test_dsk_script_has_export_clause_for_each_slide():
    script = _dsk_sample_script()
    for _slide, _ordinal, tmp in _dsk_per_slide():
        assert str(tmp) in script


def test_dsk_script_export_clause_has_m4v_destination_and_properties():
    script = _dsk_sample_script()
    assert "as QuickTime movie with properties" in script
    assert "movie format:native size" in script
    assert "movie codec:AppleProRes422LT" in script
    assert "movie framerate:FPS30" in script
    assert "skipped slides:false" in script
    assert ".m4v\"" in script


def test_dsk_script_deletes_by_keep_list_membership():
    script = _dsk_sample_script()
    assert "set keepList to {2, 5}" in script
    assert "if keepList does not contain i then delete slide i of theDoc" in script


def test_dsk_script_toggles_skipped_per_ordinal():
    script = _dsk_sample_script()
    assert "set skipped of slide 1 of theDoc to false" in script
    assert "set skipped of slide 1 of theDoc to true" in script
    assert "set skipped of slide 2 of theDoc to false" in script
    assert "set skipped of slide 2 of theDoc to true" in script


def test_dsk_script_closes_without_saving():
    script = _dsk_sample_script()
    assert "close theDoc saving no" in script


def test_dsk_script_no_base_layout_set():
    script = _dsk_sample_script()
    assert "set base layout of s to targetLayout" not in script


def test_dsk_script_no_drawable_deletes():
    script = _dsk_sample_script()
    assert "delete theObj" not in script
    assert "locked of theObj" not in script


# --- quit script -------------------------------------------------------------


def test_quit_script_closes_by_stem_or_filename_not_every_document():
    script = dme._quit_script("Sermon", "Sermon.key")
    assert "close every document" not in script
    assert 'close (every document whose name is "Sermon" or name is "Sermon.key")' in script


# --- lock file -----------------------------------------------------------


def test_lock_acquire_writes_pid_and_release_unlocks(tmp_path, monkeypatch):
    lock_path = tmp_path / "keynote.lock"
    _set(monkeypatch, "LOCK_PATH", lock_path)
    fd = dme._acquire_lock()
    assert lock_path.read_text().splitlines()[0] == str(dme.os.getpid())
    dme._release_lock(fd)


def test_lock_second_acquire_contends_on_open_flock(tmp_path, monkeypatch):
    # flock is held per open-file-description, so two independent `_acquire_lock` calls in
    # the same process still contend -- this exercises the real concurrency guard.
    lock_path = tmp_path / "keynote.lock"
    _set(monkeypatch, "LOCK_PATH", lock_path)
    fd1 = dme._acquire_lock()
    with pytest.raises(RuntimeError, match="lock held"):
        dme._acquire_lock()
    dme._release_lock(fd1)
    fd2 = dme._acquire_lock()
    dme._release_lock(fd2)


def test_lock_release_allows_reacquire(tmp_path, monkeypatch):
    lock_path = tmp_path / "keynote.lock"
    _set(monkeypatch, "LOCK_PATH", lock_path)
    fd1 = dme._acquire_lock()
    dme._release_lock(fd1)
    fd2 = dme._acquire_lock()
    dme._release_lock(fd2)


# --- _keynote_pid shares _keynote_running's fallback --------------------------


def test_keynote_pid_uses_same_fallback_as_keynote_running(monkeypatch):
    _set(monkeypatch, "_keynote_pids", lambda: [4242])
    assert dme._keynote_running() is True
    assert dme._keynote_pid() == 4242


def test_keynote_pid_none_when_not_running(monkeypatch):
    _set(monkeypatch, "_keynote_pids", lambda: [])
    assert dme._keynote_running() is False
    assert dme._keynote_pid() is None


# --- _keynote_pids resolution (bundle-executable, not display name) -----------


def test_keynote_pids_matches_by_cfbundleexecutable_via_pgrep(monkeypatch, tmp_path):
    app = tmp_path / "Keynote Creator Studio.app"
    (app / "Contents").mkdir(parents=True)
    monkeypatch.setattr(dme.keynote_app, "app_path", lambda identifier: app)
    monkeypatch.setattr(dme.keynote_app, "executable_name", lambda identifier: "Keynote")

    def fake_run(cmd, **kwargs):
        assert cmd == ["pgrep", "-x", "Keynote"]
        return _FakeCompleted(returncode=0, stdout="4242\n")

    monkeypatch.setattr(dme.subprocess, "run", fake_run)
    assert dme._keynote_pids() == [4242]


def test_keynote_pids_propagates_malformed_bundle_error(monkeypatch):
    def _raise(identifier):
        raise RuntimeError("Missing or invalid CFBundleExecutable")

    monkeypatch.setattr(dme.keynote_app, "executable_name", _raise)
    with pytest.raises(RuntimeError, match="CFBundleExecutable"):
        dme._keynote_pids()


def test_keynote_pids_no_executable_name_raises(monkeypatch):
    monkeypatch.setattr(dme.keynote_app, "executable_name", lambda identifier: None)

    def _forbidden(*a, **k):
        raise AssertionError("must not probe when the executable name is unknown")

    monkeypatch.setattr(dme.subprocess, "run", _forbidden)
    with pytest.raises(RuntimeError, match="not resolvable"):
        dme._keynote_pids()


def test_keynote_running_propagates_no_executable_name_error(monkeypatch):
    monkeypatch.setattr(dme.keynote_app, "executable_name", lambda identifier: None)
    with pytest.raises(RuntimeError, match="not resolvable"):
        dme._keynote_running()


def test_export_slide_clips_refuses_at_preflight_when_keynote_unresolvable(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    _stub_offline_payload(monkeypatch)
    lock_path = tmp_path / "keynote.lock"
    _set(monkeypatch, "LOCK_PATH", lock_path)
    monkeypatch.setattr(dme.keynote_app, "executable_name", lambda identifier: None)

    def _forbidden_copy(src, dest):
        raise AssertionError("must not copy the source deck when Keynote is unresolvable")

    monkeypatch.setattr(dme, "copy_keynote", _forbidden_copy)

    with pytest.raises(RuntimeError, match="not resolvable"):
        dme.export_slide_clips(fw, [17], out_dir)

    assert not lock_path.exists()


def test_keynote_pids_falls_back_to_ps_scan_of_macos_dir(monkeypatch, tmp_path):
    app = tmp_path / "Keynote Creator Studio.app"
    (app / "Contents").mkdir(parents=True)
    monkeypatch.setattr(dme.keynote_app, "app_path", lambda identifier: app)
    monkeypatch.setattr(dme.keynote_app, "executable_name", lambda identifier: "Keynote")

    macos_dir = str(app / "Contents" / "MacOS")
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if cmd[0] == "pgrep":
            return _FakeCompleted(returncode=1, stdout="")
        assert cmd == ["ps", "-axo", "pid=,comm="]
        return _FakeCompleted(
            returncode=0,
            stdout=f"  111 /usr/libexec/some-other-daemon\n  4242 {macos_dir}/Keynote\n",
        )

    monkeypatch.setattr(dme.subprocess, "run", fake_run)
    assert dme._keynote_pids() == [4242]
    assert calls["n"] == 2


def test_keynote_pids_end_to_end_with_fake_plist_and_pgrep(monkeypatch, tmp_path):
    import plistlib

    app = tmp_path / "Keynote Creator Studio.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": "com.apple.Keynote", "CFBundleExecutable": "Keynote"}, handle)

    dme.keynote_app.clear_cache()
    monkeypatch.setattr(dme.keynote_app, "_from_workspace", lambda identifier: None)
    monkeypatch.setattr(dme.keynote_app, "_candidate_apps", lambda: iter([app]))

    def fake_run(cmd, **kwargs):
        assert cmd == ["pgrep", "-x", "Keynote"]
        return _FakeCompleted(returncode=0, stdout="7777\n")

    monkeypatch.setattr(dme.subprocess, "run", fake_run)
    try:
        assert dme._keynote_pids() == [7777]
    finally:
        dme.keynote_app.clear_cache()


# --- _ffprobe fallback ------------------------------------------------------


def test_ffprobe_falls_back_to_ffmpeg_i_when_ffprobe_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme.shutil, "which", lambda name: None)

    class _Proc:
        stderr = "Duration: 00:00:08.43, start: 0.0\nStream #0:0: Video: h264, yuv420p, 1920x1080, 30 fps"

    monkeypatch.setattr(dme.subprocess, "run", lambda *a, **k: _Proc())
    width, height, fps, duration = dme._ffprobe(tmp_path / "x.m4v")
    assert (width, height, fps) == (1920, 1080, 30.0)
    assert duration == pytest.approx(8.43)


def test_ffprobe_rejects_zero_dims(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme.shutil, "which", lambda name: None)

    class _Proc:
        stderr = "Duration: 00:00:00.00, start: 0.0\nStream #0:0: Video: h264, yuv420p, 0x0, 0 fps"

    monkeypatch.setattr(dme.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(RuntimeError):
        dme._ffprobe(tmp_path / "x.m4v")


# --- live path (faked) -----------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_DEFAULT_PAYLOAD_SLIDES = [
    {"number": 17, "items": [{"kind": "shape", "kindIndex": 0}]},
    {"number": 32, "items": [{"kind": "shape", "kindIndex": 0}]},
]


def _stub_offline_payload(monkeypatch, *, slides=None):
    if slides is None:
        slides = _DEFAULT_PAYLOAD_SLIDES
    payload = {"slideWidth": 7680.0, "slideHeight": 1080.0, "slides": list(slides)}
    classes = [
        SlideClass(
            s["number"], "static", 0, 0, tuple((i["kind"], i["kindIndex"]) for i in s["items"]), (), (), None, 0, ()
        )
        for s in slides
    ]
    monkeypatch.setattr(dme, "offline_wall_payload", lambda path: payload)
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: classes)
    monkeypatch.setattr(dme, "attach_group_content_signature", lambda path, payload, **k: None)
    return payload


def _stub_live(monkeypatch, tmp_path, *, keynote_running=False, stub_content_assert=True, payload_slides=None):
    _stub_offline_payload(monkeypatch, slides=payload_slides)
    # Preflight sees `keynote_running`; once we copy the scratch and are about to run the
    # export AppleScript (which `activate`s Keynote), the process is genuinely running --
    # so the teardown quit-guard (which re-checks `_keynote_running`) fires as it would live.
    state = {"running": keynote_running}
    _set(monkeypatch, "_keynote_running", lambda: state["running"])

    def fake_copy_keynote(src, dest):
        state["running"] = True
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"key")
        return dest

    monkeypatch.setattr(dme, "copy_keynote", fake_copy_keynote)
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)
    monkeypatch.setattr(dme._DisplayPoke, "start", lambda self: None)
    monkeypatch.setattr(dme._DisplayPoke, "stop", lambda self: None)
    monkeypatch.setattr(dme._RssWatchdog, "start", lambda self: None)
    monkeypatch.setattr(dme._RssWatchdog, "stop", lambda self: None)
    _set(monkeypatch, "_keynote_pid", lambda: None)

    calls = {"osascript": 0, "bared": []}

    def fake_bare_source_build_ins(deck, targets):
        calls["bared"].append((Path(deck), {n: list(ids) for n, ids in targets.items()}))
        return {"refused": False, "reason": None, "touched": [], "applied": 0}

    monkeypatch.setattr(dme, "bare_source_build_ins", fake_bare_source_build_ins)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls["osascript"] += 1
        text = script_path.read_text()
        if "using terms from" not in text:
            return _FakeCompleted(returncode=1, stderr="bad script")
        if "export theDoc" in text:
            lines = []
            for job in _current_jobs[0]:
                job.tmp.parent.mkdir(parents=True, exist_ok=True)
                job.tmp.write_bytes(b"movie-bytes")
                lines.append(f"OBED\t{job.slide}\t2026-09-10 00:00:00")
            return _FakeCompleted(returncode=0, stderr="\n".join(lines))
        # only the quit script reaches here -- simulate a successful quit.
        state["running"] = False
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (1920, 1080, 30.0, 8.43))

    def fake_ffmpeg_process(raw, dest, *, crop_rect, wall_w, wall_h, codec):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"movie-bytes")
        return 1920, 1080

    monkeypatch.setattr(dme, "_ffmpeg_process", fake_ffmpeg_process)
    if stub_content_assert:
        monkeypatch.setattr(dme, "_assert_clip_covers_frame", lambda *a, **k: None)
    calls["state"] = state
    return calls


_current_jobs: list[list] = [[]]


def _patch_build_export_script_capture(monkeypatch):
    orig = dme._build_export_script

    def wrapper(**kwargs):
        _current_jobs[0] = list(kwargs["per_slide"])
        return orig(**kwargs)

    monkeypatch.setattr(dme, "_build_export_script", wrapper)


def _layout_objects_for_precondition(*, donor_rects, fw_rects, name="Black"):
    """Minimal `KN.ThemeArchive` graph with one layout named `name` -- `donor_rects`
    (in the template) and `fw_rects` (already owned by the FW deck), each a list of
    (x, y, w, h) drawable frames on a 1920x1080 canvas."""
    return _layout_objects_multi(entries=[(name, donor_rects)]), _layout_objects_multi(entries=[(name, fw_rects)])


def _layout_objects_multi(*, entries):
    """`KN.ThemeArchive` graph with one layout per `(name, rects)` in `entries`, each
    `rects` a list of (x, y, w, h) drawable frames on a 1920x1080 canvas. An empty
    `entries` list yields a deck that owns no layouts at all."""
    objects = {
        "theme": {
            "_pbtype": "KN.ThemeArchive",
            "templates": [{"identifier": f"node{i}"} for i in range(len(entries))],
        },
        "show": {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}},
    }
    for i, (name, rects) in enumerate(entries):
        drawables = [{"identifier": f"d{i}_{j}"} for j in range(len(rects))]
        objects[f"node{i}"] = {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": f"slide{i}"}}
        objects[f"slide{i}"] = {"_pbtype": "KN.SlideArchive", "name": name, "drawablesZOrder": drawables}
        for j, (x, y, w, h) in enumerate(rects):
            objects[f"d{i}_{j}"] = {
                "_pbtype": "TSD.ImageArchive",
                "geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}},
            }
    return objects


def test_export_slide_clips_refuses_unsafe_same_named_fw_layout_with_safe_donor(monkeypatch, tmp_path):
    """A safe template donor named "Black" must not save a full-canvas FW-owned "Black"
    layout from being baked into every clip: `export_slide_clips` must run the shared
    offline precondition (restored here to the real implementation) and refuse before
    Keynote is ever launched (`copy_keynote` must not be reached)."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    template = tmp_path / "Donor.key"
    template.write_bytes(b"template")

    donor_objects, fw_objects = _layout_objects_for_precondition(
        donor_rects=[],
        fw_rects=[(-10.0, 0.0, 8000.0, 1080.0)],
    )

    def _dispatched_load_deck(path):
        return (donor_objects, {}, {}) if Path(path) == template else (fw_objects, {}, {})

    _stub_offline_payload(monkeypatch)
    monkeypatch.setattr(dme.dsk_live, "check_layout_import_preconditions", _REAL_CHECK_LAYOUT_IMPORT_PRECONDITIONS)
    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _copy_keynote_forbidden(src, dest):
        raise AssertionError("Keynote must not launch once the precondition refuses")

    monkeypatch.setattr(dme, "copy_keynote", _copy_keynote_forbidden)
    _set(monkeypatch, "_keynote_running", lambda: False)
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)

    with pytest.raises(dme.dsk_live.LayoutImportRefusal, match="not alpha-safe"):
        dme.export_slide_clips(
            fw, [17], out_dir, layout_template=template, black_layout_names=("Black",),
        )


def test_export_slide_clips_uses_fw_owned_alias_absent_from_template(monkeypatch, tmp_path):
    """`black_layout_names` is a list of ALTERNATIVE aliases (any one acceptable), not
    all required: an alpha-safe FW-owned "BLACK BLANK" must proceed even though the
    layout template owns none of the aliases at all -- no import needed or attempted."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    template = tmp_path / "Donor.key"
    template.write_bytes(b"template")

    fw_objects = _layout_objects_multi(entries=[("BLACK BLANK", [])])
    template_objects = _layout_objects_multi(entries=[])

    def _dispatched_load_deck(path):
        return (template_objects, {}, {}) if Path(path) == template else (fw_objects, {}, {})

    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _precondition_forbidden(*a, **k):
        raise AssertionError("no import precondition is needed when the FW deck already owns a safe alias")

    monkeypatch.setattr(dme.dsk_live, "check_layout_import_preconditions", _precondition_forbidden)

    imported: list[list[str]] = []
    _real_layout_import_lines = dme.dsk_live.layout_import_lines

    def _capture_layout_import_lines(doc_var, layout_names, template_path):
        imported.append(list(layout_names) if not isinstance(layout_names, str) else [layout_names])
        return _real_layout_import_lines(doc_var, layout_names, template_path)

    monkeypatch.setattr(dme.dsk_live, "layout_import_lines", _capture_layout_import_lines)

    calls = _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(
        fw, [17], out_dir, layout_template=template, black_layout_names=dme.DEFAULT_BLACK_LAYOUT_NAMES,
    )

    assert {r.slide for r in results} == {17}
    assert calls["osascript"] == 2
    # the script still embeds a fallback import of the FW-owned name (the runtime "if
    # blackLayoutName is empty" guard skips it since the FW deck already owns it), but
    # the offline precondition -- which would wrongly require the template to also own
    # it -- must not run for an alias that needs no import.
    assert imported == [["BLACK BLANK"]]


def test_export_slide_clips_imports_single_template_donor_when_no_fw_alias(monkeypatch, tmp_path):
    """Neither FW-owned alias is alpha-safe (or present); the template owns a safe
    "Black" -- exactly that one name must be validated and imported, not the whole
    alias list as required imports."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    template = tmp_path / "Donor.key"
    template.write_bytes(b"template")

    fw_objects = _layout_objects_multi(entries=[])
    template_objects = _layout_objects_multi(entries=[("Black", [])])

    def _dispatched_load_deck(path):
        return (template_objects, {}, {}) if Path(path) == template else (fw_objects, {}, {})

    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)
    monkeypatch.setattr(dme.dsk_live, "check_layout_import_preconditions", _REAL_CHECK_LAYOUT_IMPORT_PRECONDITIONS)

    imported: list[list[str]] = []
    _real_layout_import_lines = dme.dsk_live.layout_import_lines

    def _capture_layout_import_lines(doc_var, layout_names, template_path):
        imported.append(list(layout_names) if not isinstance(layout_names, str) else [layout_names])
        return _real_layout_import_lines(doc_var, layout_names, template_path)

    monkeypatch.setattr(dme.dsk_live, "layout_import_lines", _capture_layout_import_lines)

    calls = _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(
        fw, [17], out_dir, layout_template=template, black_layout_names=dme.DEFAULT_BLACK_LAYOUT_NAMES,
    )

    assert {r.slide for r in results} == {17}
    assert imported == [["Black"]]


def test_export_slide_clips_refuses_when_neither_fw_nor_template_owns_an_alias(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    template = tmp_path / "Donor.key"
    template.write_bytes(b"template")

    fw_objects = _layout_objects_multi(entries=[])
    template_objects = _layout_objects_multi(entries=[])

    def _dispatched_load_deck(path):
        return (template_objects, {}, {}) if Path(path) == template else (fw_objects, {}, {})

    _stub_offline_payload(monkeypatch)
    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _copy_keynote_forbidden(src, dest):
        raise AssertionError("Keynote must not launch once the precondition refuses")

    monkeypatch.setattr(dme, "copy_keynote", _copy_keynote_forbidden)
    _set(monkeypatch, "_keynote_running", lambda: False)
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)

    with pytest.raises(dme.dsk_live.LayoutImportRefusal, match="no alpha-safe layout"):
        dme.export_slide_clips(
            fw, [17], out_dir, layout_template=template, black_layout_names=dme.DEFAULT_BLACK_LAYOUT_NAMES,
        )


def test_export_slide_clips_uses_fw_owned_alias_with_nonexistent_template(monkeypatch, tmp_path):
    """FW-owned alpha-safe alias resolution must run regardless of whether the template
    exists: a safe FW-owned alias proceeds with that single name and no import, even
    when `layout_template` points at a nonexistent path."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    missing_template = tmp_path / "NoSuchDonor.key"

    fw_objects = _layout_objects_multi(entries=[("BLACK BLANK", [])])

    def _dispatched_load_deck(path):
        assert Path(path) != missing_template, "nonexistent template must never be loaded"
        return fw_objects, {}, {}

    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _precondition_forbidden(*a, **k):
        raise AssertionError("no import precondition is needed when the FW deck already owns a safe alias")

    monkeypatch.setattr(dme.dsk_live, "check_layout_import_preconditions", _precondition_forbidden)

    imported: list[list[str]] = []
    _real_layout_import_lines = dme.dsk_live.layout_import_lines

    def _capture_layout_import_lines(doc_var, layout_names, template_path):
        imported.append(list(layout_names) if not isinstance(layout_names, str) else [layout_names])
        return _real_layout_import_lines(doc_var, layout_names, template_path)

    monkeypatch.setattr(dme.dsk_live, "layout_import_lines", _capture_layout_import_lines)

    calls = _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(
        fw, [17], out_dir, layout_template=missing_template, black_layout_names=dme.DEFAULT_BLACK_LAYOUT_NAMES,
    )

    assert {r.slide for r in results} == {17}
    assert imported == []


def test_export_slide_clips_refuses_unsafe_fw_alias_with_nonexistent_template(monkeypatch, tmp_path):
    """An unsafe FW-owned alias with no usable template must refuse offline, not fall
    through to passing the raw alias list to the live script."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    missing_template = tmp_path / "NoSuchDonor.key"

    fw_objects = _layout_objects_multi(entries=[("Black", [(-10.0, 0.0, 8000.0, 1080.0)])])

    def _dispatched_load_deck(path):
        return fw_objects, {}, {}

    _stub_offline_payload(monkeypatch)
    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _copy_keynote_forbidden(src, dest):
        raise AssertionError("Keynote must not launch once the precondition refuses")

    monkeypatch.setattr(dme, "copy_keynote", _copy_keynote_forbidden)
    _set(monkeypatch, "_keynote_running", lambda: False)
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)

    with pytest.raises(dme.dsk_live.LayoutImportRefusal, match="no alpha-safe layout"):
        dme.export_slide_clips(
            fw, [17], out_dir, layout_template=missing_template, black_layout_names=("Black",),
        )


def test_export_slide_clips_refuses_no_fw_alias_with_nonexistent_template(monkeypatch, tmp_path):
    """No FW-owned alias at all, and no usable template: must refuse offline."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    missing_template = tmp_path / "NoSuchDonor.key"

    fw_objects = _layout_objects_multi(entries=[])

    def _dispatched_load_deck(path):
        return fw_objects, {}, {}

    _stub_offline_payload(monkeypatch)
    monkeypatch.setattr(dme.dsk_live, "_load_deck", _dispatched_load_deck)
    monkeypatch.setattr(dme, "_resolve_black_layout_name", _REAL_RESOLVE_BLACK_LAYOUT_NAME)
    monkeypatch.setattr(dme, "_resolve_black_layout_donor", _REAL_RESOLVE_BLACK_LAYOUT_DONOR)

    def _copy_keynote_forbidden(src, dest):
        raise AssertionError("Keynote must not launch once the precondition refuses")

    monkeypatch.setattr(dme, "copy_keynote", _copy_keynote_forbidden)
    _set(monkeypatch, "_keynote_running", lambda: False)
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)

    with pytest.raises(dme.dsk_live.LayoutImportRefusal, match="no alpha-safe layout"):
        dme.export_slide_clips(
            fw, [17], out_dir, layout_template=missing_template, black_layout_names=dme.DEFAULT_BLACK_LAYOUT_NAMES,
        )


def test_export_slide_clips_happy_path(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [17, 32], out_dir, log=lambda *_: None)

    assert calls["osascript"] == 2  # export batch + final quit
    assert {r.slide for r in results} == {17, 32}
    for r in results:
        assert r.width == 1920 and r.height == 1080
        assert r.path.exists()
        assert r.path.suffix == ".mov"
        assert r.path.parent == out_dir


def test_export_slide_clips_runs_content_assert_for_real(monkeypatch, tmp_path):
    # F5: the content assert must actually execute inside export_slide_clips, not be
    # stubbed out of the call path -- exercise it for real with a fake full-frame bbox.
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path, stub_content_assert=False)
    _patch_build_export_script_capture(monkeypatch)
    seen_paths = []

    def fake_stats(path, *, at_s=1.0):
        seen_paths.append(path)
        return (0, 0, 1920, 1080), 1.0

    monkeypatch.setattr(dme, "_non_black_stats", fake_stats)

    results = dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)

    assert seen_paths, "content assert never sampled a frame"
    assert {r.slide for r in results} == {17}


def test_export_slide_clips_content_assert_refuses_quadrant_clip(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, stub_content_assert=False)
    _patch_build_export_script_capture(monkeypatch)
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((0, 0, 960, 935), 1.0))

    with pytest.raises(RuntimeError, match="coal-slide"):
        dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)


def test_export_slide_clips_refuses_when_keynote_running(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    _stub_live(monkeypatch, tmp_path, keynote_running=True)
    with pytest.raises(RuntimeError, match="already running"):
        dme.export_slide_clips(fw, [17], out_dir)


def test_export_slide_clips_refuses_private_tmp(monkeypatch, tmp_path):
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    with pytest.raises(ValueError, match="private/tmp"):
        dme.export_slide_clips(fw, [17], Path("/private/tmp/dsk-out"))


def test_export_slide_clips_refuses_out_dir_inside_source_package(monkeypatch, tmp_path):
    fw = tmp_path / "Sermon.key"
    fw.mkdir()
    (fw / "index.apxl").write_bytes(b"")
    with pytest.raises(ValueError, match="source .key package"):
        dme.export_slide_clips(fw, [17], fw / "out")


def test_export_slide_clips_rejects_unknown_codec(monkeypatch, tmp_path):
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    with pytest.raises(ValueError, match="codec"):
        dme.export_slide_clips(fw, [17], tmp_path / "out", codec="mpeg1")


def test_export_slide_clips_rejects_unknown_fps(monkeypatch, tmp_path):
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    with pytest.raises(ValueError):
        dme.export_slide_clips(fw, [17], tmp_path / "out", fps=48)


def test_export_slide_clips_cleanup_on_exception(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_offline_payload(monkeypatch)
    running_state = {"running": False}
    _set(monkeypatch, "_keynote_running", lambda: running_state["running"])

    def fake_copy_keynote(src, dest):
        running_state["running"] = True
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"key")
        return dest

    monkeypatch.setattr(dme, "copy_keynote", fake_copy_keynote)

    released = {"lock": False}
    _set(monkeypatch, "_acquire_lock", lambda: None)

    def _release(fd):
        released["lock"] = True

    _set(monkeypatch, "_release_lock", _release)
    monkeypatch.setattr(dme._DisplayPoke, "start", lambda self: None)
    stopped = {"poke": False, "watchdog": False}

    def _stop_poke(self):
        stopped["poke"] = True

    monkeypatch.setattr(dme._DisplayPoke, "stop", _stop_poke)
    monkeypatch.setattr(dme._RssWatchdog, "start", lambda self: None)

    def _stop_watchdog(self):
        stopped["watchdog"] = True

    monkeypatch.setattr(dme._RssWatchdog, "stop", _stop_watchdog)
    _set(monkeypatch, "_keynote_pid", lambda: None)

    quit_calls = {"n": 0}

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" in text:
            raise RuntimeError("boom during export")
        quit_calls["n"] += 1
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="boom during export"):
        dme.export_slide_clips(fw, [17], out_dir)

    assert stopped["poke"] and stopped["watchdog"]
    assert released["lock"]
    assert quit_calls["n"] == 1


def test_export_slide_clips_appplescript_error_reraised_with_number(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        calls["osascript"] += 1
        if "export theDoc" in text:
            return _FakeCompleted(returncode=1, stderr="ERR\t17\t-1728\tCan't get slide 1.")
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="-1728"):
        dme.export_slide_clips(fw, [17], out_dir)


def test_export_slide_clips_retries_1712_once(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path)
    state = calls["state"]
    _patch_build_export_script_capture(monkeypatch)

    attempts = {"n": 0}

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" not in text:
            state["running"] = False  # simulate the -1712 quit-and-wait succeeding
            return _FakeCompleted(returncode=0)
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _FakeCompleted(returncode=1, stderr="-1712")
        for job in _current_jobs[0]:
            job.tmp.parent.mkdir(parents=True, exist_ok=True)
            job.tmp.write_bytes(b"movie-bytes")
        return _FakeCompleted(returncode=0, stderr=f"OBED\t17\tstamp")

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    results = dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)
    assert attempts["n"] == 2
    assert {r.slide for r in results} == {17}


def test_export_slide_clips_missing_export_raises(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="Expected export missing"):
        dme.export_slide_clips(fw, [17], out_dir)


def test_export_slide_clips_publishes_atomically_ignores_stale_dest(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    stale_dest = out_dir / dme.clip_name(fw.stem, 17)
    stale_dest.write_bytes(b"stale")

    calls = _stub_live(monkeypatch, tmp_path)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls["osascript"] += 1
        text = script_path.read_text()
        if "export theDoc" not in text:
            return _FakeCompleted(returncode=0)
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="Expected export missing"):
        dme.export_slide_clips(fw, [17], out_dir)
    # the pre-existing stale destination is never accepted as success
    assert stale_dest.read_bytes() == b"stale"


# --- crop wiring -------------------------------------------------------------


def test_derive_include_side_crop_uses_visible_union(monkeypatch, tmp_path):
    fake_payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": []}, {"number": 44, "items": [{"kind": "shape", "kindIndex": 0}]}],
    }
    monkeypatch.setattr(dme, "visible_union", lambda items, *, include_side, wall, **k: Rect(10, 20, 100, 200))
    crops = dme._derive_include_side_crop(fake_payload, [44])
    assert crops == {44: Rect(10, 20, 100, 200)}


def test_derive_include_side_crop_refuses_degenerate_union(monkeypatch, tmp_path):
    fake_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 44, "items": []}]}
    monkeypatch.setattr(dme, "visible_union", lambda items, *, include_side, wall, **k: None)
    with pytest.raises(ValueError, match="degenerate"):
        dme._derive_include_side_crop(fake_payload, [44])


# --- delete-id derivation -----------------------------------------------------


def test_derive_delete_ids_matches_classification():
    slides_by_number = {
        7: {
            "number": 7,
            "items": [
                {"kind": "image", "kindIndex": 0},
                {"kind": "image", "kindIndex": 1},
                {"kind": "text", "kindIndex": 2},
                {"kind": "text", "kindIndex": 3},
            ],
        }
    }
    cls = SlideClass(
        number=7,
        category="static",
        build_count=0,
        movie_count=0,
        kept=(("image", 0),),
        dropped_side=(("text", 3),),
        dropped_backdrop=(),
        transition=None,
        connection_line_builds=0,
        dropped_duplicate=(("image", 1),),
    )

    derived = dme._derive_delete_ids({7: cls}, slides_by_number, [7])

    expected_ids = {("text", 3), ("image", 1), ("text", 2)}
    assert set(derived[7]) == expected_ids
    assert derived[7] == dme._delete_order(list(expected_ids))


def test_derive_delete_ids_unknown_slide_raises():
    with pytest.raises(ValueError, match="not found"):
        dme._derive_delete_ids({}, {}, [9])


def test_derive_delete_ids_refuses_empty_slide():
    slides_by_number = {9: {"number": 9, "items": [{"kind": "image", "kindIndex": 0}]}}
    cls = SlideClass(9, "empty", 0, 0, (), (), (), None, 0, ())

    with pytest.raises(ValueError, match="empty"):
        dme._derive_delete_ids({9: cls}, slides_by_number, [9])


def test_validate_delete_ids_refuses_id_not_present_on_slide():
    slide = {"items": [{"kind": "image", "kindIndex": 0}, {"kind": "image", "kindIndex": 1}]}
    cls = SlideClass(17, "static", 0, 0, (("image", 0),), (), (), None, 0, ())

    with pytest.raises(ValueError, match="not present"):
        dme._validate_delete_ids(17, (("image", 9),), cls, slide)


def test_export_slide_clips_refuses_supplied_delete_id_that_is_kept(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    fake_payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 17,
                "items": [{"kind": "image", "kindIndex": 0}, {"kind": "image", "kindIndex": 1}],
            }
        ],
    }
    monkeypatch.setattr(dme, "offline_wall_payload", lambda path: fake_payload)
    monkeypatch.setattr(dme, "attach_group_content_signature", lambda path, payload, **k: None)
    cls = SlideClass(17, "static", 0, 0, (("image", 0),), (), (), None, 0, ())
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])

    with pytest.raises(ValueError, match="kept content"):
        dme.export_slide_clips(fw, [17], out_dir, delete_ids={17: (("image", 0),)})


def test_export_slide_clips_refuses_supplied_delete_ids_for_empty_slide(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    fake_payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 9, "items": [{"kind": "image", "kindIndex": 0}]}],
    }
    monkeypatch.setattr(dme, "offline_wall_payload", lambda path: fake_payload)
    monkeypatch.setattr(dme, "attach_group_content_signature", lambda path, payload, **k: None)
    cls = SlideClass(9, "empty", 0, 0, (), (), (), None, 0, ())
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])

    with pytest.raises(ValueError, match="empty"):
        dme.export_slide_clips(fw, [9], out_dir, delete_ids={9: ()})


def test_export_slide_clips_logs_mirror_warnings_when_delete_ids_supplied_for_every_slide(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    payload_slides = [
        {"number": 17, "items": [{"kind": "image", "kindIndex": 0}, {"kind": "image", "kindIndex": 1}]}
    ]
    _stub_live(monkeypatch, tmp_path, payload_slides=payload_slides)
    _patch_build_export_script_capture(monkeypatch)
    cls = SlideClass(
        number=17,
        category="static",
        build_count=0,
        movie_count=0,
        kept=(("image", 0),),
        dropped_side=(),
        dropped_backdrop=(),
        transition=None,
        connection_line_builds=0,
        dropped_duplicate=(("image", 1),),
        mirror_warnings=("mirror-pair survivor side chosen by a single vote: 'right'",),
    )
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])

    logged: list[str] = []
    dme.export_slide_clips(fw, [17], out_dir, delete_ids={17: (("image", 1),)}, log=logged.append)

    assert "slide 17: mirror-pair survivor side chosen by a single vote: 'right'" in logged


def test_export_slide_clips_unknown_slide_raises(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[])

    with pytest.raises(ValueError, match="not found"):
        dme.export_slide_clips(fw, [17], out_dir)


def test_export_slide_clips_deletefail_raises(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        calls["osascript"] += 1
        if "export theDoc" in text:
            return _FakeCompleted(
                returncode=0,
                stderr="DELETEFAIL\t17\timage 2 of slide 1\t-1728\tCan't delete.",
            )
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="delete failed"):
        dme.export_slide_clips(fw, [17], out_dir)


# --- quit-and-wait before a -1712 retry --------------------------------------


def test_quit_and_wait_for_exit_skips_quit_script_when_not_running(monkeypatch, tmp_path):
    _set(monkeypatch, "_keynote_running", lambda: False)

    def _forbidden(*a, **k):
        raise AssertionError("must not run a quit script when Keynote isn't running")

    _set(monkeypatch, "_run_quit_script", _forbidden)
    dme._quit_and_wait_for_exit("Sermon", "Sermon.key", tmp_path)


def test_quit_and_wait_for_exit_waits_until_process_gone(monkeypatch, tmp_path):
    calls = {"quit": 0, "sleep": 0}
    running = iter([True, True, False])

    _set(monkeypatch, "_keynote_running", lambda: next(running, False))
    _set(monkeypatch, "_run_quit_script", lambda *a: calls.__setitem__("quit", calls["quit"] + 1))
    monkeypatch.setattr(dme.time, "sleep", lambda s: calls.__setitem__("sleep", calls["sleep"] + 1))

    dme._quit_and_wait_for_exit("Sermon", "Sermon.key", tmp_path)
    assert calls["quit"] == 1
    assert calls["sleep"] >= 1


def test_quit_and_wait_for_exit_bounded_when_process_never_exits(monkeypatch, tmp_path):
    _set(monkeypatch, "_keynote_running", lambda: True)
    _set(monkeypatch, "_run_quit_script", lambda *a: None)
    _set(monkeypatch, "_KEYNOTE_QUIT_WAIT_S", 0)
    monkeypatch.setattr(dme.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="still running"):
        dme._quit_and_wait_for_exit("Sermon", "Sermon.key", tmp_path)  # doesn't hang, doesn't lie


# --- watchdog ---------------------------------------------------------------


def test_export_slide_clips_1712_retry_recopies_scratch(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)

    copy_calls = {"n": 0}

    def fake_copy_keynote(src, dest):
        copy_calls["n"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"key")
        return dest

    monkeypatch.setattr(dme, "copy_keynote", fake_copy_keynote)

    attempts = {"n": 0}

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" not in text:
            return _FakeCompleted(returncode=0)
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _FakeCompleted(returncode=1, stderr="-1712")
        for job in _current_jobs[0]:
            job.tmp.parent.mkdir(parents=True, exist_ok=True)
            job.tmp.write_bytes(b"movie-bytes")
        return _FakeCompleted(returncode=0, stderr="OBED\t17\tstamp")

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)
    assert copy_calls["n"] == 2  # one pristine copy per attempt


def test_export_slide_clips_1712_retry_does_not_recopy_when_keynote_never_exits(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path)
    state = calls["state"]
    _patch_build_export_script_capture(monkeypatch)
    _set(monkeypatch, "_KEYNOTE_QUIT_WAIT_S", 0)
    monkeypatch.setattr(dme.time, "sleep", lambda s: None)

    copy_calls = {"n": 0}

    def fake_copy_keynote(src, dest):
        copy_calls["n"] += 1
        state["running"] = True
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"key")
        return dest

    monkeypatch.setattr(dme, "copy_keynote", fake_copy_keynote)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" not in text:
            return _FakeCompleted(returncode=0)  # quit script "succeeds" but Keynote stays up
        return _FakeCompleted(returncode=1, stderr="-1712")

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="still running"):
        dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)
    assert copy_calls["n"] == 1  # never recopies onto a still-open document


def test_run_osascript_single_reader_progress_live(monkeypatch, tmp_path):
    class _FakePopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.stdout = iter(["done\n"])
            self.stderr = iter(["OBED\t1\tx\n", "OBED\t2\tx\n"])
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(dme.subprocess, "Popen", lambda *a, **k: _FakePopen())
    script_path = tmp_path / "x.applescript"
    script_path.write_text("noop")

    seen: list[int] = []
    registered: list[object] = []
    proc = dme._run_osascript(
        script_path,
        on_progress=lambda slide: seen.append(slide),
        register_proc=lambda p: registered.append(p),
    )
    assert seen == [1, 2]
    assert proc.stdout == "done\n"
    assert "OBED\t1\tx" in proc.stderr
    assert registered[-1] is None  # cleared in finally


def test_export_slide_clips_failing_ffprobe_leaves_no_destination(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path)
    _patch_build_export_script_capture(monkeypatch)
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (_ for _ in ()).throw(RuntimeError("ffprobe failed")))

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        dme.export_slide_clips(fw, [17], out_dir, log=lambda *_: None)

    dest = out_dir / dme.clip_name(fw.stem, 17)
    assert not dest.exists()


def test_ffmpeg_process_passthrough_remuxes_with_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (3840, 1080, 30.0, 8.0))
    captured = {}

    def fake_stage(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", fake_stage)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    w, h = dme._ffmpeg_process(raw, dest, crop_rect=None, wall_w=3840, wall_h=1080, codec="AppleProRes422LT")
    assert (w, h) == (3840, 1080)
    assert "-c" in captured["cmd"] and "copy" in captured["cmd"]
    assert str(dest) in captured["cmd"]


def test_ffmpeg_process_crop_uses_prores_ks_for_prores_codec(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (3840, 1080, 30.0, 8.0))
    captured = {}

    def fake_stage(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", fake_stage)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    rect = Rect(0, 0, 100, 100)
    w, h = dme._ffmpeg_process(raw, dest, crop_rect=rect, wall_w=3840, wall_h=1080, codec="AppleProRes422LT")
    assert (w, h) == (100, 100)
    assert "prores_ks" in captured["cmd"]
    assert "-profile:v" in captured["cmd"]
    cmd = captured["cmd"]
    assert "-an" not in cmd
    assert "-c:a" in cmd and "copy" in cmd
    assert "-map" in cmd and "0:v:0" in cmd and "0:a?" in cmd


def test_ffmpeg_process_crop_uses_libx264_for_h264_codec(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (3840, 1080, 30.0, 8.0))
    captured = {}

    def fake_stage(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", fake_stage)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    rect = Rect(0, 0, 100, 100)
    dme._ffmpeg_process(raw, dest, crop_rect=rect, wall_w=3840, wall_h=1080, codec="h264")
    assert "libx264" in captured["cmd"]
    assert "prores_ks" not in captured["cmd"]


def test_ffmpeg_process_rejects_raw_dims_mismatching_native_wall_size(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (1920, 1080, 30.0, 8.0))

    def _forbidden(cmd):
        raise AssertionError("must not encode against an unverified raw canvas")

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", _forbidden)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    with pytest.raises(RuntimeError, match="native wall size"):
        dme._ffmpeg_process(raw, dest, crop_rect=None, wall_w=3840, wall_h=1080, codec="AppleProRes422LT")


def test_ffmpeg_process_normalises_odd_crop_to_even(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (3840, 1080, 30.0, 8.0))
    captured = {}

    def fake_stage(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr(dme, "_run_ffmpeg_stage", fake_stage)
    raw = tmp_path / "raw.m4v"
    dest = tmp_path / "out.mov"
    rect = Rect(1, 1, 99, 45)
    w, h = dme._ffmpeg_process(raw, dest, crop_rect=rect, wall_w=3840, wall_h=1080, codec="AppleProRes422LT")
    assert (w, h) == (100, 46)
    assert "crop=100:46:0:0" in captured["cmd"]


def test_normalize_even_crop_floors_origin_and_expands_size():
    assert dme._normalize_even_crop(1, 1, 99, 45, 3840, 1080) == (0, 0, 100, 46)


def test_normalize_even_crop_re_clamps_to_frame():
    assert dme._normalize_even_crop(3839, 1, 1, 1, 3840, 1080) == (3838, 0, 2, 2)


def test_normalize_even_crop_degenerate_raises():
    # an odd frame edge leaves no even-aligned room for the re-clamped crop.
    with pytest.raises(ValueError, match="Degenerate"):
        dme._normalize_even_crop(4, 4, 1, 1, 5, 5)


# --- clip content assert (coal-slide signature) -------------------------------


def test_clip_content_assert_rejects_quadrant_clip(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((0, 0, 1920, 935), 1.0))
    with pytest.raises(RuntimeError, match="coal-slide"):
        dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0)


def test_clip_content_assert_passes_full_frame(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((0, 0, 3840, 1080), 1.0))
    dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0)


def test_clip_content_assert_allows_expected_top_left_content(monkeypatch, tmp_path):
    # A slide whose own expected content genuinely lives in the top-left (e.g. --include-side
    # content anchored left) must not trip the quadrant heuristic.
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((0, 0, 1920, 935), 1.0))
    expected = Rect(0, 0, 1900, 900)
    dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0, expected=expected)


def test_clip_content_assert_refuses_under_covered_expected(monkeypatch, tmp_path):
    # Not confined to the top-left quadrant, but far short of the expected content rect.
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((3700, 1000, 3800, 1080), 1.0))
    expected = Rect(0, 0, 3840, 1080)
    with pytest.raises(RuntimeError, match="covers less than"):
        dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0, expected=expected)


def test_clip_content_assert_all_black_frames_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: (None, 0.0))
    logged = []
    dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0, log=logged.append)
    assert logged and "content assert skipped" in logged[0]


def test_clip_content_assert_sparse_dark_frames_warn_not_refuse(monkeypatch, tmp_path):
    # A few ember pixels in the top-left corner: non-zero non-black bbox but density far
    # below the low-information threshold -- a genuinely dark clip, not a coal-slide crop.
    monkeypatch.setattr(dme, "_non_black_stats", lambda path, **k: ((0, 0, 20, 20), 0.001))
    logged = []
    dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0, log=logged.append)
    assert any("low-information" in m for m in logged)


def test_clip_content_assert_samples_quarter_half_three_quarter_duration(monkeypatch, tmp_path):
    seen = []

    def fake_stats(path, *, at_s=1.0):
        seen.append(at_s)
        return (0, 0, 3840, 1080), 1.0

    monkeypatch.setattr(dme, "_non_black_stats", fake_stats)
    dme._assert_clip_covers_frame(tmp_path / "clip.mov", 3840, 1080, duration=8.0)
    assert seen == sorted(seen)
    assert seen == [2.0, 4.0, 6.0]


def test_export_slide_clips_cleans_up_work_dir_on_failure(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_offline_payload(monkeypatch)
    _set(monkeypatch, "_keynote_running", lambda: False)
    monkeypatch.setattr(
        dme,
        "copy_keynote",
        lambda src, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"key"))[-1] and dest,
    )
    _set(monkeypatch, "_acquire_lock", lambda: None)
    _set(monkeypatch, "_release_lock", lambda fd: None)
    monkeypatch.setattr(dme._DisplayPoke, "start", lambda self: None)
    monkeypatch.setattr(dme._DisplayPoke, "stop", lambda self: None)
    monkeypatch.setattr(dme._RssWatchdog, "start", lambda self: None)
    monkeypatch.setattr(dme._RssWatchdog, "stop", lambda self: None)
    _set(monkeypatch, "_keynote_pid", lambda: None)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" in text:
            raise RuntimeError("boom during export")
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match="boom during export"):
        dme.export_slide_clips(fw, [17], out_dir)

    leftover = [p for p in out_dir.iterdir() if p.name.startswith(".dsk-export-")]
    assert leftover == []


def test_rss_watchdog_loop_terminates_fake_process(monkeypatch):
    class _FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    fake_proc = _FakeProc()
    breached = {"n": 0}

    def _on_breach():
        breached["n"] += 1
        fake_proc.terminate()

    watchdog = dme._RssWatchdog(get_pid=lambda: 123, limit_bytes=1000, on_breach=_on_breach)

    rss_values = iter([500, 2000])
    _set(monkeypatch, "_sample_rss_bytes", lambda pid: next(rss_values))
    monkeypatch.setattr(watchdog._stop, "wait", lambda timeout: watchdog.breached)

    watchdog._loop()

    assert watchdog.breached
    assert breached["n"] == 1
    assert fake_proc.terminated
    assert watchdog.peak_rss_bytes == 2000


# --- export_dsk_slide_clips (offline, faked LiveBatch) -------------------------


class _FakeDskLiveBatch:
    """Stands in for `dsk_live.LiveBatch`: no Keynote, no lock/watchdog/poke. `run` writes
    every `tmp.NNNN.m4v` the generated script references, so `export_dsk_slide_clips`
    finds the exports it expects."""

    def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
        self.deck = Path(deck)
        self.out_dir = Path(out_dir)
        self.work = None
        self.scratch = None

    def __enter__(self):
        self.work = self.out_dir / f".dsk-export-{self.deck.stem}"
        self.work.mkdir(parents=True, exist_ok=True)
        self.scratch = self.work / self.deck.name
        self.scratch.write_bytes(b"key")
        return self

    def __exit__(self, *exc):
        return False

    def run(self, script_path, *, on_progress=None):
        text = script_path.read_text()
        for name in sorted(set(re.findall(r"tmp\.\d{4}\.m4v", text))):
            (self.work / name).write_bytes(b"movie-bytes")
        return _FakeCompleted(returncode=0, stderr="")


def _stub_dsk_offline(monkeypatch, *, count=5):
    payload = {
        "slideWidth": 1920.0,
        "slideHeight": 1080.0,
        "slides": [{"number": n} for n in range(1, count + 1)],
    }
    monkeypatch.setattr(dme, "offline_wall_payload", lambda path: payload)
    monkeypatch.setattr(dme.dsk_live, "LiveBatch", _FakeDskLiveBatch)
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")

    def fake_ffmpeg_process(raw, dest, *, crop_rect, wall_w, wall_h, codec):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw.read_bytes())
        return wall_w, wall_h

    monkeypatch.setattr(dme, "_ffmpeg_process", fake_ffmpeg_process)
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (1920, 1080, 30.0, 2.0))
    return payload


def test_export_dsk_slide_clips_publishes_named_clips(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon_DSK.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch)

    results = dme.export_dsk_slide_clips(deck, [2, 5], out_dir, log=lambda *_: None)

    assert {r.slide for r in results} == {2, 5}
    assert (out_dir / "Sermon_DSK.002.mov").is_file()
    assert (out_dir / "Sermon_DSK.005.mov").is_file()
    for r in results:
        assert r.width == 1920 and r.height == 1080


def test_export_dsk_slide_clips_uses_ordinals_in_script(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon_DSK.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch)

    orig = dme._build_dsk_export_script
    captured = {}

    def wrapper(**kwargs):
        captured["per_slide"] = list(kwargs["per_slide"])
        return orig(**kwargs)

    monkeypatch.setattr(dme, "_build_dsk_export_script", wrapper)

    dme.export_dsk_slide_clips(deck, [2, 5], out_dir, log=lambda *_: None)

    ordinals = {slide: ordinal for slide, ordinal, _tmp in captured["per_slide"]}
    assert ordinals == {2: 1, 5: 2}


def test_export_dsk_slide_clips_refuses_non_1920_deck(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch)
    monkeypatch.setattr(
        dme, "offline_wall_payload",
        lambda path: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slides": [{"number": 1}]},
    )
    with pytest.raises(ValueError, match="not a 1920x1080 DSK deck"):
        dme.export_dsk_slide_clips(deck, [1], out_dir, log=lambda *_: None)


def test_export_dsk_slide_clips_refuses_unknown_slide(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon_DSK.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch, count=3)
    with pytest.raises(ValueError, match="not found"):
        dme.export_dsk_slide_clips(deck, [99], out_dir, log=lambda *_: None)


def test_export_dsk_slide_clips_empty_slides_returns_empty(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon_DSK.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch)
    assert dme.export_dsk_slide_clips(deck, [], out_dir, log=lambda *_: None) == []


def test_export_dsk_slide_clips_preflights_ffmpeg_before_live_batch(monkeypatch, tmp_path):
    deck = tmp_path / "Sermon_DSK.key"
    deck.write_bytes(b"source")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _stub_dsk_offline(monkeypatch)
    monkeypatch.setattr(dme, "ffmpeg_exe", lambda: None)

    def _forbidden(*_a, **_k):
        raise AssertionError("LiveBatch must not open when ffmpeg is missing")

    monkeypatch.setattr(dme.dsk_live, "LiveBatch", _forbidden)

    with pytest.raises(RuntimeError, match="ffmpeg executable not found"):
        dme.export_dsk_slide_clips(deck, [1], out_dir, log=lambda *_: None)


# --- per-movie pure-video mode ----------------------------------------------


def test_rect_intersect_clips_offcanvas_movie_to_centre_panel():
    # FW 11-shaped: a 3840x2160 movie parked at y -667 so it bleeds off both edges of the
    # wall; the pure clip must crop to what the centre panel actually shows.
    offcanvas = Rect(1920.0, -667.0, 3840.0, 2160.0)
    result = dme._rect_intersect(offcanvas, dme.CENTRE_PANEL_RECT)
    assert result == Rect(1920.0, 0.0, 3840.0, 1080.0)


def test_rect_intersect_degenerate_raises():
    with pytest.raises(ValueError, match="Degenerate"):
        dme._rect_intersect(Rect(0, 0, 10, 10), Rect(100, 100, 10, 10))


def test_derive_pure_video_delete_ids_keeps_only_target_movie():
    items = [
        {"kind": "movie", "kindIndex": 0},
        {"kind": "movie", "kindIndex": 1},
        {"kind": "text", "kindIndex": 0},
        {"kind": "shape", "kindIndex": 0},
        {"kind": "group", "kindIndex": 0},
        {"kind": "line", "kindIndex": 0},
        {"kind": "image", "kindIndex": 0},
    ]
    target = ("movie", 1)

    deleted = dme._derive_pure_video_delete_ids(items, target)

    assert target not in deleted
    expected = {("movie", 0), ("text", 0), ("shape", 0), ("group", 0), ("line", 0), ("image", 0)}
    assert set(deleted) == expected
    assert deleted == dme._delete_order(list(expected))


def _mixed_slide_two_movies():
    return {
        "number": 12,
        "items": [
            {"kind": "movie", "kindIndex": 0, "x": 1920.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
            {"kind": "movie", "kindIndex": 1, "x": 3840.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
            {"kind": "text", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0},
            {"kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0},
        ],
    }


def test_viewport_crop_rect_is_aspect_fill_with_normalized_zoom_and_pan():
    source = Rect(0, 0, 1920, 1080)
    target = Rect(43, 802, 300, 263)
    centred = dme.viewport_crop_rect(source, target)
    left_zoomed = dme.viewport_crop_rect(source, target, zoom=1.25, pan_x=-1, pan_y=1)
    right_zoomed = dme.viewport_crop_rect(source, target, zoom=1.25, pan_x=1, pan_y=-1)

    assert centred.w / centred.h == pytest.approx(target.w / target.h)
    assert left_zoomed.w / left_zoomed.h == pytest.approx(target.w / target.h)
    assert left_zoomed.w == pytest.approx(centred.w / 1.25)
    assert left_zoomed.x == pytest.approx(0)
    assert left_zoomed.y + left_zoomed.h == pytest.approx(1080)
    assert right_zoomed.x + right_zoomed.w == pytest.approx(1920)
    assert right_zoomed.y == pytest.approx(0)


def test_movie_crop_plans_from_compiled_preserves_each_occurrence_and_mask():
    plans = dme.movie_crop_plans_from_compiled(({
        "source_mode": "fw",
        "source_slides": [108, 109, 110],
        "media": [
            {"occurrence_id": "108:a", "source_slide": 108, "source_item": ("movie", 0), "timing": "after_transition",
             "target_rect": Rect(43, 802, 300, 263), "viewport": {"zoom": 1.1, "panX": -0.2, "panY": 0.3}},
            {"occurrence_id": "110:b", "source_slide": 110, "source_item": ("movie", 1), "timing": "with_build_1",
             "target_rect": Rect(343, 802, 300, 263), "viewport": {}},
        ],
    },))
    assert [(p.occurrence_id, p.source_slide, p.source_item) for p in plans] == [
        ("108:a", 108, ("movie", 0)), ("110:b", 110, ("movie", 1)),
    ]
    assert plans[0].source_mode == "fw"
    assert (plans[0].zoom, plans[0].pan_x, plans[0].pan_y) == (1.1, -0.2, 0.3)
    assert all(plan.bare for plan in plans)


def test_compiled_stacked_media_bares_only_layers_after_the_first():
    plans = dme.movie_crop_plans_from_compiled(({
        "source_mode": "lw",
        "source_slides": [50],
        "media_layout": "stacked",
        "media": [
            {"occurrence_id": "50:lower", "source_slide": 50, "source_item": ("movie", 0), "timing": "source", "target_rect": Rect(43, 802, 935, 263)},
            {"occurrence_id": "50:upper", "source_slide": 50, "source_item": ("movie", 1), "timing": "source", "target_rect": Rect(43, 802, 935, 263)},
        ],
    },))
    assert [plan.bare for plan in plans] == [False, True]


@pytest.mark.parametrize("zoom,pan_x,pan_y", [(0.99, 0, 0), (1, -1.01, 0), (1, 0, 1.01)])
def test_viewport_crop_rect_refuses_invalid_mask_values(zoom, pan_x, pan_y):
    with pytest.raises(ValueError):
        dme.viewport_crop_rect(Rect(0, 0, 100, 100), Rect(0, 0, 50, 50), zoom=zoom, pan_x=pan_x, pan_y=pan_y)


def test_export_slide_clips_per_movie_produces_one_clip_per_movie_item(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert len(results) == 2
    names = sorted(r.path.name for r in results)
    assert names == ["Sermon.012.01.mov", "Sermon.012.02.mov"]
    by_movie_index = {r.movie_id[1]: r for r in results}
    assert by_movie_index[0].movie_id == ("movie", 0)
    assert by_movie_index[1].movie_id == ("movie", 1)
    assert by_movie_index[0].crop_rect == Rect(1920.0, 0.0, 1920.0, 1080.0)
    assert by_movie_index[1].crop_rect == Rect(3840.0, 0.0, 1920.0, 1080.0)


def _stacked_slide_two_movies():
    """FRC Wall slide 50's shape: two movies layered on the centre panel."""
    return {
        "number": 12,
        "items": [
            {"kind": "movie", "kindIndex": 0, "index": 0, "x": 1920.0, "y": -1079.0, "w": 3840.0, "h": 2160.0},
            {"kind": "movie", "kindIndex": 1, "index": 1, "x": 1915.0, "y": -163.0, "w": 3840.0, "h": 2160.0},
        ],
    }


def test_export_slide_clips_per_movie_bares_only_the_upper_clip_of_a_stacked_slide(monkeypatch, tmp_path):
    """The upper stacked clip's intermediate must be the BARE movie: its source build-in left
    attached would be baked into the clip AND re-created by the assembler, doubling the
    delay (Codex r2). The first stacked clip gets no build-in from the assembler, so it is
    exported exactly as before."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path, payload_slides=[_stacked_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)
    monkeypatch.setattr(
        dme, "deck_builds",
        lambda deck: {12: {"builds": [
            {"kind": "movie", "kindIndex": 0, "chunkOrder": [0]},
            {"kind": "movie", "kindIndex": 1, "chunkOrder": [1]},
        ]}},
    )

    dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert len(calls["bared"]) == 1
    deck, targets = calls["bared"][0]
    assert deck != fw
    assert deck.name == fw.name and deck.parent.name.startswith(".dsk-export-")
    assert targets == {12: [("movie", 1)]}


def test_clip_result_bare_marks_only_the_upper_clip_of_a_stacked_slide(monkeypatch, tmp_path):
    """Plan §4 item 30(d): the assembler may only write a source build-in onto a clip it
    knows was exported BARE, so `ClipResult.bare` must carry the job's own flag out to the
    caller -- true for the upper stacked clip, false for the one below it."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[_stacked_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)
    monkeypatch.setattr(
        dme, "deck_builds",
        lambda deck: {12: {"builds": [
            {"kind": "movie", "kindIndex": 0, "chunkOrder": [0]},
            {"kind": "movie", "kindIndex": 1, "chunkOrder": [1]},
        ]}},
    )

    results = dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert {r.movie_id: r.bare for r in results} == {("movie", 0): False, ("movie", 1): True}


def test_clip_result_bare_is_false_for_a_side_by_side_slide(monkeypatch, tmp_path):
    """Null control: nothing on an unstacked row is bared, so no clip is ever eligible for
    a build-in write."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert [r.bare for r in results] == [False, False]


def test_export_slide_clips_per_movie_does_not_bare_a_side_by_side_slide(monkeypatch, tmp_path):
    """Null control: an ordinary row of movies keeps today's export untouched, so a movie
    with builds the barer would refuse cannot newly fail the whole export."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert calls["bared"] == []


def test_export_slide_clips_does_not_bare_build_ins_in_whole_slide_mode(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    dme.export_slide_clips(fw, [12], out_dir, log=lambda *_: None)

    assert calls["bared"] == []


def test_export_slide_clips_names_the_memory_limit_when_the_watchdog_breaches(monkeypatch, tmp_path):
    """Live r18: the 6.7 GB FRC deck breached the 3 GB default and the job error was a bare
    "Keynote export AppleScript failed:" with empty stderr. The breach must name itself and
    the override."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    def breaching_start(self):
        self.breached = True
        self.peak_rss_bytes = 3_400_000_000

    monkeypatch.setattr(dme._RssWatchdog, "start", breaching_start)
    _set(monkeypatch, "_run_osascript", lambda *a, **k: _FakeCompleted(returncode=-15, stderr=""))

    with pytest.raises(RuntimeError, match=r"memory limit.*peak 3\.4 GB.*OBED_DSK_RSS_LIMIT_GB"):
        dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)


def test_bare_pure_video_movies_refuses_to_touch_the_source_deck(tmp_path):
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    jobs = [dme._SlideJob(slide=12, ordinal=1, crop_rect=Rect(0, 0, 10, 10), dest=fw, tmp=fw, movie_id=("movie", 0), bare=True)]
    with pytest.raises(RuntimeError, match="refusing to bare source build-ins on the source deck"):
        dme._bare_pure_video_movies(fw, fw, jobs, lambda *_: None)


def test_bare_pure_video_movies_surfaces_a_refusal(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch" / "Sermon.key"
    scratch.parent.mkdir()
    scratch.write_bytes(b"key")
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    monkeypatch.setattr(
        dme, "bare_source_build_ins",
        lambda deck, targets: {"refused": True, "reason": "slide 12 movie 1: 2 listed build(s)", "touched": [], "applied": 0},
    )
    jobs = [dme._SlideJob(slide=12, ordinal=1, crop_rect=Rect(0, 0, 10, 10), dest=fw, tmp=fw, movie_id=("movie", 1), bare=True)]
    with pytest.raises(RuntimeError, match="pure-video intermediate: slide 12 movie 1"):
        dme._bare_pure_video_movies(scratch, fw, jobs, lambda *_: None)


def test_export_slide_clips_per_movie_fires_on_progress_per_clip_with_distinct_wall_s(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    calls = _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    seen: list[tuple[int, int | None]] = []
    ticks = {"n": 0}

    def _fake_monotonic():
        ticks["n"] += 1
        return float(ticks["n"])

    monkeypatch.setattr(dme.time, "monotonic", _fake_monotonic)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls["osascript"] += 1
        text = script_path.read_text()
        if "using terms from" not in text:
            return _FakeCompleted(returncode=0)
        lines = []
        for job in _current_jobs[0]:
            job.tmp.parent.mkdir(parents=True, exist_ok=True)
            job.tmp.write_bytes(b"movie-bytes")
            on_progress(job.slide, job.movie_id[1])
            seen.append((job.slide, job.movie_id[1]))
            lines.append(f"OBED\t{job.slide}\t{job.movie_id[1]}\tstamp")
        return _FakeCompleted(returncode=0, stderr="\n".join(lines))

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    results = dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert seen == [(12, 0), (12, 1)]
    wall_s_by_index = {r.movie_id[1]: r.wall_s for r in results}
    assert wall_s_by_index[0] != wall_s_by_index[1]


def test_export_slide_clips_per_movie_error_surfaces_structured_message(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    _stub_live(monkeypatch, tmp_path, payload_slides=[_mixed_slide_two_movies()])
    _patch_build_export_script_capture(monkeypatch)

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        text = script_path.read_text()
        if "export theDoc" in text:
            return _FakeCompleted(
                returncode=1, stderr="ERR\t12\t2\t-1728\tCan't export movie item 2."
            )
        return _FakeCompleted(returncode=0)

    _set(monkeypatch, "_run_osascript", fake_run_osascript)

    with pytest.raises(RuntimeError, match=r"-1728.*Can't export movie item 2\."):
        dme.export_slide_clips(fw, [12], out_dir, per_movie=True)


def test_export_slide_clips_per_movie_offcanvas_movie_crops_to_panel(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    slide = {
        "number": 11,
        "items": [
            {"kind": "movie", "kindIndex": 0, "x": 1920.0, "y": -667.0, "w": 3840.0, "h": 2160.0},
        ],
    }
    _stub_live(monkeypatch, tmp_path, payload_slides=[slide])
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [11], out_dir, per_movie=True, log=lambda *_: None)

    assert len(results) == 1
    assert results[0].crop_rect == Rect(1920.0, 0.0, 3840.0, 1080.0)


def test_export_slide_clips_per_movie_rejects_delete_ids(monkeypatch, tmp_path):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    with pytest.raises(ValueError, match="per_movie"):
        dme.export_slide_clips(fw, [12], out_dir, per_movie=True, delete_ids={12: (("image", 0),)})


def test_export_slide_clips_per_movie_uses_kept_movie_ids_not_all_movies(monkeypatch, tmp_path):
    """A side movie the classifier dropped (absent from `cls.kept`) must not get its own
    per-movie clip -- only the movie ids `classify_deck` actually kept are exported,
    regardless of how many top-level movie items the slide has."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    slide = {
        "number": 12,
        "items": [
            {"kind": "movie", "kindIndex": 0, "x": 1920.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
            {"kind": "movie", "kindIndex": 1, "x": 0.0, "y": 0.0, "w": 500.0, "h": 1080.0},
        ],
    }
    _stub_live(monkeypatch, tmp_path, payload_slides=[slide])
    cls = SlideClass(12, "mixed", 0, 2, (("movie", 0),), (("movie", 1),), (), None, 0, ())
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [12], out_dir, per_movie=True, log=lambda *_: None)

    assert len(results) == 1
    assert results[0].movie_id == ("movie", 0)
    assert [r.path.name for r in results] == ["Sermon.012.01.mov"]


def test_visual_movie_order_sorts_by_x_then_y():
    rects = {
        ("movie", 0): Rect(2850.0, 0.0, 100.0, 100.0),
        ("movie", 1): Rect(1280.0, 0.0, 100.0, 100.0),
    }
    assert dme.visual_movie_order(rects) == [("movie", 1), ("movie", 0)]


def test_visual_movie_order_raises_on_exact_tie():
    rects = {
        ("movie", 0): Rect(100.0, 0.0, 50.0, 50.0),
        ("movie", 1): Rect(100.0, 0.0, 50.0, 50.0),
    }
    with pytest.raises(ValueError, match=r"\('movie', 0\).*\('movie', 1\)"):
        dme.visual_movie_order(rects)


def test_export_slide_clips_per_movie_names_by_visual_order_not_kind_index(monkeypatch, tmp_path):
    """FW 13 shape: kindIndex 0 sits at x=3500 (right) and kindIndex 1 sits at x=2000
    (left). The clip index MM must follow visual (x) order, so the LEFT movie
    (kindIndex 1) is `.013.01.mov` and the RIGHT movie (kindIndex 0) is `.013.02.mov`."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    slide = {
        "number": 13,
        "items": [
            {"kind": "movie", "kindIndex": 0, "x": 3500.0, "y": 0.0, "w": 500.0, "h": 1080.0},
            {"kind": "movie", "kindIndex": 1, "x": 2000.0, "y": 0.0, "w": 500.0, "h": 1080.0},
        ],
    }
    _stub_live(monkeypatch, tmp_path, payload_slides=[slide])
    cls = SlideClass(13, "mixed", 0, 2, (("movie", 0), ("movie", 1)), (), (), None, 0, ())
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])
    _patch_build_export_script_capture(monkeypatch)

    results = dme.export_slide_clips(fw, [13], out_dir, per_movie=True, log=lambda *_: None)

    assert [(r.movie_id, r.path.name) for r in results] == [
        (("movie", 1), "Sermon.013.01.mov"),
        (("movie", 0), "Sermon.013.02.mov"),
    ]


def test_export_slide_clips_per_movie_content_assert_uses_visible_intersection(monkeypatch, tmp_path):
    """A movie mostly outside the centre panel must have its coverage check against the
    *visible* intersection (`job.crop_rect`), not the full off-canvas movie rectangle --
    otherwise a correctly-cropped clip whose movie is less than half onscreen is wrongly
    rejected for covering too little of an inflated expected rect."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    slide = {
        "number": 11,
        "items": [
            # Spans x=[-2000, 4000); only [1920, 4000) (2080 of 6000, ~35%) overlaps the
            # centre panel [1920, 5760).
            {"kind": "movie", "kindIndex": 0, "x": -2000.0, "y": 0.0, "w": 6000.0, "h": 1080.0},
        ],
    }
    _stub_live(monkeypatch, tmp_path, payload_slides=[slide], stub_content_assert=False)
    _patch_build_export_script_capture(monkeypatch)

    captured = {}

    def fake_assert(path, width, height, *, duration, expected=None, log=print):
        captured["expected"] = expected

    monkeypatch.setattr(dme, "_assert_clip_covers_frame", fake_assert)

    dme.export_slide_clips(fw, [11], out_dir, per_movie=True, log=lambda *_: None)

    assert captured["expected"] == Rect(0.0, 0.0, 2080.0, 1080.0)


def test_export_slide_clips_per_movie_odd_intersection_normalizes_with_matching_geometry(monkeypatch, tmp_path):
    """A 101x100 visible intersection normalizes to an even 102x100 published size;
    `ClipResult.width`/`height` must be that actual published size, and `crop_rect` the
    same even-normalised wall-space crop actually used, so their aspects agree exactly
    (no drift) and the assembler can fit from the same reported geometry."""
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    slide = {
        "number": 1,
        "items": [
            {"kind": "movie", "kindIndex": 0, "x": 2000.0, "y": 10.0, "w": 101.0, "h": 100.0},
        ],
    }
    cls = SlideClass(1, "mixed", 0, 1, (("movie", 0),), (), (), None, 0, ())
    _stub_live(monkeypatch, tmp_path, payload_slides=[slide], stub_content_assert=True)
    monkeypatch.setattr(dme, "classify_deck", lambda path, **k: [cls])
    _patch_build_export_script_capture(monkeypatch)

    def fake_ffmpeg_process(raw, dest, *, crop_rect, wall_w, wall_h, codec):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"movie-bytes")
        x, y, w, h = dme._clamp_crop(crop_rect, wall_w, wall_h)
        return dme._normalize_even_crop(x, y, w, h, wall_w, wall_h)[2:]

    monkeypatch.setattr(dme, "_ffmpeg_process", fake_ffmpeg_process)
    monkeypatch.setattr(dme, "_ffprobe", lambda path: (102, 100, 30.0, 8.43))

    results = dme.export_slide_clips(fw, [1], out_dir, per_movie=True, log=lambda *_: None)

    assert len(results) == 1
    r = results[0]
    assert (r.width, r.height) == (102, 100)
    assert (r.crop_rect.w, r.crop_rect.h) == (102, 100)
    aspect_reported = r.crop_rect.w / r.crop_rect.h
    aspect_output = r.width / r.height
    assert abs(aspect_reported - aspect_output) / aspect_output < 0.005


def _per_movie_jobs():
    return [
        dme._SlideJob(
            12,
            1,
            Rect(1920.0, 0.0, 1920.0, 1080.0),
            Path("/out/Sermon.012.01.mov"),
            Path("/work/tmp.0012.01.m4v"),
            delete_ids=(("movie", 1), ("image", 0)),
            movie_id=("movie", 0),
        ),
        dme._SlideJob(
            12,
            1,
            Rect(3840.0, 0.0, 1920.0, 1080.0),
            Path("/out/Sermon.012.02.mov"),
            Path("/work/tmp.0012.02.m4v"),
            delete_ids=(("movie", 0), ("image", 0)),
            movie_id=("movie", 1),
        ),
    ]


def _per_movie_script():
    return dme._build_export_script(
        scratch_path=Path("/Users/x/Desktop/dsk-d3-work/.dsk-export-Sermon/Sermon.key"),
        stem="Sermon",
        layout_template=None,
        per_slide=_per_movie_jobs(),
        codec="AppleProRes422LT",
        fps=30,
    )


def test_script_has_one_export_clause_per_movie_item():
    script = _per_movie_script()
    assert script.count("export theDoc to POSIX file") == 2
    for job in _per_movie_jobs():
        assert str(job.tmp) in script


def test_script_per_movie_duplicates_and_deletes_scratch_slide():
    script = _per_movie_script()
    assert script.count("duplicate slide 1 to after slide 1 of theDoc") == 2
    # One success-path delete (unindented under "tell theDoc") and one error-path delete
    # (nested inside the export's on-error handler) per job -- four occurrences total.
    assert script.count("delete slide 2 of theDoc") == 4
    lines = script.splitlines()
    assert lines.count("      delete slide 2 of theDoc") == 2
    assert lines.count("          delete slide 2 of theDoc") == 2
    assert "movie 2 of slide 2" in script  # deletes the OTHER movie (kindIndex 1) for job 1
    assert "movie 1 of slide 2" in script  # deletes the OTHER movie (kindIndex 0) for job 2


def test_script_per_movie_resets_duplicate_transition_before_export():
    """The duplicate's outgoing transition must be cleared before export, so a per-movie
    pure clip never bakes the source slide's magic move/dissolve -- the assembler adds
    its own dissolve on the assembled DSK slide separately."""
    script = _per_movie_script()
    clause = "set transition properties of slide 2 to {transition effect:no transition effect}"
    assert script.count(clause) == 2
    lines = script.splitlines()
    transition_idxs = [i for i, line in enumerate(lines) if clause in line]
    export_idxs = [i for i, line in enumerate(lines) if "export theDoc to POSIX file" in line]
    assert len(transition_idxs) == len(export_idxs) == 2
    for t_idx, e_idx in zip(transition_idxs, export_idxs):
        assert t_idx < e_idx


def test_script_per_movie_export_error_deletes_scratch_slide_before_reraising():
    """If the per-movie export itself errors, the AppleScript must delete the duplicate
    scratch slide (in a nested try/on error) before re-raising, so a failed batch never
    leaves a stray slide behind in the scratch deck."""
    script = _per_movie_script()
    for job in _per_movie_jobs():
        marker = (
            f'log ("ERR" & tab & "{job.slide}" & tab & "{job.movie_id[1]}" & tab & errNum & tab & errMsg)'
        )
        idx = script.index(marker)
        following = script[idx : idx + 400]
        assert following.index("try") < following.index("delete slide 2 of theDoc") < following.index(
            "end try"
        ) < following.index("error errMsg number errNum")


def test_script_locked_guard_is_its_own_try_and_delete_still_follows():
    """Some Keynote builds raise -1728 ("Can't get locked of ...") for the `group` class
    even when the object exists and is deletable -- the locked-unlock probe must not abort
    the whole delete block when that happens. Covers both the whole-slide and per-movie
    delete emission, which share `_delete_block`."""
    for script in (_sample_script(), _per_movie_script()):
        lines = script.splitlines()
        locked_idxs = [i for i, line in enumerate(lines) if "if locked of theObj then set locked of theObj to false" in line]
        assert locked_idxs
        for idx in locked_idxs:
            assert lines[idx - 1].strip() == "try"
            assert lines[idx + 1].strip() == "end try"
            assert lines[idx - 2].strip().startswith("set theObj to")
            outer_try_idx = idx - 3
            assert lines[outer_try_idx].strip() == "try"
            following = "\n".join(lines[idx + 2 : idx + 20])
            assert "delete theObj" in following or "showing to false" in following


def test_derive_pure_video_delete_ids_orders_fw12_group_last_within_its_class():
    """Real FW deck item set for a per-movie slide with a standalone `group` item (a
    watermark/badge unrelated to any movie), read from `DSK_Gen_Export_Input.key` slide
    12: 4 images, 1 kept movie, 1 group. The derived delete set must carry every
    non-movie item and stay in `_delete_order` (descending kindIndex per class)."""
    items = [
        {"kind": "image", "kindIndex": 0},
        {"kind": "image", "kindIndex": 1},
        {"kind": "image", "kindIndex": 2},
        {"kind": "image", "kindIndex": 3},
        {"kind": "movie", "kindIndex": 0},
        {"kind": "group", "kindIndex": 0},
    ]
    movie_id = ("movie", 0)
    delete_ids = dme._derive_pure_video_delete_ids(items, movie_id)
    assert movie_id not in delete_ids
    assert set(delete_ids) == {
        ("image", 0),
        ("image", 1),
        ("image", 2),
        ("image", 3),
        ("group", 0),
    }
    by_kind: dict[str, list[int]] = {}
    for kind, kind_index in delete_ids:
        by_kind.setdefault(kind, []).append(kind_index)
    for kind_indexes in by_kind.values():
        assert kind_indexes == sorted(kind_indexes, reverse=True)


# --------------------------------------------------------------------------
# movie_order -- visual for side-by-side rows, SOURCE BUILD ORDER when stacked
# --------------------------------------------------------------------------
def test_movies_stacked_false_for_side_by_side_panels():
    # Two centre/right panels that merely abut share an edge but no area: they stay
    # "unstacked" and keep the plain left-to-right visual order.
    rects = {("movie", 0): Rect(0, 0, 3840, 1080), ("movie", 1): Rect(3840, 0, 3840, 1080)}
    assert not dme.movies_stacked(rects)
    assert dme.movie_order(rects) == [("movie", 0), ("movie", 1)]


def test_movies_stacked_false_for_hairline_clip():
    # A sliver of overlap (1% of the smaller rect's area) is a layout hairline, not a stack.
    rects = {("movie", 0): Rect(0, 0, 1000, 1000), ("movie", 1): Rect(990, 0, 1000, 1000)}
    assert not dme.movies_stacked(rects)
    assert dme.movie_order(rects) == [("movie", 0), ("movie", 1)]


def test_movies_stacked_false_for_a_pair_covering_four_fifths_of_the_smaller():
    # Owner 2026-09-20: the threshold is 0.9, so a heavy clip -- 1600x1080 of the smaller
    # 2000x1080, i.e. 0.8 -- is still a row, not a layered pair.
    rects = {("movie", 0): Rect(1920, 0, 2000, 1080), ("movie", 1): Rect(2320, 0, 2000, 1080)}
    assert not dme.movies_stacked(rects)
    assert dme.movie_order(rects) == [("movie", 0), ("movie", 1)]


def test_movies_stacked_true_just_above_the_threshold():
    # 1900x1080 of the smaller 2000x1080 = 0.95, over the 0.9 threshold.
    rects = {("movie", 0): Rect(1920, 0, 2000, 1080), ("movie", 1): Rect(2020, 0, 2000, 1080)}
    assert dme.movies_stacked(rects)
    assert dme.stack_mode(rects) == "stacked"


def test_movies_stacked_true_for_the_visible_slide_50_shape():
    # Full_Report_Card_Wall.key slide 50 clipped to the centre panel: movie 1 is 5 px
    # narrower INSIDE movie 0, so the intersection is 100% of the smaller visible rect.
    # The FULL item rects only overlap ~0.58 and no longer count as a stack.
    rects = {
        ("movie", 0): Rect(1920, -1079, 3840, 2160),
        ("movie", 1): Rect(1915, -163, 3840, 2160),
    }
    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    assert (visible[("movie", 0)].x, visible[("movie", 0)].w) == (1920.0, 3840.0)
    assert (visible[("movie", 1)].x, visible[("movie", 1)].w) == (1920.0, 3835.0)
    assert dme.movies_stacked(visible)
    assert not dme.movies_stacked(rects)


def test_movie_order_stacked_follows_source_build_order_not_x():
    # Visually movie 1 sorts first (x 1915 < 1920), but movie 0 carries the
    # apple:movie-start build at chunk 0 and movie 1 the apple:dissolve In at chunk 1:
    # movie 0 plays, then movie 1 dissolves in on top.
    rects = {
        ("movie", 0): Rect(1920, -1079, 3840, 2160),
        ("movie", 1): Rect(1915, -163, 3840, 2160),
    }
    assert dme.visual_movie_order(rects) == [("movie", 1), ("movie", 0)]
    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    order = dme.movie_order(visible, {("movie", 0): 0, ("movie", 1): 1})
    assert order == [("movie", 0), ("movie", 1)]


def test_movie_order_stacked_movie_without_build_sorts_first_by_z():
    rects = {
        ("movie", 0): Rect(1920, 0, 3840, 1080),
        ("movie", 1): Rect(1920, 0, 3840, 1080),
        ("movie", 2): Rect(1920, 0, 3840, 1080),
    }
    order = dme.movie_order(
        rects,
        {("movie", 1): 3},
        {("movie", 0): 7, ("movie", 2): 2},
    )
    assert order == [("movie", 2), ("movie", 0), ("movie", 1)]


def test_movie_order_stacked_refuses_without_build_order():
    rects = {
        ("movie", 0): Rect(1920, 0, 3840, 1080),
        ("movie", 1): Rect(1920, 0, 3840, 1080),
    }
    with pytest.raises(ValueError, match="stacked"):
        dme.movie_order(rects)


def test_movie_order_stacked_refuses_on_build_order_tie():
    rects = {
        ("movie", 0): Rect(1920, 0, 3840, 1080),
        ("movie", 1): Rect(1920, 0, 3840, 1080),
    }
    with pytest.raises(ValueError, match="tie at build order"):
        dme.movie_order(rects, {("movie", 0): 1, ("movie", 1): 1})


def test_movie_order_stacked_refuses_unbuilt_movie_without_z_order():
    rects = {
        ("movie", 0): Rect(1920, 0, 3840, 1080),
        ("movie", 1): Rect(1920, 0, 3840, 1080),
    }
    with pytest.raises(ValueError, match="no build and no z-order"):
        dme.movie_order(rects, {("movie", 0): 0})


def test_stack_mode_refuses_a_partial_stack():
    # Two movies cover each other, a third sits beside them: visual order and build order
    # each govern part of the slide, so there is no single order to derive.
    rects = {
        ("movie", 0): Rect(1920, 0, 3840, 1080),
        ("movie", 1): Rect(1920, 0, 3840, 1080),
        ("movie", 2): Rect(5760, 0, 1920, 1080),
    }
    with pytest.raises(ValueError, match="partially overlap"):
        dme.stack_mode(rects)
    with pytest.raises(ValueError, match="partially overlap"):
        dme.movie_order(rects, {("movie", 0): 0, ("movie", 1): 1, ("movie", 2): 2})


def test_stack_mode_visual_for_a_row_whose_neighbours_clip():
    # Codex r2: three movies side by side in the centre panel, each adjacent pair clipping
    # into the next by ~6% of the smaller visible area (the outer two do not meet at all).
    # Clipping is not layering: the row is ordinary, so it keeps the visual order instead
    # of refusing as a partial stack.
    rects = {
        ("movie", 0): Rect(1920, 0, 1400, 1080),
        ("movie", 1): Rect(3236, 0, 1400, 1080),
        ("movie", 2): Rect(4552, 0, 1400, 1080),
    }
    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    assert dme.stack_mode(visible) == "visual"
    assert not dme.movies_stacked(visible)
    assert dme.movie_order(visible) == [("movie", 0), ("movie", 1), ("movie", 2)]


def test_stack_mode_stacked_for_the_visible_slide_50_shape():
    # Full_Report_Card_Wall.key slide 50 still layers once clipped to the centre panel:
    # each movie's visible rect is all but covered by the other.
    rects = {
        ("movie", 0): Rect(1920, -1079, 3840, 2160),
        ("movie", 1): Rect(1915, -163, 3840, 2160),
    }
    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    assert dme.stack_mode(visible) == "stacked"


def test_stack_mode_refuses_a_partial_stack_of_nearly_covered_movies():
    # A genuine partial stack: movies 0 and 1 cover 95% of each other (over the 0.9
    # threshold), movie 2 sits clear of both. Real layering plus a plain neighbour still
    # has no single order.
    rects = {
        ("movie", 0): Rect(1920, 0, 2000, 1080),
        ("movie", 1): Rect(2020, 0, 2000, 1080),
        ("movie", 2): Rect(4100, 0, 1000, 1080),
    }
    with pytest.raises(ValueError, match="partially overlap"):
        dme.stack_mode(rects)


def test_stack_mode_visual_for_a_pair_below_the_threshold_beside_a_third():
    # The same shape at 80% overlap is no longer a stack at all, so the slide is an
    # ordinary row and keeps the visual order instead of refusing.
    rects = {
        ("movie", 0): Rect(1920, 0, 2000, 1080),
        ("movie", 1): Rect(2320, 0, 2000, 1080),
        ("movie", 2): Rect(4600, 0, 1000, 1080),
    }
    assert dme.stack_mode(rects) == "visual"
    assert dme.movie_order(rects) == [("movie", 0), ("movie", 1), ("movie", 2)]


def test_visible_movie_rects_decide_the_mode_the_full_rects_would_miss():
    # Codex r1: the full item rects only clip (a third of the smaller), but what the clip
    # actually shows -- the centre-panel crop, which cuts movie 0 down to the sliver that
    # movie 1 covers -- is a stack. One predicate, one mode.
    rects = {("movie", 0): Rect(0, 0, 3000, 1080), ("movie", 1): Rect(2000, 0, 3000, 1080)}
    assert dme.stack_mode(rects) == "visual"

    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    assert dme.stack_mode(visible) == "stacked"
    # the caller's already-decided mode wins over re-deriving it from the rects passed in
    order = dme.movie_order(rects, {("movie", 0): 1, ("movie", 1): 0}, mode="stacked")
    assert order == [("movie", 1), ("movie", 0)]


def test_visible_movie_rects_clip_to_the_crop_and_zero_outside_it():
    rects = {("movie", 0): Rect(1920, 0, 3840, 1080), ("movie", 1): Rect(0, 0, 100, 1080)}
    visible = dme.visible_movie_rects(rects, dme.CENTRE_PANEL_RECT)
    assert (visible[("movie", 0)].x, visible[("movie", 0)].w) == (1920.0, 3840.0)
    assert visible[("movie", 1)].w == 0.0
    assert dme.stack_mode(visible) == "visual"


def test_movie_build_order_takes_the_lowest_chunk_per_movie():
    records = [
        {"kind": "movie", "kindIndex": 0, "chunkOrder": [3, 1]},
        {"kind": "movie", "kindIndex": 1, "chunkOrder": [2]},
        {"kind": "movie", "kindIndex": 2, "chunkOrder": []},
        {"kind": "image", "kindIndex": 0, "chunkOrder": [0]},
    ]
    order = dme.movie_build_order(records, [("movie", 0), ("movie", 1), ("movie", 2)])
    assert order == {("movie", 0): 1, ("movie", 1): 2}
