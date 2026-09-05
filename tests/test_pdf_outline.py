"""Cued outline PDFs for Sermon Checker (not for generate)."""

from pathlib import Path

import pytest

from obed_edom.outline_check import load_playlist, outline_report
from obed_edom.parse_outline import parse_outline


def _write_cued_pdf(path: Path) -> Path:
    from reportlab.pdfgen import canvas

    path = Path(path)
    c = canvas.Canvas(str(path))
    y = 800
    for line in (
        "[LW] [DSK-PP]",
        "Ezekiel 36:26 I will give you a new heart and put a new spirit in you.",
        "[LW-TITLE]",
        "Faith that moves mountains",
    ):
        c.drawString(72, y, line)
        y -= 18
    c.save()
    return path


def test_load_playlist_reads_a_cued_pdf(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    playlist, paragraphs = load_playlist(path)
    assert len(paragraphs) == 4
    assert playlist.count("lw") == 2
    assert playlist.count("dsk") == 1
    assert playlist.rows[0].script.startswith("Ezekiel 36:26")


def test_outline_report_accepts_pdf(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    report = outline_report(path)
    assert report["lwCues"] == 2
    assert report["dskCues"] == 1
    assert len(report["rows"]) == 2
    assert report["paragraphs"]


def test_parse_outline_rejects_pdf(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    with pytest.raises(ValueError, match=r"\.docx"):
        parse_outline(path)
