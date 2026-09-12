from collections import Counter

import pytest

import obed_edom.diff_keynotes as diff_keynotes
from obed_edom.diagnostics import DiagnosticsWriter, load_records, replay
from obed_edom.diff_keynotes import compare_inspects
from obed_edom.text_diff import classify_text_diff


def _record(left: str, right: str) -> dict:
    """A single-attempt text record built the way `select_text_sources` actually
    picks it (typed left empty, so only the clean/full attempt is tried)."""
    (attempts, typed_skip) = diff_keynotes.select_text_sources(left, "", "", right, "", "")
    (source, a, b, reason), = attempts
    finding = classify_text_diff(a, b, "LW", "DSK")
    return {
        "kind": "text",
        "pairIndex": 0,
        "pairNumber": 1,
        "left": {"text": left, "typed": "", "extracted": left, "ocr": "", "outsidePhotos": left},
        "right": {"text": right, "typed": "", "extracted": right, "ocr": "", "outsidePhotos": right},
        "shares": {"typedLeft": 0.0, "typedRight": 0.0, "cleanLeft": 1.0, "cleanRight": 1.0},
        "typedSkip": typed_skip,
        "carried": None,
        "attempts": [
            {
                "source": source,
                "reason": reason,
                "inputLeft": a,
                "inputRight": b,
                "ignoreLeftTokens": [],
                "carried": None,
                "finding": {"rule": finding.rule, "message": finding.message, "default": finding.default}
                if finding
                else None,
            }
        ],
        "outcome": {"rule": finding.rule, "message": finding.message, "severity": finding.default}
        if finding
        else None,
    }


