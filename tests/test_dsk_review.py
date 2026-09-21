from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from obed_edom.dsk_review import (
    ReviewValidationError,
    apply_editable_review,
    build_review,
    compile_review,
    validate_payload,
)


FIXTURE = Path(__file__).parent / "fixtures" / "dsk_review" / "v2_review.json"


def _review() -> dict:
    return json.loads(FIXTURE.read_text())


def _envelope(review: dict) -> dict:
    return {
        "schemaVersion": 2,
        "sourceFingerprint": review["source"]["fingerprint"],
        "defaults": copy.deepcopy(review["defaults"]),
        "decisions": [{"id": c["id"], **copy.deepcopy(c["decision"])} for c in review["compositions"]],
    }


def test_v2_fixture_compiles_folded_still_and_stacked_layers() -> None:
    review = validate_payload(_review())
    compiled = {item.id: item for item in compile_review(review)}

    folded = compiled["sequence:108-110"]
    assert folded.source_slides == (108, 109, 110)
    assert [media.playback["kind"] for media in folded.media] == ["movie", "movie", "image"]
    assert [media.timing for media in folded.media] == ["after_transition", "with_build_1", "with_build_1"]
    assert [media.source_slide for media in folded.media] == [110, 110, 110]

    stacked = compiled["slide:50"]
    assert [media.timing for media in stacked.media] == ["source", "source"]
    assert stacked.media[0].target_rect == stacked.media[1].target_rect


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda p: p["compositions"][0].__setitem__("id", "sequence:108-110"), "duplicate composition"),
        (lambda p: p["compositions"][0]["decision"].__setitem__("alignment", "auto"), "alignment"),
        (lambda p: p["compositions"][0]["decision"]["masks"].__setitem__("not-an-occurrence", {"zoom": 1, "panX": 0, "panY": 0}), "unknown occurrence"),
        (lambda p: p["compositions"][0]["decision"]["viewport"].__setitem__("width", float("inf")) if p["compositions"][0]["decision"]["viewport"] else p["compositions"][0]["decision"].__setitem__("viewport", {"width": float("inf"), "height": 2, "aspectLocked": True}), "finite"),
    ],
)
def test_v2_rejects_invalid_ids_enums_and_nonfinite_geometry(mutate, needle: str) -> None:
    payload = _review()
    mutate(payload)
    with pytest.raises(ReviewValidationError, match=needle):
        validate_payload(payload)


def test_editable_envelope_requires_every_composition_and_preserves_metadata() -> None:
    review = validate_payload(_review())
    envelope = _envelope(review)
    envelope["decisions"].pop()
    with pytest.raises(ReviewValidationError, match="every composition"):
        apply_editable_review(review, envelope)

    envelope = _envelope(review)
    envelope["decisions"][0]["alignment"] = "right"
    merged = apply_editable_review(review, envelope)
    assert merged["compositions"][0]["decision"]["alignment"] == "right"
    assert merged["compositions"][0]["media"] == review["compositions"][0]["media"]


def test_compiler_rejects_viewport_beyond_safe_area() -> None:
    payload = _review()
    payload["compositions"][0]["decision"]["viewport"] = {
        "width": 1900,
        "height": 263,
        "aspectLocked": True,
    }
    with pytest.raises(ReviewValidationError, match="safe area"):
        compile_review(payload)


def test_magic_move_planner_fails_closed_when_terminal_mapping_is_ambiguous() -> None:
    payload = {
        "slides": [
            {"number": 1, "items": [{"kind": "movie", "kindIndex": 0, "fileName": "a.mov", "x": 0, "y": 0, "w": 10, "h": 10}]},
            {"number": 2, "items": [{"kind": "movie", "kindIndex": 0, "fileName": "b.mov", "x": 0, "y": 0, "w": 10, "h": 10}]},
        ]
    }
    classes = {number: SimpleNamespace(category="movie", is_text=False) for number in (1, 2)}
    review = build_review(
        path="/fixture.key", fingerprint="digest", payload=payload, classes=classes, thumbs={}, selected=[1, 2],
        transitions={1: "apple:magic-move"}, content_only=True,
    )
    assert [composition["id"] for composition in review["compositions"]] == ["slide:1", "slide:2"]
    assert "not proven" in review["compositions"][0]["warnings"][0]


