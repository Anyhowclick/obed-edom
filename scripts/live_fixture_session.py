"""Drive the live host from a terminal against an already-exported deck folder.

Field tool for bring-up (OBS attach via OBED_LIVE_ATTACH, or the HDMI window): it
bypasses the dashboard and Keynote, so an export whose movies are known to decode
(e.g. the H.264 P2 fixture) can be shown when a fresh export's HEVC will not.
It works on a disposable copy; the export folder itself is never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import sys
import termios
import time
import tty
from pathlib import Path
from typing import TextIO

from obed_edom.html_preview import cache_dir
from obed_edom.live_host import LiveOutputHost
from obed_edom.live_session import PlayerCommandRejected

SESSION_DIGEST = "5e" * 32
HELP = "a/→/space/enter=advance  g N=go to slide N  s=show  h=hide  o=observe  q=stop and quit  :=type a command"
KEYS = {" ": "a", "\r": "a", "\n": "a", "\x1b[C": "a", "\x1bOC": "a", "\x04": "q"}
LINE_KEYS = {":": ":", "g": "g "}


def command_for(key: str) -> str:
    return KEYS.get(key, key)


def _read_key(fd: int) -> str:
    key = os.read(fd, 1)
    if key == b"\x1b" and select.select([fd], [], [], 0.05)[0]:
        key += os.read(fd, 1)
        if key[-1:] in (b"[", b"O"):
            while select.select([fd], [], [], 0.05)[0]:
                key += os.read(fd, 1)
                if 0x40 <= key[-1] <= 0x7E:
                    break
    return key.decode(errors="replace")


def read_command(stdin: TextIO) -> str | None:
    try:
        if not stdin.isatty():
            return input("> ").strip()
        fd = stdin.fileno()
        saved = termios.tcgetattr(fd)
        print("> ", end="", flush=True)
        try:
            tty.setcbreak(fd, termios.TCSANOW)
            key = _read_key(fd)
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, saved)
        if not key:
            return None
        if key in LINE_KEYS:
            typed = input(LINE_KEYS[key]).strip()
            return typed if key == ":" else f"g {typed}"
        command = command_for(key)
        print(command if command.isprintable() else "")
        return command
    except EOFError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True, help="Keynote HTML export folder (contains assets/)")
    parser.add_argument("--index", type=Path, help="index.html to use instead of the export's own")
    parser.add_argument("--display", type=int, help="display id for HDMI mode (ignored when OBED_LIVE_ATTACH is set)")
    args = parser.parse_args()

    destination = cache_dir(SESSION_DIGEST) / "html"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.export, destination)
    if args.index:
        shutil.copy2(args.index, destination / "index.html")
    header = json.loads((destination / "assets/header.json").read_text())
    slides = [
        {"originalOrdinal": index + 1, "playerIndex": index, "exportedUuid": uuid, "skipped": False}
        for index, uuid in enumerate(header["slideList"])
    ]
    player = LiveOutputHost(destination, slides, display_id=args.display)

    def report(observed) -> None:
        print(f"  slide {observed.original_slide} scene {observed.scene_id} busy={observed.busy} visible={observed.output_visible}")

    try:
        report(player.observe())
        output = player.output
        print(f"  transport={output.get('transport')} viewport={output.get('viewport')} continuity={output.get('continuity')}")
        print(f"  log: {output.get('logPath')}")
        print(HELP)
        while True:
            line = read_command(sys.stdin)
            if line is None or line in ("q", "quit"):
                break
            try:
                if line in ("", "a"):
                    observed = player.execute("advance")
                elif line == "s":
                    observed = player.execute("show")
                elif line == "h":
                    observed = player.execute("hide")
                elif line == "o":
                    observed = player.observe()
                elif line.startswith("g") and line[1:].strip().isdigit():
                    observed = player.execute("goTo", int(line[1:].strip()))
                else:
                    print(HELP)
                    continue
                deadline = time.monotonic() + 30
                while observed.busy and time.monotonic() < deadline:
                    time.sleep(0.1)
                    observed = player.observe()
                report(observed)
            except PlayerCommandRejected as exc:
                print(f"  refused: {exc}")
    finally:
        try:
            player.stop()
        finally:
            shutil.rmtree(destination.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
