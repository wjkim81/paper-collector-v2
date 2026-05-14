"""Paper: unified representation across all paper sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Paper:
    """A single paper, normalized across all sources.

    At least one identifier or a title should be provided. The
    `primary_id` method picks the strongest available identifier for
    deduplication.

    Attributes:
        doi: Digital Object Identifier (e.g., "10.1038/s41586-021-03819-2").
        arxiv_id: arXiv identifier (e.g., "2307.06207" or "cs.AI/0703123").
        pubmed_id: PubMed ID (PMID).
        ieee_id: IEEE article number.
        dblp_key: DBLP record key.
        s2_id: Semantic Scholar paper ID.
        title: Paper title.
        authors: List of author names as strings.
        abstract: Paper abstract.
        year: Publication year.
        venue: Journal name or conference name.
        publication_type: One of "journal", "conference", "preprint".
        keywords: Author keywords or index terms.
        paper_url: Direct paper/PDF URL (typically arXiv or preprint).
        official_url: Publisher's official page.
        source: Name of the source that produced this Paper
            (e.g., "arxiv", "ieee").
        source_raw: Original API response, preserved for debugging and
            future re-parsing. Optional.
        ai_relevance_score: Optional relevance score from AI screening
            (0.0 - 1.0).
        ai_summary: Optional AI-generated summary.
    """

    # Identifiers
    doi: str | None = None
    arxiv_id: str | None = None
    pubmed_id: str | None = None
    ieee_id: str | None = None
    dblp_key: str | None = None
    s2_id: str | None = None

    # Core metadata
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    publication_type: str = ""

    # Categorization
    keywords: list[str] = field(default_factory=list)

    # URLs
    paper_url: str = ""
    official_url: str = ""

    # Source tracking
    source: str = ""
    source_raw: dict[str, Any] | None = None

    # AI enrichment (optional)
    ai_relevance_score: float | None = None
    ai_summary: str | None = None

    def primary_id(self) -> str:
        """Return the strongest available identifier for deduplication.

        Priority: DOI > arXiv ID > PubMed ID > normalized title.

        Returns:
            A string identifier prefixed with its kind (e.g., "doi:...").

        Raises:
            ValueError: If no identifier and no title are available.
        """
        if self.doi:
            return f"doi:{self.doi.lower()}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.pubmed_id:
            return f"pmid:{self.pubmed_id}"
        if self.title:
            normalized = " ".join(self.title.lower().split())
            return f"title:{normalized}"
        raise ValueError("Paper has no identifier and no title")
