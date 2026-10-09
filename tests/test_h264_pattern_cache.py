"""The disposable H.264 pattern movie (`_write_h264_pattern` / `_replace_hevc_movies` in
`scripts/p2_recovery_html_dissolve_live.py`) is encoded once per call for identical slots and
memoised on disk under `<cache_root>/h264-pattern/`.

Fixture-free and fast: ffmpeg is replaced by a tiny executable script that logs its argv (one
JSON line per invocation) and writes bytes derived from its own tag and argv, so a "different
ffmpeg binary" or "different argv" produces different output, exactly as the real encoder would.
`OBED_EDOM_CACHE_DIR` points the cache at a per-test directory.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "p2_recovery_html_dissolve_live.py"
DURATION = 46.0333
MOVIE = f"Untitled.mov-0.0000-{DURATION}.mov"


def _load_dissolve_live_module():
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("p2_recovery_html_dissolve_live", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dissolve_live = _load_dissolve_live_module()

FAKE_FFMPEG = """#!{python}
# tag: {tag}
import json, os, sys, time
time.sleep(float(os.environ.get("FAKE_FFMPEG_SLEEP", "0")))
with open(os.environ["FAKE_FFMPEG_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_FFMPEG_FAIL"):
    sys.exit(1)
with open(sys.argv[-1], "wb") as f:
    f.write(("{tag}|" + "|".join(sys.argv[1:-1])).encode() * 64)
"""


class FakeFfmpeg:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.dir = tmp_path / "bin"
        self.dir.mkdir()
        self.log = tmp_path / "ffmpeg-calls.jsonl"
        self.log.touch()
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("FAKE_FFMPEG_LOG", str(self.log))
        self.use("a")

    def make(self, tag: str) -> Path:
        exe = self.dir / f"ffmpeg-{tag}"
        exe.write_text(FAKE_FFMPEG.format(python=sys.executable, tag=tag))
        exe.chmod(0o755)
        return exe

    def use(self, tag: str) -> Path:
        exe = self.make(tag)
        self.monkeypatch.setattr(dissolve_live, "_ffmpeg", lambda: str(exe))
        return exe

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeFfmpeg:
    monkeypatch.setenv("OBED_EDOM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("OBED_H264_PATTERN_CACHE", raising=False)
    monkeypatch.delenv("FAKE_FFMPEG_SLEEP", raising=False)
    monkeypatch.delenv("FAKE_FFMPEG_FAIL", raising=False)
    return FakeFfmpeg(tmp_path, monkeypatch)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export(root: Path, slots: list[str]) -> Path:
    """A stand-in HTML export: one HEVC placeholder per `assets/<uuid>/assets/<name>` slot."""
    for i, name in enumerate(slots):
        mov = root / "assets" / f"UUID-{i}" / "assets" / name
        mov.parent.mkdir(parents=True)
        mov.write_bytes(b"HEVC original " + name.encode())
    return root


def _cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "h264-pattern"


def _cache_entry(tmp_path: Path) -> tuple[Path, dict]:
    movies = sorted(_cache_dir(tmp_path).glob("*.mp4"))
    assert len(movies) == 1, movies
    return movies[0], json.loads(movies[0].with_suffix(".json").read_text())


def test_ffmpeg_argv_is_the_original_encode(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    """The cache must not change what is encoded: the argv (between the executable and the
    output path) is byte-for-byte the pre-cache command from af5c7ff7 — the movie whose sha256
    is 8b20587612e9… with the bundled imageio-ffmpeg."""
    dissolve_live._write_h264_pattern(tmp_path / "out" / MOVIE, seconds=DURATION)
    (argv,) = ffmpeg.calls()
    assert argv[:-1] == [
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=gray:s=1920x540:rate=30:duration=46.0333",
        "-vf",
        r"geq=lum='if(lt(X\,120)*lt(Y\,48)\,16+mod(N\,220)\,if(gt(mod(X+T*720\,48)\,24)\,230\,25))':cb=128:cr=128",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-an",
        "-movflags",
        "+faststart",
    ]
    assert argv[-1].endswith(".mp4"), "ffmpeg picks the mp4 muxer from the output extension"


@pytest.mark.parametrize("cache", ["on", "off"])
def test_identical_slots_encode_once_per_call(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: str
) -> None:
    """Four slots with the same duration (the real P2 export) cost one encode; a slot with a
    different duration is keyed separately and gets its own encode. Holds with the disk cache
    off too, so the saving does not depend on the cache."""
    if cache == "off":
        monkeypatch.setenv("OBED_H264_PATTERN_CACHE", "off")
    other = "Untitled.mov-0.0000-10.0000.mov"
    root = _export(tmp_path / "export", [MOVIE] * 4 + [other])
    record = dissolve_live._replace_hevc_movies(root)

    assert len(ffmpeg.calls()) == 2
    assert sorted(c[4] for c in ffmpeg.calls()) == [
        "color=c=gray:s=1920x540:rate=30:duration=10.0",
        "color=c=gray:s=1920x540:rate=30:duration=46.0333",
    ]
    assert record["replacedN"] == 5
    by_name: dict[str, list[dict]] = {}
    for info in record["files"]:
        by_name.setdefault(Path(info["replaced"]).name, []).append(info)
        assert _sha(root / info["replaced"]) == info["sha256"]
        assert info["path"] == str(root / info["replaced"])
        assert info["bytes"] == (root / info["replaced"]).stat().st_size
    same = by_name[MOVIE]
    assert len({i["sha256"] for i in same}) == 1
    assert [i["source"] for i in same] == ["encoded", "clone", "clone", "clone"]
    assert all(i["clonedFrom"] == same[0]["replaced"] for i in same[1:])
    assert by_name[other][0]["source"] == "encoded"
    assert by_name[other][0]["seconds"] == 10.0
    assert by_name[other][0]["sha256"] != same[0]["sha256"]
    assert not list(root.rglob("*.tmp*")), "no temp files left behind"


def test_cache_hit_across_calls_skips_encoder(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    first = dissolve_live._write_h264_pattern(tmp_path / "arm1" / MOVIE, seconds=DURATION)
    second = dissolve_live._write_h264_pattern(tmp_path / "arm2" / MOVIE, seconds=DURATION)

    assert len(ffmpeg.calls()) == 1
    assert (first["source"], second["source"]) == ("encoded", "cache")
    assert first["sha256"] == second["sha256"] == _sha(tmp_path / "arm2" / MOVIE)
    assert first["cacheKey"] == second["cacheKey"] and len(first["cacheKey"]) == 64
    assert (tmp_path / "arm1" / MOVIE).read_bytes() == (tmp_path / "arm2" / MOVIE).read_bytes()
    movie, meta = _cache_entry(tmp_path)
    assert meta["key"] == first["cacheKey"] and meta["sha256"] == _sha(movie)


def test_cached_copy_is_independent_of_the_cache_entry(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    """The delivered file is a clone, not a hard link: scribbling on an arm's copy (as a later
    pipeline step might) cannot reach the cache entry another arm will read."""
    dest = tmp_path / "arm1" / MOVIE
    dissolve_live._write_h264_pattern(dest, seconds=DURATION)
    dest.write_bytes(b"scribbled")
    movie, meta = _cache_entry(tmp_path)
    assert _sha(movie) == meta["sha256"]
    again = dissolve_live._write_h264_pattern(tmp_path / "arm2" / MOVIE, seconds=DURATION)
    assert again["source"] == "cache"


def test_different_binary_argv_or_parameters_miss(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = dissolve_live._write_h264_pattern(tmp_path / "base" / MOVIE, seconds=DURATION)

    ffmpeg.use("b")
    other_binary = dissolve_live._write_h264_pattern(tmp_path / "bin" / MOVIE, seconds=DURATION)
    assert other_binary["source"] == "encoded"
    assert other_binary["cacheKey"] != base["cacheKey"]

    ffmpeg.use("a")
    assert dissolve_live._write_h264_pattern(tmp_path / "back" / MOVIE, seconds=DURATION)["source"] == "cache"

    original_args = dissolve_live._h264_pattern_args
    monkeypatch.setattr(
        dissolve_live, "_h264_pattern_args", lambda **kw: [*original_args(**kw)[:-1], "+faststart+frag_keyframe"]
    )
    other_argv = dissolve_live._write_h264_pattern(tmp_path / "argv" / MOVIE, seconds=DURATION)
    assert other_argv["source"] == "encoded"
    monkeypatch.setattr(dissolve_live, "_h264_pattern_args", original_args)

    other_fps = dissolve_live._write_h264_pattern(tmp_path / "fps" / MOVIE, seconds=DURATION, fps=25)
    other_secs = dissolve_live._write_h264_pattern(tmp_path / "secs" / MOVIE, seconds=12.5)
    assert other_fps["source"] == other_secs["source"] == "encoded"

    keys = {r["cacheKey"] for r in (base, other_binary, other_argv, other_fps, other_secs)}
    assert len(keys) == 5
    assert len(ffmpeg.calls()) == 5


@pytest.mark.parametrize("damage", ["flip-byte", "truncate", "delete-movie", "garbled-meta", "meta-other-key"])
def test_damaged_cache_entry_is_detected_and_reencoded(
    ffmpeg: FakeFfmpeg, tmp_path: Path, damage: str
) -> None:
    """A hit is only trusted when the delivered copy hashes to the sha recorded at encode time.
    Same-size corruption (flip-byte) proves the check is content, not size or path."""
    good = dissolve_live._write_h264_pattern(tmp_path / "arm1" / MOVIE, seconds=DURATION)
    movie, meta = _cache_entry(tmp_path)
    data = bytearray(movie.read_bytes())
    if damage == "flip-byte":
        data[len(data) // 2] ^= 0xFF
        movie.write_bytes(bytes(data))
    elif damage == "truncate":
        movie.write_bytes(bytes(data[:100]))
    elif damage == "delete-movie":
        movie.unlink()
    elif damage == "garbled-meta":
        movie.with_suffix(".json").write_text("{not json")
    elif damage == "meta-other-key":
        movie.with_suffix(".json").write_text(json.dumps({**meta, "key": "0" * 64}))

    dest = tmp_path / "arm2" / MOVIE
    again = dissolve_live._write_h264_pattern(dest, seconds=DURATION)
    assert again["source"] == "encoded"
    assert len(ffmpeg.calls()) == 2
    assert again["sha256"] == good["sha256"] == _sha(dest)
    movie, meta = _cache_entry(tmp_path)
    assert meta["sha256"] == _sha(movie) == good["sha256"], "the entry is repaired"
    assert dissolve_live._write_h264_pattern(tmp_path / "arm3" / MOVIE, seconds=DURATION)["source"] == "cache"


def test_failed_encode_raises_and_leaves_no_entry(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "arm1" / MOVIE
    dest.parent.mkdir()
    dest.write_bytes(b"HEVC original")
    monkeypatch.setenv("FAKE_FFMPEG_FAIL", "1")
    with pytest.raises(RuntimeError, match="ffmpeg encode failed"):
        dissolve_live._write_h264_pattern(dest, seconds=DURATION)
    assert dest.read_bytes() == b"HEVC original"
    assert not list(_cache_dir(tmp_path).glob("*.mp4")) and not list(_cache_dir(tmp_path).glob("*.json"))
    assert not list(_cache_dir(tmp_path).glob("*.tmp*")) and not list(dest.parent.glob("*.tmp*"))
    monkeypatch.delenv("FAKE_FFMPEG_FAIL")
    assert dissolve_live._write_h264_pattern(dest, seconds=DURATION)["source"] == "encoded"


_RUNNER = """
import importlib.util, json, sys, time
from pathlib import Path
repo, stub, dest, ready, go = sys.argv[1:]
for sub in ("scripts", "src"):
    sys.path.insert(0, f"{repo}/{sub}")
