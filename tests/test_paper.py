"""Tests for the Paper dataclass."""

from __future__ import annotations

import pytest

from paper_collector.core.paper import Paper


def test_paper_minimal() -> None:
    """Paper can be created with just a title."""
    p = Paper(title="Attention Is All You Need")
    assert p.title == "Attention Is All You Need"
    assert p.doi is None
    assert p.authors == []
    assert p.source_raw is None


def test_paper_with_all_fields() -> None:
    """All Paper fields are settable."""
    p = Paper(
        doi="10.1234/example",
        arxiv_id="2307.06207",
        title="Test Paper",
        authors=["Alice", "Bob"],
        abstract="Lorem ipsum.",
        year=2024,
        venue="Nature",
        publication_type="journal",
        keywords=["ai", "ml"],
        paper_url="https://arxiv.org/abs/2307.06207",
        official_url="https://doi.org/10.1234/example",
        source="arxiv",
        source_raw={"raw": "response"},
        ai_relevance_score=0.9,
        ai_summary="A summary.",
    )
    assert p.doi == "10.1234/example"
    assert p.authors == ["Alice", "Bob"]
    assert p.ai_relevance_score == 0.9


def test_primary_id_prefers_doi() -> None:
    """primary_id returns DOI when available, lowercased."""
    p = Paper(
        doi="10.1234/Example",
        arxiv_id="2107.12345",
        pubmed_id="123456",
        title="Test",
    )
    assert p.primary_id() == "doi:10.1234/example"


def test_primary_id_falls_back_to_arxiv() -> None:
    """primary_id falls back to arxiv_id when no DOI."""
    p = Paper(arxiv_id="2107.12345", pubmed_id="123456", title="Test")
    assert p.primary_id() == "arxiv:2107.12345"


def test_primary_id_falls_back_to_pubmed() -> None:
    """primary_id falls back to pubmed_id when no DOI or arXiv."""
    p = Paper(pubmed_id="123456", title="Test")
    assert p.primary_id() == "pmid:123456"


def test_primary_id_falls_back_to_normalized_title() -> None:
    """primary_id falls back to normalized title (collapsed whitespace)."""
    p = Paper(title="  Test   Paper  ")
    assert p.primary_id() == "title:test paper"


def test_primary_id_raises_without_identifier_or_title() -> None:
    """primary_id raises if Paper has neither identifier nor title."""
    p = Paper()
    with pytest.raises(ValueError, match="no identifier and no title"):
        p.primary_id()
