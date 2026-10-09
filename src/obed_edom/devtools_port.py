"""Chrome's self-chosen remote-debugging port (`--remote-debugging-port=0`)."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEVTOOLS_ACTIVE_PORT = "DevToolsActivePort"


@dataclass(frozen=True)
class DevToolsEndpoint:
    """Chrome's `DevToolsActivePort`: the port it bound and its browser target path."""

    port: int
    browser_path: str


class ForeignDevToolsEndpoint(RuntimeError):
    """The port answers, but not as the Chrome that wrote the `DevToolsActivePort`."""


def parse_devtools_active_port(text: str) -> DevToolsEndpoint | None:
    """None until both lines (port, then browser target path) are there."""
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].isascii() or not lines[0].isdigit() or not lines[1].strip():
        return None
    port = int(lines[0])
    return DevToolsEndpoint(port, lines[1].strip()) if 0 < port < 65536 else None


def wait_devtools_active_port(
    profile: Path, proc: subprocess.Popen, timeout_s: float = 15.0, poll_s: float = 0.05
) -> DevToolsEndpoint:
    """The endpoint Chrome launched with `--remote-debugging-port=0` bound for itself, read from
    `<profile>/DevToolsActivePort` (the caller removes a stale one before launch). An exited Chrome
    fails even when its file is complete: the port it names is no longer Chrome's."""
    path = profile / DEVTOOLS_ACTIVE_PORT
    deadline = time.monotonic() + timeout_s
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"Chrome exited ({proc.returncode}) before its DevTools port could be used ({path})")
        try:
            endpoint = parse_devtools_active_port(path.read_text())
        except (OSError, UnicodeDecodeError):
            endpoint = None
        if endpoint is not None:
            return endpoint
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Chrome wrote no {path} within {timeout_s} s")
        time.sleep(poll_s)


def verify_devtools_owner(endpoint: DevToolsEndpoint, timeout_s: float) -> None:
    """Raises `ForeignDevToolsEndpoint` unless the port's `/json/version` names `endpoint`'s browser
    target; connection errors propagate as-is for the caller to retry."""
    with urllib.request.urlopen(f"http://127.0.0.1:{endpoint.port}/json/version", timeout=timeout_s) as response:
        version = json.loads(response.read())
    ws_url = version.get("webSocketDebuggerUrl") if isinstance(version, dict) else None
    if not isinstance(ws_url, str) or urlsplit(ws_url).path != endpoint.browser_path:
        raise ForeignDevToolsEndpoint(
            f"127.0.0.1:{endpoint.port} is another DevTools endpoint: its browser target is {ws_url!r}, "
            f"not {endpoint.browser_path}"
        )