spec = importlib.util.spec_from_file_location("dissolve_live", f"{repo}/scripts/p2_recovery_html_dissolve_live.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m._ffmpeg = lambda: stub
Path(ready).touch()
deadline = time.monotonic() + 60
while not Path(go).exists():
    if time.monotonic() > deadline:
        sys.exit("never released")
    time.sleep(0.01)
print(json.dumps(m._write_h264_pattern(Path(dest), seconds=46.0333)))
"""


def test_concurrent_fillers_encode_once_and_leave_one_valid_entry(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    """Two processes (two P2 arms) miss the same key at the same moment. The encoder sleeps so
    the fills would overlap without the per-key lock; with it, one encodes and the other waits
    and takes the hit. Both arms end up with intact bytes and the cache holds one valid entry."""
    runner = tmp_path / "runner.py"
    runner.write_text(_RUNNER)
    stub = ffmpeg.make("a")
    go = tmp_path / "go"
    env = {**os.environ, "FAKE_FFMPEG_SLEEP": "1.0"}
    procs = []
    for i in range(2):
        cmd = [sys.executable, str(runner), str(REPO), str(stub), str(tmp_path / f"arm{i}" / MOVIE),
               str(tmp_path / f"ready{i}"), str(go)]
        procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    deadline = time.monotonic() + 60
    while not all((tmp_path / f"ready{i}").exists() for i in range(2)):
        assert time.monotonic() < deadline, "runners never became ready"
        time.sleep(0.01)
    go.touch()
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        results.append(json.loads(out))

    assert len(ffmpeg.calls()) == 1
    assert sorted(r["source"] for r in results) == ["cache", "encoded"]
    assert results[0]["sha256"] == results[1]["sha256"]
    for i in range(2):
        assert _sha(tmp_path / f"arm{i}" / MOVIE) == results[0]["sha256"]
    movie, meta = _cache_entry(tmp_path)
    assert meta["sha256"] == _sha(movie) == results[0]["sha256"]
    assert not list(_cache_dir(tmp_path).glob("*.tmp*"))


def test_force_off_env_reencodes_and_leaves_cache_alone(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dissolve_live._write_h264_pattern(tmp_path / "arm1" / MOVIE, seconds=DURATION)
    before = {p.name: p.read_bytes() for p in _cache_dir(tmp_path).iterdir()}

    monkeypatch.setenv("OBED_H264_PATTERN_CACHE", "off")
    off = dissolve_live._write_h264_pattern(tmp_path / "arm2" / MOVIE, seconds=DURATION)
    assert off["source"] == "encoded" and off["cacheKey"] is None
    assert off["sha256"] == _sha(tmp_path / "arm2" / MOVIE)
    assert len(ffmpeg.calls()) == 2
    assert {p.name: p.read_bytes() for p in _cache_dir(tmp_path).iterdir()} == before

    monkeypatch.setenv("OBED_H264_PATTERN_CACHE", "0")
    with pytest.raises(SystemExit, match="must be unset or 'off'"):
        dissolve_live._write_h264_pattern(tmp_path / "arm3" / MOVIE, seconds=DURATION)


def test_unusable_cache_dir_falls_back_to_encoding(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("OBED_EDOM_CACHE_DIR", str(blocker))
    info = dissolve_live._write_h264_pattern(tmp_path / "arm1" / MOVIE, seconds=DURATION)
    assert info["source"] == "encoded" and info["cacheKey"] is None
    assert info["sha256"] == _sha(tmp_path / "arm1" / MOVIE)


def test_replacement_record_carries_cache_hit_and_sha(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    """What `p2_recovery_html_adversarial.py --disposable` writes to `asset-replace.json`."""
    records = []
    for arm in ("arm1", "arm2"):
        root = _export(tmp_path / arm, [MOVIE] * 4)
        records.append(json.loads(json.dumps(dissolve_live._replace_hevc_movies(root))))
        for info in records[-1]["files"]:
            assert info["sha256"] == _sha(root / info["replaced"])

    first, second = records
    assert [f["source"] for f in first["files"]] == ["encoded", "clone", "clone", "clone"]
    assert [f["source"] for f in second["files"]] == ["cache", "clone", "clone", "clone"]
    key = first["files"][0]["cacheKey"]
    assert key and all(f["cacheKey"] == key for r in records for f in r["files"])
    assert len({f["sha256"] for r in records for f in r["files"]}) == 1
    assert len(ffmpeg.calls()) == 1


def test_prewarm_fills_the_cache_so_later_arms_only_clone(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    """`run_gates.sh` prewarms once before any timed run, so no P2 arm's ffmpeg encode overlaps a
    capture: every duration the arms will need is encoded up front, and the arms then hit."""
    other = "Untitled.mov-0.0000-10.0000.mov"
    source = _export(tmp_path / "html-unmodified", [MOVIE] * 4 + [other])
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}

    cold = dissolve_live.prewarm_h264_patterns(source)
    assert [(r["seconds"], r["source"]) for r in cold] == [(10.0, "encoded"), (DURATION, "encoded")]
    assert all(len(r["cacheKey"]) == 64 and len(r["sha256"]) == 64 for r in cold)
    assert len(ffmpeg.calls()) == 2
    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == before, "the source export is untouched"

    warm = dissolve_live.prewarm_h264_patterns(source)
    assert [r["source"] for r in warm] == ["cache", "cache"]
    assert [(r["cacheKey"], r["sha256"]) for r in warm] == [(r["cacheKey"], r["sha256"]) for r in cold]

    arm = _export(tmp_path / "arm", [MOVIE] * 4 + [other])
    record = dissolve_live._replace_hevc_movies(arm)
    assert sorted(f["source"] for f in record["files"]) == ["cache", "cache", "clone", "clone", "clone"]
    assert len(ffmpeg.calls()) == 2, "no encode after the prewarm"


def test_prewarm_with_the_cache_off_encodes_nothing(
    ffmpeg: FakeFfmpeg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OBED_H264_PATTERN_CACHE", "off")
    source = _export(tmp_path / "html-unmodified", [MOVIE] * 2)
    assert dissolve_live.prewarm_h264_patterns(source) == [{"seconds": DURATION, "source": "off", "cacheKey": None}]
    assert ffmpeg.calls() == []
    assert not _cache_dir(tmp_path).exists()


def test_prewarm_of_an_export_without_movies_is_empty(ffmpeg: FakeFfmpeg, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert dissolve_live.prewarm_h264_patterns(tmp_path / "empty") == []
    assert ffmpeg.calls() == []
