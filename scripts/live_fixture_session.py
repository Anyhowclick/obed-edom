"""Drive the live host from a terminal against an already-exported deck folder.

Field tool for bring-up (OBS attach via OBED_LIVE_ATTACH, or the HDMI window): it
bypasses the dashboard and Keynote, so an export whose movies are known to decode
(e.g. the H.264 P2 fixture) can be shown when a fresh export's HEVC will not.
It works on a disposable copy; the export folder itself is never modified.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from obed_edom.html_preview import cache_dir
from obed_edom.live_host import LiveOutputHost
from obed_edom.live_session import PlayerCommandRejected

SESSION_DIGEST = "5e" * 32
HELP = "a/space=advance  g N=go to slide N  s=show  h=hide  o=observe  q=stop and quit"


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
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if line in ("q", "quit"):
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
