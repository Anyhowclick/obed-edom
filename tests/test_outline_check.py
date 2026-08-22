from pathlib import Path

import pytest
from obed_edom.annotate import annotate_outline
from obed_edom.outline_check import (
    SemanticOutlineError,
    correspondence,
    corroborate,
    cue_playlist,
    load_playlist,
    outline_flavour,
    read_cues,
    rows_for_slots,
    slots_from_cues,
)
from obed_edom.parse_outline import load_paragraphs, parse_outline
from obed_edom.slide_map import map_slides

from outline_fixtures import build_outline, verse_after_point_variant

ROOT = Path(__file__).resolve().parents[1]
OUTLINES = ROOT / "Sermon Outlines"
_NEED = ["Sermon BC.docx", "Offering JX.docx"]

pytestmark = pytest.mark.skipif(
    not all((OUTLINES / name).is_file() for name in _NEED),
    reason="Sermon Outlines/ fixtures are local operator files (gitignored)",
)


def _cue(source: Path, dest: Path) -> Path:
    outline = parse_outline(source)
    lw, dsk, _ = map_slides(outline)
    return annotate_outline(outline, lw, dsk, dest)


@pytest.fixture(scope="module")
def cued(tmp_path_factory) -> Path:
    """The offering outline, cued. Six LW cues, seven DSK, one held wall."""
    out = tmp_path_factory.mktemp("cued")
    return _cue(OUTLINES / "Offering JX.docx", out / "Offering_CUED.docx")


@pytest.fixture(scope="module")
def cued_split(tmp_path_factory) -> Path:
    """A sermon whose points carry [VERSE-AFTER-POINT], so POST slides exist."""
    out = tmp_path_factory.mktemp("cued_split")
    variant = verse_after_point_variant(OUTLINES / "Sermon BC.docx", out / "BC_VAP.docx")
    return _cue(variant, out / "BC_VAP_CUED.docx")


def catalog(count: int, *, skipped: tuple[int, ...] = (), texts: tuple[str, ...] = ()) -> list[dict]:
    return [
        {
            "index": i,
            "number": i + 1,
            "skipped": i in skipped,
            "png": None,
            "text": texts[i] if i < len(texts) else "",
        }
        for i in range(count)
    ]


def test_offering_playlist_shape(cued):
    """Adjacent cues are one advance; a lone [DSK-PP] means the wall holds."""
    playlist, _ = load_playlist(cued)
    assert len(playlist.rows) == 7
    assert playlist.count("lw") == 6
    assert playlist.count("dsk") == 7

    holds = [row for row in playlist.rows if row.lw is None]
    assert len(holds) == 1
    assert holds[0].index == 2
    assert holds[0].dsk is not None

    first = playlist.rows[0]
    assert first.tags == ["LW-OFFERING FILLER", "DSK-PP-QR CODE"]


def test_bare_reference_line_joins_the_row_it_belongs_to(cued):
    """Generate cues the verse body and leaves the reference on the line above."""
    playlist, _ = load_playlist(cued)
    verse_row = playlist.rows[1]
    assert "Mark 6:30-32" in verse_row.script
    assert "If God gives such attention" in verse_row.script


def test_split_sermon_playlist_matches_its_decks(cued_split):
    """A point too long for the lower third shows up as an LW-only row."""
    playlist, _ = load_playlist(cued_split)
    assert playlist.count("lw") == 7
    assert playlist.count("dsk") == 5
    assert playlist.rows[-1].lw is not None
    assert playlist.rows[-1].dsk is None


def test_correspondence_is_quiet_when_the_decks_match(cued):
    playlist, _ = load_playlist(cued)
    rules = {f.rule for f in correspondence(playlist, {"lw": catalog(6), "dsk": catalog(7)})}
    assert rules == {"cue.hold"}


def test_uncued_slide_is_reported(cued):
    playlist, _ = load_playlist(cued)
    flags = correspondence(playlist, {"lw": catalog(7), "dsk": catalog(7)})
    rules = [f.rule for f in flags]
    assert "cue.lw_count" in rules
    assert "cue.uncued_slide" in rules
    uncued = next(f for f in flags if f.rule == "cue.uncued_slide")
    assert uncued.slide == 7
    assert uncued.deck == "lw"


def test_cue_with_no_slide_is_reported(cued):
    playlist, _ = load_playlist(cued)
    flags = correspondence(playlist, {"lw": catalog(6), "dsk": catalog(6)})
    rules = [f.rule for f in flags]
    assert "cue.dsk_count" in rules
    assert "cue.no_slide" in rules


def test_skipped_slides_do_not_need_a_cue(cued):
    playlist, _ = load_playlist(cued)
    flags = correspondence(
        playlist, {"lw": catalog(7, skipped=(6,)), "dsk": catalog(7)}
    )
    assert not any(f.rule in {"cue.lw_count", "cue.uncued_slide"} for f in flags)


