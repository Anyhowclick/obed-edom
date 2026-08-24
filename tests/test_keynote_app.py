"""Which Keynote gets driven, and which cache partition it reads.

Keynote 15 ships as a separate app with its own bundle identifier while keeping
the bundle name "Keynote", so name-based lookup reaches whichever build
LaunchServices prefers. These tests pin the two consequences: every generated
script addresses the app by bundle id, and a payload produced by one build is
never handed to a run of another.

The tool is 15.x only, so there is deliberately no fallback to another build.
"""

from pathlib import Path

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
    untagged = tmp_path / "output" / ".cache" / "inspect" / "abc.v2.json"
    assert inspect_cache_path("abc", tmp_path, app_version="15.3.1") != untagged


def test_app_version_is_filename_safe(tmp_path: Path):
    path = inspect_cache_path("abc", tmp_path, app_version="15.3.1 (beta/2)")
    assert "/" not in path.name.replace(".json", "")
    assert " " not in path.name
