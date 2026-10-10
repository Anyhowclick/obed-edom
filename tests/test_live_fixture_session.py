"""Offline tests for `scripts/live_fixture_session.py`'s command reader: the presenter-key → command mapping, the
single-key mode on a pseudo-terminal (terminal state restored on every exit path) and the whole-line fallback when stdin
is not a terminal. No browser, OBS or Keynote.
"""
from __future__ import annotations

import io
import os
import sys
import termios
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import live_fixture_session as session  # noqa: E402

RIGHT = "\x1b[C"
LEFT = "\x1b[D"


def _attrs(fd: int) -> list:
    """Terminal attributes minus PENDIN, the status bit the kernel itself sets whenever ICANON is switched back on."""
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~getattr(termios, "PENDIN", 0)
    return attrs


@pytest.fixture
def pty_stdin():
    """A pseudo-terminal: bytes written to `master` arrive as keystrokes on the returned TTY `stdin`."""
    master, slave = os.openpty()
    stdin = os.fdopen(slave, "r")
    try:
        yield master, stdin
    finally:
        stdin.close()
        os.close(master)


@pytest.mark.parametrize("key", [RIGHT, "\x1bOC", " ", "\r", "\n", "a"])
def test_presenter_keys_advance(key: str) -> None:
    assert session.command_for(key) == "a"


@pytest.mark.parametrize("key", ["s", "h", "o", "q"])
def test_letter_keys_pass_through(key: str) -> None:
    assert session.command_for(key) == key


def test_ctrl_d_quits() -> None:
    assert session.command_for("\x04") == "q"


def test_left_arrow_is_unbound() -> None:
    # LiveOutputHost has no back/previous operation, so ← falls through to the dispatcher's help line.
    assert session.command_for(LEFT) == LEFT


def test_non_tty_reads_whole_lines(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("g 3\n\n s \nq\n"))
    assert not sys.stdin.isatty()
    assert [session.read_command(sys.stdin) for _ in range(5)] == ["g 3", "", "s", "q", None]
    assert capsys.readouterr().out == "> " * 5


@pytest.mark.parametrize(("typed", "expected"), [(RIGHT, "a"), (" ", "a"), ("\n", "a"), ("s", "s"), (LEFT, LEFT)])
def test_tty_reads_single_keys(pty_stdin, typed: str, expected: str) -> None:
    master, stdin = pty_stdin
    before = _attrs(stdin.fileno())
    os.write(master, typed.encode())
    assert session.read_command(stdin) == expected
    assert _attrs(stdin.fileno()) == before


def test_tty_splits_back_to_back_arrows(pty_stdin) -> None:
    master, stdin = pty_stdin
    os.write(master, (RIGHT + RIGHT + "h").encode())
    assert [session.read_command(stdin) for _ in range(3)] == ["a", "a", "h"]


@pytest.mark.parametrize(("key", "typed", "expected"), [("g", " 12 ", "g 12"), (":", "g 4", "g 4"), (":", "o", "o")])
def test_tty_line_keys_prompt_for_a_typed_command(pty_stdin, monkeypatch: pytest.MonkeyPatch, key: str, typed: str, expected: str) -> None:
    master, stdin = pty_stdin
    before = _attrs(stdin.fileno())
    prompts: list[tuple[str, list]] = []

    def fake_input(prompt: str) -> str:
        prompts.append((prompt, _attrs(stdin.fileno())))
        return typed

    monkeypatch.setattr("builtins.input", fake_input)
    os.write(master, key.encode())
    assert session.read_command(stdin) == expected
    assert prompts == [(session.LINE_KEYS[key], before)], "the typed prompt must run in the restored (cooked) terminal mode"


def test_tty_line_prompt_eof_ends_input(pty_stdin, monkeypatch: pytest.MonkeyPatch) -> None:
    master, stdin = pty_stdin

    def eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    os.write(master, b":")
    assert session.read_command(stdin) is None


def test_tty_restores_terminal_on_ctrl_c(pty_stdin, monkeypatch: pytest.MonkeyPatch) -> None:
    _master, stdin = pty_stdin
    fd = stdin.fileno()
    before = _attrs(fd)
    seen: list[int] = []

    def interrupted(read_fd: int) -> str:
        seen.append(termios.tcgetattr(read_fd)[3])
        raise KeyboardInterrupt

    monkeypatch.setattr(session, "_read_key", interrupted)
    with pytest.raises(KeyboardInterrupt):
        session.read_command(stdin)
    assert seen and not seen[0] & (termios.ICANON | termios.ECHO), "the key read must happen in cbreak mode"
    assert _attrs(fd) == before
