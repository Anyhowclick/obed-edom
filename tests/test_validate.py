from sermon_slides.validate import validate_style_text


def test_style_en_dash_and_books():
    flags = validate_style_text("See Psalms 23 and Revelation 1. Lived 1980-2012. Meet 3-4 Jun.", location="t")
    cats = {f.category for f in flags}
    assert "book_name" in cats
    assert "date" in cats
    messages = " ".join(f.message for f in flags)
    assert "Psalm" in messages
    assert "Revelations" in messages
    assert "en dash" in messages


def test_trinity_lowercase_god():
    flags = validate_style_text("we love god forever", location="t")
    assert any(f.category == "trinity" for f in flags)
