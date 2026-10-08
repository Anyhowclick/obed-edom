import re

import pytest

from obed_edom.web import job_names
from obed_edom.web.job_names import generate_job_name, normalise_job_name

NAME_RE = re.compile(r"^[a-z]+-[a-z]+(-\d+)?$")


def test_generated_names_are_two_words_and_unique():
    taken: set[str] = set()
    for _ in range(200):
        name = generate_job_name(taken)
        assert NAME_RE.match(name), name
        assert name not in taken
        taken.add(name)


@pytest.mark.parametrize(
    "taken,expected",
    [
        ({"quiet-jordan"}, "quiet-jordan-2"),
        ({"quiet-jordan", "quiet-jordan-2", "quiet-jordan-3"}, "quiet-jordan-4"),
    ],
    ids=["first_suffix", "increments_past_existing"],
)
def test_name_generation_falls_back_to_suffix_when_exhausted(monkeypatch, taken, expected):
    monkeypatch.setattr(job_names, "ADJECTIVES", ("quiet",))
    monkeypatch.setattr(job_names, "PLACES", ("jordan",))
    assert generate_job_name(taken) == expected


@pytest.mark.parametrize("raw", ["../evil", ".", "..", "", "   ", "/etc/passwd"])
def test_normalise_rejects_traversal_and_empty(raw):
    with pytest.raises(ValueError):
        normalise_job_name(raw)


def test_normalise_rejects_names_over_the_length_cap():
    with pytest.raises(ValueError):
        normalise_job_name("a" * 60)


def test_normalise_lowercases_and_hyphenates():
    assert normalise_job_name("  Quiet   Jordan  ") == "quiet-jordan"
    assert normalise_job_name("Quiet_Jordan!!") == "quietjordan"
    assert normalise_job_name("--quiet--jordan--") == "quiet-jordan"
