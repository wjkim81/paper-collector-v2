"""PubMed source implementation via NCBI E-utilities.

Uses a two-step workflow:
  1. ESearch (esearch.fcgi) — query → list of PMIDs (JSON)
  2. ESummary (esummary.fcgi) — PMIDs → metadata records (JSON)

EFetch (XML) is intentionally not used in this implementation. ESummary
provides title, authors, journal, year, DOI, and other commonly used
fields. If full abstracts are needed later, an EFetch path can be added.

API documentation: https://www.ncbi.nlm.nih.gov/books/NBK25500/
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

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH_URL = f"{EUTILS_BASE_URL}/esearch.fcgi"
ESUMMARY_URL = f"{EUTILS_BASE_URL}/esummary.fcgi"

RATE_LIMIT_WITH_KEY = 10.0  # 10 req/sec with API key
RATE_LIMIT_NO_KEY = 3.0  # 3 req/sec without API key

# Polite identification per NCBI guidelines.
TOOL_NAME = "paper-collector-v2"
TOOL_EMAIL = "wjkim81@users.noreply.github.com"

# Max IDs to fetch in a single ESummary call (NCBI allows several hundred).
ESUMMARY_BATCH_SIZE = 200


def _extract_authors(record: dict[str, Any]) -> list[str]:
    """Extract author names from an ESummary record.

    `authors` is a list of {"name": "Smith J", "authtype": "Author", ...}.
    """
    authors = record.get("authors") or []
    names: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        if author.get("authtype") and author["authtype"].lower() != "author":
            continue
        name = author.get("name", "").strip()
        if name:
            names.append(name)
    return names


def _extract_year(record: dict[str, Any]) -> int | None:
    """Pull the publication year from an ESummary record.

    `pubdate` examples: "2021 Jul 15", "2024", "2023 Mar".
    """
    pubdate = record.get("pubdate") or record.get("epubdate") or ""
    head = pubdate.strip().split(" ", 1)[0]
    if head.isdigit():
        return int(head)
    return None


def _extract_doi(record: dict[str, Any]) -> str | None:
    """Pull the DOI from an ESummary record's articleids list."""
    for ident in record.get("articleids") or []:
        if not isinstance(ident, dict):
            continue
        if ident.get("idtype", "").lower() == "doi":
            value = (ident.get("value") or "").strip()
            if value:
                return value
    return None


def _extract_pmcid(record: dict[str, Any]) -> str | None:
    """Pull the PMC ID (PubMed Central) if available."""
    for ident in record.get("articleids") or []:
        if not isinstance(ident, dict):
            continue
        if ident.get("idtype", "").lower() == "pmc":
            value = (ident.get("value") or "").strip()
            if value:
                return value
    return None


def _map_publication_type(record: dict[str, Any]) -> str:
    """Map ESummary `pubtype` to our normalized publication_type."""
    pubtypes = record.get("pubtype") or []
    if not isinstance(pubtypes, list):
        return ""
    lowered = " ".join(str(p).lower() for p in pubtypes)
    if "review" in lowered or "journal article" in lowered:
        return "journal"
    if "preprint" in lowered:
        return "preprint"
    if "conference" in lowered:
        return "conference"
    return "journal"  # default for PubMed (mostly journals)


