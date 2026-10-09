import threading
import time
from pathlib import Path

import pytest

from obed_edom.devtools_port import parse_devtools_active_port, wait_devtools_active_port


@pytest.mark.parametrize(
    ("text", "port"),
    [
        ("9222\n/devtools/browser/abc\n", 9222),
        ("51234\n/devtools/browser/abc", 51234),
        ("65535\r\n/devtools/browser/abc\r\n", 65535),
        ("", None),
        ("9222", None),
        ("9222\n", None),
        ("92", None),
        ("9222\n   \n", None),
        ("0\n/devtools/browser/abc", None),
        ("65536\n/devtools/browser/abc", None),
        ("-1\n/devtools/browser/abc", None),
        ("92a2\n/devtools/browser/abc", None),
        (" 9222\n/devtools/browser/abc", None),
        ("\u0669\u0662\n/devtools/browser/abc", None),
    ],
)
def test_parse_devtools_active_port(text, port):
    """Only a complete file (port line and browser path line) yields a port; a partial write,
    a non-ASCII digit string or an out-of-range number never does."""
    assert parse_devtools_active_port(text) == port


class _Proc:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_wait_devtools_active_port_returns_once_the_file_is_complete(tmp_path):
    path = tmp_path / "DevToolsActivePort"

    def write():
        path.write_text("51")
        time.sleep(0.1)
        path.write_text("51234\n/devtools/browser/abc\n")

    writer = threading.Timer(0.1, write)
    writer.start()
    try:
        assert wait_devtools_active_port(tmp_path, _Proc(), timeout_s=5.0, poll_s=0.01) == 51234
    finally:
        writer.join()


def test_wait_devtools_active_port_fails_fast_when_chrome_exits(tmp_path):
    start = time.monotonic()
    with pytest.raises(RuntimeError, match=r"Chrome exited \(1\) before writing"):
        wait_devtools_active_port(tmp_path, _Proc(returncode=1), timeout_s=30.0)
    assert time.monotonic() - start < 1.0


def test_wait_devtools_active_port_times_out_on_a_never_complete_file(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222")
    with pytest.raises(RuntimeError, match="within 0.2 s"):
        wait_devtools_active_port(tmp_path, _Proc(), timeout_s=0.2, poll_s=0.01)


def test_wait_devtools_active_port_reads_a_file_left_by_a_chrome_that_then_exited(tmp_path):
    """The port file is read before the exit check, so a complete file is never discarded; the caller
    removes any stale file before launch (`attach_chrome`, `ChromeCdp._spawn`)."""
    (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
    assert wait_devtools_active_port(Path(tmp_path), _Proc(returncode=0), timeout_s=0.1) == 9333
