import io
import json
from pathlib import Path

import pytest

from fake_chrome import FakeChromeProcess, FakeTime
from obed_edom import devtools_port
from obed_edom.devtools_port import (
    DevToolsEndpoint,
    ForeignDevToolsEndpoint,
    parse_devtools_active_port,
    verify_devtools_owner,
    wait_devtools_active_port,
)


@pytest.mark.parametrize(
    ("text", "endpoint"),
    [
        ("9222\n/devtools/browser/abc\n", DevToolsEndpoint(9222, "/devtools/browser/abc")),
        ("51234\n/devtools/browser/abc", DevToolsEndpoint(51234, "/devtools/browser/abc")),
        ("65535\r\n/devtools/browser/abc\r\n", DevToolsEndpoint(65535, "/devtools/browser/abc")),
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
def test_parse_devtools_active_port(text, endpoint):
    """Only a complete file (port line and browser path line) yields an endpoint; a partial write,
    a non-ASCII digit string or an out-of-range number never does."""
    assert parse_devtools_active_port(text) == endpoint


def test_wait_devtools_active_port_returns_once_the_file_is_complete(tmp_path, monkeypatch):
    """Chrome writes a partial file on the 2nd poll interval and completes it on the 4th: the wait
    reads past the partial write and returns the endpoint on the pass after completion."""
    path = tmp_path / "DevToolsActivePort"

    def chrome_writes():
        if len(clock.sleeps) == 2:
            path.write_text("51")
        elif len(clock.sleeps) == 4:
            path.write_text("51234\n/devtools/browser/abc\n")

    clock = FakeTime(on_sleep=chrome_writes).install(monkeypatch, devtools_port)
    endpoint = wait_devtools_active_port(tmp_path, FakeChromeProcess(), timeout_s=5.0, poll_s=0.01)
    assert endpoint == DevToolsEndpoint(51234, "/devtools/browser/abc")
    assert clock.sleeps == [0.01] * 4


def test_wait_devtools_active_port_fails_fast_when_chrome_exits(tmp_path, monkeypatch):
    clock = FakeTime().install(monkeypatch, devtools_port)
    chrome = FakeChromeProcess(alive_polls=0, code=1)
    with pytest.raises(RuntimeError, match=r"Chrome exited \(1\) before its DevTools port could be used"):
        wait_devtools_active_port(tmp_path, chrome, timeout_s=30.0)
    assert clock.sleeps == [] and chrome.polls == 1


def test_wait_devtools_active_port_times_out_on_a_never_complete_file(tmp_path, monkeypatch):
    """A file that never completes is polled every `poll_s` until the simulated deadline."""
    clock = FakeTime().install(monkeypatch, devtools_port)
    (tmp_path / "DevToolsActivePort").write_text("9222")
    chrome = FakeChromeProcess()
    with pytest.raises(RuntimeError, match="within 0.2 s"):
        wait_devtools_active_port(tmp_path, chrome, timeout_s=0.2, poll_s=0.05)
    assert clock.sleeps == [0.05] * 4
    assert clock.elapsed == pytest.approx(0.2)
    assert chrome.polls == 5


def test_wait_devtools_active_port_refuses_a_complete_file_left_by_a_chrome_that_then_exited(tmp_path):
    """Codex round 2: the exit check comes BEFORE the file is accepted. A Chrome that wrote its
    port and then died no longer owns that port -- another process may already have bound it -- so a
    complete file from an exited Chrome is an error, never a port to drive."""
    (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
    with pytest.raises(RuntimeError, match=r"Chrome exited \(0\) before its DevTools port could be used"):
        wait_devtools_active_port(Path(tmp_path), FakeChromeProcess(alive_polls=0, code=0), timeout_s=0.1)


def test_positive_control_the_same_complete_file_from_a_live_chrome_is_accepted(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
    endpoint = wait_devtools_active_port(Path(tmp_path), FakeChromeProcess(), timeout_s=0.1)
    assert endpoint == DevToolsEndpoint(9333, "/devtools/browser/x")


def _version_endpoint(monkeypatch, body):
    asked = []

    def urlopen(url, timeout=None):
        asked.append((url, timeout))
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(devtools_port.urllib.request, "urlopen", urlopen)
    return asked


def test_verify_devtools_owner_accepts_the_browser_target_chrome_wrote(monkeypatch):
    asked = _version_endpoint(monkeypatch, {"Browser": "Chrome/154", "webSocketDebuggerUrl": "ws://127.0.0.1:51234/devtools/browser/fresh"})
    verify_devtools_owner(DevToolsEndpoint(51234, "/devtools/browser/fresh"), 0.5)
    assert asked == [("http://127.0.0.1:51234/json/version", 0.5)]


@pytest.mark.parametrize(
    "body",
    [
        {"webSocketDebuggerUrl": "ws://127.0.0.1:51234/devtools/browser/other"},
        {"webSocketDebuggerUrl": "ws://127.0.0.1:51234/devtools/browser/fresh-other"},
        {"webSocketDebuggerUrl": "ws://127.0.0.1:51234/x/devtools/browser/fresh"},
        {"Browser": "Chrome/154"},
        [],
    ],
)
def test_verify_devtools_owner_refuses_another_endpoint_on_the_port(monkeypatch, body):
    """Codex round 3: the port answering is not proof it is still this Chrome's (it may have exited
    and another CDP server rebound the port). Only the browser target path from line two of
    `DevToolsActivePort` identifies it; any other answer is a foreign endpoint."""
    _version_endpoint(monkeypatch, body)
    with pytest.raises(ForeignDevToolsEndpoint, match=r"127\.0\.0\.1:51234 is another DevTools endpoint: .* not /devtools/browser/fresh"):
        verify_devtools_owner(DevToolsEndpoint(51234, "/devtools/browser/fresh"), 0.5)


def test_verify_devtools_owner_lets_a_refused_connection_propagate_for_a_retry(monkeypatch):
    monkeypatch.setattr(devtools_port.urllib.request, "urlopen", lambda url, timeout=None: (_ for _ in ()).throw(ConnectionRefusedError()))
    with pytest.raises(ConnectionRefusedError):
        verify_devtools_owner(DevToolsEndpoint(51234, "/devtools/browser/fresh"), 0.5)
