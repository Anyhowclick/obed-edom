from __future__ import annotations

import os
import shutil
import tempfile

# The dashboard app builds its JobRunner at import time, and a finished run is
# saved to disk. Without this, every test that touches the app leaves sessions
# in the real output/.sessions, and they turn up in the dashboard's History
# pointing at pytest temp files that no longer exist ("files missing").
_TEST_OUTPUT_ROOT = tempfile.mkdtemp(prefix="obed-edom-tests-")
os.environ.setdefault("OBED_EDOM_OUTPUT_ROOT", _TEST_OUTPUT_ROOT)


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_TEST_OUTPUT_ROOT, ignore_errors=True)
