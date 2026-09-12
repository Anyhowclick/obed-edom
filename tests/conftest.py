from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable

import pytest

os.environ.setdefault("OBED_OFFLINE_WRITE", "off")

# The dashboard app builds its JobRunner at import time, and a finished run is
# saved to disk. Without this, every test that touches the app leaves sessions
# in the real output/.sessions, and they turn up in the dashboard's History
# pointing at pytest temp files that no longer exist ("files missing").
_TEST_OUTPUT_ROOT = tempfile.mkdtemp(prefix="obed-edom-tests-")
os.environ.setdefault("OBED_EDOM_OUTPUT_ROOT", _TEST_OUTPUT_ROOT)

# `defaultExportDir` reads from cache_root()/settings.json. Without this, a
# developer's real settings.json (in the repo .cache) would leak into tests.
_TEST_CACHE_ROOT = tempfile.mkdtemp(prefix="obed-edom-tests-cache-")
os.environ.setdefault("OBED_EDOM_CACHE_DIR", _TEST_CACHE_ROOT)


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_TEST_OUTPUT_ROOT, ignore_errors=True)
    shutil.rmtree(_TEST_CACHE_ROOT, ignore_errors=True)


def _fake_osascript(
    monkeypatch,
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    on_argv: Callable[[list[str]], None] | None = None,
):
    """Patch the runner's private ``_execute`` seam (never the shared ``subprocess``
    module) so ``run_applescript``/``run_jxa`` complete immediately with the given
    result, instead of launching real osascript."""
    from obed_edom import osascript_runner

    def fake_execute(argv, *, timeout=None, is_cancelled=None):
        if on_argv is not None:
            on_argv(argv)
        return osascript_runner.OsaResult(
            argv=argv, returncode=returncode, stdout=stdout, stderr=stderr, elapsed=0.0
        )

    monkeypatch.setattr(osascript_runner, "_execute", fake_execute)
    monkeypatch.setattr(osascript_runner, "_launch_keynote", lambda: None)


@pytest.fixture
def live_osascript():
    """Opt a test out of the real-osascript tripwire below."""
    yield


@pytest.fixture(autouse=True)
def _no_real_osascript(request, monkeypatch):
    """Every osascript-runner call goes through ``_execute``; fail loudly instead of
    launching real Keynote when a test forgets to mock it. A test that genuinely needs
    the real executor (the PATH-stub timeout test, and the unrelated ``osacompile``
    test that never touches this module) opts out via ``live_osascript``."""
    if "live_osascript" in request.fixturenames:
        yield
        return
    from obed_edom import osascript_runner

    def _boom(*args, **kwargs):
        raise AssertionError(f"real osascript in tests: {args}")

    monkeypatch.setattr(osascript_runner, "_execute", _boom)
    monkeypatch.setattr(osascript_runner, "_launch_keynote", _boom)
    yield
