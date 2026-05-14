"""Metadata enrichment via CrossRef.

When we have a DOI but incomplete Paper metadata (e.g., from arXiv we
might know the arXiv ID but not the journal name after publication), we
can ask CrossRef for a CSL JSON record and merge it into the Paper.

This is a non-destructive merge: existing non-empty Paper fields are
kept; CrossRef values only fill in gaps.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from paper_collector.core.paper import Paper

CROSSREF_DOI_URL = "https://doi.org/{doi}"
CSL_JSON_ACCEPT = "application/vnd.citationstyles.csl+json"
USER_AGENT = (
    "paper-collector/0.1 (https://github.com/wjkim81/paper-collector-v2; "
    "mailto:wjkim81@users.noreply.github.com)"
)
DEFAULT_TIMEOUT = 30.0

logger = logging.getLogger(__name__)


class MetadataError(Exception):
    """Raised when CrossRef metadata cannot be obtained for a DOI."""


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def doi_to_csl_json(doi: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Fetch CSL JSON metadata for a DOI from CrossRef.

    Args:
        doi: The DOI (with or without prefix).
        timeout: HTTP timeout in seconds.

    Returns:
        A CSL JSON dict.

    Raises:
        MetadataError: If the DOI cannot be resolved.
    """
    from paper_collector.enrich.bibtex import _normalize_doi

    normalized = _normalize_doi(doi)
    url = CROSSREF_DOI_URL.format(doi=normalized)
    headers = {"Accept": CSL_JSON_ACCEPT, "User-Agent": USER_AGENT}
    logger.info("crossref metadata: doi=%s", normalized)

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        if response.status_code == 404:
            raise MetadataError(f"DOI not found: {normalized}")
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def enrich_paper(paper: Paper) -> Paper:
    """Return a new Paper enriched with CrossRef metadata when available.

    The merge is non-destructive: existing non-empty fields on `paper`
    are preserved; CrossRef values only fill in empty fields.

    If the Paper has no DOI, it is returned unchanged.

    Args:
        paper: The Paper to enrich.

    Returns:
        A new Paper instance with merged metadata. If no DOI or the
        CrossRef lookup fails, returns the input paper unchanged.
    """
    if not paper.doi:
        return paper

    try:
        csl = doi_to_csl_json(paper.doi)
    except (MetadataError, httpx.HTTPError) as e:
        logger.warning("could not enrich %s: %s", paper.doi, e)
        return paper

    return _merge_csl_into_paper(paper, csl)


def _merge_csl_into_paper(paper: Paper, csl: dict[str, Any]) -> Paper:
    """Build a new Paper by filling empty fields from CSL JSON."""
    updates: dict[str, Any] = {}

    if not paper.title and csl.get("title"):
        updates["title"] = _normalize_text(csl["title"])

    if not paper.abstract and csl.get("abstract"):
        updates["abstract"] = _normalize_text(csl["abstract"])

    if not paper.authors:
        authors = _extract_authors(csl)
        if authors:
            updates["authors"] = authors

    if not paper.year:
        year = _extract_year(csl)
        if year:
            updates["year"] = year

    if not paper.venue:
        venue = csl.get("container-title") or csl.get("publisher")
        if venue:
            updates["venue"] = _normalize_text(venue)

    if not paper.publication_type:
        csl_type = csl.get("type", "")
        if "journal" in csl_type:
            updates["publication_type"] = "journal"
        elif csl_type in {"paper-conference", "proceedings-article"}:
            updates["publication_type"] = "conference"
        elif csl_type == "posted-content":
            updates["publication_type"] = "preprint"

    if not paper.official_url and csl.get("URL"):
        updates["official_url"] = csl["URL"]

    return replace(paper, **updates) if updates else paper


def _normalize_text(value: Any) -> str:
    """Collapse whitespace and ensure a string."""
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    return " ".join(str(value).split())


def _extract_authors(csl: dict[str, Any]) -> list[str]:
    """Extract author names from CSL JSON `author` field."""
    raw = csl.get("author", [])
    names: list[str] = []
    for entry in raw:
        given = entry.get("given", "").strip()
        family = entry.get("family", "").strip()
        if given and family:
            names.append(f"{given} {family}")
        elif family:
            names.append(family)
        elif entry.get("literal"):
            names.append(str(entry["literal"]).strip())
    return names


def _extract_year(csl: dict[str, Any]) -> int | None:
    """Pull the year from issued/published-print/published-online dates."""
    for key in ("issued", "published-print", "published-online", "created"):
        block = csl.get(key)
        if not block:
            continue
        parts = block.get("date-parts")
        if parts and isinstance(parts, list) and parts[0]:
            first = parts[0][0]
            if isinstance(first, int):
                return first
            if isinstance(first, str) and first.isdigit():
                return int(first)
    return None
