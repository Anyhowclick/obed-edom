"""Prepare-time conversion of export movies, against the real bundled ffmpeg.

Clips are tiny lavfi renders (320x180, at most 30 frames, about 1 s), generated once per
module and copied into a fresh fake export for each test."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from obed_edom import html_preview as hp
from obed_edom import preview_movies as pm
from obed_edom.html_preview import PreviewError
from obed_edom.live_codec import movie_codec, movie_geometry, movie_timing, webm_info
from obed_edom.maps_movie import ffmpeg_exe

LAVFI = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1"]
PRORES_LT = ["-c:v", "prores_ks", "-profile:v", "1"]
PRORES_4444 = ["-c:v", "prores_ks", "-profile:v", "4"]


def ffmpeg(*args: str | Path) -> None:
    subprocess.run([ffmpeg_exe(), "-nostdin", "-y", "-v", "error", *map(str, args)], check=True)


def restamp_mvhd(src: Path, dest: Path) -> None:
    """A copy with only its `mvhd` creation time changed, the way Keynote's per-slide
    copies differ: same `mdat`, different file sha256."""
    data = bytearray(src.read_bytes())
    at = data.index(b"mvhd") + 8
    data[at : at + 4] = (int.from_bytes(data[at : at + 4], "big") + 1).to_bytes(4, "big")
    dest.write_bytes(bytes(data))


@pytest.fixture(scope="module")
def clips(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("clips")
    out = {name: d / f"{name}.{ext}" for name, ext in [
        ("prores", "mov"), ("prores_copy", "mov"), ("hevc_full", "mov"), ("hevc", "mov"),
        ("alpha_const", "mov"), ("alpha_real", "mov"), ("odd", "mov"), ("h264", "mp4"),
    ]}
    ffmpeg(*LAVFI, "-f", "lavfi", "-i", "sine=d=1", *PRORES_LT, "-c:a", "aac", "-shortest", out["prores"])
    restamp_mvhd(out["prores"], out["prores_copy"])
    ffmpeg(*LAVFI, "-c:v", "libx265", "-tag:v", "hvc1", "-x265-params", "log-level=error",
           "-video_track_timescale", "30", out["hevc_full"])
    ffmpeg("-display_rotation", "90", "-ss", "0.3", "-i", out["hevc_full"], "-c", "copy",
           "-video_track_timescale", "30", out["hevc"])
    ffmpeg(*LAVFI, "-vf", "format=yuva444p10le", *PRORES_4444, out["alpha_const"])
    ffmpeg(*LAVFI, "-vf", "format=rgba,colorchannelmixer=aa=0.5", *PRORES_4444, "-pix_fmt", "yuva444p10le",
           out["alpha_real"])
    ffmpeg(*LAVFI, "-vf", "format=yuv444p10le,crop=319:180", *PRORES_4444, out["odd"])
    ffmpeg(*LAVFI, "-c:v", "libx264", out["h264"])
    return out


def add_movie(export: Path, uuid: str, clip: Path, name: str) -> Path:
    """Puts `clip` in slide `uuid`'s folder under Keynote's trimmed name for asset `name` and
    references it from a movie node in that slide's JSON."""
    folder = export / "assets" / uuid
    payload_path = folder / f"{uuid}.json"
    payload = json.loads(payload_path.read_text()) if payload_path.is_file() else {"uuid": uuid}
    asset_id = f"{name}-0.0000-1.0000"
    filename = f"{asset_id}{Path(name).suffix}"
    (folder / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clip, folder / "assets" / filename)
    payload.setdefault("assets", {})[asset_id] = {"type": "video", "url": {"web": f"assets/{filename}"}}
    payload.setdefault("events", []).append(
        {"movie": {"asset": asset_id, "isStreaming": False, "startTime": 0, "endTime": 1}, "baseLayer": {}}
    )
    payload_path.write_text(json.dumps(payload))
    return folder / "assets" / filename


def export_with(tmp_path, monkeypatch, movies: list[tuple[str, Path, str]]) -> tuple[Path, list[dict], dict]:
    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    export = tmp_path / ".html-preview" / "deck-p3-r1" / "html"
    paths = {}
    for uuid, clip, name in movies:
        paths[(uuid, name)] = add_movie(export, uuid, clip, name)
    uuids = list(dict.fromkeys(uuid for uuid, _clip, _name in movies))
    slides = [{"exportedUuid": uuid, "skipped": False} for uuid in uuids]
    return export, slides, paths


def tree_shas(export: Path) -> dict[str, str]:
    return {
        p.relative_to(export).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(export.rglob("*")) if p.is_file()
    }


