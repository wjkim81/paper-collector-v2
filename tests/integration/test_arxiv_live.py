"""Integration tests for the arXiv source.

These tests hit the live arXiv API. They are slow and require a network
connection. To run them:

    uv run pytest tests/integration/ -v -m integration

They are skipped by default in the regular test run.
"""

from __future__ import annotations

import pytest

from paper_collector.sources.arxiv import ArxivSource

pytestmark = pytest.mark.integration


def test_live_search_returns_results() -> None:
    """A live search for a well-known term returns at least one paper."""
    source = ArxivSource()
    papers = list(source.search("attention is all you need", max_results=3))
    assert len(papers) >= 1
    for p in papers:
        assert p.source == "arxiv"
        assert p.title
        assert p.arxiv_id


def test_live_fetch_by_id_returns_paper() -> None:
    """Fetching a known arXiv ID returns the corresponding paper."""
    source = ArxivSource()
    paper = source.fetch_by_id("2307.06207")
    assert paper is not None
    assert paper.arxiv_id.startswith("2307.06207")
    assert "Neural Fields" in paper.title or "LCNF" in paper.title.upper()
