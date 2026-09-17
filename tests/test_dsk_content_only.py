"""Tests for `content_only` (`--content-only`) shipped mode: `assemble_dsk_deck` drops
every text-class slide (`SlideClass.is_text`, the classifier's own predicate) before
planning, reports them on `AssembleResult.skipped`, forces `no_pills`/`no_style`, and
narrows an `import` layout policy to the alpha-safe black layout only. No test may
launch Keynote; the autouse fixture below raises if subprocess.run/Popen is reached
without an explicit monkeypatch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import obed_edom.dsk_assemble as dsa
import obed_edom.iwa_builds as iwa_builds
import obed_edom.iwa_write as iwa_write
from obed_edom.dsk_assemble import (
    AssembleResult,
    AssemblyRefusal,
    SlideDecision,
    assemble_dsk_deck,
)
from obed_edom.dsk_plan import classify_slide

WALL = (7680.0, 1080.0)
LONG_TEXT = " ".join(["word"] * 20)


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


def _text_item(kind_index, text=LONG_TEXT, x=1920, y=0, w=3698.0, h=494.4):
    return {"kind": "text", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h, "text": text}


def _image_item(kind_index, x=1920, y=0, w=3840, h=1080):
    return {"kind": "image", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _movie_item(kind_index, x=1920, y=-763, w=3840, h=2160):
    return {"kind": "movie", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _slide(number, items, skipped=False):
    return {"number": number, "index": number - 1, "skipped": skipped, "items": items}


def _payload(slides, wall=WALL):
    return {"slideWidth": wall[0], "slideHeight": wall[1], "slides": slides}


def _classify(slide, **kwargs):
    return classify_slide(slide, kwargs.pop("builds", None), WALL, **kwargs)


def _fake_copy_keynote(src, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fake-assembled-deck")
    return dest


def _make_fake_live_batch(stderr_text="", returncode=0):
    class _FakeLiveBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def __exit__(self, exc_type, exc, _tb):
            return False

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            return subprocess.CompletedProcess([], returncode, "", stderr_text)

    return _FakeLiveBatch


def _patch_common(monkeypatch, payload, classes, stderr_text="", returncode=0):
    monkeypatch.setattr(
        dsa, "load_assembly_inputs",
        lambda deck, include_side=frozenset(), text_slide_words=10, no_dedupe=False,
        no_drop_panel_backdrop=False: (payload, classes, {}),
    )
    monkeypatch.setattr(dsa, "LiveBatch", _make_fake_live_batch(stderr_text, returncode))
    monkeypatch.setattr(dsa, "copy_keynote", _fake_copy_keynote)
    monkeypatch.setattr(dsa, "_load_deck", lambda path: ({}, {}, {}))
    monkeypatch.setattr(dsa, "deck_builds", lambda path, *, deck=None: {})
    monkeypatch.setattr(dsa, "_restore_clip_zorder", lambda out_path, plan, warnings: {})
    monkeypatch.setattr(dsa, "_restore_clip_timing", lambda staging_path, plan, log: {})
    monkeypatch.setattr(iwa_write, "card_styles", lambda objects, id_to_file: [])
    monkeypatch.setattr(
        iwa_write, "match_card_stroke_styles",
        lambda out_styles, src_styles, *, canvas_scale, min_refs: {
            "widths": {}, "chosen": [], "notes": [], "out_selected": []
        },
    )
    monkeypatch.setattr(iwa_write, "patch_stroke_widths", lambda deck, widths: {"refused": False})
    monkeypatch.setattr(
        iwa_write, "patch_media_stroke", lambda deck, strokes: {"refused": False, "patched": [], "created": []}
    )
    monkeypatch.setattr(iwa_builds, "deck_builds", lambda path, *, deck=None: {})
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [], "missing": [], "transitions": [], "order": []
        },
    )


def _fixture(tmp_path):
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    return fw_deck, out_path


# --------------------------------------------------------------------------
# The skip predicate, the report field, and the log lines.
# --------------------------------------------------------------------------
def test_content_only_skips_text_slides_keeps_movie_and_image(tmp_path, monkeypatch):
    fw_deck, out_path = _fixture(tmp_path)
    text_slide = _slide(5, [_text_item(0)])
    image_slide = _slide(21, [_image_item(0)])
    movie_slide = _slide(32, [_movie_item(0)])
    payload = _payload([text_slide, image_slide, movie_slide])
    classes = [_classify(text_slide), _classify(image_slide), _classify(movie_slide)]
    assert classes[0].is_text is True
    assert classes[1].is_text is False
    assert classes[2].is_text is False

    decisions = {
        5: SlideDecision(5, "in_deck"),
        21: SlideDecision(21, "in_deck"),
        32: SlideDecision(32, "in_deck"),
    }
    _patch_common(monkeypatch, payload, classes)
    # Kept slides 21,32 -> ordinals 1,2; slide 32 is the clip slide, so its staged
    # transition must read back as the expected dissolve (see dsk_assemble's own
    # `_verify_builds` clip-transition read-back, Codex r1 finding 10).
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {
            2: {"slideId": "o2", "builds": [], "transition": {
                "attributes": {"databaseEffect": "apple:dissolve", "databaseDuration": 0.5}
            }},
        },
    )

    logs: list[str] = []
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={32: Path("/tmp/clip.mov")},
        layout_policy="preserve", content_only=True, log=logs.append,
    )

    assert isinstance(result, AssembleResult)
    assert result.slides_kept == (21, 32)
    assert result.skipped == ({"slide": 5, "reason": "text", "category": classes[0].category, "longTextIds": [["text", 0]]},)
    assert "slide 5: text slide skipped (content-only)" in logs


def test_content_only_off_keeps_text_slides(tmp_path, monkeypatch):
    fw_deck, out_path = _fixture(tmp_path)
    text_slide = _slide(5, [_text_item(0)])
    payload = _payload([text_slide])
    classes = [_classify(text_slide)]
    decisions = {5: SlideDecision(5, "in_deck")}
    _patch_common(monkeypatch, payload, classes)

    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", content_only=False,
    )
    assert result.slides_kept == (5,)
    assert result.skipped == ()


def test_content_only_all_skipped_refuses(tmp_path, monkeypatch):
    fw_deck, out_path = _fixture(tmp_path)
    text_slide = _slide(13, [_text_item(0)])
    payload = _payload([text_slide])
    classes = [_classify(text_slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    _patch_common(monkeypatch, payload, classes)

    with pytest.raises(AssemblyRefusal, match="content-only: no content slides in the selection"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", content_only=True,
        )


# --------------------------------------------------------------------------
# no_pills / no_style forced on; import_layout_names narrowed to the black alias.
# --------------------------------------------------------------------------
def test_content_only_forces_no_pills_and_no_style(tmp_path, monkeypatch):
    fw_deck, out_path = _fixture(tmp_path)
    image_slide = _slide(21, [_image_item(0)])
    payload = _payload([image_slide])
    classes = [_classify(image_slide)]
    decisions = {21: SlideDecision(21, "in_deck")}
    _patch_common(monkeypatch, payload, classes)

    def _forbidden_pass(*_args, **_kwargs):
        raise AssertionError("style/pill pass must not run in content-only mode")

    monkeypatch.setattr(dsa, "_write_style_pass", _forbidden_pass)
    monkeypatch.setattr(dsa, "_write_pill_pass", _forbidden_pass)

    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve",
        content_only=True, no_pills=False, no_style=False,
    )
    assert result.slides_kept == (21,)


def test_content_only_narrows_import_layout_names(tmp_path, monkeypatch):
    fw_deck, out_path = _fixture(tmp_path)
    image_slide = _slide(21, [_image_item(0)])
    payload = _payload([image_slide])
    classes = [_classify(image_slide)]
    decisions = {21: SlideDecision(21, "in_deck")}
    _patch_common(monkeypatch, payload, classes)

    captured: dict = {}

    def _fake_precondition_check(fw_deck, *, layout_template, layout_names):
        captured["layout_names"] = tuple(layout_names)

    monkeypatch.setattr(dsa, "check_layout_import_preconditions", _fake_precondition_check)
    monkeypatch.setattr(dsa, "resolve_slide_layouts", lambda payload, classes, plan: {21: "Blank Black"})
    monkeypatch.setattr(
        dsa, "verify_staged_layouts_alpha_safe",
        lambda staging_path, plan, *, expected_layout_names=None, hidden=None, log=print: None,
    )

    assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="import", content_only=True,
    )

    assert captured["layout_names"] == dsa.DEFAULT_TRANSPARENT_LAYOUT_NAMES


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text_fit": "shrink"},
        {"min_text_pt": 30.0},
        {"allow_split": False},
        {"split_overrides": {3: 2}},
    ],
)
def test_content_only_refuses_text_only_kwargs(tmp_path, kwargs):
    """Library callers get the same refusal the CLI gives for --split/--no-split/
    --text-fit shrink/--min-text-pt under --content-only, instead of a silent no-op.
    The refusal fires before any deck is read, so no fixture is needed."""
    with pytest.raises(ValueError, match="no meaning with content_only=True"):
        assemble_dsk_deck(
            tmp_path / "missing (FW).key",
            tmp_path / "out" / "x_DSK.key",
            decisions={1: SlideDecision(slide=1, action="in_deck", anchor="auto", keep_side=False)},
            content_only=True,
            **kwargs,
        )