def test_converts_every_non_h264_copy_in_place_with_identical_timing(tmp_path, monkeypatch, clips):
    export, slides, paths = export_with(tmp_path, monkeypatch, [
        ("S1", clips["prores"], "clip.mov"),
        ("S2", clips["prores_copy"], "clip.mov"),
        ("S1", clips["hevc"], "untitled.mov"),
        ("S2", clips["alpha_const"], "keyed.mov"),
        ("S1", clips["alpha_real"], "keyed-real.mov"),
        ("S2", clips["alpha_real"], "keyed-real.mov"),
        ("S3", clips["h264"], "wa.mp4"),
    ])
    sources = {key: (movie_timing(p), movie_geometry(p), hashlib.sha256(p.read_bytes()).hexdigest())
               for key, p in paths.items()}
    assert sources[("S1", "clip.mov")][2] != sources[("S2", "clip.mov")][2]
    assert sources[("S1", "untitled.mov")][0].edits[0][1] > 0
    assert not sources[("S1", "untitled.mov")][0].identity_edits
    h264_before = paths[("S3", "wa.mp4")].read_bytes()
    lines: list[str] = []

    record = pm.convert_movies(export, slides, log=lines.append)

    assert record["encoder"] == "libx264 crf14 fast yuv420p; aac 192k"
    assert record["alphaEncoder"] == "libvpx-vp9 crf20 yuva420p; silent WebM"
    assert any(line.startswith("Converting untitled.mov to H.264 · 0 / 1 s") for line in lines)
    assert any(line.startswith("Converting keyed-real.mov to VP9 alpha · 0 / 1 s") for line in lines)
    assert sorted(p.name for p in export.rglob("*") if p.is_file() and p.suffix != ".json") == sorted(
        p.name for p in paths.values()
    )
    for key, path in paths.items():
        timing, geometry, _sha = sources[key]
        if key[1] == "keyed-real.mov":
            info = webm_info(path)
            assert movie_codec(path) == "V_VP9"
            assert info is not None and info.alpha
            assert (info.width, info.height) == (geometry.width, geometry.height)
            assert abs(info.duration_s - timing.presented_s) <= 0.5 / 30
        else:
            out_timing, out_geometry = movie_timing(path), movie_geometry(path)
            assert movie_codec(path) == "avc1"
            assert out_timing.timescale == timing.timescale
            assert abs(out_timing.presented_s - timing.presented_s) <= 0.5 / 30
            assert (out_geometry.width, out_geometry.height, out_geometry.matrix) == (
                geometry.width, geometry.height, geometry.matrix,
            )
    assert movie_geometry(paths[("S1", "untitled.mov")]).matrix[:2] == (0, -65536)
    assert paths[("S3", "wa.mp4")].read_bytes() == h264_before
    assert paths[("S1", "clip.mov")].stat().st_nlink == 2
    assert paths[("S1", "clip.mov")].stat().st_ino == paths[("S2", "clip.mov")].stat().st_ino
    assert paths[("S1", "keyed-real.mov")].stat().st_ino == paths[("S2", "keyed-real.mov")].stat().st_ino
    root = export.resolve()
    by_path = {entry["path"]: entry for entry in record["converted"]}
    assert set(by_path) == {
        p.resolve().relative_to(root).as_posix() for key, p in paths.items() if key != ("S3", "wa.mp4")
    }
    for (uuid, name), path in paths.items():
        if name == "wa.mp4":
            continue
        entry = by_path[path.resolve().relative_to(root).as_posix()]
        assert entry == {
            "path": entry["path"],
            "asset": name,
            "sourceCodec": "HEVC" if name == "untitled.mov" else "ProRes",
            "targetCodec": "VP9 alpha" if name == "keyed-real.mov" else "H.264",
            "sourceSha256": sources[(uuid, name)][2],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    assert pm.unconverted(export, slides) == []
    assert pm.convert_movies(export, slides, log=lines.append)["converted"] == []


@pytest.mark.parametrize(
    "bad, match",
    [
        ("alpha_loss", "lost transparency during conversion"),
        ("odd", "its size 319×180 is odd"),
        ("dropped", "the converted file plays"),
        ("missing", "its file is missing from the export"),
        ("disk_full", r"H\.264 conversion failed: \[Errno 28\] No space left on device"),
    ],
)
def test_refuses_by_name_and_leaves_the_export_untouched(tmp_path, monkeypatch, clips, bad, match):
    clip = clips["alpha_real"] if bad == "alpha_loss" else clips.get(bad, clips["alpha_const"])
    export, slides, paths = export_with(tmp_path, monkeypatch, [
        ("S1", clips["prores"], "fine.mov"),
        ("S2", clip, "bad.mov"),
    ])
    if bad == "dropped":
        encode_argv = pm._encode_argv

        def dropping_argv(*args):
            argv = encode_argv(*args)
            return [*argv[:-1], "-frames:v", "20", argv[-1]]

        monkeypatch.setattr(pm, "_encode_argv", dropping_argv)
    if bad == "alpha_loss":
        alpha_argv = pm._alpha_encode_argv

        def opaque_argv(*args):
            argv = alpha_argv(*args)
            argv[argv.index("yuva420p")] = "yuv420p"
            return argv

        monkeypatch.setattr(pm, "_alpha_encode_argv", opaque_argv)
    if bad == "disk_full":
        def full_disk(*_args):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(pm.os, "replace", full_disk)
    missing = []
    if bad == "missing":
        paths[("S2", "bad.mov")].unlink()
        missing = [paths[("S2", "bad.mov")].relative_to(export).as_posix()]
    before = tree_shas(export)

    with pytest.raises(PreviewError, match=rf"bad\.mov: {match}"):
        pm.convert_movies(export, slides, log=lambda _line: None)

    assert tree_shas(export) == before
    assert pm.unconverted(export, slides) == sorted([p for p in before if p.endswith(".mov")] + missing)
