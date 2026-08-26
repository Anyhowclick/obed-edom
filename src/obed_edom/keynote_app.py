"""Which Keynote to drive.

Keynote 15 ships as "Keynote Creator Studio" with bundle identifier
``com.apple.Keynote``, while 14.x is ``com.apple.iWork.Keynote``. Both set their
bundle name to "Keynote", so ``tell application "Keynote"`` reaches whichever
LaunchServices happens to prefer — 14.5 on a machine with both installed. Every
AppleScript, JXA and ``open`` call therefore addresses Keynote by bundle
identifier, and this module is the single place that decides which one.

**This tool is Keynote 15.x only.** 14.x support was removed deliberately once the
staff machines were confirmed on 15.3.1. If something breaks in a way that smells
like a scripting difference — a master not found, a collection that will not
enumerate, an export that silently produces nothing — a 14.x machine is one of the
first things to rule out, and the fix is to restore a fallback here rather than to
work around it at the call site.

Set ``OBED_EDOM_KEYNOTE_BUNDLE_ID`` to drive a different build, which also
partitions the inspect cache so payloads from two builds cannot overwrite each
other.

Resolution asks LaunchServices first, which is one targeted lookup and touches no
other app. Reading ``Info.plist`` off disk is the fallback for when LaunchServices
is unavailable, as it is inside a sandbox; that path checks the names Keynote has
shipped under before scanning, so it rarely has to parse unrelated bundles.
"""

from __future__ import annotations

import os
import plistlib
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

BUNDLE_ID_ENV = "OBED_EDOM_KEYNOTE_BUNDLE_ID"
# Keynote 15.x. 14.x was com.apple.iWork.Keynote and is no longer supported.
KEYNOTE_BUNDLE_ID = "com.apple.Keynote"
UNKNOWN_VERSION = "unknown"

_SEARCH_DIRS = ("/Applications", "~/Applications")
# Tried before scanning, so a hit parses one Apple bundle rather than every app on
# the machine. 15.x ships under the Creator Studio name; plain "Keynote.app" is
# still checked because that is what a future rename would most likely go back to.
_LIKELY_NAMES = ("Keynote Creator Studio.app", "Keynote.app")


def _bundle_info(app: Path) -> dict | None:
    """Parsed ``Info.plist``, or None when it cannot be read.

    The fallback scan reaches arbitrary third-party bundles, and malformed ones do
    exist — a truncated binary plist raises from ``plistlib``, invalid XML raises
    ``ExpatError``. None of them may stop us finding Keynote, so any failure just
    skips that app.
    """
    try:
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            return plistlib.load(handle)
    except Exception:  # noqa: BLE001 - see docstring
        return None


def _candidate_apps() -> Iterator[Path]:
    """Apps to inspect, the names Keynote uses first, then everything else."""
    bases = [Path(folder).expanduser() for folder in _SEARCH_DIRS]
    seen: set[Path] = set()
    for base in bases:
        for name in _LIKELY_NAMES:
            app = base / name
            if app.is_dir():
                seen.add(app)
                yield app
    for base in bases:
        if not base.is_dir():
            continue
        for app in sorted(base.glob("*.app")):
            if app not in seen:
                yield app


def _from_disk(identifier: str) -> Path | None:
    for app in _candidate_apps():
        info = _bundle_info(app)
        if info and info.get("CFBundleIdentifier") == identifier:
            return app
    return None


def _from_workspace(identifier: str) -> Path | None:
    try:
        from AppKit import NSWorkspace  # noqa: PLC0415
    except ImportError:
        return None
    try:
        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(identifier)
    except Exception:  # noqa: BLE001 - a LaunchServices miss must never break generate
        return None
    path = url.path() if url is not None else None
    return Path(str(path)) if path else None


@lru_cache(maxsize=None)
def app_path(identifier: str) -> Path | None:
    """Where the app with this bundle identifier lives, or None if absent."""
    return _from_workspace(identifier) or _from_disk(identifier)


@lru_cache(maxsize=None)
def bundle_id() -> str:
    """The bundle identifier every Keynote call should target.

    Returned whether or not the app is installed, so a missing Keynote fails
    naming the identifier that was asked for rather than silently falling back to
    another build.
    """
    return (os.environ.get(BUNDLE_ID_ENV) or "").strip() or KEYNOTE_BUNDLE_ID


@lru_cache(maxsize=None)
def app_version(identifier: str | None = None) -> str:
    """``CFBundleShortVersionString`` of the targeted app, e.g. ``15.3.1``."""
    path = app_path(identifier or bundle_id())
    info = _bundle_info(path) if path is not None else None
    if not info:
        return UNKNOWN_VERSION
    return str(info.get("CFBundleShortVersionString") or UNKNOWN_VERSION)


def clear_cache() -> None:
    """Forget resolution, after the environment or the installed apps change."""
    app_path.cache_clear()
    bundle_id.cache_clear()
    app_version.cache_clear()
