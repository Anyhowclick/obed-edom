"""On-demand Keynote HTML build preview (P1).

Parses an HTML export, maps player slides back to the source deck's original
ordinals, and caches the result by source digest, parser version, and renderer
contract. Reuse also requires the current Keynote identity. Live export uses
``dsk_live.LiveBatch``; this module must not import ``web.*``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obed_edom import keynote_app
from obed_edom.baseline import deck_digest
from obed_edom.dsk_live import LiveBatch, _as_escape, _keynote_tell, _keynote_terms, _osascript_path
from obed_edom.iwa_runs import _normalize_text
from obed_edom.offline_inspect import _canvas_size
from obed_edom.paths import _within_root, output_root

MANIFEST_VERSION = 2
PARSER_VERSION = 2
# Adapter/player contract this parser understands. Bump when hash channel,
# identity field, or required header fields change. Distinct from Keynote's
# own HTML export major/minor (measured 1.2 on 2026-09-12).
RENDERER_CONTRACT_VERSION = 1
# Recorded in tests/fixtures/html_preview/renderer_contract.json from the
# 2026-09-12 probe: header.json major/minor on both DSK and GW exports.
EXPORT_CONTRACT_MAJOR = 1
EXPORT_CONTRACT_MINOR = 2
# Recorded in tests/fixtures/html_preview/hash_channel.json from the 2026-09-12
# probe: the player writes #<n> on every advance and honours hash assignment.
# First exported slide is #0 (slideList order).
PLAYER_HASH_INDEX_BASE = 0
HTML_PREVIEW_ROOT = ".html-preview"
HEADER_CANDIDATES = ("assets/header.json", "assets/header.jsonp")
PLAYER_JS = Path("assets") / "player" / "main.js"
_JSON_ASSIGN = re.compile(r"^(?:(?:var|let|const)\s+)?[A-Za-z_$][\w$]*\s*=\s*")
_REMOTE_MEDIA = re.compile(
    r"https?://(?:(?:www\.)?youtube\.com/embed|player\.vimeo\.com)",
    re.IGNORECASE,
)
_SOURCE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REGISTRY_LOCK = threading.Lock()
PREVIEW_ISSUE_SOURCE = "obed-edom-preview"
_DIAGNOSTICS_MARK = "data-obed-preview-diagnostics"
# First script in the served player document. Must run before assets/player/main.js.
_PLAYER_DIAGNOSTICS_SCRIPT = """
(function(){
  if (window.__obedPreviewDiagnostics) return;
  window.__obedPreviewDiagnostics = true;
  function send(kind, detail) {
    var label = kind + ": " + String(detail == null ? "" : detail).replace(/\\s+/g, " ").trim();
    if (label.length <= kind.length + 2) return;
    try { parent.postMessage({ source: "obed-edom-preview", label: label }, "*"); } catch (e) {}
  }
  window.addEventListener("error", function(event) {
    if (event.message) { send("error", event.message); return; }
    var el = event.target;
    if (el && el !== window && el !== document) {
      send("resource", el.currentSrc || el.src || el.href || el.nodeName || "failed");
    }
  }, true);
  window.addEventListener("unhandledrejection", function(event) {
    send("error", event.reason || "unhandledrejection");
  });
  var cons = console;
  var origError = cons.error.bind(cons);
  var origWarn = cons.warn.bind(cons);
  cons.error = function() { send("console", Array.prototype.join.call(arguments, " ")); origError.apply(cons, arguments); };
  cons.warn = function() { send("console", Array.prototype.join.call(arguments, " ")); origWarn.apply(cons, arguments); };
  if (typeof fetch === "function") {
    var origFetch = fetch.bind(window);
    window.fetch = function(input, init) {
      var url = (typeof input === "string" || (typeof URL !== "undefined" && input instanceof URL)) ? String(input) : input.url;
      return origFetch(input, init).then(function(res) {
        if (!res.ok) send("network", res.status + " " + url);
        return res;
      }, function(err) { send("network", "failed " + url); throw err; });
    };
  }
  if (typeof XMLHttpRequest !== "undefined") {
    var XO = XMLHttpRequest.prototype.open;
    var XS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
      this.__obedUrl = String(url);
      return XO.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
      var xhr = this;
      var url = xhr.__obedUrl || "";
      xhr.addEventListener("error", function() { send("network", "failed " + url); });
      xhr.addEventListener("load", function() { if (xhr.status >= 400) send("network", xhr.status + " " + url); });
      return XS.apply(xhr, arguments);
    };
  }
})();
""".strip()


def inject_player_diagnostics(html: str) -> str:
    """Put capture hooks in the player document before any exported scripts or assets."""
    if _DIAGNOSTICS_MARK in html:
        return html
    snippet = f'<script {_DIAGNOSTICS_MARK}="1">{_PLAYER_DIAGNOSTICS_SCRIPT}</script>'
    match = re.search(r"<head[^>]*>", html, flags=re.IGNORECASE)
    if match:
        return html[: match.end()] + snippet + html[match.end() :]
    match = re.search(r"<html[^>]*>", html, flags=re.IGNORECASE)
    if match:
        return html[: match.end()] + snippet + html[match.end() :]
    return snippet + html


class PreviewError(ValueError):
    """Operator-facing preview failure."""


class PreviewStale(PreviewError):
    """Source digest changed between propose and apply, or cache identity drifted."""


class PreviewStructureError(PreviewError):
    """Exported HTML tree is missing required player/header/slide files."""


class PreviewMappingError(PreviewError):
    """Exported slide sequence does not match the source non-skipped sequence."""


@dataclass(frozen=True)
class SourceSlide:
    ordinal: int
    slide_id: str
    skipped: bool
    identity: tuple[str, ...] = field(default_factory=tuple)


def preview_root() -> Path:
    return output_root() / HTML_PREVIEW_ROOT


def validate_source_digest(source_digest: str) -> str:
    digest = (source_digest or "").strip().lower()
    if not _SOURCE_DIGEST_RE.fullmatch(digest):
        raise PreviewError("invalid source digest")
    return digest


def cache_key(source_digest: str) -> str:
    digest = validate_source_digest(source_digest)
    return f"{digest}-p{PARSER_VERSION}-r{RENDERER_CONTRACT_VERSION}"


def parse_export_key(export_key: str) -> str:
    """Return the digest encoded in a server-minted cache key."""
    key = (export_key or "").strip().lower()
    suffix = f"-p{PARSER_VERSION}-r{RENDERER_CONTRACT_VERSION}"
    if not key.endswith(suffix):
        raise PreviewError("invalid preview cache key")
    return validate_source_digest(key[: -len(suffix)])


def cache_dir(source_digest: str) -> Path:
    return unresolved_cache_folder(source_digest)


def unresolved_cache_folder(source_digest: str) -> Path:
    """Named cache folder. Do not ``resolve()`` before checking for a symlink."""
    name = cache_key(source_digest)
    root = preview_root()
    folder = root / name
    if folder.name != name or folder.parent != root:
        raise PreviewError("preview cache folder name mismatch")
    return folder


def unresolved_export_html(source_digest: str) -> Path:
    html = unresolved_cache_folder(source_digest) / "html"
    if html.name != "html":
        raise PreviewError("preview export folder name mismatch")
    return html


def reject_unresolved_cache_symlinks(source_digest: str) -> tuple[Path, Path]:
    """Refuse cache/html paths that are symlinks *before* ``resolve()`` follows them."""
    folder = unresolved_cache_folder(source_digest)
    html = unresolved_export_html(source_digest)
    if folder.is_symlink():
        raise PreviewError("preview cache folder cannot be a symlink")
    if html.is_symlink():
        raise PreviewError("preview export root cannot be a symlink")
    return folder, html


def resolved_cache_folder(source_digest: str) -> Path:
    """Absolute cache folder for a validated digest; must stay under preview_root()."""
    folder, _html = reject_unresolved_cache_symlinks(source_digest)
    cache = preview_root().resolve()
    resolved = folder.resolve()
    if resolved.name != folder.name or not _within_root(resolved, cache):
        raise PreviewError("preview cache folder is outside the cache root")
    return resolved


def current_keynote_identity() -> dict[str, str]:
    return {
        "keynoteVersion": keynote_app.app_version(),
        "keynoteBundleId": keynote_app.bundle_id(),
    }


def header_export_contract(header: dict[str, Any]) -> dict[str, int]:
    if "major" not in header or "minor" not in header:
        raise PreviewStructureError("header is missing export contract version")
    try:
        major = int(header["major"])
        minor = int(header["minor"])
    except (TypeError, ValueError) as exc:
        raise PreviewStructureError("header export contract version is not an integer") from exc
    return {"major": major, "minor": minor}


def validate_export_contract(header: dict[str, Any]) -> dict[str, int]:
    contract = header_export_contract(header)
    if (contract["major"], contract["minor"]) != (EXPORT_CONTRACT_MAJOR, EXPORT_CONTRACT_MINOR):
        raise PreviewStructureError(
            f"export contract {contract['major']}.{contract['minor']} is not "
            f"{EXPORT_CONTRACT_MAJOR}.{EXPORT_CONTRACT_MINOR}"
        )
    return contract


def identity_key(texts: Sequence[str]) -> tuple[str, ...]:
    tokens = {_normalize_text(text) for text in texts}
    return tuple(sorted(token for token in tokens if token))


def export_payload_identity(payload: Any) -> tuple[str, ...]:
    """Probe-backed identity: ``accessibility[].text`` from the 2026-09-12 HTML export."""
    if not isinstance(payload, dict):
        return ()
    texts: list[str] = []
    raw = payload.get("accessibility")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("text"):
                texts.append(str(item["text"]))
    return identity_key(texts)


def source_slide_identity(
    slide_id: str,
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    file_ids: dict[str, list[str]],
    cache: dict[str, Any],
) -> tuple[str, ...]:
    from obed_edom.iwa_runs import _slide_grouped_text, _slide_text_objects  # noqa: PLC0415

    fname = id_to_file.get(slide_id)
    ids = file_ids.get(fname, []) if fname else []
    texts = [str(obj.get("text") or "") for obj in _slide_text_objects(ids, objects, cache)]
    texts.extend(str(obj.get("text") or "") for obj in _slide_grouped_text(ids, objects, cache))
    return identity_key(texts)


def assert_identity_mapping(live: Sequence[SourceSlide], exported: Sequence[dict[str, Any]]) -> None:
    """Refuse a same-length reorder or any pairing that identity cannot confirm uniquely."""
    source_keys = [slide.identity for slide in live]
    export_keys = [tuple(item.get("identity") or ()) for item in exported]
    if len(source_keys) != len(export_keys):
        raise PreviewMappingError(
            f"exported {len(export_keys)} slide(s) but the source has {len(source_keys)} non-skipped slide(s)"
        )
    source_counts = Counter(source_keys)
    export_counts = Counter(export_keys)
    if source_counts != export_counts:
        raise PreviewMappingError("exported slide identities do not match the source")
    if any(count != 1 for count in source_counts.values()):
        raise PreviewMappingError("ambiguous source-to-export mapping")
    export_index = {key: index for index, key in enumerate(export_keys)}
    for index, key in enumerate(source_keys):
        if export_index[key] != index:
            raise PreviewMappingError("exported slides are not in source order")


def player_hash(player_index: int) -> str:
    return f"#{player_index + PLAYER_HASH_INDEX_BASE}"


def parse_jsonish(text: str) -> Any:
    """Parse raw JSON or the `var local_header = {...};` JSONP the exporter writes."""
    payload = text.lstrip("\ufeff").strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass
    stripped = _JSON_ASSIGN.sub("", payload, count=1).strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PreviewStructureError(f"could not parse JSON/JSONP: {exc}") from exc


def read_jsonish(path: Path) -> Any:
    return parse_jsonish(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def tree_bytes(root: Path) -> int:
    total = 0
    for child in root.rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def load_header(export_root: Path) -> tuple[dict[str, Any], str]:
    for rel in HEADER_CANDIDATES:
        path = export_root / rel
        if path.is_file() and not path.is_symlink():
            data = read_jsonish(path)
            if not isinstance(data, dict):
                raise PreviewStructureError(f"{rel} is not an object")
            return data, rel
    raise PreviewStructureError("export is missing assets/header.json or assets/header.jsonp")


def header_slide_list(header: dict[str, Any]) -> list[str]:
    raw = header.get("slideList")
    if not isinstance(raw, list) or not raw:
        raise PreviewStructureError("header.slideList is missing or empty")
    uuids: list[str] = []
    seen: set[str] = set()
    for item in raw:
        uuid = str(item or "").strip()
        if not uuid:
            raise PreviewStructureError("header.slideList contains an empty id")
        if uuid in seen:
            raise PreviewMappingError(f"header.slideList repeats {uuid}")
        seen.add(uuid)
        uuids.append(uuid)
    count = header.get("slideCount")
    if count is not None and int(count) != len(uuids):
        raise PreviewMappingError(
            f"header.slideCount ({count}) does not match slideList length ({len(uuids)})"
        )
    return uuids


def header_canvas(header: dict[str, Any], fallback: tuple[float, float]) -> dict[str, float]:
    width = header.get("slideWidth", header.get("width"))
    height = header.get("slideHeight", header.get("height"))
    if width and height:
        return {"width": float(width), "height": float(height)}
    return {"width": float(fallback[0]), "height": float(fallback[1])}


def source_slides(path: Path) -> tuple[list[SourceSlide], tuple[float, float]]:
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 — optional iwa extra

    objects, id_to_file, file_ids = _load_deck(path)
    cache: dict[str, Any] = {}
    slides = [
        SourceSlide(
            ordinal=index,
            slide_id=slide_id,
            skipped=skipped,
            identity=source_slide_identity(slide_id, objects, id_to_file, file_ids, cache),
        )
        for index, (slide_id, skipped) in enumerate(slide_order(objects), start=1)
    ]
    if not slides:
        raise PreviewStructureError(f"{path.name} has no slides")
    return slides, _canvas_size(objects)


def find_remote_media(node: Any) -> list[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if _REMOTE_MEDIA.search(value):
                lower = value.lower()
                if "youtube" in lower:
                    found.add("youtube")
                if "vimeo" in lower:
                    found.add("vimeo")
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return sorted(found)


def _slide_payload_path(slide_dir: Path, uuid: str) -> Path:
    for name in (f"{uuid}.json", f"{uuid}.jsonp", "slide.json", "slide.jsonp"):
        candidate = slide_dir / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    matches = [
        child
        for child in slide_dir.iterdir()
        if child.is_file()
        and not child.is_symlink()
        and child.suffix in {".json", ".jsonp"}
    ]
    if len(matches) == 1:
        return matches[0]
    raise PreviewStructureError(f"slide {uuid} is missing its JSON payload")


def slide_asset_paths(export_root: Path, uuid: str) -> dict[str, str]:
    slide_dir = export_root / "assets" / uuid
    if slide_dir.is_symlink() or not slide_dir.is_dir():
        raise PreviewStructureError(f"slide {uuid} folder is missing")
    payload = _slide_payload_path(slide_dir, uuid)
    assets: dict[str, str] = {
        "folder": f"assets/{uuid}",
        "payload": payload.relative_to(export_root).as_posix(),
    }
    thumb = slide_dir / "thumbnail.jpeg"
    if thumb.is_file() and not thumb.is_symlink():
        assets["thumbnail"] = thumb.relative_to(export_root).as_posix()
    return assets


def discover_export_assets(export_root: Path, uuids: Sequence[str]) -> list[dict[str, Any]]:
    index = export_root / "index.html"
    if not index.is_file() or index.is_symlink():
        raise PreviewStructureError("export is missing index.html")
    player = export_root / PLAYER_JS
    if not player.is_file() or player.is_symlink():
        raise PreviewStructureError(f"export is missing {PLAYER_JS.as_posix()}")
    out: list[dict[str, Any]] = []
    for uuid in uuids:
        assets = slide_asset_paths(export_root, uuid)
        payload = read_jsonish(export_root / assets["payload"])
        out.append(
            {
                "uuid": uuid,
                "assets": assets,
                "remoteMedia": find_remote_media(payload),
                "identity": export_payload_identity(payload),
            }
        )
    return out


def build_manifest(
    *,
    source: Sequence[SourceSlide],
    header: dict[str, Any],
    exported: Sequence[dict[str, Any]],
    source_digest: str,
    keynote_version: str,
    player_digest: str,
    canvas: dict[str, float],
    header_path: str,
    keynote_bundle_id: str | None = None,
) -> dict[str, Any]:
    header_uuids = header_slide_list(header)
    exported_uuids = [str(item["uuid"]) for item in exported]
    if exported_uuids != header_uuids:
        raise PreviewMappingError("discovered slide folders do not match header.slideList")
    contract = validate_export_contract(header)
    live = [slide for slide in source if not slide.skipped]
    if len(live) != len(header_uuids):
        raise PreviewMappingError(
            f"exported {len(header_uuids)} slide(s) but the source has {len(live)} non-skipped slide(s)"
        )
    assert_identity_mapping(live, exported)
    exported_by_uuid = {str(item["uuid"]): item for item in exported}
    identity = current_keynote_identity()
    slides: list[dict[str, Any]] = []
    player_index = 0
    for src in source:
        if src.skipped:
            slides.append(_skipped_entry(src))
            continue
        uuid = header_uuids[player_index]
        item = exported_by_uuid[uuid]
        slides.append(
            {
                "originalOrdinal": src.ordinal,
                "originalSlideId": src.slide_id,
                "skipped": False,
                "exportedUuid": uuid,
                "playerIndex": player_index,
                "playerHash": player_hash(player_index),
                "assetPaths": item["assets"],
                "unsupportedMedia": list(item.get("remoteMedia") or []),
                "identity": list(src.identity),
            }
        )
        player_index += 1
    return {
        "version": MANIFEST_VERSION,
        "parserVersion": PARSER_VERSION,
        "rendererContractVersion": RENDERER_CONTRACT_VERSION,
        "exportContract": contract,
        "hashIndexBase": PLAYER_HASH_INDEX_BASE,
        "sourceDigest": validate_source_digest(source_digest),
        "keynoteVersion": keynote_version,
        "keynoteBundleId": keynote_bundle_id or identity["keynoteBundleId"],
        "canvas": canvas,
        "playerDigest": player_digest,
        "headerPath": header_path,
        "slides": slides,
    }


def _skipped_entry(src: SourceSlide) -> dict[str, Any]:
    return {
        "originalOrdinal": src.ordinal,
        "originalSlideId": src.slide_id,
        "skipped": True,
        "exportedUuid": None,
        "playerIndex": None,
        "playerHash": None,
        "assetPaths": {},
        "unsupportedMedia": [],
        "identity": list(src.identity),
    }


def verify_manifest(
    manifest: dict[str, Any],
    source: Sequence[SourceSlide],
    source_digest: str,
    *,
    keynote_version: str | None = None,
    keynote_bundle_id: str | None = None,
) -> None:
    if int(manifest.get("version") or 0) != MANIFEST_VERSION:
        raise PreviewStructureError(
            f"unsupported preview manifest version {manifest.get('version')!r}"
        )
    if int(manifest.get("parserVersion") or 0) != PARSER_VERSION:
        raise PreviewStructureError(
            f"preview parser version {manifest.get('parserVersion')!r} is not {PARSER_VERSION}"
        )
    if int(manifest.get("rendererContractVersion") or 0) != RENDERER_CONTRACT_VERSION:
        raise PreviewStructureError(
            f"preview renderer contract {manifest.get('rendererContractVersion')!r} "
            f"is not {RENDERER_CONTRACT_VERSION}"
        )
    contract = manifest.get("exportContract")
    if not isinstance(contract, dict) or (
        int(contract.get("major") or -1),
        int(contract.get("minor") or -1),
    ) != (EXPORT_CONTRACT_MAJOR, EXPORT_CONTRACT_MINOR):
        raise PreviewStructureError("preview export contract does not match this renderer")
    identity = current_keynote_identity()
    expected_version = keynote_version if keynote_version is not None else identity["keynoteVersion"]
    expected_bundle = keynote_bundle_id if keynote_bundle_id is not None else identity["keynoteBundleId"]
    if manifest.get("keynoteVersion") != expected_version:
        raise PreviewStale("cached preview was exported with a different Keynote version")
    if manifest.get("keynoteBundleId") != expected_bundle:
        raise PreviewStale("cached preview was exported with a different Keynote identity")
    if manifest.get("sourceDigest") != validate_source_digest(source_digest):
        raise PreviewStale("cached preview does not match the current source digest")
    if int(manifest.get("hashIndexBase", PLAYER_HASH_INDEX_BASE)) != PLAYER_HASH_INDEX_BASE:
        raise PreviewStructureError("preview hash index base does not match this parser")
    slides = manifest.get("slides")
    if not isinstance(slides, list) or len(slides) != len(source):
        raise PreviewMappingError("manifest slide count does not match the source deck")
    player_seen: set[int] = set()
    exported = 0
    for src, entry in zip(source, slides, strict=True):
        if int(entry.get("originalOrdinal") or 0) != src.ordinal:
            raise PreviewMappingError("manifest originalOrdinal drifted from the source order")
        if str(entry.get("originalSlideId") or "") != src.slide_id:
            raise PreviewMappingError("manifest originalSlideId drifted from the source deck")
        if bool(entry.get("skipped")) != src.skipped:
            raise PreviewMappingError(f"slide {src.ordinal} skipped flag does not match the source")
        if tuple(entry.get("identity") or ()) != src.identity:
            raise PreviewMappingError(f"slide {src.ordinal} identity drifted from the source")
        if src.skipped:
            if entry.get("playerIndex") is not None or entry.get("exportedUuid"):
                raise PreviewMappingError(f"skipped slide {src.ordinal} has player identity")
            continue
        player_index = entry.get("playerIndex")
        if not isinstance(player_index, int) or player_index < 0:
            raise PreviewMappingError(f"slide {src.ordinal} is missing a player index")
        if player_index in player_seen:
            raise PreviewMappingError(f"player index {player_index} is mapped twice")
        if entry.get("playerHash") != player_hash(player_index):
            raise PreviewMappingError(f"slide {src.ordinal} hash is not the measured channel")
        if player_index != exported:
            raise PreviewMappingError(
                f"slide {src.ordinal} player index {player_index} is not export order {exported}"
            )
        player_seen.add(player_index)
        exported += 1
    live = sum(1 for slide in source if not slide.skipped)
    if exported != live:
        raise PreviewMappingError("manifest exported count does not match non-skipped source slides")


def manifest_from_export(
    export_root: Path,
    *,
    source: Sequence[SourceSlide],
    source_digest: str,
    keynote_version: str,
    canvas: tuple[float, float],
) -> dict[str, Any]:
    header, header_path = load_header(export_root)
    uuids = header_slide_list(header)
    exported = discover_export_assets(export_root, uuids)
    player_digest = file_sha256(export_root / PLAYER_JS)
    manifest = build_manifest(
        source=source,
        header=header,
        exported=exported,
        source_digest=source_digest,
        keynote_version=keynote_version,
        player_digest=player_digest,
        canvas=header_canvas(header, canvas),
        header_path=header_path,
    )
    verify_manifest(manifest, source, source_digest)
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PreviewStructureError("manifest.json is not an object")
    return data


def build_html_export_script(scratch: Path, dest: Path) -> str:
    """Close-by-name → open → exact-name bind → `export as HTML` → close. No properties."""
    stem = _as_escape(scratch.stem)
    doc_name = _as_escape(scratch.name)
    return "\n".join(
        [
            _keynote_terms(),
            _keynote_tell(),
            "  with timeout of 3600 seconds",
            "    activate",
            "    try",
            f'      close (every document whose name is "{stem}" or name is "{doc_name}") saving no',
            "      delay 0.3",
            "    end try",
            f'    set theFile to POSIX file "{_as_escape(str(scratch))}"',
            "    set theDoc to open theFile",
            "    delay 8",
            f'    if (name of theDoc) is not "{stem}" and (name of theDoc) is not "{doc_name}" then',
            '      error "scratch document name mismatch"',
            "    end if",
            f'    export theDoc to POSIX file "{_as_escape(str(dest))}" as HTML',
            '    log ("OBED" & tab & "1" & tab & ((current date) as string))',
            "    try",
            "      close theDoc saving no",
            "    end try",
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def export_html(deck: Path, dest: Path, *, log: Callable[[str], None] = print) -> None:
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work_root = dest.parent / f".export-work-{os.getpid()}"
    work_root.mkdir(parents=True, exist_ok=True)
    try:
        with LiveBatch(deck, work_root, log=log) as batch:
            assert batch.scratch is not None and batch.work is not None
            script_path = _osascript_path(build_html_export_script(batch.scratch, dest), batch.work)
            proc = batch.run(script_path)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
                raise PreviewError(f"HTML export failed: {err}")
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    if not (dest / "index.html").is_file():
        raise PreviewStructureError("HTML export finished without index.html")


def _registry_path() -> Path:
    return preview_root() / "registry.json"


def _load_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.is_file():
        return {"version": 1, "exports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "exports": {}}
    if not isinstance(data, dict):
        return {"version": 1, "exports": {}}
    data.setdefault("version", 1)
    data.setdefault("exports", {})
    return data


def _save_registry(data: dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _same_digest(expected: str | None, actual: str) -> bool:
    if not expected:
        return True
    try:
        return validate_source_digest(expected) == actual
    except PreviewError:
        return False


def claim_export(export_key: str, job_id: str, meta: dict[str, Any]) -> None:
    digest = parse_export_key(export_key)
    _folder, html = reject_unresolved_cache_symlinks(digest)
    with _REGISTRY_LOCK:
        registry = _load_registry()
        entry = dict(registry["exports"].get(export_key) or {})
        claims = [str(c) for c in entry.get("claims") or [] if str(c) != job_id]
        claims.append(job_id)
        entry["digest"] = digest
        entry["root"] = str(html)
        if "bytes" in meta:
            entry["bytes"] = meta["bytes"]
        entry["claims"] = claims
        registry["exports"][export_key] = entry
        _save_registry(registry)


def release_claim(export_key: str, job_id: str) -> list[str]:
    """Drop ``job_id`` from the export. Returns remaining claims (possibly empty)."""
    with _REGISTRY_LOCK:
        registry = _load_registry()
        entry = dict(registry["exports"].get(export_key) or {})
        claims = [str(c) for c in entry.get("claims") or [] if str(c) != job_id]
        if claims:
            entry["claims"] = claims
            registry["exports"][export_key] = entry
        else:
            registry["exports"].pop(export_key, None)
        _save_registry(registry)
        return claims


def other_claims(export_key: str, job_id: str) -> list[str]:
    with _REGISTRY_LOCK:
        entry = (_load_registry().get("exports") or {}).get(export_key) or {}
        return [str(c) for c in entry.get("claims") or [] if str(c) != job_id]


def export_claims(export_key: str) -> list[str]:
    with _REGISTRY_LOCK:
        entry = (_load_registry().get("exports") or {}).get(export_key) or {}
        return [str(c) for c in entry.get("claims") or []]


def job_owns_export(export_key: str, job_id: str) -> bool:
    return bool(job_id) and job_id in export_claims(export_key)


def load_cached(
    source_digest: str,
    source: Sequence[SourceSlide],
) -> tuple[dict[str, Any], Path, int] | None:
    try:
        folder, html = reject_unresolved_cache_symlinks(source_digest)
    except PreviewError:
        return None
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file() or not html.is_dir() or html.is_symlink():
        return None
    try:
        manifest = read_manifest(manifest_path)
        verify_manifest(manifest, source, source_digest)
        player = html / PLAYER_JS
        if not player.is_file() or file_sha256(player) != manifest.get("playerDigest"):
            return None
        discover_export_assets(html, header_slide_list(load_header(html)[0]))
    except (PreviewError, OSError, json.JSONDecodeError):
        return None
    return manifest, html, tree_bytes(html)


def _proposal_slides(source: Sequence[SourceSlide]) -> list[dict[str, Any]]:
    live_index = 0
    out: list[dict[str, Any]] = []
    for src in source:
        if src.skipped:
            out.append(_skipped_entry(src))
            continue
        out.append(
            {
                "originalOrdinal": src.ordinal,
                "originalSlideId": src.slide_id,
                "skipped": False,
                "exportedUuid": None,
                "playerIndex": live_index,
                "playerHash": player_hash(live_index),
                "assetPaths": {},
                "unsupportedMedia": [],
                "identity": list(src.identity),
            }
        )
        live_index += 1
    return out


def _ready_result(
    *,
    path: Path,
    source_digest: str,
    source: Sequence[SourceSlide],
    manifest: dict[str, Any],
    export_root: Path,
    reused: bool,
    job_id: str,
) -> dict[str, Any]:
    digest = validate_source_digest(source_digest)
    key = cache_key(digest)
    bytes_used = tree_bytes(export_root)
    _folder, html = reject_unresolved_cache_symlinks(digest)
    claim_export(key, job_id, {"bytes": bytes_used})
    return {
        "phase": "ready",
        "path": str(path),
        "sourceDigest": digest,
        "exportKey": key,
        "exportRoot": str(html),
        "keynoteVersion": manifest.get("keynoteVersion") or keynote_app.app_version(),
        "keynoteBundleId": manifest.get("keynoteBundleId") or keynote_app.bundle_id(),
        "parserVersion": PARSER_VERSION,
        "rendererContractVersion": RENDERER_CONTRACT_VERSION,
        "manifestVersion": MANIFEST_VERSION,
        "exportContract": manifest.get("exportContract")
        or {"major": EXPORT_CONTRACT_MAJOR, "minor": EXPORT_CONTRACT_MINOR},
        "hashIndexBase": PLAYER_HASH_INDEX_BASE,
        "canvas": manifest.get("canvas"),
        "slides": manifest.get("slides") or _proposal_slides(source),
        "manifest": manifest,
        "needsExport": False,
        "reused": reused,
        "bytes": bytes_used,
    }


def propose_preview(
    path: Path,
    *,
    expected_digest: str | None = None,
    job_id: str,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    path = Path(path).expanduser()
    if not path.exists():
        raise PreviewError(f"Not found: {path}")
    digest = validate_source_digest(deck_digest(path))
    if expected_digest and not _same_digest(expected_digest, digest):
        raise PreviewStale("source deck changed since this review was opened")
    source, canvas = source_slides(path)
    log(f"{path.name}: {len(source)} slide(s), {sum(1 for s in source if s.skipped)} skipped")
    cached = load_cached(digest, source)
    if cached is not None:
        manifest, html, nbytes = cached
        log(f"Reusing cached HTML preview ({nbytes} bytes)")
        return _ready_result(
            path=path,
            source_digest=digest,
            source=source,
            manifest=manifest,
            export_root=html,
            reused=True,
            job_id=job_id,
        )
    return {
        "phase": "review",
        "path": str(path),
        "sourceDigest": digest,
        "exportKey": cache_key(digest),
        "exportRoot": None,
        **current_keynote_identity(),
        "parserVersion": PARSER_VERSION,
        "rendererContractVersion": RENDERER_CONTRACT_VERSION,
        "manifestVersion": MANIFEST_VERSION,
        "exportContract": {"major": EXPORT_CONTRACT_MAJOR, "minor": EXPORT_CONTRACT_MINOR},
        "hashIndexBase": PLAYER_HASH_INDEX_BASE,
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "slides": _proposal_slides(source),
        "manifest": None,
        "needsExport": True,
        "reused": False,
        "bytes": 0,
    }


def apply_preview(
    proposal: dict[str, Any],
    *,
    job_id: str,
    log: Callable[[str], None] = print,
    export_html_fn: Callable[..., None] | None = None,
) -> dict[str, Any]:
    path = Path(str(proposal.get("path") or "")).expanduser()
    if not path.exists():
        raise PreviewError("The deck has moved since proposing the preview.")
    expected = str(proposal.get("sourceDigest") or "")
    digest = validate_source_digest(deck_digest(path))
    if expected and not _same_digest(expected, digest):
        raise PreviewStale("source deck changed between proposal and apply")
    source, canvas = source_slides(path)
    cached = load_cached(digest, source)
    if cached is not None:
        manifest, html, nbytes = cached
        log(f"Reusing cached HTML preview ({nbytes} bytes)")
        return _ready_result(
            path=path,
            source_digest=digest,
            source=source,
            manifest=manifest,
            export_root=html,
            reused=True,
            job_id=job_id,
        )
    folder = cache_dir(digest)
    html = folder / "html"
    log("Exporting HTML player from a scratch copy…")
    writer = export_html_fn or export_html
    try:
        writer(path, html, log=log)
        manifest = manifest_from_export(
            html,
            source=source,
            source_digest=digest,
            keynote_version=keynote_app.app_version(),
            canvas=canvas,
        )
        write_manifest(folder / "manifest.json", manifest)
    except Exception:
        if html.exists():
            shutil.rmtree(html, ignore_errors=True)
        raise
    log(f"HTML preview ready ({tree_bytes(html)} bytes)")
    return _ready_result(
        path=path,
        source_digest=digest,
        source=source,
        manifest=manifest,
        export_root=html,
        reused=False,
        job_id=job_id,
    )


def release_owned_claim(export_key: str, job_id: str) -> list[str] | None:
    """Drop ``job_id`` if it owns a claim. ``None`` means this job never claimed the export."""
    with _REGISTRY_LOCK:
        registry = _load_registry()
        entry = dict(registry["exports"].get(export_key) or {})
        claims = [str(c) for c in entry.get("claims") or []]
        if job_id not in claims:
            return None
        remaining = [claim for claim in claims if claim != job_id]
        if remaining:
            entry["claims"] = remaining
            registry["exports"][export_key] = entry
        else:
            registry["exports"].pop(export_key, None)
        _save_registry(registry)
        return remaining


def cleanup_preview(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Delete only the cache folder named by a validated server export key.

    ``sourceDigest`` and ``exportRoot`` on the job result are untrusted: an
    absolute digest plus an empty root must not redirect deletion outside
    ``preview_root()``.
    """
    export_key = str(result.get("exportKey") or "")
    if not export_key:
        return {"deleted": False, "retained": False, "otherClaims": []}
    digest = parse_export_key(export_key)
    folder, html = reject_unresolved_cache_symlinks(digest)
    remaining = release_owned_claim(export_key, job_id)
    if remaining is None:
        return {
            "deleted": False,
            "retained": bool(other_claims(export_key, job_id)),
            "otherClaims": other_claims(export_key, job_id),
        }
    if remaining:
        return {"deleted": False, "retained": True, "otherClaims": remaining}
    cache = preview_root().resolve()
    if folder.is_symlink() or html.is_symlink():
        raise PreviewError("refusing to delete a preview folder that is a symlink")
    resolved = folder.resolve()
    if resolved.name != folder.name or not _within_root(resolved, cache):
        raise PreviewError("refusing to delete a preview folder outside the cache")
    if folder.exists():
        shutil.rmtree(folder)
    return {"deleted": True, "retained": False, "otherClaims": []}


