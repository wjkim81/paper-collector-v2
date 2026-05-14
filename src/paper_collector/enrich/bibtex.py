"""BibTeX export via CrossRef content negotiation.

A single HTTP request to `https://doi.org/{doi}` returns a clean BibTeX
entry when the `Accept: application/x-bibtex` header is set. This module
wraps that capability for individual DOIs, individual Paper objects, and
collections of Paper objects exported to a `.bib` file.

For arXiv-only preprints without a publisher DOI, we fall back to the
arXiv DOI shadow (`10.48550/arXiv.{id}`) which CrossRef also resolves.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from paper_collector.core.paper import Paper

CROSSREF_DOI_URL = "https://doi.org/{doi}"
BIBTEX_ACCEPT = "application/x-bibtex"
USER_AGENT = (
    "paper-collector/0.1 (https://github.com/wjkim81/paper-collector-v2; "
    "mailto:wjkim81@users.noreply.github.com)"
)
DEFAULT_TIMEOUT = 30.0

logger = logging.getLogger(__name__)


class BibTeXError(Exception):
    """Raised when a BibTeX entry cannot be obtained for a DOI."""


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def doi_to_bibtex(doi: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch a BibTeX entry for a DOI from CrossRef.

    Args:
        doi: The Digital Object Identifier (e.g., "10.1038/s41586-021-03819-2").
            May include or omit the "doi:" prefix or "https://doi.org/" URL.
        timeout: HTTP timeout in seconds.

    Returns:
        The BibTeX entry as a string (ends with a newline; ready to write
        into a `.bib` file).

    Raises:
        BibTeXError: If the DOI cannot be resolved or returns no BibTeX.
        httpx.HTTPError: For unrecoverable transport errors.
    """
    normalized = _normalize_doi(doi)
    url = CROSSREF_DOI_URL.format(doi=normalized)
    headers = {"Accept": BIBTEX_ACCEPT, "User-Agent": USER_AGENT}
    logger.info("crossref bibtex: doi=%s", normalized)

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        if response.status_code == 404:
            raise BibTeXError(f"DOI not found: {normalized}")
        response.raise_for_status()
        body = response.text.strip()
        if not body or not body.startswith("@"):
            raise BibTeXError(
                f"CrossRef returned no BibTeX for {normalized}: {body[:200]!r}"
            )
        return body + "\n"


def paper_to_bibtex(paper: Paper) -> str:
    """Return the BibTeX entry for a Paper, using its DOI when present.

    For arXiv-only preprints, falls back to the arXiv DOI shadow
    `10.48550/arXiv.{id}` (CrossRef resolves these for papers posted
    after the shadow program began).

    Args:
        paper: The Paper to convert.

    Returns:
        The BibTeX entry as a string.

    Raises:
        BibTeXError: If the Paper has no DOI and no arXiv ID, or if
            CrossRef cannot resolve any of them.
    """
    doi = paper.doi
    if doi:
        return doi_to_bibtex(doi)

    if paper.arxiv_id:
        # Strip version suffix (v1, v2, ...) — arXiv DOI shadows are
        # versionless.
        base_id = paper.arxiv_id.split("v")[0]
        shadow_doi = f"10.48550/arXiv.{base_id}"
        try:
            return doi_to_bibtex(shadow_doi)
        except BibTeXError as e:
            raise BibTeXError(
                f"No DOI on paper {paper.title!r}, and arXiv shadow DOI "
                f"{shadow_doi} could not be resolved: {e}"
            ) from e

    raise BibTeXError(
        f"Paper {paper.title!r} has no DOI and no arXiv ID; cannot export."
    )


def papers_to_bibfile(
    papers: Iterable[Paper],
    path: str | Path,
    *,
    skip_failures: bool = True,
) -> tuple[int, list[tuple[Paper, str]]]:
    """Write multiple papers to a `.bib` file.

    Args:
        papers: Papers to export.
        path: Output file path (will be overwritten).
        skip_failures: If True (default), skip papers whose BibTeX cannot
            be fetched and report them in the failures list. If False,
            raise on the first failure.

    Returns:
        A tuple `(success_count, failures)` where `failures` is a list
        of `(paper, reason)` pairs for papers that could not be exported.
    """
    output_path = Path(path)
    written = 0
    failures: list[tuple[Paper, str]] = []
    entries: list[str] = []

    for paper in papers:
        try:
            entries.append(paper_to_bibtex(paper))
            written += 1
        except BibTeXError as e:
            failures.append((paper, str(e)))
            if not skip_failures:
                raise

    output_path.write_text("\n".join(entries), encoding="utf-8")
    logger.info(
        "wrote %d entries to %s (%d failures)",
        written,
        output_path,
        len(failures),
    )
    return written, failures


def _normalize_doi(doi: str) -> str:
    """Normalize a DOI string into the bare form used in URLs.

    Accepts forms like "10.x/y", "doi:10.x/y", "https://doi.org/10.x/y".
    """
    s = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix) :]
            break
    return s.strip().strip("/")
