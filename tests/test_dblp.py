"""Tests for the DBLP source.

These tests do not hit the live DBLP API. Network tests live in
`tests/integration/` and are opted in via the `integration` marker.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from paper_collector.sources.base import SourceConfig
from paper_collector.sources.dblp import (
    DBLPSource,
    _coerce_authors,
    _coerce_year,
    _map_publication_type,
)

SAMPLE_HIT_MULTI_AUTHOR = {
    "@score": "1",
    "@id": "1",
    "info": {
        "authors": {
            "author": [
                {"@pid": "1/2", "text": "Ashish Vaswani"},
                {"@pid": "3/4", "text": "Noam Shazeer"},
            ]
        },
        "title": "Attention Is All You Need",
        "venue": "NeurIPS",
        "year": "2017",
        "type": "Conference and Workshop Papers",
        "key": "conf/nips/VaswaniSPUJGKP17",
        "doi": "10.5555/3295222.3295349",
        "ee": "https://papers.nips.cc/paper/7181-attention-is-all-you-need",
        "url": "https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17",
    },
    "url": "https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17",
}

SAMPLE_HIT_SINGLE_AUTHOR = {
    "info": {
        "authors": {"author": {"@pid": "5/6", "text": "Geoffrey E. Hinton"}},
        "title": "Some Solo Paper",
        "venue": "Nature",
        "year": "2024",
        "type": "Journal Articles",
        "key": "journals/nature/Hinton24",
    },
}

SAMPLE_RESPONSE_MULTI = {
    "result": {
        "hits": {
            "@total": "2",
            "hit": [SAMPLE_HIT_MULTI_AUTHOR, SAMPLE_HIT_SINGLE_AUTHOR],
        }
    }
}

SAMPLE_RESPONSE_SINGLE_HIT = {
    "result": {
        "hits": {
            "@total": "1",
            "hit": SAMPLE_HIT_MULTI_AUTHOR,  # dict, not list
        }
    }
}

SAMPLE_RESPONSE_EMPTY = {"result": {"hits": {"@total": "0"}}}


@pytest.fixture
def source() -> DBLPSource:
    """A DBLPSource with rate limiting disabled for fast tests."""
    config = SourceConfig(
        name="dblp",
        rate_limit_per_second=0.0,
        max_retries=1,
        timeout_seconds=5.0,
    )
    return DBLPSource(config=config)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def test_map_publication_type_conference() -> None:
    assert _map_publication_type("Conference and Workshop Papers") == "conference"


def test_map_publication_type_journal() -> None:
    assert _map_publication_type("Journal Articles") == "journal"


def test_map_publication_type_informal() -> None:
    assert _map_publication_type("Informal and Other Publications") == "preprint"


def test_map_publication_type_unknown() -> None:
    assert _map_publication_type("Something Else") == ""


def test_coerce_authors_handles_list() -> None:
    info = SAMPLE_HIT_MULTI_AUTHOR["info"]
    assert _coerce_authors(info) == ["Ashish Vaswani", "Noam Shazeer"]


def test_coerce_authors_handles_single_dict() -> None:
    info = SAMPLE_HIT_SINGLE_AUTHOR["info"]
    assert _coerce_authors(info) == ["Geoffrey E. Hinton"]


def test_coerce_authors_handles_missing() -> None:
    assert _coerce_authors({}) == []


def test_coerce_year_parses_string() -> None:
    assert _coerce_year({"year": "2024"}) == 2024


def test_coerce_year_returns_none_on_missing() -> None:
    assert _coerce_year({}) is None


def test_coerce_year_returns_none_on_invalid() -> None:
    assert _coerce_year({"year": "not a year"}) is None


# ----------------------------------------------------------------------
# _hit_to_paper
# ----------------------------------------------------------------------


def test_hit_to_paper_full(source: DBLPSource) -> None:
    """A DBLP hit is converted to a Paper with all fields filled."""
    paper = source._hit_to_paper(SAMPLE_HIT_MULTI_AUTHOR)
    assert paper.title == "Attention Is All You Need"
    assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper.year == 2017
    assert paper.venue == "NeurIPS"
    assert paper.publication_type == "conference"
    assert paper.dblp_key == "conf/nips/VaswaniSPUJGKP17"
    assert paper.doi == "10.5555/3295222.3295349"
    assert paper.source == "dblp"
    assert paper.source_raw is not None


# ----------------------------------------------------------------------
# search (mocked HTTP)
# ----------------------------------------------------------------------


def test_search_parses_multiple_hits(source: DBLPSource) -> None:
    """A search with multiple hits returns multiple Papers."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_MULTI):
        papers = list(source.search("test", max_results=10))
    assert len(papers) == 2
    assert papers[0].title == "Attention Is All You Need"
    assert papers[1].authors == ["Geoffrey E. Hinton"]


def test_search_handles_single_hit_as_dict(source: DBLPSource) -> None:
    """When DBLP returns a single hit as a dict (not a list), we handle it."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_SINGLE_HIT):
        papers = list(source.search("test", max_results=10))
    assert len(papers) == 1
    assert papers[0].dblp_key == "conf/nips/VaswaniSPUJGKP17"


def test_search_handles_empty_response(source: DBLPSource) -> None:
    """An empty response returns no papers."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_EMPTY):
        papers = list(source.search("nothing", max_results=10))
    assert papers == []


def test_search_respects_max_results(source: DBLPSource) -> None:
    """The search stops at max_results."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_MULTI):
        papers = list(source.search("test", max_results=1))
    assert len(papers) == 1


# ----------------------------------------------------------------------
# fetch_by_id
# ----------------------------------------------------------------------


def test_fetch_by_id_returns_paper_when_key_matches(source: DBLPSource) -> None:
    """fetch_by_id returns the Paper when key matches a hit."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_MULTI):
        paper = source.fetch_by_id("conf/nips/VaswaniSPUJGKP17")
    assert paper is not None
    assert paper.title == "Attention Is All You Need"


def test_fetch_by_id_returns_none_when_no_match(source: DBLPSource) -> None:
    """fetch_by_id returns None if no hit's key matches."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_MULTI):
        paper = source.fetch_by_id("conf/something/Nonexistent")
    assert paper is None


def test_fetch_by_id_returns_none_when_empty(source: DBLPSource) -> None:
    """fetch_by_id returns None on empty response."""
    with patch.object(source, "_get", return_value=SAMPLE_RESPONSE_EMPTY):
        paper = source.fetch_by_id("anything")
    assert paper is None
