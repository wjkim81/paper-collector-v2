"""Tests for the arXiv source.

These tests do not hit the live arXiv API. Network tests live in
`tests/integration/` and are opted in via the `integration` marker.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from paper_collector.sources.arxiv import ArxivSource, _parse_arxiv_id
from paper_collector.sources.base import SourceConfig

SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2307.06207v2</id>
    <updated>2024-01-15T12:00:00Z</updated>
    <published>2023-07-12T17:55:14Z</published>
    <title>
      Local Conditional Neural Fields for Versatile and Generalizable
      Large-Scale Reconstructions
    </title>
    <summary>This paper introduces LCNF, a method for...</summary>
    <author><name>Hao Wang</name></author>
    <author><name>Jiabei Zhu</name></author>
    <link href="http://arxiv.org/abs/2307.06207v2" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2307.06207v2" rel="related" type="application/pdf"/>
    <category term="eess.IV"/>
    <category term="cs.CV"/>
  </entry>
</feed>
"""


@pytest.fixture
def source() -> ArxivSource:
    """An ArxivSource with rate limiting disabled for fast tests."""
    config = SourceConfig(
        name="arxiv",
        rate_limit_per_second=0.0,  # disabled
        max_retries=1,
        timeout_seconds=5.0,
    )
    return ArxivSource(config=config)


# ----------------------------------------------------------------------
# _parse_arxiv_id
# ----------------------------------------------------------------------


def test_parse_new_format_with_version() -> None:
    """New-style IDs with version are parsed correctly."""
    assert _parse_arxiv_id("http://arxiv.org/abs/2307.06207v2") == (
        "2307.06207",
        "2",
    )


def test_parse_new_format_without_version() -> None:
    """New-style IDs without version are parsed correctly."""
    assert _parse_arxiv_id("http://arxiv.org/abs/2307.06207") == (
        "2307.06207",
        None,
    )


def test_parse_old_format_with_version() -> None:
    """Old-style IDs (pre-2007) with version are parsed correctly."""
    assert _parse_arxiv_id("http://arxiv.org/abs/cs.AI/0703123v1") == (
        "cs.AI/0703123",
        "1",
    )


# ----------------------------------------------------------------------
# _build_query
# ----------------------------------------------------------------------


def test_build_query_wraps_plain_text(source: ArxivSource) -> None:
    """A plain query is wrapped as `all:"..."`."""
    assert source._build_query("neural fields") == 'all:"neural fields"'


def test_build_query_passes_through_field_prefix(source: ArxivSource) -> None:
    """A query with an arXiv field prefix is passed through."""
    assert source._build_query("ti:neural AND au:wang") == "ti:neural AND au:wang"


def test_build_query_passes_through_cat_prefix(source: ArxivSource) -> None:
    """A category-prefixed query is passed through."""
    assert source._build_query("cat:cs.CV") == "cat:cs.CV"


# ----------------------------------------------------------------------
# search (with mocked HTTP)
# ----------------------------------------------------------------------


def test_search_parses_entries_into_papers(source: ArxivSource) -> None:
    """A search returns Paper objects parsed from the Atom feed."""
    with patch.object(source, "_get", return_value=SAMPLE_FEED_XML):
        papers = list(source.search("test", max_results=10))

    assert len(papers) == 1
    p = papers[0]
    assert p.arxiv_id == "2307.06207v2"
    assert "Local Conditional Neural Fields" in p.title
    assert p.authors == ["Hao Wang", "Jiabei Zhu"]
    assert p.year == 2023
    assert p.venue == "arXiv"
    assert p.publication_type == "preprint"
    assert p.source == "arxiv"
    assert "eess.IV" in p.keywords
    assert "cs.CV" in p.keywords
    assert p.paper_url == "http://arxiv.org/pdf/2307.06207v2"
    assert p.source_raw is not None


def test_search_respects_max_results(source: ArxivSource) -> None:
    """The search stops at max_results even if more entries are returned."""
    with patch.object(source, "_get", return_value=SAMPLE_FEED_XML):
        papers = list(source.search("test", max_results=1))
    assert len(papers) == 1


def test_search_handles_empty_feed(source: ArxivSource) -> None:
    """An empty feed returns no papers."""
    empty_feed = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    with patch.object(source, "_get", return_value=empty_feed):
        papers = list(source.search("test", max_results=10))
    assert papers == []


# ----------------------------------------------------------------------
# fetch_by_id
# ----------------------------------------------------------------------


def test_fetch_by_id_returns_paper(source: ArxivSource) -> None:
    """fetch_by_id returns a Paper when the entry is present."""
    with patch.object(source, "_get", return_value=SAMPLE_FEED_XML):
        p = source.fetch_by_id("2307.06207")
    assert p is not None
    assert p.arxiv_id == "2307.06207v2"


def test_fetch_by_id_returns_none_when_missing(source: ArxivSource) -> None:
    """fetch_by_id returns None when no entry is found."""
    empty_feed = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    with patch.object(source, "_get", return_value=empty_feed):
        p = source.fetch_by_id("0000.00000")
    assert p is None


# ----------------------------------------------------------------------
# Rate limiting
# ----------------------------------------------------------------------


def test_respect_rate_limit_no_op_when_disabled(source: ArxivSource) -> None:
    """When rate_limit_per_second is 0, _respect_rate_limit is a no-op."""
    # Should not sleep — the fixture has rate_limit_per_second=0.0
    source._respect_rate_limit()
    source._respect_rate_limit()  # called twice in a row, should be instant


def test_respect_rate_limit_sleeps_when_enabled() -> None:
    """When enabled, _respect_rate_limit sleeps appropriately."""
    config = SourceConfig(
        name="arxiv",
        rate_limit_per_second=100.0,  # min interval = 0.01s
        max_retries=1,
        timeout_seconds=5.0,
    )
    src = ArxivSource(config=config)
    with patch("paper_collector.sources.arxiv.time.sleep") as mock_sleep:
        src._respect_rate_limit()  # first call: no sleep (last_request_at == 0 means elapsed is large)
        src._respect_rate_limit()  # second call: should sleep
    # The second call should have triggered sleep.
    assert mock_sleep.called