class PubMedSource(BaseSource):
    """Source that searches PubMed via NCBI E-utilities.

    Uses an API key from settings when available; otherwise falls back
    to the unauthenticated rate limit. The two-step ESearch→ESummary
    flow returns JSON in both phases.

    Example:
        >>> source = PubMedSource()
        >>> for paper in source.search("optical coherence tomography", max_results=5):
        ...     print(paper.title, paper.year)
    """

    def __init__(
        self,
        config: SourceConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize the PubMed source.

        Args:
            config: Optional source configuration. If None, a sensible
                default is built based on whether an API key is set.
            api_key: Explicit NCBI API key. If None, settings.ncbi_api_key
                is used (loaded from .env).
        """
        if api_key is None:
            settings = get_settings()
            api_key = settings.ncbi_api_key

        if config is None:
            rate = RATE_LIMIT_WITH_KEY if api_key else RATE_LIMIT_NO_KEY
            config = SourceConfig(
                name="pubmed",
                rate_limit_per_second=rate,
                max_retries=3,
                timeout_seconds=30.0,
            )
        super().__init__(config)
        self.api_key = api_key
        self._last_request_at: float = 0.0

    def search(self, query: str, max_results: int = 100) -> Iterator[Paper]:
        """Search PubMed for papers matching a query.

        Args:
            query: Free-text search query (PubMed syntax supported, e.g.,
                'cancer[title] AND 2024[pdat]').
            max_results: Maximum number of results to return.

        Yields:
            Paper objects, one at a time.
        """
        self.logger.info("pubmed search: query=%r max_results=%d", query, max_results)
        pmids = self._esearch(query, max_results=max_results)
        if not pmids:
            return

        # Fetch metadata in batches.
        for batch_start in range(0, len(pmids), ESUMMARY_BATCH_SIZE):
            batch = pmids[batch_start : batch_start + ESUMMARY_BATCH_SIZE]
            records = self._esummary(batch)
            for pmid in batch:
                record = records.get(pmid)
                if record is None:
                    continue
                yield self._record_to_paper(pmid, record)

    def fetch_by_id(self, identifier: str) -> Paper | None:
        """Fetch a single paper by PMID.

        Args:
            identifier: A PubMed ID (PMID), as a string.

        Returns:
            A Paper if found, None otherwise.
        """
        normalized = identifier.strip()
        self.logger.info("pubmed fetch_by_id: pmid=%r", normalized)
        records = self._esummary([normalized])
        record = records.get(normalized)
        if record is None:
            return None
        return self._record_to_paper(normalized, record)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _common_params(self) -> dict[str, str | int]:
        """Return params common to all E-utility requests."""
        params: dict[str, str | int] = {
            "tool": TOOL_NAME,
            "email": TOOL_EMAIL,
            "retmode": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _esearch(self, query: str, max_results: int) -> list[str]:
        """Issue an ESearch request; return a list of PMIDs."""
        params: dict[str, str | int] = {
            **self._common_params(),
            "db": "pubmed",
            "term": query,
            "retmax": min(max_results, 10000),  # PubMed E-utility cap
        }
        self._respect_rate_limit()
        data = self._get(ESEARCH_URL, params)
        result = data.get("esearchresult", {})
        idlist = result.get("idlist") or []
        if not isinstance(idlist, list):
            return []
        self.logger.debug("pubmed esearch returned %d ids", len(idlist))
        return [str(x) for x in idlist]

    def _esummary(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        """Issue an ESummary request for the given PMIDs.

        Returns:
            A dict mapping PMID -> record dict. PMIDs that have no
            record (e.g., suppressed) are omitted.
        """
        if not pmids:
            return {}
        params: dict[str, str | int] = {
            **self._common_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
        }
        self._respect_rate_limit()
        data = self._get(ESUMMARY_URL, params)
        result = data.get("result", {})
        uids = result.get("uids") or []
        out: dict[str, dict[str, Any]] = {}
        for uid in uids:
            uid_str = str(uid)
            record = result.get(uid_str)
            if isinstance(record, dict):
                out[uid_str] = record
        return out

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Issue a GET request to an NCBI URL with retry on transient errors."""
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.get(url, params=params)
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

    def _record_to_paper(self, pmid: str, record: dict[str, Any]) -> Paper:
        """Convert an ESummary record into a Paper."""
        title = str(record.get("title") or "").strip().rstrip(".")
        venue = str(record.get("fulljournalname") or record.get("source") or "").strip()
        return Paper(
            pubmed_id=pmid,
            doi=_extract_doi(record),
            title=" ".join(title.split()),
            authors=_extract_authors(record),
            year=_extract_year(record),
            venue=venue,
            publication_type=_map_publication_type(record),
            paper_url=(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""),
            official_url=(
                f"https://doi.org/{_extract_doi(record)}"
                if _extract_doi(record)
                else ""
            ),
            source="pubmed",
            source_raw=record,
        )
