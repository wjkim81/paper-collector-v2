"""Semantic Scholar source implementation.

Uses the Academic Graph API. Two distinguishing features versus other
sources:

1. The `paper_id` accepts DOI, arXiv ID, and PMID prefixes directly,
   which makes Semantic Scholar a natural enrichment source for papers
   discovered elsewhere.
2. The response includes a `tldr` field — an AI-generated summary
   produced by Allen AI's SciTLDR model. We map this to Paper.ai_summary.

API key is optional. With a key, each user gets a dedicated 1 RPS rate
limit (slower but stable). Without one, requests share a generous public
rate limit. The key is loaded from settings.semantic_scholar_api_key.

Docs: https://api.semanticscholar.org/api-docs/
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

from paper_collector.config import get_settings
from paper_collector.core.paper import Paper
from paper_collector.sources.base import BaseSource, SourceConfig

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
S2_SEARCH_URL = f"{S2_BASE_URL}/paper/search"
S2_PAPER_URL = f"{S2_BASE_URL}/paper/{{paper_id}}"

# Rate limits per Semantic Scholar docs:
# - With API key: 1 req/sec dedicated.
# - Without API key: shared public limit (we use 1 req/sec to be polite).
RATE_LIMIT_WITH_KEY = 1.0
RATE_LIMIT_NO_KEY = 1.0

# Fields we request. Semantic Scholar requires explicit field selection.
DEFAULT_FIELDS = (
    "paperId,title,abstract,year,venue,publicationVenue,publicationDate,"
    "publicationTypes,authors,externalIds,tldr,openAccessPdf,url"
)


def _extract_authors(record: dict[str, Any]) -> list[str]:
    """Extract author names from a Semantic Scholar paper record."""
    authors = record.get("authors") or []
    names: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = (author.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _extract_year(record: dict[str, Any]) -> int | None:
    """Pull the publication year. Prefer `year`, fall back to date parse."""
    year = record.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)
    pub_date = record.get("publicationDate") or ""
    head = pub_date.split("-", 1)[0] if pub_date else ""
    if head.isdigit():
        return int(head)
    return None


def _extract_venue(record: dict[str, Any]) -> str:
    """Pull a venue name, preferring the richer `publicationVenue.name`."""
    pv = record.get("publicationVenue") or {}
    if isinstance(pv, dict):
        name = (pv.get("name") or "").strip()
        if name:
            return name
    return (record.get("venue") or "").strip()


def _map_publication_type(record: dict[str, Any]) -> str:
    """Map Semantic Scholar publicationTypes to our normalized values."""
    types = record.get("publicationTypes") or []
    if not isinstance(types, list):
        return ""
    lowered = " ".join(str(t).lower() for t in types)
    if "journalarticle" in lowered or "review" in lowered:
        return "journal"
    if "conference" in lowered:
        return "conference"
    if "preprint" in lowered:
        return "preprint"
    return ""


def _extract_external_ids(record: dict[str, Any]) -> dict[str, str]:
    """Pull a flat dict of external identifiers, lowercased keys."""
    ext = record.get("externalIds") or {}
    if not isinstance(ext, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in ext.items() if v}


def _extract_tldr(record: dict[str, Any]) -> str | None:
    """Pull the AI-generated TLDR if present."""
    tldr = record.get("tldr")
    if isinstance(tldr, dict):
        text = (tldr.get("text") or "").strip()
        if text:
            return text
    return None


def _extract_paper_url(record: dict[str, Any]) -> str:
    """Prefer the open-access PDF link; fall back to the Semantic Scholar page."""
    oa = record.get("openAccessPdf")
    if isinstance(oa, dict):
        url = (oa.get("url") or "").strip()
        if url:
            return url
    return (record.get("url") or "").strip()


class SemanticScholarSource(BaseSource):
    """Source that searches and fetches papers from Semantic Scholar.

    Example:
        >>> source = SemanticScholarSource()
        >>> for paper in source.search("local conditional neural fields", max_results=5):
        ...     print(paper.title, paper.ai_summary)
    """

    def __init__(
        self,
        config: SourceConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize the Semantic Scholar source.

        Args:
            config: Optional source configuration. If None, uses defaults.
            api_key: Explicit API key. If None, settings.semantic_scholar_api_key
                is used (loaded from .env).
        """
        if api_key is None:
            settings = get_settings()
            api_key = settings.semantic_scholar_api_key

        if config is None:
            rate = RATE_LIMIT_WITH_KEY if api_key else RATE_LIMIT_NO_KEY
            config = SourceConfig(
                name="semantic_scholar",
                rate_limit_per_second=rate,
                max_retries=3,
                timeout_seconds=30.0,
            )
        super().__init__(config)
        self.api_key = api_key
        self._last_request_at: float = 0.0

    def search(self, query: str, max_results: int = 100) -> Iterator[Paper]:
        """Search Semantic Scholar for papers matching a query.

        Args:
            query: Free-text search query.
            max_results: Maximum number of results to return.

        Yields:
            Paper objects, one at a time.
        """
        self.logger.info("s2 search: query=%r max_results=%d", query, max_results)
        page_size = min(100, max_results)
        offset = 0
        returned = 0

        while returned < max_results:
            current_page = min(page_size, max_results - returned)
            records = self._search_page(query, offset=offset, limit=current_page)
            if not records:
                break

            for record in records:
                yield self._record_to_paper(record)
                returned += 1
                if returned >= max_results:
                    return

            if len(records) < current_page:
                break
            offset += current_page

    def fetch_by_id(self, identifier: str) -> Paper | None:
        """Fetch a single paper by ID.

        The identifier may be a Semantic Scholar hex ID, or prefixed:
            - "DOI:10.x/y"
            - "ARXIV:2307.06207"
            - "PMID:34265844"

        Args:
            identifier: A paper identifier (see formats above).

        Returns:
            A Paper if found, None otherwise.
        """
        normalized = identifier.strip()
        self.logger.info("s2 fetch_by_id: id=%r", normalized)
        record = self._fetch_paper(normalized)
        if record is None:
            return None
        return self._record_to_paper(record)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _common_headers(self) -> dict[str, str]:
        """Return headers for all S2 requests (incl. optional API key)."""
        headers: dict[str, str] = {"User-Agent": "paper-collector-v2"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _search_page(
        self, query: str, *, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch one page of search results."""
        params: dict[str, str | int] = {
            "query": query,
            "fields": DEFAULT_FIELDS,
            "limit": limit,
            "offset": offset,
        }
        self._respect_rate_limit()
        data = self._get(S2_SEARCH_URL, params)
        records = data.get("data") or []
        if not isinstance(records, list):
            return []
        self.logger.debug("s2 search returned %d records", len(records))
        return records

    def _fetch_paper(self, paper_id: str) -> dict[str, Any] | None:
        """Fetch a single paper record by ID. Returns None on 404."""
        url = S2_PAPER_URL.format(paper_id=paper_id)
        params: dict[str, str | int] = {"fields": DEFAULT_FIELDS}
        self._respect_rate_limit()
        try:
            data = self._get(url, params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return data if isinstance(data, dict) else None

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Issue a GET to an S2 URL with retry on transient errors."""
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.get(url, params=params, headers=self._common_headers())
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

    def _record_to_paper(self, record: dict[str, Any]) -> Paper:
        """Convert a Semantic Scholar paper record into a Paper."""
        ext = _extract_external_ids(record)
        doi = ext.get("doi") or None
        arxiv_id = ext.get("arxiv") or None
        pubmed_id = ext.get("pubmed") or None
        s2_id = record.get("paperId") or ext.get("corpusid") or None

        title = (record.get("title") or "").strip()
        abstract = (record.get("abstract") or "").strip()

        return Paper(
            doi=doi,
            arxiv_id=arxiv_id,
            pubmed_id=pubmed_id,
            s2_id=str(s2_id) if s2_id else None,
            title=" ".join(title.split()),
            authors=_extract_authors(record),
            abstract=" ".join(abstract.split()),
            year=_extract_year(record),
            venue=_extract_venue(record),
            publication_type=_map_publication_type(record),
            paper_url=_extract_paper_url(record),
            official_url=(f"https://doi.org/{doi}" if doi else ""),
            source="semantic_scholar",
            source_raw=record,
            ai_summary=_extract_tldr(record),
        )
