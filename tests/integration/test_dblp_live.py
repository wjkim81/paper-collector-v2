"""Integration tests for the DBLP source.

These tests hit the live DBLP API. They are slow and require network.
Run with: uv run pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import pytest

from paper_collector.sources.dblp import DBLPSource

pytestmark = pytest.mark.integration


def test_live_search_returns_results() -> None:
    """A live search for a well-known query returns at least one paper."""
    source = DBLPSource()
    papers = list(source.search("attention is all you need", max_results=3))
    assert len(papers) >= 1
    for p in papers:
        assert p.source == "dblp"
        assert p.title
        assert p.dblp_key


@pytest.mark.skip(reason="fetch_by_id not yet implemented for DBLP — see dblp.py TODO")
def test_live_fetch_by_id_returns_paper() -> None:
    """Fetching by a known DBLP key returns the corresponding paper.

    Skipped until fetch_by_id is reimplemented against the XML endpoint
    or the SPARQL service. The search API doesn't support literal key
    lookup and the JSON per-record endpoint doesn't exist.
    """
    source = DBLPSource()
    paper = source.fetch_by_id("conf/nips/VaswaniSPUJGKP17")
    assert paper is not None
    assert "Attention" in paper.title
    assert paper.year == 2017
