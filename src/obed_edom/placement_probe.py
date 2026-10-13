"""Compositor placement probe: pinned assets, probe page and the pure snap/frac classifier (plan keynote_live_cef_placement §11.1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

PATTERN_SHA256 = ""
MOTION_SHA256 = ""
MANIFEST_SHA256 = ""


class ProbeVerdict(str, Enum):
    SNAP = "snap"
    FRAC = "frac"
    UNKNOWN = "unknown"


class ToneMap(str, Enum):
    IDENTITY = "identity"
    GPU_ANALYTIC = "gpu_analytic"


@dataclass(frozen=True)
class ProbeAsset:
    name: str
    sha256: str
    data: bytes


@dataclass(frozen=True)
class ProbeAssets:
    manifest_sha256: str
    pattern: ProbeAsset
    motion: ProbeAsset


@dataclass(frozen=True)
class ProbeSpec:
    run_id: str
    width: int
    height: int
    fps: int
    dpr: float


@dataclass(frozen=True)
class ProbeIdentity:
    run_id: str
    source_uuid: str | None
    target_id: str
    context_id: str
    connection_generation: int
    ua: str
    dpr: float


@dataclass(frozen=True)
class ProbeCapture:
    identity: ProbeIdentity
    sequence: int
    nonce: str
    phase: str
    pose: int | None
    png: bytes
    paint_observed_s: float
    capture_started_s: float
    capture_finished_s: float


@dataclass(frozen=True)
class PoseGeometry:
    pose: int
    rect: tuple[float, float, float, float]
    content_box: tuple[float, float, float, float]
    box: tuple[int, int, int, int]
    snap_dy: int
    frac_dy: int


@dataclass(frozen=True)
class ClassifierInput:
    spec: ProbeSpec
    assets_sha256: tuple[str, str, str]
    identity: ProbeIdentity
    ready_state: int
    video_size: tuple[int, int]
    color_tuple: tuple[str, str, str, bool]
    freshness: tuple[ProbeCapture, ...]
    poses: tuple[PoseGeometry, ...]
    captures: tuple[ProbeCapture, ...]


@dataclass(frozen=True)
class PoseScore:
    pose: int
    tone_map: ToneMap
    snap_share: float
    frac_share: float
    inner_pixels: int


@dataclass(frozen=True)
class ProbeResult:
    verdict: ProbeVerdict
    tone_map: ToneMap | None
    grant_eligible: bool
    reason: str
    scores: tuple[PoseScore, ...]


def load_probe_assets() -> ProbeAssets:
    raise NotImplementedError


def render_probe_page(spec: ProbeSpec) -> bytes:
    raise NotImplementedError


def classify_probe(data: ClassifierInput) -> ProbeResult:
    raise NotImplementedError
