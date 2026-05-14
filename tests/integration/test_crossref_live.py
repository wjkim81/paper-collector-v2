"""Integration tests for CrossRef enrichment.

These tests hit the live CrossRef API. They are slow and require network.
Run with: uv run pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import pytest

from paper_collector.core.paper import Paper
from paper_collector.enrich.bibtex import doi_to_bibtex, paper_to_bibtex
from paper_collector.enrich.metadata import doi_to_csl_json, enrich_paper

pytestmark = pytest.mark.integration


# A famously stable DOI: AlphaFold paper in Nature.
ALPHAFOLD_DOI = "10.1038/s41586-021-03819-2"


def test_live_doi_to_bibtex_returns_valid_entry() -> None:
    """A known DOI returns a parseable BibTeX entry."""
    bibtex = doi_to_bibtex(ALPHAFOLD_DOI)
    assert bibtex.startswith("@")
    assert "AlphaFold" in bibtex
    assert "Jumper" in bibtex


def test_live_doi_to_csl_json_returns_metadata() -> None:
    """A known DOI returns CSL JSON with expected fields."""
    data = doi_to_csl_json(ALPHAFOLD_DOI)
    assert "title" in data
    assert "author" in data
    assert any("Jumper" in (a.get("family") or "") for a in data["author"])


def test_live_arxiv_shadow_doi_via_paper() -> None:
    """An arXiv-only Paper can be exported via the shadow DOI."""
    paper = Paper(arxiv_id="1706.03762", title="Attention Is All You Need")
    bibtex = paper_to_bibtex(paper)
    assert bibtex.startswith("@")


def test_live_enrich_paper_fills_metadata() -> None:
    """enrich_paper fills empty fields for a real DOI."""
    paper = Paper(doi=ALPHAFOLD_DOI)
    enriched = enrich_paper(paper)
    assert enriched.title and "AlphaFold" in enriched.title
    assert enriched.year == 2021
    assert enriched.venue  # Nature
    assert enriched.authors  # at least one
