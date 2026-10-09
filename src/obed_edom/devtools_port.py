"""Chrome's self-chosen remote-debugging port (`--remote-debugging-port=0`)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

DEVTOOLS_ACTIVE_PORT = "DevToolsActivePort"


def parse_devtools_active_port(text: str) -> int | None:
    """The port on the first line of Chrome's `DevToolsActivePort` file (port line, then the browser
    target path); None until both lines are there."""
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].isascii() or not lines[0].isdigit() or not lines[1].strip():
        return None
    port = int(lines[0])
    return port if 0 < port < 65536 else None


def wait_devtools_active_port(
    profile: Path, proc: subprocess.Popen, timeout_s: float = 15.0, poll_s: float = 0.05
) -> int:
    """The port Chrome launched with `--remote-debugging-port=0` bound for itself, read from
    `<profile>/DevToolsActivePort` (the caller removes a stale one before launch). An exited Chrome
    fails even when its file is complete: the port it names is no longer Chrome's."""
    path = profile / DEVTOOLS_ACTIVE_PORT
    deadline = time.monotonic() + timeout_s
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"Chrome exited ({proc.returncode}) before its DevTools port could be used ({path})")
        try:
            port = parse_devtools_active_port(path.read_text())
        except (OSError, UnicodeDecodeError):
            port = None
        if port is not None:
            return port
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Chrome wrote no {path} within {timeout_s} s")
        time.sleep(poll_s)
