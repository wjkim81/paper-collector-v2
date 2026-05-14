"""Integration tests for Semantic Scholar source.

These hit the live S2 API and may be rate-limited without an API key.
"""

from __future__ import annotations

import pytest

from paper_collector.sources.semantic_scholar import SemanticScholarSource

pytestmark = pytest.mark.integration


def test_live_fetch_by_arxiv_id() -> None:
    """Fetch the LCNF paper by arXiv ID prefix."""
    source = SemanticScholarSource()
    paper = source.fetch_by_id("ARXIV:2307.06207")
    assert paper is not None
    assert "Neural Fields" in paper.title or "LCNF" in paper.title.upper()
    assert paper.arxiv_id == "2307.06207"


def test_live_fetch_by_doi() -> None:
    """Fetch the AlphaFold paper by DOI prefix."""
    source = SemanticScholarSource()
    paper = source.fetch_by_id("DOI:10.1038/s41586-021-03819-2")
    assert paper is not None
    assert "AlphaFold" in paper.title
    assert paper.year == 2021


def test_live_search_returns_results() -> None:
    """A live search returns at least one paper with a TLDR."""
    source = SemanticScholarSource()
    papers = list(source.search("attention is all you need", max_results=3))
    assert len(papers) >= 1
    # Some of the top results should have TLDRs.
    assert any(p.ai_summary for p in papers)
