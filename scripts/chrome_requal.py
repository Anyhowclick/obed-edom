#!/usr/bin/env python3
"""Re-qualify one Chrome major for the LIVE movie-freeze placement grant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import sys
import time
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import dissolve_probe as d  # noqa: E402
import mm_opacity_probe as mmo  # noqa: E402
from obed_edom import live_host  # noqa: E402
from obed_edom.fixture_paths import main_checkout  # noqa: E402

GATES = ("handoff", "frozen_frame", "frozen_region", "cost", "grant", "cvc")
CORE_ARMS = (
    "grant-chrome", "grant-attach", "channel-predefined", "life-grant-reload", "opaque-off", "off", "noblend",
    "on", "on2", "m-paused", "m-off", "m-on", "m-hold", "m-raw",
)
SNAP_CELLS: dict[str, tuple[str, ...]] = {
    name: tuple(arm for arm in (name, d.ARMS[name].twin) if arm is not None)
    for name in ("m-snap", "m-snap-clipx", "m-snap-clipy", "m-snap-lbfrac", "m-snap-lbfrac-clipx",
                 "m-snap-lbfrac-clipy", "m-snap-shift")
}
ARMS = CORE_ARMS + tuple(arm for cell in SNAP_CELLS.values() for arm in cell)
DECISION_SHA256 = "26c4c3e6790218233a8d6b3920920ead5d2ff3e4741d7082bb7faf487cf8c13c"


def chrome_version(chrome: Path) -> str:
    with (chrome.parents[1] / "Info.plist").open("rb") as handle:
        version = plistlib.load(handle).get("CFBundleShortVersionString")
    if not isinstance(version, str) or not version.split(".", 1)[0].isdigit():
        raise ValueError("Info.plist has no usable CFBundleShortVersionString")
    return version


def qualify(verdict: dict, products: dict[str, str | None], version: str) -> tuple[str, list[str]]:
    failed: list[str] = []
    inconclusive: list[str] = []
    expected = {f"Chrome/{version}", f"HeadlessChrome/{version}"}
    for name in (arm for arm in ARMS if arm != "m-raw"):
        product = products.get(name)
        if name not in products:
            inconclusive.append(f"{name}: recorded product is missing")
        elif product not in expected:
            inconclusive.append(f"{name}: recorded product {product!r} does not match {version}")

    for name in GATES:
        reading = verdict["gates"].get(name, {}).get("verdict")
        if reading == "FAIL":
            failed.append(f"gate {name}: required PASS became FAIL")
        elif reading != "PASS":
            inconclusive.append(f"gate {name}: expected PASS, got {reading!r}")

    for name in CORE_ARMS:
        arm = verdict["detail"].get(name)
        if arm is None:
            inconclusive.append(f"{name}: scored arm is missing")
            continue
        problems = arm.get("problems")
        if problems:
            inconclusive.append(f"{name}: " + "; ".join(map(str, problems)))
        elif arm.get("outcome") == "MISMATCH":
            failed.append(f"{name}: core arm is MISMATCH")
        elif arm.get("outcome") != "MATCH":
            inconclusive.append(f"{name}: expected MATCH, got {arm.get('outcome')!r}")

    for name in SNAP_CELLS:
        arm = verdict["detail"].get(name)
        if arm is None:
            inconclusive.append(f"{name}: scored cell is missing")
            continue
        usable = arm.get("problems") == []
        if not usable:
            inconclusive.append(f"{name}: arm problems are {arm.get('problems')!r}")
        checks = arm["checks"]
        for check in ("reference", "mask") + (() if name == "m-snap-shift" else ("geometry",)):
            value = checks.get(check, {}).get("verdict")
            if value == "FAIL" and usable:
                failed.append(f"{name}: required {check} PASS became FAIL")
            elif value != "PASS":
                inconclusive.append(f"{name}: expected {check} PASS, got {value!r}")
        holder = checks.get("holder_pixels")
        limitation = ["no L_path for the arm's compositing path"]
        if holder.get("verdict") != "INCONCLUSIVE" or holder.get("problems") != limitation:
            inconclusive.append(f"{name}: holder_pixels limitation changed unexpectedly")

    status = "FAIL" if failed else "INCONCLUSIVE" if inconclusive else "PASS"
    return status, failed + inconclusive


def print_retry(out: Path, reasons: list[str], command: str) -> None:
    targets = sorted({arm for name in {r.split(":", 1)[0] for r in reasons}
                      for arm in SNAP_CELLS.get(name, (name,))} & set(ARMS))
    for name in targets:
        print("delete:", shlex.join(["/usr/bin/trash", str(out / "runs" / name)]))
    print("rerun:", command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decision", type=Path, default=main_checkout() / "output/evidence/s2-dev/"
                        "dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json")
    args = parser.parse_args(argv)
    out, chrome = args.out.expanduser().resolve(), args.chrome.expanduser().resolve()
    try:
        if any(part.lower() == "output" for part in out.parts):
            raise ValueError("--out must not contain an output path component")
        if not chrome.is_file() or not os.access(chrome, os.X_OK):
            raise ValueError(f"Chrome executable is missing or not executable: {chrome}")
        version = chrome_version(chrome)
        decision_bytes = args.decision.expanduser().resolve().read_bytes()
        if hashlib.sha256(decision_bytes).hexdigest() != DECISION_SHA256:
            raise ValueError("decision record SHA-256 does not match the pinned Q0b record")
        decision = json.loads(decision_bytes)
    except (OSError, ValueError) as exc:
        print(f"INCONCLUSIVE: {exc}")
        return 2

    for folder in (out / "runs", out / "scratch", out / "host"):
        folder.mkdir(parents=True, exist_ok=True)
    os.environ["OBED_EDOM_OUTPUT_ROOT"] = str(out / "host")
    d.CHROME = chrome
    major = int(version.split(".", 1)[0])
    qualified = tuple(sorted({*live_host.QUALIFIED_SNAP_MAJORS, major}))
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
    with mock.patch.object(live_host, "QUALIFIED_SNAP_MAJORS", qualified):
        for name in ARMS:
            run_dir = out / "runs" / name
            if (run_dir / "record.json").is_file():
                print(f"{name}: skipped", flush=True)
                continue
            if run_dir.is_dir():
                shutil.rmtree(run_dir)
            deadline = time.monotonic() + 300
            while (mmo.headless_chromes() or os.getloadavg()[0] >= 3.5) and time.monotonic() < deadline:
                time.sleep(5)
            running, load = mmo.headless_chromes(), os.getloadavg()[0]
            if running or load >= d.MAX_LOAD:
                print(f"INCONCLUSIVE: refusing {name}; {running} headless Chromes, 1-min load {load:.2f}")
                return 2
            record, images = d.run_arm(name, out / "scratch", decision)
            d.save_run(out, name, record, images)
            print(f"{name}: {'error' if record.get('error') else 'ok'}", flush=True)

    try:
        runs = d.load_runs(out)
    except ValueError as exc:
        print(f"INCONCLUSIVE: saved runs are malformed: {exc}")
        reasons = []
        for name in ARMS:
            try:
                json.loads((out / "runs" / name / "record.json").read_text())
            except (OSError, ValueError):
                reason = f"{name}: saved record is malformed"
                reasons.append(reason)
                print(f"- {reason}")
        print_retry(out, reasons, command)
        return 2
    verdict = d.score_runs(runs, decision)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    products = {name: ((record.get("output") or {}).get("placement") or {}).get("product")
                for name, (record, _images) in runs.items()}
    status, reasons = qualify(verdict, products, version)
    try:
        final_version = chrome_version(chrome)
    except (OSError, ValueError) as exc:
        final_version = f"unreadable ({exc})"
    if final_version != version:
        reasons.append(f"browser identity: version changed from {version} to {final_version}")
    if reasons and status == "PASS":
        status = "INCONCLUSIVE"

    print(status)
    for reason in reasons:
        print(f"- {reason}")
    if status == "PASS":
        print(f"QUALIFIED_SNAP_MAJORS = {qualified}")
        if major in live_host.QUALIFIED_SNAP_MAJORS:
            print(f"Chrome {major} is already qualified")
        return 0
    if status == "INCONCLUSIVE":
        print_retry(out, reasons, command)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
