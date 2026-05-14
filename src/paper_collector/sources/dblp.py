"""DBLP source implementation.

DBLP is the de facto computer science bibliography. The public API
returns JSON and requires no authentication.

API documentation: https://dblp.org/faq/13501473.html
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from paper_collector.core.paper import Paper
from paper_collector.sources.base import BaseSource, SourceConfig

DBLP_API_URL = "https://dblp.org/search/publ/api"
DEFAULT_RATE_LIMIT = 1.0  # 1 request per second (polite default)


def _map_publication_type(dblp_type: str) -> str:
    """Map DBLP type strings to our normalized publication_type."""
    if not dblp_type:
        return ""
    lowered = dblp_type.lower()
    if "conference" in lowered or "workshop" in lowered:
        return "conference"
    if "journal" in lowered:
        return "journal"
    if "informal" in lowered or "preprint" in lowered:
        return "preprint"
    return ""


def _coerce_authors(info: dict[str, Any]) -> list[str]:
    """Extract author names from a DBLP info object.

    DBLP returns authors in one of three shapes depending on count:
      - missing entirely
      - {"author": {"@pid": "...", "text": "Alice"}} (single author)
      - {"author": [{...}, {...}]} (multiple authors)
    """
    authors_block = info.get("authors") or {}
    raw = authors_block.get("author")
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            text = entry.get("text") or entry.get("@text")
            if text:
                names.append(str(text).strip())
        elif isinstance(entry, str):
            names.append(entry.strip())
    return names


def _coerce_year(info: dict[str, Any]) -> int | None:
    """Parse `info.year` (which may be a str or int) into an int."""
    raw = info.get("year")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _coerce_str(info: dict[str, Any], key: str) -> str:
    """Pull a string field from `info` (may be missing or non-str)."""
    value = info.get(key)
    if value is None:
        return ""
    return str(value).strip()


class DBLPSource(BaseSource):
    """Source that searches DBLP via its public publication search API.

    DBLP requires no authentication. The API returns JSON.

    Example:
        >>> source = DBLPSource()
        >>> for paper in source.search("attention is all you need", max_results=5):
        ...     print(paper.title, paper.venue, paper.year)
    """

    def __init__(self, config: SourceConfig | None = None) -> None:
        """Initialize the DBLP source.

        Args:
            config: Optional source configuration. If None, uses defaults
                appropriate for DBLP (1 req/sec).
        """
        if config is None:
            config = SourceConfig(
                name="dblp",
                rate_limit_per_second=DEFAULT_RATE_LIMIT,
                max_retries=3,
                timeout_seconds=30.0,
            )
        super().__init__(config)
        self._last_request_at: float = 0.0

    def search(self, query: str, max_results: int = 100) -> Iterator[Paper]:
        """Search DBLP for publications matching a query.

        Args:
            query: Free-text search query.
            max_results: Maximum number of results to return.

        Yields:
            Paper objects, one at a time.
        """
        self.logger.info("dblp search: query=%r max_results=%d", query, max_results)
        page_size = min(100, max_results)
        start = 0
        returned = 0

        while returned < max_results:
            current_page = min(page_size, max_results - returned)
            hits = self._fetch_page(query, start=start, page_size=current_page)
            if not hits:
                break

            for hit in hits:
                yield self._hit_to_paper(hit)
                returned += 1
                if returned >= max_results:
                    return

            if len(hits) < current_page:
                break
            start += current_page

    def fetch_by_id(self, identifier: str) -> Paper | None:
        """Fetch a single paper by its DBLP key.

        DBLP keys look like "conf/cvpr/SmithJ20" or "journals/nature/Foo24".
        DBLP doesn't offer a dedicated by-key endpoint via the search API,
        so we search for the key directly and filter results.

        Args:
            identifier: A DBLP key.

        Returns:
            A Paper if found, None otherwise.
        """
        normalized = identifier.strip()
        self.logger.info("dblp fetch_by_id: key=%r", normalized)
        hits = self._fetch_page(normalized, start=0, page_size=10)
        for hit in hits:
            if hit.get("info", {}).get("key") == normalized:
                return self._hit_to_paper(hit)
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        query: str,
        *,
        start: int = 0,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch one page of DBLP results."""
        params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "h": page_size,
            "f": start,
        }
        self._respect_rate_limit()
        data = self._get(params)

        result = data.get("result", {})
        hits_block = result.get("hits", {})
        raw_hits = hits_block.get("hit", [])
        if isinstance(raw_hits, dict):
            # DBLP collapses a single-hit list to a dict.
            raw_hits = [raw_hits]
        self.logger.debug("dblp fetched %d hits (start=%d)", len(raw_hits), start)
        return list(raw_hits)

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Issue a GET request to DBLP with retry on transient errors."""
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.get(DBLP_API_URL, params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    def _respect_rate_limit(self) -> None:
        """Sleep if needed to honor the configured rate limit."""
        if self.config.rate_limit_per_second <= 0:
            return
        min_interval = 1.0 / self.config.rate_limit_per_second
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _hit_to_paper(self, hit: dict[str, Any]) -> Paper:
        """Convert a DBLP hit dict into a Paper."""
        info = hit.get("info", {}) or {}
        dblp_key = info.get("key") or hit.get("@id") or ""

        # DBLP `ee` is the "electronic edition" — usually the publisher
        # URL. `url` (top-level) is the DBLP record URL.
        ee = info.get("ee") or ""
        if isinstance(ee, list):
            ee = ee[0] if ee else ""
        dblp_record_url = hit.get("url") or ""

        return Paper(
            dblp_key=dblp_key or None,
            doi=_coerce_str(info, "doi") or None,
            title=" ".join(_coerce_str(info, "title").split()),
            authors=_coerce_authors(info),
            year=_coerce_year(info),
            venue=_coerce_str(info, "venue"),
            publication_type=_map_publication_type(_coerce_str(info, "type")),
            paper_url=str(ee).strip(),
            official_url=str(dblp_record_url).strip(),
            source="dblp",
            source_raw=hit,
        )
