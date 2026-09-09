"""Which Keynote gets driven, and which cache partition it reads.

Keynote 15 ships as a separate app with its own bundle identifier while keeping
the bundle name "Keynote", so name-based lookup reaches whichever build
LaunchServices prefers. These tests pin the two consequences: every generated
script addresses the app by bundle id, and a payload produced by one build is
never handed to a run of another.

The tool is 15.x only, so there is deliberately no fallback to another build.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from obed_edom import keynote_app
from obed_edom.baseline import inspect_cache_path, preview_cache_dir
from obed_edom.inspect import export_applescript


@pytest.fixture(autouse=True)
def _fresh_resolution():
    keynote_app.clear_cache()
    yield
    keynote_app.clear_cache()


def test_pinned_bundle_id_wins(monkeypatch):
    """For driving a different 15.x build, e.g. a beta, against its own cache
    partition. Not for reviving 14.x."""
    monkeypatch.setenv(keynote_app.BUNDLE_ID_ENV, "com.apple.Keynote.beta")
    assert keynote_app.bundle_id() == "com.apple.Keynote.beta"


def test_defaults_to_keynote_15(monkeypatch):
    monkeypatch.delenv(keynote_app.BUNDLE_ID_ENV, raising=False)
    keynote_app.clear_cache()
    assert keynote_app.bundle_id() == "com.apple.Keynote"


def test_a_missing_app_never_falls_back_to_another_build(monkeypatch):
    """15.x only. The identifier asked for is the one that fails, by name, rather
    than a 14.x install quietly answering for it."""
    monkeypatch.setenv(keynote_app.BUNDLE_ID_ENV, "com.example.NotKeynote")
    monkeypatch.setattr(keynote_app, "_from_workspace", lambda identifier: None)
    monkeypatch.setattr(keynote_app, "_from_disk", lambda identifier: None)
    keynote_app.clear_cache()
    assert keynote_app.bundle_id() == "com.example.NotKeynote"
    assert keynote_app.app_version() == keynote_app.UNKNOWN_VERSION


def test_launchservices_answers_before_any_bundle_is_parsed(monkeypatch):
    """The disk scan is what reaches unrelated apps, so it must stay a fallback."""
    monkeypatch.delenv(keynote_app.BUNDLE_ID_ENV, raising=False)
    monkeypatch.setattr(
        keynote_app, "_from_workspace", lambda identifier: Path("/Applications/ls.app")
    )

    def _boom(identifier):
        raise AssertionError("scanned disk despite a LaunchServices hit")

    monkeypatch.setattr(keynote_app, "_from_disk", _boom)
    keynote_app.clear_cache()
    assert keynote_app.app_path("com.apple.Keynote") == Path("/Applications/ls.app")


def test_known_keynote_names_are_tried_before_scanning(monkeypatch, tmp_path: Path):
    apps = tmp_path / "Applications"
    (apps / "Keynote Creator Studio.app").mkdir(parents=True)
    (apps / "Aaa Unrelated.app").mkdir()
    monkeypatch.setattr(keynote_app, "_SEARCH_DIRS", (str(apps),))
    order = list(keynote_app._candidate_apps())
    assert order[0].name == "Keynote Creator Studio.app"
    assert order[-1].name == "Aaa Unrelated.app"


def test_scripts_address_keynote_by_bundle_id(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(keynote_app.BUNDLE_ID_ENV, "com.apple.Keynote")
    keynote_app.clear_cache()
    script = export_applescript(tmp_path / "deck.key", tmp_path / "out")
    assert 'tell application id "com.apple.Keynote"' in script
    assert 'using terms from application id "com.apple.Keynote"' in script
    assert 'application "Keynote"' not in script


def test_export_applescript_ordering_guards_and_cleanup(tmp_path: Path):
    script = export_applescript(tmp_path / "Sermon.key", tmp_path / "out")
    close_by_name = script.index('close (every document whose name is "Sermon") saving no')
    close_by_name_key = script.index(
        'close (every document whose name is "Sermon.key") saving no'
    )
    open_at = script.index("open theFile")
    bind_at = script.index('set theDocs to (every document whose name is "Sermon" '
                            'or name is "Sermon.key")')
    count_guard_at = script.index("if (count of theDocs) is 0 then error")
    item_bind_at = script.index("set theDoc to item 1 of theDocs")
    export_at = script.index("export theDoc to exportFolder as slide images")
    on_error_at = script.index("on error errMsg number errNum")
    close_doc_at = script.rindex("close theDoc saving no")

    assert close_by_name < close_by_name_key < open_at < bind_at
    assert bind_at < count_guard_at < item_bind_at < export_at < on_error_at < close_doc_at
    assert "with timeout of 3600 seconds" in script
    assert "activate" in script
    assert "document 1" not in script


def test_export_applescript_closes_by_name_and_reraises_on_export_error(tmp_path: Path):
    script = export_applescript(tmp_path / "Sermon.key", tmp_path / "out")
    on_error_at = script.index("on error errMsg number errNum")
    error_close = script.index('close (every document whose name is "Sermon") saving no',
                                on_error_at)
    reraise_at = script.index("error errMsg number errNum", error_close)
    assert on_error_at < error_close < reraise_at


def test_export_open_applescript_has_no_close_by_name_or_open(tmp_path: Path):
    from obed_edom.inspect import _export_open_applescript

    script = _export_open_applescript(tmp_path / "Sermon.key", tmp_path / "out")
    assert "open theFile" not in script
    assert "document 1" not in script
    bind_at = script.index('set theDocs to (every document whose name is "Sermon" '
                            'or name is "Sermon.key")')
    count_guard_at = script.index("if (count of theDocs) is 0 then error")
    item_bind_at = script.index("set theDoc to item 1 of theDocs")
    export_at = script.index("export theDoc to exportFolder as slide images")
    on_error_at = script.index("on error errMsg number errNum")
    close_doc_at = script.rindex("close theDoc saving no")
    assert bind_at < count_guard_at < item_bind_at < export_at < on_error_at < close_doc_at
    assert "with timeout of 3600 seconds" in script


def test_close_document_by_name_runs_osascript_with_both_name_forms(tmp_path: Path, monkeypatch):
    from obed_edom import inspect as inspect_mod

    captured: dict = {}

    def fake_run(args, **kwargs):
        script_path = Path(args[-1])
        captured["script"] = script_path.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    inspect_mod._close_document_by_name(tmp_path / "Sermon.key")
    script = captured["script"]
    assert 'name is "Sermon"' in script
    assert 'name is "Sermon.key"' in script
    assert "saving no" in script


# --- BLOCKER 4: a non-zero osascript exit always wins, even with stale PNGs -------


def test_run_applescript_export_nonzero_exit_wins_over_stale_pngs(tmp_path, monkeypatch):
    from obed_edom import inspect as inspect_mod

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    (export_dir / "stale.png").write_bytes(b"\x89PNG")

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="export bound wrong document")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    err = inspect_mod._run_applescript_export("script text", export_dir)
    assert err == "Preview export failed: export bound wrong document"


def test_run_applescript_export_expected_count_mismatch_is_an_error(tmp_path, monkeypatch):
    from obed_edom import inspect as inspect_mod

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    (export_dir / "slide-1.png").write_bytes(b"\x89PNG")

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    err = inspect_mod._run_applescript_export("script text", export_dir, expected=2)
    assert err == "Preview export wrote 1 of 2 PNGs"


def test_run_applescript_export_expected_count_match_succeeds(tmp_path, monkeypatch):
    from obed_edom import inspect as inspect_mod

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    (export_dir / "slide-1.png").write_bytes(b"\x89PNG")

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    assert inspect_mod._run_applescript_export("script text", export_dir, expected=1) is None


def test_set_export_state_explicit_error_wins_over_stale_pngs(tmp_path):
    from obed_edom import inspect as inspect_mod

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    (export_dir / "stale.png").write_bytes(b"\x89PNG")

    payload: dict = {}
    exported = inspect_mod._set_export_state(
        payload, export_dir, "Preview export failed: boom", failed=True
    )
    assert exported is False
    assert payload["exported"] is False
    assert payload["exportError"] == "Preview export failed: boom"


def test_cache_is_partitioned_by_app_version(tmp_path: Path):
    fifteen = inspect_cache_path("abc", tmp_path, app_version="15.3.1")
    fourteen = inspect_cache_path("abc", tmp_path, app_version="14.5")
    assert fifteen != fourteen
    assert "15.3.1" in fifteen.name
    assert preview_cache_dir("abc", tmp_path, app_version="15.3.1") != preview_cache_dir(
        "abc", tmp_path, app_version="14.5"
    )


def test_untagged_payloads_are_not_read(tmp_path: Path):
    """Pre-tag payloads were produced by 14.5 and must stay invisible, or a 15.x
    run would silently reuse a reading from an unsupported build."""
    untagged = tmp_path / ".cache" / "inspect" / "abc.v2.json"
    assert inspect_cache_path("abc", tmp_path, app_version="15.3.1") != untagged


def test_app_version_is_filename_safe(tmp_path: Path):
    path = inspect_cache_path("abc", tmp_path, app_version="15.3.1 (beta/2)")
    assert "/" not in path.name.replace(".json", "")
    assert " " not in path.name
