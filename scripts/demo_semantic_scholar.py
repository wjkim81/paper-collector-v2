"""Demo: Semantic Scholar search and enrichment.

Showcases two flows:
  1. Search by free-text query.
  2. Fetch by an arXiv ID to get TLDR and citation data.

Run with: uv run python scripts/demo_semantic_scholar.py
"""

from __future__ import annotations

import logging

from paper_collector.sources.semantic_scholar import SemanticScholarSource


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    source = SemanticScholarSource()

    # 1. Search.
    print("=== Search: 'local conditional neural fields' ===\n")
    for i, paper in enumerate(
        source.search("local conditional neural fields", max_results=3), start=1
    ):
        print(f"[{i}] {paper.title}")
        print(f"    venue: {paper.venue} ({paper.year})")
        print(
            f"    authors: {', '.join(paper.authors[:3])}"
            f"{'...' if len(paper.authors) > 3 else ''}"
        )
        if paper.ai_summary:
            print(f"    TLDR: {paper.ai_summary[:120]}...")
        print()

    # 2. Enrichment-style fetch: pass an arXiv ID directly.
    print("=== Fetch by ARXIV:2307.06207 (LCNF paper) ===\n")
    paper = source.fetch_by_id("ARXIV:2307.06207")
    if paper:
        print(f"Title: {paper.title}")
        print(f"Year: {paper.year}  Venue: {paper.venue}")
        print(f"DOI: {paper.doi}")
        print(f"arXiv: {paper.arxiv_id}")
        print(f"S2 ID: {paper.s2_id}")
        if paper.ai_summary:
            print(f"TLDR: {paper.ai_summary}")


if __name__ == "__main__":
    main()
