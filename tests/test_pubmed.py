"""Tests for the PubMed source.

These tests do not hit the live NCBI API. Network tests live in
`tests/integration/` and are opted in via the `integration` marker.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from paper_collector.sources.base import SourceConfig
from paper_collector.sources.pubmed import (
    PubMedSource,
    _extract_authors,
    _extract_doi,
    _extract_pmcid,
    _extract_year,
    _map_publication_type,
)

SAMPLE_ESEARCH_RESPONSE = {
    "esearchresult": {
        "count": "2",
        "retmax": "2",
        "retstart": "0",
        "idlist": ["33887189", "29950172"],
    }
}

SAMPLE_RECORD = {
    "uid": "33887189",
    "pubdate": "2021 Apr 22",
    "epubdate": "2021 Apr 22",
    "source": "Nat Methods",
    "authors": [
        {"name": "Jumper J", "authtype": "Author"},
        {"name": "Evans R", "authtype": "Author"},
    ],
    "title": "Highly accurate protein structure prediction with AlphaFold.",
    "volume": "596",
    "issue": "7873",
    "pages": "583-589",
    "fulljournalname": "Nature",
    "pubtype": ["Journal Article", "Research Support, Non-U.S. Gov't"],
    "articleids": [
        {"idtype": "pubmed", "value": "33887189"},
        {"idtype": "doi", "value": "10.1038/s41586-021-03819-2"},
        {"idtype": "pmc", "value": "PMC8371605"},
    ],
}

SAMPLE_ESUMMARY_RESPONSE = {
    "result": {
        "uids": ["33887189"],
        "33887189": SAMPLE_RECORD,
    }
}


@pytest.fixture
def source() -> PubMedSource:
    """A PubMedSource with rate limiting disabled for fast tests."""
    config = SourceConfig(
        name="pubmed",
        rate_limit_per_second=0.0,
        max_retries=1,
        timeout_seconds=5.0,
    )
    return PubMedSource(config=config, api_key=None)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def test_extract_authors_returns_names() -> None:
    """Author names are extracted from the authors list."""
    assert _extract_authors(SAMPLE_RECORD) == ["Jumper J", "Evans R"]


def test_extract_authors_handles_missing() -> None:
    """An empty record returns no authors."""
    assert _extract_authors({}) == []


def test_extract_year_parses_full_pubdate() -> None:
    """Year is parsed from 'YYYY Mon DD' format."""
    assert _extract_year({"pubdate": "2021 Apr 22"}) == 2021


def test_extract_year_parses_year_only() -> None:
    """Year is parsed when only year is present."""
    assert _extract_year({"pubdate": "2024"}) == 2024


def test_extract_year_returns_none_when_invalid() -> None:
    """Non-numeric pubdate returns None."""
    assert _extract_year({"pubdate": "no date"}) is None


def test_extract_year_returns_none_when_missing() -> None:
    """Missing pubdate returns None."""
    assert _extract_year({}) is None


def test_extract_doi_finds_doi() -> None:
    """DOI is extracted from the articleids list."""
    assert _extract_doi(SAMPLE_RECORD) == "10.1038/s41586-021-03819-2"


def test_extract_doi_returns_none_when_missing() -> None:
    """No DOI returns None."""
    assert _extract_doi({}) is None
    assert _extract_doi({"articleids": []}) is None


def test_extract_pmcid_finds_pmc() -> None:
    """PMC ID is extracted from articleids."""
    assert _extract_pmcid(SAMPLE_RECORD) == "PMC8371605"


def test_map_publication_type_journal() -> None:
    """Journal Article maps to 'journal'."""
    record = {"pubtype": ["Journal Article"]}
    assert _map_publication_type(record) == "journal"


def test_map_publication_type_preprint() -> None:
    """Preprint maps to 'preprint'."""
    record = {"pubtype": ["Preprint"]}
    assert _map_publication_type(record) == "preprint"


def test_map_publication_type_default() -> None:
    """Empty pubtype defaults to 'journal' (PubMed is mostly journals)."""
    assert _map_publication_type({"pubtype": []}) == "journal"


# ----------------------------------------------------------------------
# _record_to_paper
# ----------------------------------------------------------------------


def test_record_to_paper_full(source: PubMedSource) -> None:
    """A full ESummary record converts to a Paper with all fields."""
    paper = source._record_to_paper("33887189", SAMPLE_RECORD)
    assert paper.pubmed_id == "33887189"
    assert paper.doi == "10.1038/s41586-021-03819-2"
    assert "AlphaFold" in paper.title
    assert paper.authors == ["Jumper J", "Evans R"]
    assert paper.year == 2021
    assert paper.venue == "Nature"
    assert paper.publication_type == "journal"
    assert paper.paper_url == "https://pubmed.ncbi.nlm.nih.gov/33887189/"
    assert paper.official_url == "https://doi.org/10.1038/s41586-021-03819-2"
    assert paper.source == "pubmed"
    assert paper.source_raw is not None


# ----------------------------------------------------------------------
# search (mocked HTTP)
# ----------------------------------------------------------------------


def test_search_two_step_workflow(source: PubMedSource) -> None:
    """A search invokes esearch then esummary and returns Papers."""

    def fake_get(url: str, params: dict) -> dict:
        if "esearch.fcgi" in url:
            return SAMPLE_ESEARCH_RESPONSE
        if "esummary.fcgi" in url:
            return SAMPLE_ESUMMARY_RESPONSE
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(source, "_get", side_effect=fake_get):
        papers = list(source.search("alphafold", max_results=10))

    # esearch returned 2 ids; esummary mock only contains 1 record (33887189).
    # The other is omitted because no record is present.
    assert len(papers) == 1
    assert papers[0].pubmed_id == "33887189"


def test_search_handles_empty_esearch(source: PubMedSource) -> None:
    """An empty esearch result yields no papers and skips esummary."""
    empty = {"esearchresult": {"idlist": []}}
    with patch.object(source, "_get", return_value=empty) as mock_get:
        papers = list(source.search("nothing matches", max_results=10))
    assert papers == []
    # Only one call (esearch), no esummary.
    assert mock_get.call_count == 1


# ----------------------------------------------------------------------
# fetch_by_id
# ----------------------------------------------------------------------


def test_fetch_by_id_returns_paper(source: PubMedSource) -> None:
    """fetch_by_id calls esummary directly and returns a Paper."""
    with patch.object(source, "_get", return_value=SAMPLE_ESUMMARY_RESPONSE):
        paper = source.fetch_by_id("33887189")
    assert paper is not None
    assert paper.pubmed_id == "33887189"
    assert "AlphaFold" in paper.title


def test_fetch_by_id_returns_none_when_missing(source: PubMedSource) -> None:
    """fetch_by_id returns None when no record is present."""
    empty = {"result": {"uids": []}}
    with patch.object(source, "_get", return_value=empty):
        paper = source.fetch_by_id("00000000")
    assert paper is None


# ----------------------------------------------------------------------
# API key behavior
# ----------------------------------------------------------------------


def test_common_params_includes_api_key_when_set() -> None:
    """api_key is included in params when configured."""
    src = PubMedSource(
        config=SourceConfig(
            name="pubmed", rate_limit_per_second=0.0, max_retries=1, timeout_seconds=5.0
        ),
        api_key="test-key-xyz",
    )
    params = src._common_params()
    assert params["api_key"] == "test-key-xyz"
    assert params["tool"] == "paper-collector-v2"


def test_common_params_omits_api_key_when_none() -> None:
    """api_key is omitted from params when not configured."""
    src = PubMedSource(
        config=SourceConfig(
            name="pubmed", rate_limit_per_second=0.0, max_retries=1, timeout_seconds=5.0
        ),
        api_key=None,
    )
    params = src._common_params()
    assert "api_key" not in params
