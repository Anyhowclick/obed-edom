from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from obed_edom import placement_probe
from obed_edom.placement_probe import (
    MANIFEST_SHA256,
    MOTION_SHA256,
    PATTERN_SHA256,
    ClassifierInput,
    PoseGeometry,
    ProbeCapture,
    ProbeIdentity,
    ProbeSpec,
    ProbeVerdict,
    ToneMap,
    classify_probe,
    load_probe_assets,
    render_probe_page,
)


def _geometry(pose: int) -> PoseGeometry:
    fx, fy = ((0.352, 0.036), (0.73, 0.41))[pose]
    width = 480.53125
    height = 135.140625
    x = 10 + fx
    y = 10 + fy
    return PoseGeometry(
        pose=pose,
        rect=(x, y, width, height),
        content_box=(x, y, width, height),
        box=(10, 10, math_ceil(x + width) - 9, math_ceil(y + height) - 9),
        snap_dy=140,
        frac_dy=280,
    )


def _nonce(image: np.ndarray, value: str) -> None:
    bits = f"{int(value, 16):0128b}"
    for index, bit in enumerate(bits):
        x = 1600 + (index % 16) * 8
        y = 16 + (index // 16) * 8
        image[y : y + 8, x : x + 8, :3] = 255 if bit == "1" else 0


def _png(image: np.ndarray) -> bytes:
    output = io.BytesIO()
    Image.fromarray(image, "RGBA").save(output, format="PNG")
    return output.getvalue()


def _capture(
    identity: ProbeIdentity,
    sequence: int,
    phase: str,
    pose: int | None,
    video: np.ndarray,
    snap: np.ndarray | None = None,
    frac: np.ndarray | None = None,
) -> ProbeCapture:
    image = np.full((1080, 1920, 4), (64, 64, 64, 255), np.uint8)
    geometry = _geometry(0 if pose is None else pose)
    x, y, width, height = geometry.box
    image[y : y + height, x : x + width, :3] = video[:height, :width]
    if snap is not None and frac is not None:
        image[y + geometry.snap_dy : y + geometry.snap_dy + height, x : x + width, :3] = snap[:height, :width]
        image[y + geometry.frac_dy : y + geometry.frac_dy + height, x : x + width, :3] = frac[:height, :width]
    nonce = f"{sequence:032x}"
    _nonce(image, nonce)
    started = 1 + sequence * 0.31
    return ProbeCapture(identity, sequence, nonce, phase, pose, _png(image), started - 0.31, started, started + 0.01)


def _motion(counter: int) -> np.ndarray:
    image = np.empty((137, 482, 3), np.uint8)
    for index in range(16):
        image[:, index * 482 // 16 : (index + 1) * 482 // 16] = 255 if counter >> (15 - index) & 1 else 0
    return image


def _gpu(value: np.ndarray) -> np.ndarray:
    linear = (value.astype(np.float64) / 255) ** 1.961
    encoded = np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.rint(255 * encoded).astype(np.uint8)


def _set_pixels(region: np.ndarray, count: int, value: int) -> None:
    width = region.shape[1] - 6
    indices = np.arange(count)
    region[indices // width + 3, indices % width + 3] = value


def _regions(case: str, pose: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = _geometry(pose).box[3], _geometry(pose).box[2]
    shape = (height, width, 3)
    video = np.full(shape, 100, np.uint8)
    snap = np.full(shape, 100, np.uint8)
    frac = np.full(shape, 220, np.uint8)
    inner = (slice(3, -3), slice(3, -3), slice(None))
    pixels = (height - 6) * (width - 6)
    if case == "gpu-frac":
        frac.fill(0)
        _set_pixels(frac, pixels // 10, 100)
        video = _gpu(frac)
        snap.fill(220)
    elif case in {"unknown", "stale", "unstable", "dpr"}:
        snap.fill(220)
    elif case.startswith("boundary"):
        snap.fill(100)
        frac.fill(100)
        snap_bad = pixels * 2 // 100
        frac_bad = math_ceil(pixels * 20 / 100)
        if case == "boundary-2-fail":
            snap_bad += 1
        if case == "boundary-20-fail":
            frac_bad -= 1
        _set_pixels(snap, snap_bad, 220)
        _set_pixels(frac, frac_bad, 220)
    elif case == "edge":
        snap[:3] = snap[-3:] = 220
        snap[:, :3] = snap[:, -3:] = 220
    elif case == "max-channel":
        frac.fill(100)
        frac[inner][..., 2] = 106
    return video, snap, frac


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if integer == value else integer + 1


def _input(case: str) -> ClassifierInput:
    spec = ProbeSpec("0123456789abcdef0123456789abcdef", 1920, 1080, 50, 1)
    identity = ProbeIdentity(spec.run_id, "source", "target", "context", 4, "CEF", 1)
    freshness = tuple(_capture(identity, index, "motion", None, _motion(index * 7)) for index in range(1, 4))
    captures = []
    for pose in range(2):
        video, snap, frac = _regions(case, pose)
        captures.extend(
            _capture(identity, 4 + pose * 2 + pair, "pattern", pose, video, snap, frac) for pair in range(2)
        )
    captures = tuple(captures)
    data = ClassifierInput(
        spec,
        (MANIFEST_SHA256, PATTERN_SHA256, MOTION_SHA256),
        identity,
        4,
        (1920, 540),
        ("bt709", "bt709", "bt709", False),
        freshness,
        (_geometry(0), _geometry(1)),
        captures,
    )
    if case == "stale":
        data = replace(data, captures=(replace(captures[0], nonce="f" * 32), *captures[1:]))
    elif case == "unstable":
        changed = np.asarray(Image.open(io.BytesIO(captures[1].png)).convert("RGBA")).copy()
        changed[20, 20, 0] ^= 255
        data = replace(data, captures=(captures[0], replace(captures[1], png=_png(changed)), *captures[2:]))
    elif case == "dpr":
        data = replace(data, spec=replace(spec, dpr=1.5), identity=replace(identity, dpr=1.5))
    return data


@pytest.mark.parametrize(
    ("case", "verdict", "tone_map", "eligible", "reason"),
    [
        ("assets", None, None, None, None),
        ("asset-tamper", None, None, None, None),
        ("page", None, None, None, None),
        ("snap", ProbeVerdict.SNAP, ToneMap.IDENTITY, False, "software-map"),
        ("gpu-frac", ProbeVerdict.FRAC, ToneMap.GPU_ANALYTIC, True, "classified"),
        ("unknown", ProbeVerdict.UNKNOWN, None, False, "ambiguous"),
        ("stale", ProbeVerdict.UNKNOWN, None, False, "stale-capture"),
        ("unstable", ProbeVerdict.UNKNOWN, None, False, "unstable-capture"),
        ("dpr", ProbeVerdict.UNKNOWN, None, False, "unsupported-dpr"),
        ("boundary-pass", ProbeVerdict.SNAP, ToneMap.IDENTITY, False, "software-map"),
        ("boundary-2-fail", ProbeVerdict.UNKNOWN, None, False, "ambiguous"),
        ("boundary-20-fail", ProbeVerdict.UNKNOWN, None, False, "ambiguous"),
        ("edge", ProbeVerdict.SNAP, ToneMap.IDENTITY, False, "software-map"),
        ("max-channel", ProbeVerdict.SNAP, ToneMap.IDENTITY, False, "software-map"),
    ],
)
def test_placement_probe_contract(case, verdict, tone_map, eligible, reason, monkeypatch, tmp_path):
    if case == "assets":
        assets = load_probe_assets()
        manifest = json.loads((placement_probe._DATA / "placement_probe.json").read_text())
        assert (assets.manifest_sha256, assets.pattern.sha256, assets.motion.sha256) == (
            MANIFEST_SHA256,
            PATTERN_SHA256,
            MOTION_SHA256,
        )
        assert hashlib.sha256(assets.pattern.data).hexdigest() == manifest["pattern"]["sha256"]
        assert hashlib.sha256(assets.motion.data).hexdigest() == manifest["motion"]["sha256"]
        assert manifest["generator"]["repeatSha256"] == PATTERN_SHA256
        assert len(PATTERN_SHA256) == len(MOTION_SHA256) == len(MANIFEST_SHA256) == 64
        return
    if case == "asset-tamper":
        for name in ("placement_probe.json", "placement_probe.mp4", "placement_motion.mp4"):
            shutil.copy2(placement_probe._DATA / name, tmp_path / name)
        path = tmp_path / "placement_probe.mp4"
        path.write_bytes(path.read_bytes() + b"tampered")
        monkeypatch.setattr(placement_probe, "_DATA", tmp_path)
        with pytest.raises(ValueError, match="pattern digest mismatch"):
            load_probe_assets()
        return
    if case == "page":
        page = render_probe_page(ProbeSpec("a" * 32, 1920, 1080, 50, 1)).decode()
        assert "placement_probe.mp4" in page and "placement_motion.mp4" in page
        assert "__obedProbe" in page and "command(command)" in page and "snapshot()" in page
        assert "left:1600px;top:16px" in page and "[[.352,.036],[.73,.41]]" in page
        assert "video.muted=true" in page and "BigInt(127-i)" in page
        with pytest.raises(ValueError, match="run_id"):
            render_probe_page(ProbeSpec("wrong", 1920, 1080, 50, 1))
        return
    result = classify_probe(_input(case))
    assert (result.verdict, result.tone_map, result.grant_eligible, result.reason) == (
        verdict,
        tone_map,
        eligible,
        reason,
    )
    if case == "boundary-pass":
        identity = [score for score in result.scores if score.tone_map is ToneMap.IDENTITY]
        assert all(score.snap_share <= 0.02 and score.frac_share >= 0.20 for score in identity)
