"""Run the owned live adapter headlessly against the known P2 HTML fixture.

This only proves the browser adapter can observe the recognised player.  It
does not qualify HDMI, alpha, audio, or movie continuity at a receiver.
"""

from __future__ import annotations

import json
import shutil
import time
from hashlib import sha256
from pathlib import Path

from obed_edom.html_preview import cache_dir
from obed_edom.live_host import LiveOutputHost
from obed_edom.live_runtime import RUNTIME_VERSION


FIXTURE = Path(".claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-player")
ORIGINAL_INDEX = Path(".claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-unmodified/index.html")
PROBE_DIGEST = "a" * 64


def export_digest(root: Path) -> str:
    digest = sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def wait_for_settlement(player: LiveOutputHost, timeout_s: float = 60.0) -> tuple[dict[str, object], float]:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        observed = player.observe()
        if not observed.busy:
            return observed.__dict__, time.monotonic() - started
        time.sleep(0.05)
    raise RuntimeError("Player remained busy after 60 seconds.")


def main() -> None:
    if not FIXTURE.is_dir():
        raise SystemExit(f"fixture is unavailable: {FIXTURE}")
    destination = cache_dir(PROBE_DIGEST) / "html"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, destination)
    shutil.copy2(ORIGINAL_INDEX, destination / "index.html")
    header = json.loads((destination / "assets/header.json").read_text())
    slides = [
        {
            "originalOrdinal": index + 1,
            "playerIndex": index,
            "exportedUuid": slide,
            "skipped": False,
        }
        for index, slide in enumerate(header["slideList"])
    ]
    player = LiveOutputHost(destination, slides, headless=True)
    artifact = Path("output/keynote-live-planning-2026-09-19/live-host-headless-proof.json")
    result = {
            "kind": "headless-adapter-proof",
            "status": "running",
            "hostModule": __import__("obed_edom.live_host", fromlist=["__file__"]).__file__,
            "qualification": "Not HDMI, alpha, audio, or movie-continuity qualification.",
            "playerDigest": sha256((destination / "assets/player/main.js").read_bytes()).hexdigest(),
            "exportDigest": export_digest(destination),
            "runtimeVersion": RUNTIME_VERSION,
            "steps": [],
    }
    def save() -> None: artifact.write_text(json.dumps(result, indent=2) + "\n")
    save()
    try:
        result["stage"] = "starting"
        save()
        initial = player.observe()
        result["initial"] = initial.__dict__
        result["browser"] = player._require_transport().call("Browser.getVersion")
        result["initialRuntime"] = player._require_transport().evaluate("window.__obedLive.snapshot()")
        save()
        for number in range(5):
            result["stage"] = f"advance-{number + 1}"
            save()
            acknowledged = player.execute("advance")
            result["steps"].append({"command": "advance", "ack": acknowledged.__dict__})
            save()
            if acknowledged.busy:
                result["steps"].append({"command": "hide", "ack": player.execute("hide").__dict__})
                result["steps"].append({"command": "show", "ack": player.execute("show").__dict__})
            settled, duration = wait_for_settlement(player)
            result["steps"].append({"settled": settled, "seconds": duration})
            save()
        for operation in (("goTo", 1), ("goTo", 1)):
            result["stage"] = "go-to-one"
            save()
            acknowledged = player.execute(*operation)
            result["steps"].append({"command": operation, "ack": acknowledged.__dict__})
            settled, duration = wait_for_settlement(player)
            result["steps"].append({"settled": settled, "seconds": duration})
            save()
        result["status"] = "pass"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        save()
        try:
            player.stop()
        finally:
            result["cleanupAttempted"] = True
            save()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
