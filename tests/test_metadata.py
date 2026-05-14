"""Tests for the metadata enrichment module."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from paper_collector.core.paper import Paper
from paper_collector.enrich.metadata import (
    MetadataError,
    _extract_authors,
    _extract_year,
    _merge_csl_into_paper,
    doi_to_csl_json,
    enrich_paper,
)

SAMPLE_CSL: dict = {
    "DOI": "10.1038/s41586-021-03819-2",
    "title": "Highly accurate protein structure prediction with AlphaFold",
    "container-title": "Nature",
    "publisher": "Springer Science and Business Media LLC",
    "type": "journal-article",
    "issued": {"date-parts": [[2021, 7, 15]]},
    "author": [
        {"given": "John", "family": "Jumper"},
        {"given": "Richard", "family": "Evans"},
    ],
    "URL": "http://dx.doi.org/10.1038/s41586-021-03819-2",
}


def _mock_response(json_body: dict | None = None, status: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://doi.org/test")
    if json_body is not None:
        return httpx.Response(status, request=request, json=json_body)
    return httpx.Response(status, request=request)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def test_extract_authors_combines_given_and_family() -> None:
    """Author names are combined as 'given family'."""
    csl = {
        "author": [
            {"given": "John", "family": "Jumper"},
            {"given": "Richard", "family": "Evans"},
        ]
    }
    assert _extract_authors(csl) == ["John Jumper", "Richard Evans"]


def test_extract_authors_handles_literal() -> None:
    """A literal author entry is preserved."""
    csl = {"author": [{"literal": "The OpenAI Team"}]}
    assert _extract_authors(csl) == ["The OpenAI Team"]


def test_extract_authors_handles_missing_given() -> None:
    """An author with only family name is kept."""
    csl = {"author": [{"family": "Smith"}]}
    assert _extract_authors(csl) == ["Smith"]


def test_extract_year_from_issued() -> None:
    """Year is extracted from the `issued` field."""
    csl = {"issued": {"date-parts": [[2024, 3, 15]]}}
    assert _extract_year(csl) == 2024


def test_extract_year_falls_back_to_published_print() -> None:
    """Falls back to published-print when issued is absent."""
    csl = {"published-print": {"date-parts": [[2023]]}}
    assert _extract_year(csl) == 2023


def test_extract_year_returns_none_when_absent() -> None:
    """Returns None if no date fields are present."""
    assert _extract_year({}) is None


# ----------------------------------------------------------------------
# doi_to_csl_json
# ----------------------------------------------------------------------


def test_doi_to_csl_json_returns_dict() -> None:
    """A 200 with JSON body returns the parsed dict."""
    with patch("paper_collector.enrich.metadata.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response(SAMPLE_CSL, 200)
        result = doi_to_csl_json("10.1038/s41586-021-03819-2")
    assert result["title"] == SAMPLE_CSL["title"]


def test_doi_to_csl_json_raises_on_404() -> None:
    """A 404 raises MetadataError."""
    with patch("paper_collector.enrich.metadata.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response(None, 404)
        with pytest.raises(MetadataError, match="DOI not found"):
            doi_to_csl_json("10.invalid/nothing")


# ----------------------------------------------------------------------
# _merge_csl_into_paper
# ----------------------------------------------------------------------


def test_merge_fills_empty_fields() -> None:
    """CrossRef values fill in empty Paper fields."""
    paper = Paper(doi="10.1038/s41586-021-03819-2")  # mostly empty
    merged = _merge_csl_into_paper(paper, SAMPLE_CSL)

    assert "AlphaFold" in merged.title
    assert merged.authors == ["John Jumper", "Richard Evans"]
    assert merged.year == 2021
    assert merged.venue == "Nature"
    assert merged.publication_type == "journal"
    assert merged.official_url == SAMPLE_CSL["URL"]


def test_merge_preserves_existing_values() -> None:
    """Non-empty Paper fields are not overwritten."""
    paper = Paper(
        doi="10.1038/s41586-021-03819-2",
        title="My Custom Title",
        authors=["Alice"],
        year=2020,
        venue="My Venue",
    )
    merged = _merge_csl_into_paper(paper, SAMPLE_CSL)

    assert merged.title == "My Custom Title"
    assert merged.authors == ["Alice"]
    assert merged.year == 2020
    assert merged.venue == "My Venue"
    # But empty fields are still filled.
    assert merged.publication_type == "journal"
    assert merged.official_url == SAMPLE_CSL["URL"]


def test_merge_returns_input_when_no_updates() -> None:
    """If nothing to update, the same Paper object is returned."""
    paper = Paper(
        doi="x",
        title="T",
        authors=["A"],
        year=2024,
        venue="V",
        publication_type="journal",
        official_url="http://example.com",
    )
    merged = _merge_csl_into_paper(paper, SAMPLE_CSL)
    assert merged is paper


# ----------------------------------------------------------------------
# enrich_paper
# ----------------------------------------------------------------------


def test_enrich_paper_without_doi_returns_input() -> None:
    """A Paper with no DOI is returned unchanged."""
    paper = Paper(title="No DOI here")
    enriched = enrich_paper(paper)
    assert enriched is paper


def test_enrich_paper_with_doi_calls_crossref() -> None:
    """A Paper with a DOI gets CrossRef metadata merged in."""
    paper = Paper(doi="10.1038/s41586-021-03819-2")
    with patch(
        "paper_collector.enrich.metadata.doi_to_csl_json",
        return_value=SAMPLE_CSL,
    ):
        enriched = enrich_paper(paper)
    assert "AlphaFold" in enriched.title
    assert enriched.year == 2021


def test_enrich_paper_returns_input_on_metadata_error() -> None:
    """If CrossRef fails, the original Paper is returned unchanged."""
    paper = Paper(doi="10.invalid/nothing", title="Original")
    with patch(
        "paper_collector.enrich.metadata.doi_to_csl_json",
        side_effect=MetadataError("not found"),
    ):
        enriched = enrich_paper(paper)
    assert enriched is paper
    assert enriched.title == "Original"
