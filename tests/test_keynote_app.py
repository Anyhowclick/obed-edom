"""Which Keynote gets driven, and which cache partition it reads.

Keynote 15 ships as a separate app with its own bundle identifier while keeping
the bundle name "Keynote", so name-based lookup silently reaches 14.x on a
machine with both. These tests pin the two consequences: every generated script
addresses the app by bundle id, and a payload read by one version is never handed
to the other.
"""

from pathlib import Path

import pytest
from obed_edom import keynote_app
from obed_edom.baseline import (
    LEGACY_APP_VERSION,
    inspect_cache_candidates,
    inspect_cache_path,
    legacy_inspect_cache_path,
    legacy_preview_cache_dir,
    preview_cache_candidates,
    preview_cache_dir,
)
from obed_edom.inspect import export_applescript


@pytest.fixture(autouse=True)
def _fresh_resolution():
    keynote_app.clear_cache()
    yield
    keynote_app.clear_cache()


def test_pinned_bundle_id_wins(monkeypatch):
    monkeypatch.setenv(keynote_app.BUNDLE_ID_ENV, "com.apple.iWork.Keynote")
    assert keynote_app.bundle_id() == "com.apple.iWork.Keynote"


def test_pinned_bundle_id_is_returned_even_when_absent(monkeypatch):
    """So the failure names the version that was asked for."""
    monkeypatch.setenv(keynote_app.BUNDLE_ID_ENV, "com.example.NotKeynote")
    assert keynote_app.bundle_id() == "com.example.NotKeynote"
    assert keynote_app.app_version() == keynote_app.UNKNOWN_VERSION


def test_unpinned_prefers_keynote_15(monkeypatch):
    monkeypatch.delenv(keynote_app.BUNDLE_ID_ENV, raising=False)
    monkeypatch.setattr(keynote_app, "_from_workspace", lambda identifier: None)
    monkeypatch.setattr(keynote_app, "_from_disk", lambda identifier: Path("/Applications/x.app"))
    keynote_app.clear_cache()
    assert keynote_app.bundle_id() == "com.apple.Keynote"


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


def test_falls_back_to_keynote_14_when_15_is_absent(monkeypatch):
    monkeypatch.delenv(keynote_app.BUNDLE_ID_ENV, raising=False)
    monkeypatch.setattr(
        keynote_app,
        "_from_disk",
        lambda identifier: Path("/Applications/Keynote.app")
        if identifier == "com.apple.iWork.Keynote"
        else None,
    )
    monkeypatch.setattr(keynote_app, "_from_workspace", lambda identifier: None)
    keynote_app.clear_cache()
    assert keynote_app.bundle_id() == "com.apple.iWork.Keynote"


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


def test_only_the_legacy_version_reads_untagged_payloads(tmp_path: Path):
    """The banked baseline stays a live cache for 14.5 and is invisible to 15.x."""
    legacy = legacy_inspect_cache_path("abc", tmp_path)
    assert legacy in inspect_cache_candidates("abc", tmp_path, app_version=LEGACY_APP_VERSION)
    assert legacy not in inspect_cache_candidates("abc", tmp_path, app_version="15.3.1")

    legacy_dir = legacy_preview_cache_dir("abc", tmp_path)
    assert legacy_dir in preview_cache_candidates("abc", tmp_path, app_version=LEGACY_APP_VERSION)
    assert legacy_dir not in preview_cache_candidates("abc", tmp_path, app_version="15.3.1")


def test_untagged_payloads_are_never_written_again(tmp_path: Path):
    """Writes always go to the tagged name, so a 14.5 re-inspect cannot overwrite
    the macOS 14 baseline it would otherwise collide with."""
    written = inspect_cache_path("abc", tmp_path, app_version=LEGACY_APP_VERSION)
    assert written != legacy_inspect_cache_path("abc", tmp_path)


def test_app_version_is_filename_safe(tmp_path: Path):
    path = inspect_cache_path("abc", tmp_path, app_version="15.3.1 (beta/2)")
    assert "/" not in path.name.replace(".json", "")
    assert " " not in path.name
