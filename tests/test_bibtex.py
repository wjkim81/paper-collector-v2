"""Tests for the BibTeX enrichment module.

These tests do not hit the live CrossRef API. Network tests live in
`tests/integration/` and are opted in via the `integration` marker.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from paper_collector.core.paper import Paper
from paper_collector.enrich.bibtex import (
    BibTeXError,
    _normalize_doi,
    doi_to_bibtex,
    paper_to_bibtex,
    papers_to_bibfile,
)

SAMPLE_BIBTEX = (
    "@article{Jumper_2021,\n"
    "  title={Highly accurate protein structure prediction with AlphaFold},\n"
    "  author={Jumper, John and Evans, Richard},\n"
    "  journal={Nature},\n"
    "  year={2021},\n"
    "}"
)


# ----------------------------------------------------------------------
# _normalize_doi
# ----------------------------------------------------------------------


def test_normalize_doi_strips_https_prefix() -> None:
    """The https://doi.org/ prefix is stripped."""
    assert (
        _normalize_doi("https://doi.org/10.1038/s41586-021-03819-2")
        == "10.1038/s41586-021-03819-2"
    )


def test_normalize_doi_strips_doi_prefix() -> None:
    """The doi: prefix is stripped (case insensitive)."""
    assert _normalize_doi("doi:10.1234/foo") == "10.1234/foo"
    assert _normalize_doi("DOI:10.1234/foo") == "10.1234/foo"


def test_normalize_doi_leaves_bare_doi_unchanged() -> None:
    """A bare DOI is returned as-is (trimmed)."""
    assert _normalize_doi("  10.1234/foo  ") == "10.1234/foo"


# ----------------------------------------------------------------------
# doi_to_bibtex (mocked)
# ----------------------------------------------------------------------


def _mock_response(text: str = "", status: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://doi.org/test")
    return httpx.Response(status, request=request, text=text)


def test_doi_to_bibtex_returns_text_on_success() -> None:
    """A 200 with BibTeX body is returned with a trailing newline."""
    with patch("paper_collector.enrich.bibtex.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response(SAMPLE_BIBTEX, 200)
        result = doi_to_bibtex("10.1038/s41586-021-03819-2")
    assert "@article{Jumper_2021" in result
    assert result.endswith("\n")


def test_doi_to_bibtex_raises_on_404() -> None:
    """A 404 raises BibTeXError."""
    with patch("paper_collector.enrich.bibtex.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response("", 404)
        with pytest.raises(BibTeXError, match="DOI not found"):
            doi_to_bibtex("10.invalid/nothing")


def test_doi_to_bibtex_raises_on_empty_body() -> None:
    """A 200 with non-BibTeX body raises BibTeXError."""
    with patch("paper_collector.enrich.bibtex.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response("not bibtex", 200)
        with pytest.raises(BibTeXError, match="no BibTeX"):
            doi_to_bibtex("10.1234/foo")


# ----------------------------------------------------------------------
# paper_to_bibtex
# ----------------------------------------------------------------------


def test_paper_to_bibtex_uses_doi_when_present() -> None:
    """When the Paper has a DOI, it is used directly."""
    paper = Paper(doi="10.1038/s41586-021-03819-2", title="Test")
    with patch(
        "paper_collector.enrich.bibtex.doi_to_bibtex",
        return_value=SAMPLE_BIBTEX + "\n",
    ) as mock_d2b:
        result = paper_to_bibtex(paper)
    mock_d2b.assert_called_once_with("10.1038/s41586-021-03819-2")
    assert "@article" in result


def test_paper_to_bibtex_falls_back_to_arxiv_shadow() -> None:
    """When the Paper has no DOI but an arXiv ID, the shadow DOI is tried."""
    paper = Paper(arxiv_id="2307.06207v2", title="LCNF")
    with patch(
        "paper_collector.enrich.bibtex.doi_to_bibtex",
        return_value=SAMPLE_BIBTEX + "\n",
    ) as mock_d2b:
        result = paper_to_bibtex(paper)
    # Version stripped from arxiv_id.
    mock_d2b.assert_called_once_with("10.48550/arXiv.2307.06207")
    assert "@article" in result


def test_paper_to_bibtex_raises_when_no_identifier() -> None:
    """A Paper with neither DOI nor arXiv ID cannot be exported."""
    paper = Paper(title="Lonely Paper")
    with pytest.raises(BibTeXError, match="no DOI and no arXiv ID"):
        paper_to_bibtex(paper)


def test_paper_to_bibtex_propagates_shadow_failure() -> None:
    """If the arXiv shadow DOI cannot be resolved, raise BibTeXError."""
    paper = Paper(arxiv_id="0000.00000", title="Fake")
    with (
        patch(
            "paper_collector.enrich.bibtex.doi_to_bibtex",
            side_effect=BibTeXError("not found"),
        ),
        pytest.raises(BibTeXError, match="arXiv shadow DOI"),
    ):
        paper_to_bibtex(paper)


# ----------------------------------------------------------------------
# papers_to_bibfile
# ----------------------------------------------------------------------


def test_papers_to_bibfile_writes_entries(tmp_path: Path) -> None:
    """papers_to_bibfile writes entries and returns success count."""
    papers = [
        Paper(doi="10.1/foo", title="A"),
        Paper(doi="10.2/bar", title="B"),
    ]
    out = tmp_path / "refs.bib"
    with patch(
        "paper_collector.enrich.bibtex.doi_to_bibtex",
        side_effect=["@article{A}\n", "@article{B}\n"],
    ):
        written, failures = papers_to_bibfile(papers, out)
    assert written == 2
    assert failures == []
    content = out.read_text(encoding="utf-8")
    assert "@article{A}" in content
    assert "@article{B}" in content


def test_papers_to_bibfile_skips_failures_by_default(tmp_path: Path) -> None:
    """Failures are collected, not raised, when skip_failures=True."""
    papers = [
        Paper(doi="10.1/good", title="A"),
        Paper(title="No ID"),
        Paper(doi="10.2/bad", title="C"),
    ]
    out = tmp_path / "refs.bib"

    def side(doi: str) -> str:
        if doi == "10.2/bad":
            raise BibTeXError("not found")
        return f"@article{{{doi}}}\n"

    with patch("paper_collector.enrich.bibtex.doi_to_bibtex", side_effect=side):
        written, failures = papers_to_bibfile(papers, out)

    assert written == 1
    assert len(failures) == 2  # the no-ID paper and the bad-DOI paper


def test_papers_to_bibfile_raises_when_skip_failures_false(
    tmp_path: Path,
) -> None:
    """skip_failures=False propagates the first failure."""
    papers = [Paper(title="No ID")]
    out = tmp_path / "refs.bib"
    with pytest.raises(BibTeXError):
        papers_to_bibfile(papers, out, skip_failures=False)
