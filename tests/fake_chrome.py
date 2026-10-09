"""Shared doubles for the Chrome readiness tests (live host, continuity probe, P2 spike, DevTools port):
an owned Chrome process that exits on cue, and a simulated clock so deadlines never cost real time."""

from __future__ import annotations

import time
from fractions import Fraction
from typing import Any, Callable


class FakeChromeProcess:
    """A `subprocess.Popen` stand-in for the owned Chrome. Alive for its first `alive_polls` polls,
    then exited with `code`; `die()` (or `terminate()`/`kill()`) exits it at once. `returncode` is
    set by `poll()` like Popen's, and `terminate`/`kill`/`wait` are recorded in `calls`."""

    pid = 4321

    def __init__(self, alive_polls: int = 10**9, code: int = 0) -> None:
        self.alive_polls, self.code = alive_polls, code
        self.polls = 0
        self.dead = False
        self.returncode: int | None = None
        self.calls: list[str] = []

    def die(self) -> None:
        self.dead = True

    def poll(self) -> int | None:
        self.polls += 1
        if self.polls > self.alive_polls:
            self.dead = True
        self.returncode = self.code if self.dead else None
        return self.returncode

    def terminate(self) -> None:
        self.calls.append("terminate")
        self.dead = True

    def kill(self) -> None:
        self.calls.append("kill")
        self.dead = True

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append("wait")
        self.dead = True
        self.returncode = self.code
        return self.code


class FakeTime:
    """Simulated `time` for a module under test (install it as that module's `time`): `monotonic()`
    reads the simulated now, `sleep()` advances it and records the interval; every other attribute
    is the real `time` module. Elapsed time is summed exactly, so `n` sleeps of `poll` land on the
    same float as `start + n * poll` and simulated deadlines are hit on the expected pass.
    `on_sleep` runs after each advance. A loop that reads the clock `max_reads` times without
    finishing fails instead of hanging the suite."""

    def __init__(self, on_sleep: Callable[[], None] | None = None, max_reads: int = 100_000) -> None:
        self.start = 1000.0
        self._elapsed = Fraction(0)
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep
        self.reads, self.max_reads = 0, max_reads

    @property
    def now(self) -> float:
        return float(Fraction(self.start) + self._elapsed)

    @property
    def elapsed(self) -> float:
        return float(self._elapsed)

    def monotonic(self) -> float:
        self.reads += 1
        if self.reads > self.max_reads:
            raise AssertionError(f"clock read {self.max_reads} times: the loop under test never ends")
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._elapsed += Fraction(seconds)
        if self.on_sleep is not None:
            self.on_sleep()

    async def async_sleep(self, seconds: float) -> None:
        self.sleep(seconds)

    def install(self, monkeypatch: Any, *modules: Any) -> FakeTime:
        for module in modules:
            monkeypatch.setattr(module, "time", self)
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)