def test_magic_move_uses_terminal_kept_occurrences_and_ignores_side_media() -> None:
    payload = {
        "slides": [
            {
                "number": 108,
                "items": [
                    {"kind": "image", "kindIndex": 0, "fileName": "map.png", "x": 0, "y": 0, "w": 100, "h": 100},
                    {"kind": "movie", "kindIndex": 0, "fileName": "a.mov", "x": 0, "y": 0, "w": 100, "h": 100},
                ],
            },
            {
                "number": 109,
                "items": [
                    {"kind": "image", "kindIndex": 0, "fileName": "map.png", "x": 0, "y": 0, "w": 100, "h": 100},
                    {"kind": "movie", "kindIndex": 0, "fileName": "a.mov", "x": 0, "y": 0, "w": 100, "h": 100},
                    {"kind": "image", "kindIndex": 1, "fileName": "terminal.png", "x": 100, "y": 0, "w": 100, "h": 100},
                ],
            },
        ]
    }
    classes = {
        108: SimpleNamespace(category="movie", is_text=False, kept=(("movie", 0),)),
        109: SimpleNamespace(category="mixed", is_text=False, kept=(("movie", 0), ("image", 1))),
    }
    review = build_review(
        path="/fixture.key", fingerprint="digest", payload=payload, classes=classes,
        thumbs={}, selected=[108, 109], transitions={108: "apple:magic-move"},
    )
    composition = review["compositions"][0]
    assert composition["id"] == "sequence:108-109"
    assert [(media["sourceSlide"], media["assetId"]) for media in composition["media"]] == [
        (109, "a.mov"),
        (109, "terminal.png"),
    ]


def test_review_preserves_duplicate_fully_overlapping_movie_occurrences() -> None:
    movie = {"kind": "movie", "fileName": "same.mov", "x": 10, "y": 20, "w": 300, "h": 100}
    payload = {"slides": [{"number": 50, "items": [{**movie, "kindIndex": 0}, {**movie, "kindIndex": 1}]}]}
    classes = {
        50: SimpleNamespace(category="movie", is_text=False, kept=(("movie", 0), ("movie", 1))),
    }
    review = build_review(
        path="/fixture.key", fingerprint="digest", payload=payload, classes=classes,
        thumbs={}, selected=[50], stacked={50: True},
    )
    composition = review["compositions"][0]
    assert composition["mediaLayout"] == "stacked"
    assert len(composition["media"]) == 2
    assert composition["media"][0]["occurrenceId"] != composition["media"][1]["occurrenceId"]
    assert composition["media"][0]["slot"] == composition["media"][1]["slot"]


def test_source_mode_filters_side_only_media_occurrences() -> None:
    payload = {"slides": [{"number": 7, "items": [
        {"kind": "movie", "kindIndex": 0, "fileName": "centre.mov", "x": 2000, "y": 0, "w": 100, "h": 100},
        {"kind": "movie", "kindIndex": 1, "fileName": "side.mov", "x": 20, "y": 0, "w": 100, "h": 100},
    ]}]}
    classes = {7: SimpleNamespace(category="movie", is_text=False, kept=(("movie", 0),))}
    side_classes = {7: SimpleNamespace(category="movie", is_text=False, kept=(("movie", 0), ("movie", 1)))}
    review = build_review(
        path="/fixture.key", fingerprint="digest", payload=payload, classes=classes,
        side_classes=side_classes, thumbs={}, selected=[7], stacked_fw={7: True},
    )
    assert [media["sourceModes"] for media in review["compositions"][0]["media"]] == [
        ["lw", "fw"],
        ["fw"],
    ]
    assert len(compile_review(review)[0].media) == 1
    review["compositions"][0]["decision"]["source"] = "fw"
    compiled = compile_review(review)[0]
    assert len(compiled.media) == 2
    assert compiled.media_layout == "stacked"


def test_v2_api_serializes_revision_and_binds_source(tmp_path, monkeypatch) -> None:
    import obed_edom.web.app as app_mod
    from obed_edom.dsk_plan import SlideClass

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "index": 0, "items": []}],
    }
    state = {"digest": "bound"}
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _path: payload)
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: [
        SlideClass(1, "static", 0, 0, (("shape", 0),), (), (), None, False)
    ])
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: {})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _path: state["digest"])
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _digest: tmp_path)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app_mod.app)
    started = client.post("/api/dsk", data={"path": str(deck)})
    assert started.status_code == 200
    job_id = started.json()["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "queued" and job["status"] != "running":
            break
        time.sleep(0.01)
    assert job["status"] == "done", job.get("error")
    review = job["result"]["review"]
    envelope = _envelope(review)

    saved = client.post(f"/api/dsk/{job_id}/decisions", json={"review": envelope, "baseRevision": 0})
    assert saved.status_code == 200
    assert saved.json()["result"]["review"]["revision"] == 1

    stale = client.post(f"/api/dsk/{job_id}/decisions", json={"review": envelope, "baseRevision": 0})
    assert stale.status_code == 409

    monkeypatch.setattr(app_mod, "keynote_running", lambda: True)
    current_review = saved.json()["result"]["review"]
    blocked = client.post(
        f"/api/dsk/{job_id}/apply",
        json={"review": _envelope(current_review), "baseRevision": 1},
    )
    assert blocked.status_code == 409
    assert client.get(f"/api/jobs/{job_id}").json()["result"]["review"]["revision"] == 1
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    state["digest"] = "changed"
    envelope = _envelope(saved.json()["result"]["review"])
    changed = client.post(f"/api/dsk/{job_id}/decisions", json={"review": envelope, "baseRevision": 1})
    assert changed.status_code == 409