def test_writer_round_trip(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(jobId="job1", leftLabel="LW", rightLabel="DSK")
        diag.record("text", pairIndex=0, outcome=None)
        diag.record("finding", rule="photo.differs", pairIndex=None)

    header, records = load_records(path)
    assert header == {"kind": "header", "schema": 1, "jobId": "job1", "leftLabel": "LW", "rightLabel": "DSK"}
    assert len(records) == 2
    assert records[0]["kind"] == "text"
    assert records[1]["kind"] == "finding"


def test_writer_sanitizes_a_nan_record_instead_of_dropping_it(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        diag.record("finding", rule="bad", score=float("nan"))
        diag.record("finding", rule="good", score=2)
        assert diag.error is None

    header, records = load_records(path)
    assert [r["rule"] for r in records] == ["bad", "good"]
    assert records[0]["score"] is None


def test_writer_publishes_atomically_on_commit(tmp_path):
    """The file at `path` must not exist (or change) until `commit()` succeeds; a
    reader can never see a partially-written file."""
    path = tmp_path / "diagnostics.jsonl"
    diag = DiagnosticsWriter(path)
    diag.header(leftLabel="LW", rightLabel="DSK")
    diag.record("finding", rule="photo.differs", pairIndex=None)
    assert not path.exists()
    assert diag.commit() is True
    assert path.exists()
    assert not diag.tmp_path.exists()


def test_writer_close_without_commit_discards_the_temp_file_and_keeps_the_old_one(tmp_path):
    """A failed check (writer aborted via `close()` instead of `commit()`) must leave
    any previously-published file untouched."""
    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", run=1)
    assert path.exists()
    old_contents = path.read_text(encoding="utf-8")

    diag = DiagnosticsWriter(path)
    diag.header(leftLabel="LW", rightLabel="DSK", run=2)
    diag.close()

    assert not diag.tmp_path.exists()
    assert path.read_text(encoding="utf-8") == old_contents


def test_a_successful_recheck_replaces_the_previous_diagnostics_file(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", run=1)

    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", run=2)

    header, _ = load_records(path)
    assert header["run"] == 2


def test_load_records_raises_on_schema_mismatch(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text('{"kind": "header", "schema": 99}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_records(path)


def test_replay_round_trip_agrees(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        diag.record(**_record("Your Faith", "Faith"))

    assert replay(path) == 0


def test_replay_catches_a_typed_coverage_threshold_change(tmp_path, monkeypatch):
    # Full text matches on both sides; only the typed layer differs, and its
    # share of the full text (0.7) sits between the default TYPED_COVERAGE
    # (0.6) and a raised one (0.99). At the default, the typed attempt covers
    # both sides and fires first; raising the threshold skips straight to the
    # clean/full attempt, which sees identical text and finds nothing — the
    # *selected attempt* changes even though nobody touched the terminal rule.
    a_text = "one two three four five six seven eight nine ten"
    b_text = "one two three four five six seven eight nine ten"
    a_typed = "one two three four five six seven"
    b_typed = "one two three four five six ocho"
    finding = classify_text_diff(a_typed, b_typed, "LW", "DSK")
    assert finding is not None

    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", pointTitles=[])
        diag.record(
            "text",
            pairIndex=0,
            pairNumber=1,
            left={"text": a_text, "typed": a_typed, "extracted": a_text, "ocr": "", "outsidePhotos": a_text},
            right={"text": b_text, "typed": b_typed, "extracted": b_text, "ocr": "", "outsidePhotos": b_text},
            shares={"typedLeft": 0.7, "typedRight": 0.7, "cleanLeft": 1.0, "cleanRight": 1.0},
            carried=None,
            attempts=[
                {
                    "source": "typed",
                    "reason": "typed-covers-both",
                    "inputLeft": a_typed,
                    "inputRight": b_typed,
                    "ignoreLeftTokens": [],
                    "carried": None,
                    "finding": {"rule": finding.rule, "message": finding.message, "default": finding.default},
                }
            ],
            outcome={"rule": finding.rule, "message": finding.message, "severity": finding.default},
        )

    assert replay(path) == 0

    monkeypatch.setattr(diff_keynotes, "TYPED_COVERAGE", 0.99)
    assert replay(path) == 1


def test_replay_reports_message_only_mismatches_separately(tmp_path, monkeypatch):
    import obed_edom.text_diff as text_diff

    path = tmp_path / "diagnostics.jsonl"
    rec = _record("Your Faith", "Faith")
    assert rec["outcome"] is not None
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        diag.record(**rec)

    # A purely presentational change to the phrase-rendering helper changes the
    # message but not the rule/default the classifier reaches: exit 0 by default,
    # but strict mode fails it.
    assert replay(path) == 0

    orig_phrase = text_diff._phrase
    monkeypatch.setattr(text_diff, "_phrase", lambda *a, **k: "[" + orig_phrase(*a, **k) + "]")
    assert replay(path) == 0
    assert replay(path, strict=True) == 1


def test_replay_catches_a_point_title_carry_change(tmp_path, monkeypatch):
    """`carried` (from `strip_carried_point_title`) must be part of the replay
    comparison: a point-title change that alters what gets stripped from the left
    text has to flip a recorded MATCH into a MISMATCH, not silently agree."""
    left = "Your Faith\nGod is good and He loves us always"
    right = "God is good and He loves us always"
    point_titles = ["your faith"]

    stripped, carried = diff_keynotes.strip_carried_point_title(left, right, point_titles)
    assert carried == "Your Faith"
    finding = classify_text_diff(stripped, right, "LW", "DSK")

    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", pointTitles=point_titles)
        diag.record(
            "text",
            pairIndex=0,
            pairNumber=1,
            left={"text": left, "typed": "", "extracted": left, "ocr": "", "outsidePhotos": left},
            right={"text": right, "typed": "", "extracted": right, "ocr": "", "outsidePhotos": right},
            shares={"typedLeft": 0.0, "typedRight": 0.0, "cleanLeft": 1.0, "cleanRight": 1.0},
            typedSkip="typed-empty",
            carried=carried,
            attempts=[
                {
                    "source": "clean",
                    "reason": "filter-symmetric",
                    "inputLeft": stripped,
                    "inputRight": right,
                    "ignoreLeftTokens": [],
                    "carried": carried,
                    "finding": {"rule": finding.rule, "message": finding.message, "default": finding.default}
                    if finding
                    else None,
                }
            ],
            outcome={"rule": finding.rule, "message": finding.message, "severity": finding.default}
            if finding
            else None,
        )

    assert replay(path) == 0

    # Point titles no longer include "Your Faith" -> nothing is carried/stripped
    # anymore, so the classifier now sees the leading point-title line too.
    monkeypatch.setattr(
        diff_keynotes, "strip_carried_point_title", lambda text, _other, _titles: (text, None)
    )
    assert replay(path) == 1


def test_no_finding_pairs_still_replay(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    rec = _record("Faith", "Faith")
    assert rec["outcome"] is None
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        diag.record(**rec)

    assert replay(path) == 0


def test_replay_of_an_unchanged_disabled_rule_is_a_match(tmp_path):
    """A rule configured `off` records `outcome: null`; replaying it must not report
    that as a mismatch just because the recorded outcome is empty."""
    left, right = "Your Faith", "Faith"
    (attempts, typed_skip) = diff_keynotes.select_text_sources(left, "", "", right, "", "")
    (source, a, b, reason), = attempts
    finding = classify_text_diff(a, b, "LW", "DSK")
    assert finding is not None

    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", ruleSeverities={finding.rule: "off"})
        diag.record(
            "text",
            pairIndex=0,
            pairNumber=1,
            left={"text": left, "typed": "", "extracted": left, "ocr": "", "outsidePhotos": left},
            right={"text": right, "typed": "", "extracted": right, "ocr": "", "outsidePhotos": right},
            shares={"typedLeft": 0.0, "typedRight": 0.0, "cleanLeft": 1.0, "cleanRight": 1.0},
            typedSkip=typed_skip,
            carried=None,
            attempts=[
                {
                    "source": source,
                    "reason": reason,
                    "inputLeft": a,
                    "inputRight": b,
                    "ignoreLeftTokens": [],
                    "carried": None,
                    "finding": {"rule": finding.rule, "message": finding.message, "default": finding.default},
                }
            ],
            outcome=None,
        )

    assert replay(path) == 0


def test_compare_inspects_writes_one_text_record_per_pair(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [{"kind": "text", "text": "Praise and Worship"}]},
            {"number": 2, "items": [{"kind": "text", "text": "Your Faith"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [{"kind": "text", "text": "Praise & Worship"}]},
            {"number": 2, "items": [{"kind": "text", "text": "Faith"}]},
        ],
    }
    diag_path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        result = compare_inspects(
            left, right, tmp_path, tmp_path, tmp_path / "heat",
            left_label="LW", right_label="DSK", diag=diag, diag_context={"jobId": "j1"},
        )

    header, records = load_records(diag_path)
    assert header["jobId"] == "j1"
    text_records = [r for r in records if r["kind"] == "text"]
    assert len(text_records) == len(result["pairs"])
    recorded_rules = {r["outcome"]["rule"] for r in text_records if r["outcome"]}
    flagged_rules = {f.rule for f in result["flags"] if f.category == "diff" and f.rule.startswith("text.")}
    assert recorded_rules == flagged_rules
    assert replay(diag_path) == 0


def test_text_record_carries_why_typed_was_skipped(tmp_path):
    """The text record must say *why* the typed attempt was skipped (or that it
    wasn't), so a diagnostics reader can tell without re-deriving the gate values."""
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"kind": "text", "text": "Praise and Worship"}]}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"kind": "text", "text": "Praise & Worship"}]}],
    }
    diag_path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        compare_inspects(
            left, right, tmp_path, tmp_path, tmp_path / "heat",
            left_label="LW", right_label="DSK", diag=diag, diag_context={"jobId": "j1"},
        )

    _header, records = load_records(diag_path)
    text_record = next(r for r in records if r["kind"] == "text")
    assert text_record["attempts"]
    # Both sides render typed text that covers the slide, so it isn't skipped.
    assert text_record["typedSkip"] is None