def test_single_deck_only_checks_that_deck(cued):
    playlist, _ = load_playlist(cued)
    flags = correspondence(playlist, {"lw": catalog(6)})
    assert not any(f.rule.startswith("cue.dsk") for f in flags)
    # A hold only means something when both decks are present.
    assert not any(f.rule == "cue.hold" for f in flags)


def test_unknown_bracket_is_flagged_but_stage_directions_are_not(tmp_path):
    path = build_outline(
        tmp_path / "unknown.docx",
        [
            "[LW][DSK-PP] Steep your life in God-reality.",
            "[Pray] and then [Instructions] follow.",
            "[LW][DSK-PP] Do not worry. [Turn to your neighbours and say hi]",
            "[LWW] Worry stops us from seeing God-reality.",
        ],
    )
    playlist = cue_playlist(load_paragraphs(path))
    raw = [text for _para, text in playlist.unknown]
    assert raw == ["[LWW]"]
    flags = correspondence(playlist, {"lw": catalog(2), "dsk": catalog(2)})
    assert any(f.rule == "cue.unknown" for f in flags)


def test_slots_fold_a_held_wall_into_a_combined_pair(cued):
    playlist, _ = load_playlist(cued)
    slots = slots_from_cues(playlist, catalog(6), catalog(7))
    assert slots == [
        (0, [0], 1.0),
        (1, [1, 2], 1.0),
        (2, [3], 1.0),
        (3, [4], 1.0),
        (4, [5], 1.0),
        (5, [6], 1.0),
    ]


def test_slots_skip_hidden_slides(cued):
    playlist, _ = load_playlist(cued)
    slots = slots_from_cues(playlist, catalog(7, skipped=(0,)), catalog(7))
    assert slots[0][0] == 1


def test_rows_for_slots_lines_up_with_the_pairs(cued):
    playlist, _ = load_playlist(cued)
    slots = slots_from_cues(playlist, catalog(6), catalog(7))
    rows = rows_for_slots(playlist, slots)
    assert len(rows) == len(slots)
    assert rows[1] is not None and rows[1].index == 1
    # The row after a combined pair is the next wall advance, not the hold.
    assert rows[2] is not None and rows[2].index == 3


def test_semantic_outline_is_rejected():
    assert outline_flavour(load_paragraphs(OUTLINES / "Sermon BC.docx")) == "semantic"
    with pytest.raises(SemanticOutlineError) as excinfo:
        load_playlist(OUTLINES / "Sermon BC.docx")
    assert "Sermon Base Generator" in str(excinfo.value)


def test_read_cues_ignores_semantic_tags(tmp_path):
    path = build_outline(tmp_path / "mixed.docx", ["[VERSE] Ezekiel 36:26 A new heart."])
    assert read_cues(load_paragraphs(path)) == []


SCRIPT = "I will give you a new heart and put a new spirit in you."
CHANGED = "I will give you a new soul and put a new spirit in you."


def test_corroborate_is_silent_when_everything_agrees():
    assert corroborate(SCRIPT, SCRIPT, SCRIPT) == []


def test_dsk_alone_disagreeing_is_dsk_wrong():
    """DSK is bottom of the pile either way, so this verdict does not move."""
    changed = "I will give you a new soul and put a new spirit in you."
    for final in (True, False):
        flags = corroborate(SCRIPT, SCRIPT, changed, lw_final=final)
        assert [f.rule for f in flags] == ["outline.dsk_deviates"]
        assert flags[0].deck == "dsk"


def test_a_finalised_wall_outranks_the_script():
    """LW moved on and DSK did not, which is the change that never landed."""
    flags = corroborate(SCRIPT, CHANGED, SCRIPT, lw_final=True)
    assert [f.rule for f in flags] == ["outline.dsk_stale"]
    assert flags[0].deck == "dsk"
    assert "LW:" in flags[0].message


def test_an_unfinalised_wall_is_the_one_questioned():
    flags = corroborate(SCRIPT, CHANGED, SCRIPT, lw_final=False)
    assert [f.rule for f in flags] == ["outline.lw_deviates"]
    assert flags[0].deck == "lw"


def test_decks_agreeing_against_a_finalised_wall_means_a_stale_script():
    flags = corroborate(SCRIPT, CHANGED, CHANGED, lw_final=True)
    assert [f.rule for f in flags] == ["outline.stale"]
    assert flags[0].severity == "info"


def test_decks_agreeing_before_sign_off_still_questions_them():
    flags = corroborate(SCRIPT, CHANGED, CHANGED, lw_final=False)
    assert [f.rule for f in flags] == ["outline.both_deviate"]
    assert flags[0].severity == "warning"


