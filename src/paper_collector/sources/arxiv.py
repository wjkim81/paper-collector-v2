"""arXiv source implementation.

Uses the arXiv export API (http://export.arxiv.org/api/query) which
returns Atom XML feeds. No authentication required. The conservative
default rate limit is 1 request per 3 seconds, per arXiv's guidelines.

API documentation: https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import feedparser  # type: ignore[import-untyped]
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from paper_collector.core.paper import Paper
from paper_collector.sources.base import BaseSource, SourceConfig

ARXIV_API_URL = "http://export.arxiv.org/api/query"
DEFAULT_RATE_LIMIT = 1.0 / 3.0  # 1 request per 3 seconds (arXiv guideline)


class ArxivSource(BaseSource):
    """Source that searches arXiv via its public export API.

    arXiv requires no authentication. The API returns Atom XML which we
    parse with feedparser. Rate limiting is enforced between requests.

    Example:
        >>> source = ArxivSource()
        >>> for paper in source.search("local conditional neural fields", max_results=5):
        ...     print(paper.title)
    """

    def __init__(self, config: SourceConfig | None = None) -> None:
        """Initialize the arXiv source.

        Args:
            config: Optional source configuration. If None, uses defaults
                appropriate for arXiv (rate limit of 1 req / 3 seconds).
        """
        if config is None:
            config = SourceConfig(
                name="arxiv",
                rate_limit_per_second=DEFAULT_RATE_LIMIT,
                max_retries=3,
                timeout_seconds=30.0,
            )
        super().__init__(config)
        self._last_request_at: float = 0.0

    def search(self, query: str, max_results: int = 100) -> Iterator[Paper]:
        """Search arXiv for papers matching a query.

        Args:
            query: Search query. Uses arXiv search syntax. For free-text
                search across all fields, the caller can pass a plain
                string; it will be wrapped as `all:"<query>"`.
            max_results: Maximum number of results to return.

        Yields:
            Paper objects, one at a time.
        """
        search_query = self._build_query(query)
        self.logger.info(
            "arxiv search: query=%r max_results=%d", search_query, max_results
        )

        # arXiv recommends pages of <= 2000 but we keep them smaller.
        page_size = min(100, max_results)
        start = 0
        returned = 0

        while returned < max_results:
            current_page = min(page_size, max_results - returned)
            entries = self._fetch_page(
                search_query, start=start, page_size=current_page
            )
            if not entries:
                break

            for entry in entries:
                yield self._entry_to_paper(entry)
                returned += 1
                if returned >= max_results:
                    return

            if len(entries) < current_page:
                # No more results to fetch.
                break
            start += current_page

    def fetch_by_id(self, identifier: str) -> Paper | None:
        """Fetch a single arXiv paper by its arXiv ID.

        Args:
            identifier: arXiv ID, e.g., "2307.06207" or "2307.06207v2".
                Old-style IDs like "cs.AI/0703123" are also accepted.

        Returns:
            A Paper if found, None otherwise.
        """
        normalized = identifier.strip()
        self.logger.info("arxiv fetch_by_id: id=%r", normalized)
        entries = self._fetch_page(
            search_query=None, id_list=normalized, start=0, page_size=1
        )
        if not entries:
            return None
        return self._entry_to_paper(entries[0])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_query(self, query: str) -> str:
        """Wrap a plain query as a quoted arXiv `all:` search.

        If the query already contains an arXiv field prefix (e.g.,
        `ti:`, `au:`, `abs:`, `all:`, `cat:`), it is passed through
        unchanged.
        """
        if re.search(r"\b(ti|au|abs|all|cat|jr|rn|id|co):", query):
            return query
        escaped = query.replace('"', '\\"')
        return f'all:"{escaped}"'

    def _fetch_page(
        self,
        search_query: str | None = None,
        id_list: str | None = None,
        start: int = 0,
        page_size: int = 100,
    ) -> list[Any]:
        """Fetch one page of results from arXiv.

        Either `search_query` or `id_list` must be provided.

        Returns:
            List of feedparser entry objects.
        """
        params: dict[str, str | int] = {
            "start": start,
            "max_results": page_size,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        if search_query is not None:
            params["search_query"] = search_query
        if id_list is not None:
            params["id_list"] = id_list

        self._respect_rate_limit()
        response_text = self._get(params)
        feed = feedparser.parse(response_text)
        entries: list[Any] = list(feed.entries)
        self.logger.debug("arxiv fetched %d entries (start=%d)", len(entries), start)
        return entries

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get(self, params: dict[str, Any]) -> str:
        """Issue a GET request to arXiv with retry on transient errors."""
        with httpx.Client(
            timeout=self.config.timeout_seconds, follow_redirects=True
        ) as client:
            response = client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()
            return response.text

    def _respect_rate_limit(self) -> None:
        """Sleep if needed to honor the configured rate limit."""
        if self.config.rate_limit_per_second <= 0:
            return
        min_interval = 1.0 / self.config.rate_limit_per_second
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _entry_to_paper(self, entry: Any) -> Paper:
        """Convert a feedparser entry into a Paper."""
        arxiv_id, version = _parse_arxiv_id(entry.id)
        authors = [a.name for a in getattr(entry, "authors", []) if hasattr(a, "name")]
        categories = [t.term for t in getattr(entry, "tags", []) if hasattr(t, "term")]

        # entry.published is a string like "2023-07-12T17:55:14Z"; year is the first 4 chars
        year: int | None = None
        published = getattr(entry, "published", "")
        if published[:4].isdigit():
            year = int(published[:4])

        # Find PDF link if present; otherwise fall back to entry.link.
        paper_url = ""
        for link in getattr(entry, "links", []):
            if getattr(link, "type", "") == "application/pdf":
                paper_url = link.href
                break
        if not paper_url:
            paper_url = getattr(entry, "link", "")

        # arXiv DOIs are typically minted for the preprint itself.
        doi = getattr(entry, "arxiv_doi", None) or None

        return Paper(
            arxiv_id=f"{arxiv_id}v{version}" if version else arxiv_id,
            doi=doi,
            title=" ".join(getattr(entry, "title", "").split()),
            authors=authors,
            abstract=" ".join(getattr(entry, "summary", "").split()),
            year=year,
            venue="arXiv",
            publication_type="preprint",
            keywords=categories,
            paper_url=paper_url,
            official_url=getattr(entry, "link", ""),
            source="arxiv",
            source_raw=dict(entry),
        )


def _parse_arxiv_id(entry_id: str) -> tuple[str, str | None]:
    """Extract the arXiv id and version from an entry id URL.

    Examples:
        >>> _parse_arxiv_id("http://arxiv.org/abs/2307.06207v2")
        ('2307.06207', '2')
        >>> _parse_arxiv_id("http://arxiv.org/abs/cs.AI/0703123v1")
        ('cs.AI/0703123', '1')
        >>> _parse_arxiv_id("http://arxiv.org/abs/2307.06207")
        ('2307.06207', None)
    """
    # The entry.id is a URL like http://arxiv.org/abs/<id>[v<n>]
    tail = entry_id.rsplit("/abs/", 1)[-1]
    match = re.match(r"^(?P<id>.+?)(?:v(?P<v>\d+))?$", tail)
    if match is None:
        return tail, None
    return match.group("id"), match.group("v")
