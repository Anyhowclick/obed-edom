"""Resolve which Keynote to drive, by bundle id never by name.

15.x is ``com.apple.Keynote`` (this tool's only supported version). 14.x was
``com.apple.iWork.Keynote``; both name themselves "Keynote". Override with
``OBED_EDOM_KEYNOTE_BUNDLE_ID`` (also partitions the inspect cache).
"""

from __future__ import annotations

import os
import plistlib
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

BUNDLE_ID_ENV = "OBED_EDOM_KEYNOTE_BUNDLE_ID"
KEYNOTE_BUNDLE_ID = "com.apple.Keynote"
UNKNOWN_VERSION = "unknown"

_SEARCH_DIRS = ("/Applications", "~/Applications")
_LIKELY_NAMES = ("Keynote Creator Studio.app", "Keynote.app")


def _bundle_info(app: Path) -> dict | None:
    """Parsed Info.plist, or None. Failures skip the app — third-party bundles can be malformed."""
    try:
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            return plistlib.load(handle)
    except Exception:  # noqa: BLE001 - malformed third-party plists must not abort resolution
        return None


def _candidate_apps() -> Iterator[Path]:
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
    return _from_workspace(identifier) or _from_disk(identifier)


@lru_cache(maxsize=None)
def bundle_id() -> str:
    """Returned even if the app is missing, so a miss names the identifier that was asked for."""
    return (os.environ.get(BUNDLE_ID_ENV) or "").strip() or KEYNOTE_BUNDLE_ID


@lru_cache(maxsize=None)
def app_version(identifier: str | None = None) -> str:
    path = app_path(identifier or bundle_id())
    info = _bundle_info(path) if path is not None else None
    if not info:
        return UNKNOWN_VERSION
    return str(info.get("CFBundleShortVersionString") or UNKNOWN_VERSION)


def clear_cache() -> None:
    app_path.cache_clear()
    bundle_id.cache_clear()
    app_version.cache_clear()
