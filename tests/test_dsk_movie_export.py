"""Tests for obed_edom.dsk_movie_export: pure helpers, the generated AppleScript, and
a faked live export path. No test may launch Keynote; the autouse fixture below
raises if subprocess.run/Popen is reached without an explicit monkeypatch of the
module's own `_run_osascript`/`_ffprobe`/`_keynote_running` seams.
"""
from __future__ import annotations

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


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


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
    verify_idx = script.index("base layout verify failed")
    delete_donor_idx = script.index("if donorSlide is not missing value then delete donorSlide")
    assert verify_idx < delete_donor_idx


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
    assert "lname is in approvedBlackNames" in script
    assert "tname is in approvedBlackNames" in script
    assert "words of" not in script
    assert "begins with" not in script
    assert "blankName" not in script


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

    calls = {"osascript": 0}

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