def test_three_way_disagreement_asks_for_a_human():
    flags = corroborate(
        SCRIPT,
        "I will give you a new soul and put a new spirit in you.",
        "I will give you a new heart and put a new mind in you.",
    )
    assert [f.rule for f in flags] == ["outline.three_way"]
    assert flags[0].severity == "info"


def test_commentary_between_cues_is_not_treated_as_slide_copy():
    """Most of an outline is spoken, and belongs on no slide."""
    spoken = "So, like what PAZ shared with us last weekend, do not worry!"
    assert corroborate(spoken, SCRIPT, SCRIPT) == []


def test_one_deck_plus_outline_compares_directly():
    """With one deck the ranking is two levels, and the wall's status decides."""
    assert [f.rule for f in corroborate(SCRIPT, CHANGED, "", lw_final=True)] == ["outline.stale"]
    assert [f.rule for f in corroborate(SCRIPT, CHANGED, "", lw_final=False)] == [
        "outline.lw_deviates"
    ]
    # A lower third is below the script whether or not the wall is signed off.
    for final in (True, False):
        assert [f.rule for f in corroborate(SCRIPT, "", CHANGED, lw_final=final)] == [
            "outline.dsk_deviates"
        ]


def test_findings_are_demoted_when_the_slide_has_no_selectable_text():
    """Exported JPEGs and .movs leave only OCR, so this is a note, not an error."""
    warned = corroborate(SCRIPT, SCRIPT, CHANGED, typed=True)
    noted = corroborate(SCRIPT, SCRIPT, CHANGED, typed=False)
    assert warned[0].severity == "warning"
    assert noted[0].severity == "info"
    assert "OCR" in noted[0].message


def _pair(index: int, left_number: int, right_numbers: list[int], lw: str, dsk: str) -> dict:
    return {
        "index": index,
        "number": index + 1,
        "leftIndex": left_number - 1,
        "rightIndex": right_numbers[0] - 1 if right_numbers else None,
        "rightIndexes": [n - 1 for n in right_numbers],
        "leftNumber": left_number,
        "rightNumber": right_numbers[0] if right_numbers else None,
        "rightNumbers": list(right_numbers),
        "leftRendered": lw,
        "rightRendered": dsk,
        "typed": True,
        "score": 1.0,
        "flags": [],
    }


class _SilentJob:
    def log(self, _message: str) -> None:
        return None


def _run_apply(cued: Path, pairs: list[dict], *, lw_final: bool = True):
    from obed_edom.web.app import _apply_outline

    result = {
        "outlinePath": str(cued),
        "lwFinal": lw_final,
        "leftDeck": "lw",
        "rightDeck": "dsk",
        "leftLabel": "LW",
        "rightLabel": "DSK",
        "leftCatalog": catalog(6),
        "rightCatalog": catalog(7),
    }
    return _apply_outline(_SilentJob(), result, {}, pairs)


def test_apply_outline_attaches_rows_and_verdicts_to_pairs(cued):
    """The web layer hands a row's verdict straight to the pair that owns it."""
    playlist, _ = load_playlist(cued)
    verse = playlist.rows[1].script
    pairs = [
        _pair(0, 1, [1], "Hi Church!", "Hi Church!"),
        # DSK drops a word that the outline and the wall both carry.
        _pair(1, 2, [2, 3], verse, verse.replace("God", "the Lord", 1)),
    ]
    outline_flags = _run_apply(cued, pairs)

    assert all("outlineRow" in pair for pair in pairs)
    assert pairs[1]["outlineRow"]["tags"] == ["LW", "DSK-PP"]
    assert "wildflowers" in pairs[1]["outlineRow"]["script"]

    assert "outline.dsk_deviates" in [f.rule for f in pairs[1]["flags"]]
    # Correspondence is about the script as a whole, so it stays out of the row.
    assert all(not f.rule.startswith("cue.") for f in pairs[1]["flags"])
    assert {f.rule for f in outline_flags} <= {"cue.hold", "cue.unknown"}


def test_apply_outline_honours_whether_the_wall_is_final(cued):
    """The same slides read differently depending on the sign-off answer."""
    playlist, _ = load_playlist(cued)
    verse = playlist.rows[1].script
    changed = verse.replace("God", "the Lord", 1)

    def rules(lw_final: bool) -> list[str]:
        # Rows are consumed in order, so the verse row is the second pair.
        # The wall carries the edit; the script and DSK are both behind it.
        pairs = [
            _pair(0, 1, [1], "Hi Church!", "Hi Church!"),
            _pair(1, 2, [2, 3], changed, verse),
        ]
        _run_apply(cued, pairs, lw_final=lw_final)
        return [f.rule for f in pairs[1]["flags"] if f.rule.startswith("outline.")]

    assert rules(True) == ["outline.dsk_stale"]
    assert rules(False) == ["outline.lw_deviates"]
