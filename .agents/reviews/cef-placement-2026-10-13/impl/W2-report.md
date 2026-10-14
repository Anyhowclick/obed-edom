# W2 placement-probe implementation report

## Files changed

- `src/obed_edom/placement_probe.py`
  - Preserved the frozen §11.1 enums and dataclass names/fields.
  - Added full immutable release pins, asset/manifest verification, the probe-page renderer, freshness validation, and the pure snap/frac classifier.
- `src/obed_edom/data/placement_probe.mp4`
  - Recreated retained `p2like` recipe: 1920×540, 30 fps, 3 s, H.264 High/QP 1, yuv420p, TV-range BT.709, faststart.
- `src/obed_edom/data/placement_motion.mp4`
  - Added silent 1920×540, 30 fps, 3 s H.264 motion stimulus with a 16-bit MSB-first binary frame counter.
- `src/obed_edom/data/placement_probe.json`
  - Added schema-1 provenance, dimensions/rate/duration/color tuple, toolchain versions, normalized generator argv, source-PNG digest, repeat digest, byte counts, and full asset hashes.
- `scripts/generate_placement_probe.py`
  - Added deterministic generation of both clips and the manifest using `/opt/homebrew/bin/ffmpeg`.
- `tests/test_placement_probe.py`
  - Added one parameterized test function covering assets/tampering, page contract, snap, frac, unknown, stale nonce, unstable pairs, unsupported DPR, exact 2%/20% boundaries, 3-pixel erosion, max-channel scoring, and identity-vs-GPU mapping.
- `pyproject.toml`
  - Added the two MP4s and JSON manifest explicitly to `obed_edom` package data.

## Frozen-contract mapping

- `ProbeVerdict`, `ToneMap`, `ProbeAsset`, `ProbeAssets`, `ProbeSpec`, `ProbeIdentity`, `ProbeCapture`, `PoseGeometry`, `ClassifierInput`, `PoseScore`, and `ProbeResult` retain the coordinator-provided §11.1 names and shapes.
- `PATTERN_SHA256`, `MOTION_SHA256`, and `MANIFEST_SHA256` are lowercase full 64-hex literals:
  - pattern: `7b7d66b582d1b0df0c27c11bd945c1606d11ad4d34f5031b726ee22319d19870`
  - motion: `e4640a667bbbdfca47dbde5942455d262c69a4e80c031b22cada0753763b3bfe`
  - manifest: `c804288b674507df28c6d165f09634d6483458cb4f40fb74ff73c98ec29d0bcf`
- The pattern regeneration is the retained artifact: 144,100 bytes and SHA-256 starts `7b7d66b5`; the recovered full digest is above. The generated PNG digest is `a3639a5b43e8482c1eee61015ef32443bde92fcccb6ffd94d60188141948834f`.
- The generator records Python 3.12.12, NumPy 2.5.3, Pillow 12.3.0, FFmpeg 9.0.2, x264 r3222, and its own SHA-256 `2dd0ad8a2e653c25f08558fcd7e7139021a18982ab2d85d21860cea6d1cea7f9`.
- `load_probe_assets()` verifies the pinned manifest bytes first, both asset hashes and byte counts, manifest filenames/metadata, and the independent repeated-pattern hash before returning bytes.
- `render_probe_page()` exposes the synchronous queueing API `window.__obedProbe.command(...)` and polling `snapshot()`, uses the two retained fractional poses and geometry, serves relative clip URLs, paints a 128-bit nonce as the frozen 16×8 grid at `(1600,16)`, uses one video element for motion then pattern, and publishes camelCase geometry.
- `classify_probe()` verifies binding, timing, pacing, exact nonce decoding, distinct motion hashes/counters, stable RGBA pattern pairs, source size/color/pins, and DPR 1 before applying the frozen eroded-mask/max-channel/4-LSB/2%/20% rules under identity and analytic GPU maps. Only a unique GPU-map classification is grant eligible.

## Deviations from §11

None in W2 implementation. The old full pattern digest was not present in retained evidence, but exact reproduction succeeded: both the retained 144,100-byte size and `7b7d66b5…` prefix match, and two full regenerations were byte-identical at `7b7d66b582d1b0df0c27c11bd945c1606d11ad4d34f5031b726ee22319d19870`. This therefore did not require O3's new-artifact fallback.

## Verification

- Required targeted test command:
  - `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_placement_probe.py -q -n 2 -p no:cacheprovider`
  - Final result: **14 passed, 0 failed** in 1.30 s.
- Reproducibility command regenerated all three artifacts in a fresh `/tmp/obed-placement-repeat.*` directory and compared them byte-for-byte with `cmp`.
  - Result: all three matched; pattern, motion, and manifest SHA-256 values were respectively `7b7d66b5…`, `e4640a66…`, and `c804288b…`.
- Rendered page JavaScript was piped to `node --check`.
  - Result: exit 0, no syntax findings.
- `ffprobe` verified both clips as H.264 High, 1920×540, yuv420p, TV-range BT.709, 30/1 fps, 3.000000 s, with no audio stream; motion counter samples decoded to frame indices 0, 10, 20, and 89.
- `git diff --check` on W2 text files: exit 0.

## Open items for coordinator

- W6 still owns the required CEF/Chrome harness requalification and all OBS/browser gates; none were run here under the stream restrictions.
- Wheel-installed asset verification could not be executed in this sandbox: the venv has neither `build` nor `pip`, and `uv build` panicked in its macOS system-configuration/cache path even with `UV_CACHE_DIR` moved to `/tmp`. The explicit package-data entries and source-installed hash checks are present; please verify the final wheel contents in the coordinator environment.
- No known external-red tests were run; the instructed W2-only test file is green.