def release_job_claim(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Used when a preview job is deleted; never removes another job's cache entry."""
    try:
        return cleanup_preview(job_id, result)
    except PreviewError:
        return {"deleted": False, "retained": True, "otherClaims": other_claims(str(result.get("exportKey") or ""), job_id)}


def registered_export_root(result: dict[str, Any], job_id: str) -> Path:
    export_key = str(result.get("exportKey") or "")
    if not job_owns_export(export_key, job_id):
        raise PreviewError("preview job does not own this cache")
    digest = parse_export_key(export_key)
    folder, html = reject_unresolved_cache_symlinks(digest)
    if folder.is_symlink() or html.is_symlink():
        raise PreviewError("preview export root cannot be a symlink")
    if not html.is_dir():
        raise PreviewError("preview export root is missing")
    cache = preview_root().resolve()
    resolved = html.resolve()
    if resolved.name != "html" or not _within_root(resolved, cache):
        raise PreviewError("preview export root is outside the cache")
    raw = str(result.get("exportRoot") or "")
    if raw:
        reported = Path(raw).expanduser().resolve()
        if reported != resolved:
            raise PreviewError("preview export root does not match the cache")
    return resolved


def safe_export_file(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``. Rejects traversal, absolute paths, and symlinks."""
    rel = (relative or "").strip()
    if not rel or rel.startswith("/") or "\\" in rel:
        raise PreviewError("invalid preview path")
    parts = Path(rel).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise PreviewError("invalid preview path")
    cache = preview_root().resolve()
    resolved_root = root.resolve()
    if not _within_root(resolved_root, cache):
        raise PreviewError("preview export root is outside the cache")
    current = resolved_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PreviewError("preview path escapes through a symlink")
    resolved = current.resolve()
    if not _within_root(resolved, resolved_root) or not _within_root(resolved, cache):
        raise PreviewError("preview path is outside the export")
    if not resolved.is_file():
        raise PreviewError("preview file is missing")
    return resolved
