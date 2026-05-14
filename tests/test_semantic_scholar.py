"""Tests for the Semantic Scholar source."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from paper_collector.sources.base import SourceConfig
from paper_collector.sources.semantic_scholar import (
    SemanticScholarSource,
    _extract_authors,
    _extract_external_ids,
    _extract_paper_url,
    _extract_tldr,
    _extract_venue,
    _extract_year,
    _map_publication_type,
)

SAMPLE_RECORD = {
    "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
    "title": "Attention Is All You Need",
    "abstract": "The dominant sequence transduction models...",
    "year": 2017,
    "publicationDate": "2017-06-12",
    "venue": "Neural Information Processing Systems",
    "publicationVenue": {
        "id": "12345",
        "name": "Neural Information Processing Systems",
        "type": "conference",
    },
    "publicationTypes": ["JournalArticle", "Conference"],
    "authors": [
        {"authorId": "1", "name": "Ashish Vaswani"},
        {"authorId": "2", "name": "Noam Shazeer"},
    ],
    "externalIds": {
        "ArXiv": "1706.03762",
        "DBLP": "conf/nips/VaswaniSPUJGKP17",
        "MAG": "2963403868",
        "DOI": "10.5555/3295222.3295349",
        "CorpusId": 13756489,
    },
    "tldr": {
        "model": "tldr@v2.0.0",
        "text": "A new simple network architecture based solely on attention mechanisms.",
    },
    "openAccessPdf": {
        "url": "https://arxiv.org/pdf/1706.03762.pdf",
        "status": "GREEN",
    },
    "url": "https://www.semanticscholar.org/paper/649def34",
}

SAMPLE_SEARCH_RESPONSE = {
    "total": 1,
    "offset": 0,
    "data": [SAMPLE_RECORD],
}


@pytest.fixture
def source() -> SemanticScholarSource:
    """A SemanticScholarSource with rate limiting disabled for fast tests."""
    config = SourceConfig(
        name="semantic_scholar",
        rate_limit_per_second=0.0,
        max_retries=1,
        timeout_seconds=5.0,
    )
    return SemanticScholarSource(config=config, api_key=None)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def test_extract_authors_returns_names() -> None:
    assert _extract_authors(SAMPLE_RECORD) == ["Ashish Vaswani", "Noam Shazeer"]


def test_extract_authors_handles_missing() -> None:
    assert _extract_authors({}) == []


def test_extract_year_uses_year_field() -> None:
    assert _extract_year(SAMPLE_RECORD) == 2017


def test_extract_year_falls_back_to_date() -> None:
    assert _extract_year({"publicationDate": "2024-01-15"}) == 2024


def test_extract_year_returns_none_when_absent() -> None:
    assert _extract_year({}) is None


def test_extract_venue_prefers_publication_venue_name() -> None:
    assert _extract_venue(SAMPLE_RECORD) == "Neural Information Processing Systems"


def test_extract_venue_falls_back_to_venue() -> None:
    assert _extract_venue({"venue": "Nature"}) == "Nature"


def test_extract_venue_empty_when_missing() -> None:
    assert _extract_venue({}) == ""


def test_map_publication_type_journal() -> None:
    assert _map_publication_type({"publicationTypes": ["JournalArticle"]}) == "journal"


def test_map_publication_type_conference() -> None:
    assert _map_publication_type({"publicationTypes": ["Conference"]}) == "conference"


def test_map_publication_type_preprint() -> None:
    assert _map_publication_type({"publicationTypes": ["Preprint"]}) == "preprint"


def test_extract_external_ids_lowercases_keys() -> None:
    ext = _extract_external_ids(SAMPLE_RECORD)
    assert ext["doi"] == "10.5555/3295222.3295349"
    assert ext["arxiv"] == "1706.03762"


def test_extract_tldr_returns_text() -> None:
    assert _extract_tldr(SAMPLE_RECORD).startswith("A new simple network")


def test_extract_tldr_returns_none_when_absent() -> None:
    assert _extract_tldr({}) is None


def test_extract_paper_url_prefers_open_access_pdf() -> None:
    assert _extract_paper_url(SAMPLE_RECORD) == "https://arxiv.org/pdf/1706.03762.pdf"


def test_extract_paper_url_falls_back_to_url() -> None:
    record = {"url": "https://example.com/paper"}
    assert _extract_paper_url(record) == "https://example.com/paper"


# ----------------------------------------------------------------------
# _record_to_paper
# ----------------------------------------------------------------------


def test_record_to_paper_full(source: SemanticScholarSource) -> None:
    """A full S2 record converts to a Paper with all fields filled."""
    paper = source._record_to_paper(SAMPLE_RECORD)
    assert paper.s2_id == "649def34f8be52c8b66281af98ae884c09aef38b"
    assert paper.doi == "10.5555/3295222.3295349"
    assert paper.arxiv_id == "1706.03762"
    assert paper.title == "Attention Is All You Need"
    assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper.year == 2017
    assert paper.venue == "Neural Information Processing Systems"
    assert paper.publication_type == "journal"  # JournalArticle picked up first
    assert paper.source == "semantic_scholar"
    assert paper.ai_summary and "attention mechanisms" in paper.ai_summary
    assert paper.paper_url.endswith(".pdf")


# ----------------------------------------------------------------------
# search (mocked HTTP)
# ----------------------------------------------------------------------


def test_search_parses_results(source: SemanticScholarSource) -> None:
    with patch.object(source, "_get", return_value=SAMPLE_SEARCH_RESPONSE):
        papers = list(source.search("attention", max_results=10))
    assert len(papers) == 1
    assert papers[0].title == "Attention Is All You Need"


def test_search_handles_empty(source: SemanticScholarSource) -> None:
    with patch.object(source, "_get", return_value={"total": 0, "data": []}):
        papers = list(source.search("nothing", max_results=10))
    assert papers == []


def test_search_respects_max_results(source: SemanticScholarSource) -> None:
    with patch.object(source, "_get", return_value=SAMPLE_SEARCH_RESPONSE):
        papers = list(source.search("test", max_results=1))
    assert len(papers) == 1


# ----------------------------------------------------------------------
# fetch_by_id
# ----------------------------------------------------------------------


def test_fetch_by_id_returns_paper(source: SemanticScholarSource) -> None:
    with patch.object(source, "_get", return_value=SAMPLE_RECORD):
        paper = source.fetch_by_id("ARXIV:1706.03762")
    assert paper is not None
    assert paper.arxiv_id == "1706.03762"


def test_fetch_by_id_returns_none_on_404(source: SemanticScholarSource) -> None:
    request = httpx.Request("GET", "https://api.semanticscholar.org/x")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    with patch.object(source, "_get", side_effect=error):
        paper = source.fetch_by_id("DOI:10.invalid/x")
    assert paper is None


# ----------------------------------------------------------------------
# Headers / API key
# ----------------------------------------------------------------------


def test_headers_omit_api_key_when_none() -> None:
    src = SemanticScholarSource(
        config=SourceConfig(
            name="semantic_scholar",
            rate_limit_per_second=0.0,
            max_retries=1,
            timeout_seconds=5.0,
        ),
        api_key=None,
    )
    headers = src._common_headers()
    assert "x-api-key" not in headers


def test_headers_include_api_key_when_set() -> None:
    src = SemanticScholarSource(
        config=SourceConfig(
            name="semantic_scholar",
            rate_limit_per_second=0.0,
            max_retries=1,
            timeout_seconds=5.0,
        ),
        api_key="test-key",
    )
    headers = src._common_headers()
    assert headers["x-api-key"] == "test-key"
