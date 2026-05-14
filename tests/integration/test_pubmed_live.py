"""Integration tests for the PubMed source.

These tests hit the live NCBI E-utilities API. They are slow and
require network. Run with:

    uv run pytest tests/integration/test_pubmed_live.py -v -m integration
"""

from __future__ import annotations

import pytest

from paper_collector.sources.pubmed import PubMedSource

pytestmark = pytest.mark.integration


# AlphaFold paper PMID — Jumper et al. Nature 2021.
# https://pubmed.ncbi.nlm.nih.gov/34265844/
ALPHAFOLD_PMID = "34265844"


def test_live_search_returns_results() -> None:
    """A live search for a well-known query returns at least one paper."""
    source = PubMedSource()
    papers = list(source.search("alphafold protein structure", max_results=3))
    assert len(papers) >= 1
    for p in papers:
        assert p.source == "pubmed"
        assert p.title
        assert p.pubmed_id


def test_live_fetch_by_id_returns_paper() -> None:
    """Fetching by a known PMID returns the corresponding paper."""
    source = PubMedSource()
    paper = source.fetch_by_id(ALPHAFOLD_PMID)
    assert paper is not None
    assert paper.pubmed_id == ALPHAFOLD_PMID
    assert "AlphaFold" in paper.title
    assert paper.year == 2021
    assert paper.doi == "10.1038/s41586-021-03819-2"