def test_replay_catches_a_carry_change_on_a_non_selected_attempt(tmp_path, monkeypatch):
    """The fallback (``clean``) attempt is the one selected — it carries the finding —
    but the earlier ``typed`` attempt still feeds the pair-level `carried` value that
    drives `text.point_carry`. A recorded `carried`/attempt mismatch on that unselected
    attempt must be caught even though the selected attempt's finding is unchanged."""
    point_titles = ["your faith"]
    a_typed = "Your Faith\nGod is good and He loves us always"
    b_typed = "God is good and He loves us always"
    a_text, b_text = a_typed, b_typed
    a_clean = "God is good and He is faithful always"
    b_clean = "God is good and He loves us always"

    attempts, typed_skip = diff_keynotes.select_text_sources(a_text, a_typed, a_clean, b_text, b_typed, b_clean)
    (typed_source, typed_a, typed_b, typed_reason), (clean_source, clean_a, clean_b, clean_reason) = attempts

    typed_stripped, typed_carried = diff_keynotes.strip_carried_point_title(typed_a, typed_b, point_titles)
    typed_finding = classify_text_diff(typed_stripped, typed_b, "LW", "DSK")
    assert typed_carried == "Your Faith"
    assert typed_finding is None

    clean_stripped, clean_carried = diff_keynotes.strip_carried_point_title(clean_a, clean_b, point_titles)
    clean_finding = classify_text_diff(clean_stripped, clean_b, "LW", "DSK")
    assert clean_carried is None
    assert clean_finding is not None

    pair_carried = typed_carried or clean_carried
    attempt_records = [
        {
            "source": typed_source,
            "reason": typed_reason,
            "inputLeft": typed_stripped,
            "inputRight": typed_b,
            "ignoreLeftTokens": [],
            "carried": typed_carried,
            "finding": None,
        },
        {
            "source": clean_source,
            "reason": clean_reason,
            "inputLeft": clean_stripped,
            "inputRight": clean_b,
            "ignoreLeftTokens": [],
            "carried": clean_carried,
            "finding": {
                "rule": clean_finding.rule,
                "message": clean_finding.message,
                "default": clean_finding.default,
            },
        },
    ]
    outcome = {"rule": clean_finding.rule, "message": clean_finding.message, "severity": clean_finding.default}

    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK", pointTitles=point_titles)
        diag.record(
            "text",
            pairIndex=0,
            pairNumber=1,
            left={"text": a_text, "typed": a_typed, "extracted": a_text, "ocr": "", "outsidePhotos": a_clean},
            right={"text": b_text, "typed": b_typed, "extracted": b_text, "ocr": "", "outsidePhotos": b_clean},
            shares={"typedLeft": 1.0, "typedRight": 1.0, "cleanLeft": 1.0, "cleanRight": 1.0},
            typedSkip=typed_skip,
            carried=pair_carried,
            attempts=attempt_records,
            outcome=outcome,
        )

    assert replay(path) == 0

    # On replay, make the typed attempt strip a different title (same stripped text,
    # different `carried`) while the fallback attempt's classification is unchanged.
    # This isolates the `carried` comparison from a text/behaviour change.
    real_strip = diff_keynotes.strip_carried_point_title

    def _fake_strip(text: str, other: str, titles: list[str]) -> tuple[str, str | None]:
        stripped, carried = real_strip(text, other, titles)
        if carried == "Your Faith":
            return stripped, "A Different Point"
        return stripped, carried

    monkeypatch.setattr(diff_keynotes, "strip_carried_point_title", _fake_strip)
    assert replay(path) == 1


