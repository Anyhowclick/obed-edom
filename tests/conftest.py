from __future__ import annotations

import os
import shutil
import tempfile

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
