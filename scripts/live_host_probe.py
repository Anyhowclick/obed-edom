"""Run the owned live adapter headlessly against the known P2 HTML fixture.

This only proves the browser adapter can observe the recognised player.  It
does not qualify HDMI, alpha, audio, or movie continuity at a receiver.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from hashlib import sha256
from pathlib import Path

from obed_edom import live_host as live_host_module
from obed_edom.html_preview import cache_dir
from obed_edom.live_host import LiveOutputHost, OutputDisplay
from obed_edom.live_runtime import RUNTIME_VERSION

# In this headless Chrome, --window-size=W,H yields an innerHeight of H-32
# (chrome window chrome persists even headless); pad the requested height so
# the measured viewport lands exactly on what --viewport asked for.
HEADLESS_CHROME_HEIGHT_PAD = 32


FIXTURE = Path(".claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-player")
ORIGINAL_INDEX = Path(".claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/html-unmodified/index.html")
ARTIFACT = Path("output/keynote-live-planning-2026-09-19/live-host-headless-proof.json")
PROBE_DIGEST = "a" * 64


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--original-index", type=Path, default=ORIGINAL_INDEX)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--viewport", type=str, default=None, help="Forced headless viewport, e.g. 2560x1440")
    return parser.parse_args()


def parse_viewport(value: str) -> tuple[int, int]:
    width, _, height = value.partition("x")
    return int(width), int(height)


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


def stage_geometry(player: LiveOutputHost) -> dict[str, object]:
    return player._require_transport().evaluate(
        "({"
        "stage: document.getElementById('stage').getBoundingClientRect().toJSON(),"
        "stageArea: document.getElementById('stageArea').getBoundingClientRect().toJSON(),"
        "hyperlinkPlane: document.getElementById('hyperlinkPlane').getBoundingClientRect().toJSON(),"
        "viewport: [window.innerWidth, window.innerHeight]"
        "})"
    )


def expected_fit(canvas: dict[str, object], viewport: dict[str, object]) -> dict[str, float]:
    scale = min(viewport["width"] / canvas["width"], viewport["height"] / canvas["height"])
    width, height = canvas["width"] * scale, canvas["height"] * scale
    return {
        "x": (viewport["width"] - width) / 2,
        "y": (viewport["height"] - height) / 2,
        "width": width,
        "height": height,
    }


def geometry_is_fitted(geometry: dict[str, object], canvas: dict[str, object]) -> bool:
    viewport = {"width": geometry["viewport"][0], "height": geometry["viewport"][1]}
    expected = expected_fit(canvas, viewport)
    return all(
        abs(geometry[element][field] - expected[field]) <= 1
        for element in ("stage", "stageArea", "hyperlinkPlane")
        for field in ("x", "y", "width", "height")
    )


def main() -> None:
    args = parse_args()
    if not args.fixture.is_dir():
        raise SystemExit(f"fixture is unavailable: {args.fixture}")
    destination = cache_dir(PROBE_DIGEST) / "html"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.fixture, destination)
    shutil.copy2(args.original_index, destination / "index.html")
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
    if args.viewport:
        width, height = parse_viewport(args.viewport)
        forced_display = OutputDisplay(0, 0, 0, width, height + HEADLESS_CHROME_HEIGHT_PAD, True)
        live_host_module.choose_display = lambda *_a, **_k: forced_display
    player = LiveOutputHost(destination, slides, headless=True)
    artifact = args.artifact
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
    artifact.parent.mkdir(parents=True, exist_ok=True)
    def save() -> None: artifact.write_text(json.dumps(result, indent=2) + "\n")
    save()
    try:
        result["stage"] = "starting"
        save()
        initial = player.observe()
        result["initial"] = initial.__dict__
        result["browser"] = player._require_transport().call("Browser.getVersion")
        result["initialRuntime"] = player._require_transport().evaluate("window.__obedLive.snapshot()")
        result["initialGeometry"] = stage_geometry(player)
        result["initialGeometry"]["fitted"] = geometry_is_fitted(result["initialGeometry"], player._canvas)
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
            if number == 4:
                result["finalGeometry"] = stage_geometry(player)
                result["finalGeometry"]["fitted"] = geometry_is_fitted(result["finalGeometry"], player._canvas)
            save()
        for operation in (("goTo", 1), ("goTo", 1)):
            result["stage"] = "go-to-one"
            save()
            acknowledged = player.execute(*operation)
            result["steps"].append({"command": operation, "ack": acknowledged.__dict__})
            settled, duration = wait_for_settlement(player)
            result["steps"].append({"settled": settled, "seconds": duration})
            save()
        result["stageFitted"] = bool(result["initialGeometry"]["fitted"]) and bool(result["finalGeometry"]["fitted"])
        result["status"] = "pass" if result["stageFitted"] else "error"
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