def test_replay_catches_a_tampered_typed_skip(tmp_path):
    """`typedSkip` is not derived from the attempt list, so a tampered value
    (e.g. an upstream render change that starts producing a thin typed layer,
    moving the cause from `typed-empty` to `typed-below-coverage`) must be
    caught even though the recorded attempts are byte-identical."""
    record = _record("Your Faith", "Faith")
    assert record["typedSkip"] == "typed-empty"
    record["typedSkip"] = "typed-below-coverage"

    path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        diag.record(**record)

    assert replay(path) == 1


@pytest.mark.parametrize(
    ("a_typed", "b_typed", "a_text", "b_text", "expected"),
    [
        ("", "", "Praise and Worship", "Praise & Worship", "typed-empty"),
        ("Praise", "Praise & Worship", "Praise and Worship long caption here", "Praise & Worship", "typed-below-coverage"),
        ("Praise and Worship", "Praise & Worship", "Praise and Worship", "Praise & Worship", None),
    ],
)
def test_select_text_sources_typed_skip_causes(a_typed, b_typed, a_text, b_text, expected):
    attempts, typed_skip = diff_keynotes.select_text_sources(
        a_text, a_typed, a_text, b_text, b_typed, b_text,
    )
    assert typed_skip == expected
    assert ("typed" in [a[0] for a in attempts]) == (expected is None)


def test_diagnostics_record_per_side_ocr_used(tmp_path, monkeypatch):
    """The OR'd ``ocrUsed`` field hides which side actually needed OCR; each side
    must be recorded separately so a false positive can be tuned."""
    from obed_edom.rendered import RenderedSlide

    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"kind": "text", "text": "Faith"}]}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"kind": "text", "text": "Faith Restored"}]}],
    }

    def fake_render_slide(slide, png, size, *, use_ocr=True):
        text = slide["items"][0]["text"]
        ocr_used = "Restored" in text
        return RenderedSlide(text=text, extracted=text, ocr="", ocr_used=ocr_used, outside_photos=text)

    monkeypatch.setattr(diff_keynotes, "render_slide", fake_render_slide)

    diag_path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        compare_inspects(
            left, right, tmp_path, tmp_path, tmp_path / "heat",
            left_label="LW", right_label="DSK", diag=diag, diag_context={"jobId": "j1"},
        )

    _header, records = load_records(diag_path)
    text_record = next(r for r in records if r["kind"] == "text")
    assert text_record["left"]["ocrUsed"] is False
    assert text_record["right"]["ocrUsed"] is True


