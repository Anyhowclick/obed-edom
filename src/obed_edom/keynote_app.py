"""Which Keynote to drive.

Keynote 15 ships as "Keynote Creator Studio" with bundle identifier
``com.apple.Keynote``, while 14.x is ``com.apple.iWork.Keynote``. Both set their
bundle name to "Keynote", so ``tell application "Keynote"`` reaches whichever
LaunchServices happens to prefer — 14.5 on a machine with both installed. Every
AppleScript, JXA and ``open`` call therefore addresses Keynote by bundle
identifier, and this module is the single place that decides which one.

Set ``OBED_EDOM_KEYNOTE_BUNDLE_ID`` to pin a version. That is how one Keynote is
compared against another on the same machine, where the OS is held constant: the
same variable also partitions the inspect cache, so a 14.5 payload and a 15.x
payload of the same deck coexist instead of overwriting each other.

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
# Newest first. A machine with both installed should be driven by the version the
# church machines run, not by whichever one LaunchServices answers with.
KNOWN_BUNDLE_IDS = ("com.apple.Keynote", "com.apple.iWork.Keynote")
UNKNOWN_VERSION = "unknown"

_SEARCH_DIRS = ("/Applications", "~/Applications")
# Tried before scanning: the names Keynote has shipped under. A hit here means two
# Apple bundles are parsed instead of every app on the machine.
_LIKELY_NAMES = ("Keynote.app", "Keynote Creator Studio.app")


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

    A pinned value is returned even when that app is not installed, so the
    resulting failure names the version that was asked for.
    """
    pinned = (os.environ.get(BUNDLE_ID_ENV) or "").strip()
    if pinned:
        return pinned
    for identifier in KNOWN_BUNDLE_IDS:
        if app_path(identifier) is not None:
            return identifier
    return KNOWN_BUNDLE_IDS[0]


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
