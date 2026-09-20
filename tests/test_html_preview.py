"""Offline tests for HTML build-preview mapping, cache, and path safety.

No test may launch Keynote. Live export is either unused or injected.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from obed_edom.html_preview import (
    EXPORT_CONTRACT_MAJOR,
    EXPORT_CONTRACT_MINOR,
    MANIFEST_VERSION,
    PARSER_VERSION,
    PLAYER_HASH_INDEX_BASE,
    PLAYER_JS,
    RENDERER_CONTRACT_VERSION,
    PreviewError,
    PreviewMappingError,
    PreviewStale,
    PreviewStructureError,
    SourceSlide,
    apply_preview,
    build_html_export_script,
    build_manifest,
    cache_key,
    export_payload_identity,
    header_export_contract,
    cleanup_preview,
    inject_player_diagnostics,
    current_keynote_identity,
    discover_export_assets,
    file_sha256,
    load_header,
    parse_jsonish,
    player_hash,
    propose_preview,
    registered_export_root,
    safe_export_file,
    unresolved_cache_folder,
    verify_manifest,
)

DIGEST = hashlib.sha256(b"preview-deck").hexdigest()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source() -> list[SourceSlide]:
    return [
        SourceSlide(1, "10", False, ("alpha",)),
        SourceSlide(2, "11", True, ("skipped-only",)),
        SourceSlide(3, "12", False, ("gamma",)),
    ]


def _keynote() -> dict[str, str]:
    return current_keynote_identity()


def write_fake_export(
    root: Path,
    uuids: list[str],
    *,
    jsonp: bool = False,
    remote: str | None = None,
    omit_player: bool = False,
    omit_slide: str | None = None,
    identities: list[tuple[str, ...]] | None = None,
    major: int = EXPORT_CONTRACT_MAJOR,
    minor: int = EXPORT_CONTRACT_MINOR,
) -> None:
    (root / "assets" / "player").mkdir(parents=True)
    (root / "index.html").write_text("<html><script src='assets/player/main.js'></script></html>")
    if not omit_player:
        (root / PLAYER_JS).write_text("/* keynote player */\n")
    header = {
        "slideList": uuids,
        "slideCount": len(uuids),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "creator": "Apple Keynote 15.3.1",
        "major": major,
        "minor": minor,
    }
    encoded = json.dumps(header)
    if jsonp:
        (root / "assets" / "header.jsonp").write_text(f"var local_header = {encoded};")
    else:
        (root / "assets" / "header.json").write_text(encoded)
    default_identity = {"aaa": ("alpha",), "ccc": ("gamma",)}
    for index, uuid in enumerate(uuids):
        if uuid == omit_slide:
            continue
        folder = root / "assets" / uuid
        folder.mkdir(parents=True)
        tokens = identities[index] if identities is not None else default_identity.get(uuid, (uuid,))
        payload = {"uuid": uuid, "accessibility": [{"text": token} for token in tokens]}
        if remote:
            payload["src"] = remote
        (folder / f"{uuid}.json").write_text(json.dumps(payload))
        (folder / "thumbnail.jpeg").write_bytes(b"jpeg")


def _manifest_kwargs(export: Path, header_path: str, source_digest: str = DIGEST) -> dict:
    identity = _keynote()
    return {
        "source": _source(),
        "source_digest": source_digest,
        "keynote_version": identity["keynoteVersion"],
        "keynote_bundle_id": identity["keynoteBundleId"],
        "player_digest": file_sha256(export / PLAYER_JS) if (export / PLAYER_JS).is_file() else "x",
        "canvas": {"width": 1920, "height": 1080},
        "header_path": header_path,
    }


def test_hash_channel_fixture_matches_parser_constant():
    fixture = json.loads(
        Path("tests/fixtures/html_preview/hash_channel.json").read_text(encoding="utf-8")
    )
    assert fixture["indexBase"] == PLAYER_HASH_INDEX_BASE
    assert fixture["firstExportedSlideHash"] == player_hash(0)
    assert player_hash(0) == "#0"
    assert player_hash(1) == "#1"


def test_renderer_contract_fixture_matches_parser_constants():
    fixture = json.loads(
        Path("tests/fixtures/html_preview/renderer_contract.json").read_text(encoding="utf-8")
    )
    assert fixture["headerMajor"] == EXPORT_CONTRACT_MAJOR
    assert fixture["headerMinor"] == EXPORT_CONTRACT_MINOR
    assert fixture["keynoteBundleId"] == "com.apple.Keynote"
    assert RENDERER_CONTRACT_VERSION == 1


def test_header_accepts_live_major_version_fields():
    assert header_export_contract({"majorVersion": 1, "minorVersion": 2}) == {"major": 1, "minor": 2}
    assert header_export_contract({"major": 1, "minor": 2}) == {"major": 1, "minor": 2}


def test_export_identity_reads_event_accessibility_and_drops_media():
    payload = {
        "assets": {},
        "events": [
            {
                "accessibility": [
                    {"text": "pasted-image.tiff"},
                    {"text": "Matthew 18"},
                    {
                        "text": "19 Again, truly I tell you that if two of you on earth agree "
                        "about anything they\\u2028ask for, it will be done for them\xa0by My Father in heaven. "
                    },
                    {"text": "Untitled.mov"},
                ]
            }
        ],
    }
    assert export_payload_identity(payload) == (
        "19 Again, truly I tell you that if two of you on earth agree about anything they ask for, it will be done for them by My Father in heaven.",
        "Matthew 18",
    )


def test_slide_identity_fixture_names_accessibility_field():
    fixture = json.loads(
        Path("tests/fixtures/html_preview/slide_identity.json").read_text(encoding="utf-8")
    )
    assert fixture["exportIdentityField"] == "events[].accessibility[].text"
    assert fixture["example"]["exportInOrder"] != fixture["example"]["exportReordered"]


def test_parse_jsonish_accepts_json_and_local_header_jsonp():
    assert parse_jsonish('{"slideCount": 2}') == {"slideCount": 2}
    assert parse_jsonish('var local_header = {"slideCount": 2};') == {"slideCount": 2}
    assert parse_jsonish('local_header( {"slideCount": 2} )') == {"slideCount": 2}
    assert parse_jsonish('local_slide={"ok": true}') == {"ok": True}


def test_mapping_keeps_original_numbers_across_skipped_slides(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa", "ccc"])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa", "ccc"])
    manifest = build_manifest(header=header, exported=exported, **_manifest_kwargs(export, header_path))
    verify_manifest(manifest, _source(), DIGEST)
    by_ord = {row["originalOrdinal"]: row for row in manifest["slides"]}
    assert by_ord[1]["playerIndex"] == 0
    assert by_ord[1]["playerHash"] == "#0"
    assert by_ord[1]["exportedUuid"] == "aaa"
    assert by_ord[1]["identity"] == ["alpha"]
    assert by_ord[2]["skipped"] is True
    assert by_ord[2]["playerIndex"] is None
    assert by_ord[3]["playerIndex"] == 1
    assert by_ord[3]["playerHash"] == "#1"
    assert by_ord[3]["exportedUuid"] == "ccc"


def test_jsonp_header_and_remote_media_are_recorded(tmp_path):
    export = tmp_path / "html"
    write_fake_export(
        export, ["aaa", "ccc"], jsonp=True, remote="https://www.youtube.com/embed/abc"
    )
    header, _header_path = load_header(export)
    exported = discover_export_assets(export, header["slideList"])
    assert exported[0]["remoteMedia"] == ["youtube"]
    assert exported[0]["identity"] == ("alpha",)


def test_refuse_when_export_count_does_not_match_live_source(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa"])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa"])
    with pytest.raises(PreviewMappingError, match="non-skipped"):
        build_manifest(header=header, exported=exported, **_manifest_kwargs(export, header_path))


def test_refuse_same_length_reordered_export(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["ccc", "aaa"], identities=[("gamma",), ("alpha",)])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["ccc", "aaa"])
    with pytest.raises(PreviewMappingError, match="do not match the source|not in source order"):
        build_manifest(header=header, exported=exported, **_manifest_kwargs(export, header_path))


def test_refuse_ambiguous_identical_identities(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa", "ccc"], identities=[("same",), ("same",)])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa", "ccc"])
    source = [
        SourceSlide(1, "10", False, ("same",)),
        SourceSlide(2, "11", False, ("same",)),
    ]
    kwargs = _manifest_kwargs(export, header_path)
    kwargs["source"] = source
    with pytest.raises(PreviewMappingError, match="ambiguous"):
        build_manifest(header=header, exported=exported, **kwargs)


def test_empty_identities_may_align_at_matching_positions(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa", "bbb", "ccc"], identities=[("alpha",), (), ()])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa", "bbb", "ccc"])
    source = [
        SourceSlide(1, "10", False, ("alpha",)),
        SourceSlide(2, "11", False, ()),
        SourceSlide(3, "12", False, ()),
    ]
    kwargs = _manifest_kwargs(export, header_path)
    kwargs["source"] = source
    manifest = build_manifest(header=header, exported=exported, **kwargs)
    by_ord = {row["originalOrdinal"]: row for row in manifest["slides"]}
    assert by_ord[1]["playerHash"] == "#0"
    assert by_ord[2]["playerHash"] == "#1"
    assert by_ord[3]["playerHash"] == "#2"


def test_source_notes_may_outnumber_export_tokens(tmp_path):
    export = tmp_path / "html"
    write_fake_export(
        export,
        ["aaa", "ccc"],
        identities=[("Guo Rong", "Ps Aizhen"), ()],
    )
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa", "ccc"])
    source = [
        SourceSlide(1, "10", False, ("Guo Rong", "Ps Aizhen", "Replace Guo Rong & Ps Aizhen")),
        SourceSlide(2, "12", False, ("Make the second video faster.",)),
    ]
    kwargs = _manifest_kwargs(export, header_path)
    kwargs["source"] = source
    manifest = build_manifest(header=header, exported=exported, **kwargs)
    by_ord = {row["originalOrdinal"]: row for row in manifest["slides"]}
    assert by_ord[1]["playerHash"] == "#0"
    assert by_ord[2]["playerHash"] == "#1"


def test_export_identity_drops_pdf_media_names():
    payload = {
        "events": [
            {"accessibility": [{"text": "CHC Kuching"}, {"text": "pasted-image.pdf"}]}
        ]
    }
    assert export_payload_identity(payload) == ("CHC Kuching",)


def test_refuse_empty_identity_when_export_has_text(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa", "ccc"], identities=[(), ("gamma",)])
    header, header_path = load_header(export)
    exported = discover_export_assets(export, ["aaa", "ccc"])
    source = [
        SourceSlide(1, "10", False, ()),
        SourceSlide(2, "12", False, ()),
    ]
    kwargs = _manifest_kwargs(export, header_path)
    kwargs["source"] = source
    with pytest.raises(PreviewMappingError, match="do not match the source"):
        build_manifest(header=header, exported=exported, **kwargs)


def test_refuse_missing_slide_assets(tmp_path):
    export = tmp_path / "html"
    write_fake_export(export, ["aaa", "ccc"], omit_slide="ccc")
    with pytest.raises(PreviewStructureError, match="ccc"):
        discover_export_assets(export, ["aaa", "ccc"])


def test_refuse_incompatible_manifest_version():
    source = _source()
    manifest = {
        "version": MANIFEST_VERSION + 1,
        "parserVersion": PARSER_VERSION,
        "rendererContractVersion": RENDERER_CONTRACT_VERSION,
        "hashIndexBase": PLAYER_HASH_INDEX_BASE,
        "sourceDigest": DIGEST,
        "slides": [_skipped_like(s) for s in source],
    }
    with pytest.raises(PreviewStructureError, match="unsupported preview manifest"):
        verify_manifest(manifest, source, DIGEST)


def _skipped_like(src: SourceSlide) -> dict:
    return {
        "originalOrdinal": src.ordinal,
        "originalSlideId": src.slide_id,
        "skipped": src.skipped,
        "exportedUuid": None if src.skipped else "x",
        "playerIndex": None if src.skipped else 0,
        "playerHash": None if src.skipped else "#0",
        "identity": list(src.identity),
    }


def test_export_script_uses_bundle_id_and_html_format():
    script = build_html_export_script(Path("/tmp/Deck.key"), Path("/Users/me/out/html"))
    assert "com.apple.Keynote" in script
    assert "as HTML" in script
    assert 'tell application "Keynote"' not in script
    assert "with properties" not in script


def test_propose_does_not_export(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    deck = tmp_path / "Deck.key"
    deck.write_text("deck")
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))

    def _boom(*_a, **_k):
        raise AssertionError("export must not run during propose")

    monkeypatch.setattr(hp, "export_html", _boom)
    result = propose_preview(deck, job_id="job-a")
    assert result["phase"] == "review"
    assert result["needsExport"] is True
    assert result["slides"][1]["skipped"] is True
    assert result["exportKey"] == cache_key(DIGEST)
    assert result["rendererContractVersion"] == RENDERER_CONTRACT_VERSION


def test_stale_expected_digest_is_refused(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    deck = tmp_path / "Deck.key"
    deck.write_text("deck")
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    with pytest.raises(PreviewStale, match="changed since this review"):
        propose_preview(deck, expected_digest="then", job_id="job-a")


def test_apply_refuses_when_source_digest_changes(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    deck = tmp_path / "Deck.key"
    deck.write_text("one")
    digests = iter([_digest("aaa"), _digest("bbb")])
    monkeypatch.setattr(hp, "deck_digest", lambda _p: next(digests))
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    proposal = propose_preview(deck, job_id="job-a")
    with pytest.raises(PreviewStale, match="between proposal and apply"):
        apply_preview(proposal, job_id="job-a", export_html_fn=lambda *_a, **_k: None)


def test_cached_preview_invalidates_after_keynote_upgrade(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    monkeypatch.setattr(hp.keynote_app, "app_version", lambda _identifier=None: "15.3.1")
    monkeypatch.setattr(hp.keynote_app, "bundle_id", lambda: "com.apple.Keynote")
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    ready = apply_preview(
        propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export
    )
    assert ready["reused"] is False
    monkeypatch.setattr(hp.keynote_app, "app_version", lambda _identifier=None: "15.4")
    again = propose_preview(deck, job_id="job-b")
    assert again["phase"] == "review"
    assert again["needsExport"] is True


def test_cached_preview_invalidates_after_renderer_contract_change(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    apply_preview(propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export)
    manifest_path = hp.cache_dir(DIGEST) / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["rendererContractVersion"] = RENDERER_CONTRACT_VERSION + 1
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    again = propose_preview(deck, job_id="job-b")
    assert again["needsExport"] is True
    assert again["phase"] == "review"


def test_cleanup_does_not_delete_another_jobs_cache(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    first = apply_preview(
        propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export
    )
    second = apply_preview(
        propose_preview(deck, job_id="job-b"), job_id="job-b", export_html_fn=_export
    )
    html = Path(first["exportRoot"])
    assert html.is_dir()
    cleaned = cleanup_preview("job-a", first)
    assert cleaned["retained"] is True
    assert html.is_dir()
    assert (html / "index.html").is_file()
    cleaned_b = cleanup_preview("job-b", second)
    assert cleaned_b["deleted"] is True
    assert not html.exists()


def test_cleanup_ignores_absolute_digest_and_empty_export_root(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "deck_digest", lambda _p: DIGEST)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    ready = apply_preview(
        propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export
    )
    victim = tmp_path / "escaped-p2-r1"
    victim.mkdir()
    (victim / "keep.txt").write_text("safe")

    cleanup_preview(
        "job-a",
        {
            "exportKey": "",
            "sourceDigest": str(tmp_path / "escaped"),
            "exportRoot": None,
        },
    )
    assert victim.is_dir()
    assert (victim / "keep.txt").read_text() == "safe"

    forged_key = {
        **ready,
        "sourceDigest": str(tmp_path / "escaped"),
        "exportRoot": None,
        "exportKey": f"{tmp_path / 'escaped'}-p{PARSER_VERSION}-r{RENDERER_CONTRACT_VERSION}",
    }
    with pytest.raises(PreviewError, match="invalid preview cache key|invalid source digest"):
        cleanup_preview("job-a", forged_key)
    assert victim.is_dir()
    assert (tmp_path / ".html-preview" / cache_key(DIGEST) / "html" / "index.html").is_file()

    cleanup_preview(
        "job-a",
        {
            **ready,
            "sourceDigest": str(tmp_path / "escaped"),
            "exportRoot": None,
        },
    )
    assert victim.is_dir()
    assert not (tmp_path / ".html-preview" / cache_key(DIGEST)).exists()


def test_inject_player_diagnostics_runs_before_exported_scripts():
    html = "<html><head></head><body><script src='assets/player/main.js'></script></body></html>"
    injected = inject_player_diagnostics(html)
    assert injected.index("data-obed-preview-diagnostics") < injected.index("assets/player/main.js")
    assert inject_player_diagnostics(injected) == injected


def test_symlink_cache_cannot_delete_or_serve_another_cache(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    digest_a = _digest("cache-a")
    digest_b = _digest("cache-b")
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    monkeypatch.setattr(hp, "deck_digest", lambda _p: digest_b)
    ready_b = apply_preview(
        propose_preview(deck, job_id="job-b"), job_id="job-b", export_html_fn=_export
    )
    monkeypatch.setattr(hp, "deck_digest", lambda _p: digest_a)
    ready_a = apply_preview(
        propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export
    )
    folder_a = unresolved_cache_folder(digest_a)
    folder_b = unresolved_cache_folder(digest_b)
    shutil.rmtree(folder_a)
    folder_a.symlink_to(folder_b, target_is_directory=True)

    with pytest.raises(PreviewError, match="symlink"):
        cleanup_preview("job-a", ready_a)
    assert (folder_b / "html" / "index.html").is_file()
    with pytest.raises(PreviewError, match="symlink"):
        registered_export_root(ready_a, "job-a")
    served = registered_export_root(ready_b, "job-b")
    assert safe_export_file(served, "index.html").name == "index.html"

    folder_a.unlink()
    folder_a.mkdir()
    (folder_a / "manifest.json").write_text("{}")
    (folder_a / "html").symlink_to(folder_b / "html", target_is_directory=True)
    with pytest.raises(PreviewError, match="symlink"):
        cleanup_preview("job-a", ready_a)
    assert (folder_b / "html" / "index.html").is_file()
    with pytest.raises(PreviewError, match="symlink"):
        registered_export_root(ready_a, "job-a")


def test_registered_export_root_requires_owning_job(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    digest_a = _digest("owner-a")
    digest_b = _digest("owner-b")
    deck = tmp_path / "Deck.key"
    deck.write_text("deck")

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    monkeypatch.setattr(hp, "deck_digest", lambda _p: digest_b)
    ready_b = apply_preview(
        propose_preview(deck, job_id="job-b"), job_id="job-b", export_html_fn=_export
    )
    monkeypatch.setattr(hp, "deck_digest", lambda _p: digest_a)
    apply_preview(propose_preview(deck, job_id="job-a"), job_id="job-a", export_html_fn=_export)

    with pytest.raises(PreviewError, match="does not own this cache"):
        registered_export_root(ready_b, "job-a")
    assert registered_export_root(ready_b, "job-b").name == "html"


def test_safe_export_file_rejects_traversal_and_symlinks(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp

    monkeypatch.setattr(hp, "output_root", lambda: tmp_path)
    root = hp.preview_root() / cache_key(DIGEST) / "html"
    write_fake_export(root, ["aaa", "ccc"])
    secret = tmp_path / "secret.txt"
    secret.write_text("no")
    (root / "escape.js").symlink_to(secret)
    assert safe_export_file(root, "index.html").name == "index.html"
    with pytest.raises(Exception, match="invalid preview path|outside"):
        safe_export_file(root, "../secret.txt")
    with pytest.raises(Exception, match="symlink"):
        safe_export_file(root, "escape.js")
