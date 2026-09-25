"""API tests for on-demand HTML build preview. Keynote is never launched."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obed_edom.html_preview import SourceSlide
from obed_edom.web.app import app
from tests.test_html_preview import DIGEST, _digest, write_fake_export


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


def _wait(client, job_id, tries=120):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _source():
    return [
        SourceSlide(1, "10", False, ("alpha",)),
        SourceSlide(2, "11", True, ("skipped-only",)),
        SourceSlide(3, "12", False, ("gamma",)),
    ]


def _patch_preview(monkeypatch, *, digest=DIGEST):
    import obed_edom.html_preview as hp
    import obed_edom.web.app as app_mod

    monkeypatch.setattr(hp, "deck_digest", lambda _p: digest)
    monkeypatch.setattr(hp, "source_slides", lambda _p: (_source(), (1920.0, 1080.0)))
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])

    monkeypatch.setattr(hp, "export_html", _export)
    return hp


def test_html_preview_propose_apply_serve_and_skip_identity(tmp_path, monkeypatch):
    _patch_preview(monkeypatch, digest=_digest("serve-digest"))
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)
    started = client.post("/api/html-preview", data={"path": str(deck)})
    assert started.status_code == 200
    proposed = _wait(client, started.json()["id"])
    assert proposed["status"] == "done", proposed.get("error")
    assert proposed["result"]["phase"] == "review"
    assert proposed["result"]["needsExport"] is True

    applied = client.post(f"/api/html-preview/{proposed['id']}/apply")
    assert applied.status_code == 200
    ready = _wait(client, proposed["id"])
    assert ready["status"] == "done", ready.get("error")
    result = ready["result"]
    assert result["phase"] == "ready"
    by_ord = {row["originalOrdinal"]: row for row in result["slides"]}
    assert by_ord[2]["skipped"] is True
    assert by_ord[1]["playerHash"] == "#0"
    assert by_ord[3]["playerHash"] == "#1"

    page = client.get(f"/api/html-preview/{proposed['id']}/player/index.html")
    assert page.status_code == 200
    assert b"<html>" in page.content
    assert b"data-obed-preview-diagnostics" in page.content
    assert page.content.index(b"data-obed-preview-diagnostics") < page.content.index(b"assets/player/main.js")
    assert page.headers.get("cache-control") == "no-cache"


def test_html_preview_stale_expected_digest(tmp_path, monkeypatch):
    _patch_preview(monkeypatch, digest=_digest("now"))
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)
    started = client.post(
        "/api/html-preview", data={"path": str(deck), "expected_digest": "then"}
    )
    job = _wait(client, started.json()["id"])
    assert job["status"] == "error"
    assert "changed" in (job.get("error") or "")


def test_html_preview_rejects_missing_assets(tmp_path, monkeypatch):
    import obed_edom.html_preview as hp

    _patch_preview(monkeypatch, digest=_digest("missing-digest"))

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"], omit_slide="ccc")

    monkeypatch.setattr(hp, "export_html", _export)
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)
    proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
    client.post(f"/api/html-preview/{proposed['id']}/apply")
    ready = _wait(client, proposed["id"])
    assert ready["status"] == "error"
    assert "ccc" in (ready.get("error") or "")


def test_html_preview_player_rejects_traversal_and_symlink(tmp_path, monkeypatch):
    _patch_preview(monkeypatch, digest=_digest("escape-digest"))
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)
    proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
    client.post(f"/api/html-preview/{proposed['id']}/apply")
    ready = _wait(client, proposed["id"])
    assert ready["status"] == "done", ready.get("error")
    root = Path(ready["result"]["exportRoot"])
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    (root / "leak.js").symlink_to(secret)

    escaped = client.get(f"/api/html-preview/{proposed['id']}/player/../../secret.txt")
    assert escaped.status_code == 404
    leaked = client.get(f"/api/html-preview/{proposed['id']}/player/leak.js")
    assert leaked.status_code == 404


def test_html_preview_cleanup_keeps_other_jobs_assets(tmp_path, monkeypatch):
    _patch_preview(monkeypatch, digest=_digest("shared-digest"))
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)

    def _ready():
        proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
        client.post(f"/api/html-preview/{proposed['id']}/apply")
        job = _wait(client, proposed["id"])
        assert job["status"] == "done", job.get("error")
        return job

    first = _ready()
    second = _ready()
    root = Path(first["result"]["exportRoot"])
    cleaned = client.post(f"/api/html-preview/{first['id']}/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["cleanup"]["retained"] is True
    assert root.is_dir()
    still = client.get(f"/api/html-preview/{second['id']}/player/index.html")
    assert still.status_code == 200
    gone = client.get(f"/api/html-preview/{first['id']}/player/index.html")
    assert gone.status_code == 409
    client.post(f"/api/html-preview/{second['id']}/cleanup")
    assert not root.exists()


def test_html_preview_symlink_cache_is_isolated(tmp_path, monkeypatch):
    import obed_edom.html_preview as hp

    digest_a = _digest("iso-a")
    digest_b = _digest("iso-b")
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)

    def _ready(digest: str):
        _patch_preview(monkeypatch, digest=digest)
        proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
        client.post(f"/api/html-preview/{proposed['id']}/apply")
        job = _wait(client, proposed["id"])
        assert job["status"] == "done", job.get("error")
        return job

    job_b = _ready(digest_b)
    job_a = _ready(digest_a)
    folder_a = hp.unresolved_cache_folder(digest_a)
    folder_b = hp.unresolved_cache_folder(digest_b)
    shutil.rmtree(folder_a)
    folder_a.symlink_to(folder_b, target_is_directory=True)

    hijacked = client.get(f"/api/html-preview/{job_a['id']}/player/index.html")
    assert hijacked.status_code == 404
    still = client.get(f"/api/html-preview/{job_b['id']}/player/index.html")
    assert still.status_code == 200
    assert b"<html>" in still.content

    cleaned = client.post(f"/api/html-preview/{job_a['id']}/cleanup")
    assert cleaned.status_code == 400
    assert (folder_b / "html" / "index.html").is_file()
    assert client.get(f"/api/html-preview/{job_b['id']}/player/index.html").status_code == 200


def test_html_preview_patch_cannot_serve_another_jobs_player(tmp_path, monkeypatch):
    import obed_edom.html_preview as hp
    from obed_edom.web.app import RUNNER

    digest_a = _digest("patch-a")
    digest_b = _digest("patch-b")
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)

    def _ready(digest: str, marker: str):
        _patch_preview(monkeypatch, digest=digest)

        def _export(_deck, dest, **_k):
            write_fake_export(Path(dest), ["aaa", "ccc"])
            (Path(dest) / "index.html").write_text(
                f"<html><!-- {marker} --><script src='assets/player/main.js'></script></html>"
            )

        monkeypatch.setattr(hp, "export_html", _export)
        proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
        client.post(f"/api/html-preview/{proposed['id']}/apply")
        job = _wait(client, proposed["id"])
        assert job["status"] == "done", job.get("error")
        return job

    job_b = _ready(digest_b, "DECK-B")
    job_a = _ready(digest_a, "DECK-A")
    page_b = client.get(f"/api/html-preview/{job_b['id']}/player/index.html")
    page_a = client.get(f"/api/html-preview/{job_a['id']}/player/index.html")
    assert b"DECK-B" in page_b.content
    assert b"DECK-A" in page_a.content

    patched = client.patch(f"/api/jobs/{job_a['id']}", json={"result": job_b["result"]})
    assert patched.status_code == 409
    assert b"DECK-A" in client.get(f"/api/html-preview/{job_a['id']}/player/index.html").content
    assert b"DECK-B" not in client.get(f"/api/html-preview/{job_a['id']}/player/index.html").content

    RUNNER.update_result(job_a["id"], dict(job_b["result"]))
    stolen = client.get(f"/api/html-preview/{job_a['id']}/player/index.html")
    assert stolen.status_code == 404
    assert b"DECK-B" not in stolen.content
    honest = client.get(f"/api/html-preview/{job_b['id']}/player/index.html")
    assert honest.status_code == 200
    assert b"DECK-B" in honest.content
    cleaned = client.post(f"/api/html-preview/{job_a['id']}/cleanup")
    assert cleaned.status_code == 200
    assert hp.unresolved_cache_folder(digest_b).joinpath("html", "index.html").is_file()
    assert client.get(f"/api/html-preview/{job_b['id']}/player/index.html").status_code == 200


def _ready_job(tmp_path, monkeypatch, label: str, player: bytes | None = None):
    """A ready preview job whose on-disk main.js is `player` (the stock fake player when None)."""
    hp = _patch_preview(monkeypatch, digest=_digest(label))

    def _export(_deck, dest, **_k):
        write_fake_export(Path(dest), ["aaa", "ccc"])
        if player is not None:
            (Path(dest) / hp.PLAYER_JS).write_bytes(player)

    monkeypatch.setattr(hp, "export_html", _export)
    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    client = TestClient(app)
    proposed = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
    client.post(f"/api/html-preview/{proposed['id']}/apply")
    ready = _wait(client, proposed["id"])
    assert ready["status"] == "done", ready.get("error")
    return client, deck, ready


def _pinned_player(monkeypatch) -> bytes:
    from obed_edom import live_runtime
    from tests.test_live_runtime import _synthetic_player

    player = _synthetic_player()
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
    return player


def test_html_preview_serves_the_mm_opacity_rendering_patch_without_touching_the_cache(tmp_path, monkeypatch):
    from obed_edom import live_runtime
    from obed_edom.html_preview import PLAYER_JS, file_sha256

    monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    stock = _pinned_player(monkeypatch)
    client, deck, ready = _ready_job(tmp_path, monkeypatch, "mm-opacity-on", stock)
    job_id = ready["id"]
    served = client.get(f"/api/html-preview/{job_id}/player/assets/player/main.js")
    assert served.status_code == 200
    assert served.content == live_runtime.patch_rendering(stock)
    assert served.headers["x-obed-mm-opacity"] == "on"
    assert served.headers["cache-control"] == "no-cache"
    assert served.headers["content-type"].startswith("text/javascript")
    page = client.get(f"/api/html-preview/{job_id}/player/index.html")
    assert b"var note = null;" in page.content

    # The cache stays stock: live start, live_host and the paint oracle all read these disk bytes.
    root = Path(ready["result"]["exportRoot"])
    assert (root / PLAYER_JS).read_bytes() == stock
    assert file_sha256(root / PLAYER_JS) == ready["result"]["manifest"]["playerDigest"]
    again = _wait(client, client.post("/api/html-preview", data={"path": str(deck)}).json()["id"])
    assert again["status"] == "done", again.get("error")
    assert again["result"]["reused"] is True


def test_html_preview_off_switch_serves_the_stock_player(tmp_path, monkeypatch):
    from obed_edom import live_runtime

    stock = _pinned_player(monkeypatch)
    client, _deck, ready = _ready_job(tmp_path, monkeypatch, "mm-opacity-off", stock)
    monkeypatch.setenv(live_runtime.MM_OPACITY_ENV, "off")
    served = client.get(f"/api/html-preview/{ready['id']}/player/assets/player/main.js")
    assert served.content == stock
    assert served.headers["x-obed-mm-opacity"] == "off"
    assert b"var note = null;" in client.get(f"/api/html-preview/{ready['id']}/player/index.html").content
    # Read per request: switching back needs no re-export.
    monkeypatch.setenv(live_runtime.MM_OPACITY_ENV, "auto")
    served = client.get(f"/api/html-preview/{ready['id']}/player/assets/player/main.js")
    assert served.content == live_runtime.patch_rendering(stock)


@pytest.mark.parametrize("env,mode", [(None, "unsupported"), ("bogus", "invalid")])
def test_html_preview_unsupported_or_invalid_serves_stock_with_one_player_note(tmp_path, monkeypatch, env, mode):
    from obed_edom import live_runtime
    from obed_edom.html_preview import PREVIEW_MM_OPACITY_NOTES

    # Unsupported: the fake export's stock `/* keynote player */` sha. Invalid: a pinned player, bad env value.
    player = None if env is None else _pinned_player(monkeypatch)
    client, _deck, ready = _ready_job(tmp_path, monkeypatch, f"mm-opacity-{mode}", player)
    if env is None:
        monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    else:
        monkeypatch.setenv(live_runtime.MM_OPACITY_ENV, env)
    root = Path(ready["result"]["exportRoot"])
    served = client.get(f"/api/html-preview/{ready['id']}/player/assets/player/main.js")
    assert served.status_code == 200
    assert served.content == (root / "assets" / "player" / "main.js").read_bytes()
    assert served.headers["x-obed-mm-opacity"] == mode
    page = client.get(f"/api/html-preview/{ready['id']}/player/index.html")
    assert page.content.count(PREVIEW_MM_OPACITY_NOTES[mode].encode()) == 1


def test_html_preview_patches_a_case_variant_player_path(tmp_path, monkeypatch):
    from obed_edom import live_runtime

    monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    stock = _pinned_player(monkeypatch)
    client, _deck, ready = _ready_job(tmp_path, monkeypatch, "mm-opacity-case", stock)
    root = Path(ready["result"]["exportRoot"])
    if not (root / "assets" / "Player" / "MAIN.JS").is_file():
        pytest.skip("case-sensitive filesystem")
    # A case-insensitive volume serves the same file; it must not bypass the patch or the no-cache header.
    served = client.get(f"/api/html-preview/{ready['id']}/player/assets/Player/MAIN.JS")
    assert served.status_code == 200
    assert served.content == live_runtime.patch_rendering(stock)
    assert served.headers["x-obed-mm-opacity"] == "on"
    assert served.headers["cache-control"] == "no-cache"


def test_html_preview_index_survives_an_unreadable_player(tmp_path, monkeypatch):
    from obed_edom import live_runtime

    monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    client, _deck, ready = _ready_job(tmp_path, monkeypatch, "mm-opacity-unreadable")
    player = Path(ready["result"]["exportRoot"]) / "assets" / "player" / "main.js"
    player.chmod(0)
    try:
        # The preview never refuses over the opacity patch: index.html still loads, with no note.
        page = client.get(f"/api/html-preview/{ready['id']}/player/index.html")
    finally:
        player.chmod(0o644)
    assert page.status_code == 200
    assert b"var note = null;" in page.content