def test_diagnostics_are_a_complete_inventory_of_flags(tmp_path):
    """Every flag in the result appears exactly once across the text/finding records."""
    left = {
        "path": str(tmp_path / "Sermon_A.key"),
        "slideWidth": 4200,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    {"kind": "text", "text": "Praise and Worship"},
                    # Straddles the center-wall edge -> a deck-level bounds.straddles flag.
                    {"kind": "shape", "x": 100, "y": 0, "w": 200, "h": 100},
                ],
            },
            {"number": 2, "items": [{"kind": "text", "text": "Your Faith"}]},
            {"number": 3, "items": [{"kind": "text", "text": "Closing"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_B.key"),
        "slideWidth": 4200,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [{"kind": "text", "text": "Praise & Worship"}]},
            {"number": 2, "items": [{"kind": "text", "text": "Faith"}]},
        ],
    }
    diag_path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        # Neutral labels so deck type falls back to slide width (both decks
        # are then "same type"), which is required for diff.count to fire.
        result = compare_inspects(
            left, right, tmp_path, tmp_path, tmp_path / "heat",
            left_label="LEFT", right_label="RIGHT", diag=diag, diag_context={"jobId": "j1"},
        )

    header, records = load_records(diag_path)
    assert header["jobId"] == "j1"

    recorded_rules: Counter = Counter()
    for rec in records:
        if rec["kind"] == "text":
            if rec.get("outcome"):
                recorded_rules[rec["outcome"]["rule"]] += 1
        elif rec["kind"] == "finding":
            recorded_rules[rec["rule"]] += 1

    expected_rules = Counter(f.rule for f in result["flags"])
    assert recorded_rules == expected_rules
    # unequal slide counts on same-type decks must produce a diff.count finding
    assert expected_rules["diff.count"] == 1
    # deck-level validate_inspect flags must be recorded too
    assert expected_rules["bounds.straddles"] >= 1
    assert replay(diag_path) == 0


def test_apply_outline_records_its_flags_to_diagnostics(tmp_path, monkeypatch):
    """`_apply_outline` runs after `compare_inspects`; its correspondence (deck-level)
    and corroboration (per-pair) flags must land in the same diagnostics file, not be
    silently dropped by a writer closed too early."""
    import obed_edom.web.app as app_module
    from obed_edom.outline_check import CueRef, CueRow, Playlist

    class _SilentJob:
        def log(self, _message: str) -> None:
            return None

    outline_path = tmp_path / "outline.docx"
    outline_path.write_text("stub", encoding="utf-8")

    lw_ref = CueRef(tag="LW", deck="lw", raw="[LW]", paragraph=0, start=0, end=4)
    row = CueRow(index=0, lw=lw_ref, script="I will give you a new heart.")
    playlist = Playlist(rows=[row])
    monkeypatch.setattr(app_module, "load_playlist", lambda _path: (playlist, []))

    left_catalog = [
        {"index": 0, "number": 1, "skipped": False, "png": None, "text": "I will give you a new heart."},
        # Uncued: one LW cue for two visible slides -> a real cue.* correspondence gap.
        {"index": 1, "number": 2, "skipped": False, "png": None, "text": "Amen."},
    ]
    pairs = [
        {
            "index": 0,
            "leftIndex": 0,
            "rightIndexes": [0],
            "leftNumber": 1,
            "rightNumber": 1,
            "rightNumbers": [1],
            "leftRendered": "I will give you a new heart.",
            # DSK drops a word the outline and LW both carry -> outline.dsk_deviates.
            "rightRendered": "I will give you a new soul.",
            "typed": True,
            "score": 1.0,
            "flags": [],
        }
    ]
    result = {
        "outlinePath": str(outline_path),
        "lwFinal": True,
        "leftDeck": "lw",
        "rightDeck": "dsk",
        "leftLabel": "LW",
        "rightLabel": "DSK",
        "leftCatalog": left_catalog,
        "rightCatalog": [],
    }

    diag_path = tmp_path / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")
        outline_flags = app_module._apply_outline(_SilentJob(), result, {}, pairs, diag=diag)

    assert any(f.rule == "cue.uncued_slide" for f in outline_flags)
    assert any(f.rule == "outline.dsk_deviates" for f in pairs[0]["flags"])

    _header, records = load_records(diag_path)
    finding_records = [r for r in records if r["kind"] == "finding"]

    deck_level = [r for r in finding_records if r["rule"] == "cue.uncued_slide"]
    assert deck_level and deck_level[0]["pairIndex"] is None

    pair_level = [r for r in finding_records if r["rule"] == "outline.dsk_deviates"]
    assert pair_level and pair_level[0]["pairIndex"] == 0
