"""Single shared executor for every Keynote-driver-layer ``osascript`` call: temp-script-
FILE policy (never stdin), ``open -b <bundle id>`` pre-launch, the in-process
``KEYNOTE_LOCK``, a wall-clock timeout with a kill on expiry, the cancellation poll, and
rc-based dump-on-failure.

Imports only ``keynote_app`` and stdlib — ``inspect``, ``keynote``, ``offline_write`` and
``remap_keynote`` all import this module, so a back-import here would cycle.

Out of scope: ``maps_keynote.run_osascript`` (separate subsystem, own cancellation
contract) and the two ``osascript -`` stdin dialogs in ``web/app.py`` (file-picker UI,
must not take the lock or a long timeout).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from obed_edom import keynote_app

DEFAULT_TIMEOUT = 3900.0
LAUNCH_SETTLE = 0.4
_POLL_INTERVAL = 0.05
_TIMEOUT_ENV = "OBED_OSASCRIPT_TIMEOUT"

KEYNOTE_LOCK = threading.RLock()


class OsascriptTimeout(RuntimeError):
    """The wall-clock deadline expired; the ``osascript`` child was killed."""


class OsascriptCancelled(RuntimeError):
    """``is_cancelled`` returned true; the ``osascript`` child was killed."""


@dataclass(frozen=True)
class OsaResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed: float
    dump: Path | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def keynote_timeout(override: float | None = None) -> float:
    """``override`` -> ``OBED_OSASCRIPT_TIMEOUT`` -> ``DEFAULT_TIMEOUT``; 0/negative/
    non-finite disables the limit."""
    if override is not None:
        return override
    raw = os.environ.get(_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    if not math.isfinite(value):
        return DEFAULT_TIMEOUT
    return value


def _launch_keynote() -> None:
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(LAUNCH_SETTLE)


def _kill(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _execute(
    argv: list[str],
    *,
    timeout: float | None,
    is_cancelled: Callable[[], bool] | None,
) -> OsaResult:
    if is_cancelled is not None and is_cancelled():
        raise OsascriptCancelled("Export cancelled.")
    limit = keynote_timeout(timeout)
    deadline = None if limit <= 0 else time.monotonic() + limit
    start = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err)
        while proc.poll() is None:
            if is_cancelled is not None and is_cancelled():
                _kill(proc)
                raise OsascriptCancelled("Export cancelled.")
            if deadline is not None and time.monotonic() >= deadline:
                _kill(proc)
                raise OsascriptTimeout(f"osascript timed out after {limit:.0f}s: {argv[-1]}")
            time.sleep(_POLL_INTERVAL)
        out.seek(0)
        err.seek(0)
        return OsaResult(
            argv=argv,
            returncode=proc.returncode,
            stdout=out.read().decode("utf-8", "replace"),
            stderr=err.read().decode("utf-8", "replace"),
            elapsed=time.monotonic() - start,
        )


def run_applescript(
    script: str,
    *,
    launch: bool = False,
    timeout: float | None = None,
    dump_on_failure: Path | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> OsaResult:
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        with KEYNOTE_LOCK:
            if launch:
                _launch_keynote()
            result = _execute(["osascript", str(script_path)], timeout=timeout, is_cancelled=is_cancelled)
    finally:
        script_path.unlink(missing_ok=True)
    if result.returncode != 0 and dump_on_failure is not None:
        dump_on_failure.write_text(script, encoding="utf-8")
        result = OsaResult(
            argv=result.argv,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed=result.elapsed,
            dump=dump_on_failure,
        )
    return result


def run_jxa(
    script_file: Path,
    plan: dict[str, Any],
    *,
    launch: bool = False,
    timeout: float | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> OsaResult:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = Path(handle.name)
    try:
        with KEYNOTE_LOCK:
            if launch:
                _launch_keynote()
            return _execute(
                ["osascript", "-l", "JavaScript", str(script_file), str(plan_path)],
                timeout=timeout,
                is_cancelled=is_cancelled,
            )
    finally:
        plan_path.unlink(missing_ok=True)


def parse_json_stdout(result: OsaResult, label: str) -> dict[str, Any]:
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{result.stderr}\n{result.stdout}")
    raw = (result.stdout or "").strip()
    if not raw:
        raise RuntimeError(f"{label} returned no JSON.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON: {exc}") from exc
