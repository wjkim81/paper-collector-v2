"""Demo: search PubMed and print the first few results.

Run with: uv run python scripts/demo_pubmed.py
"""

from __future__ import annotations

import logging

from paper_collector.sources.pubmed import PubMedSource


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    source = PubMedSource()
    query = "optical coherence tomography deep learning"
    print(f"Searching PubMed for: {query!r}\n")
    for i, paper in enumerate(source.search(query, max_results=5), start=1):
        print(f"[{i}] {paper.title}")
        print(f"    venue: {paper.venue} ({paper.year})")
        print(
            f"    authors: {', '.join(paper.authors[:3])}"
            f"{'...' if len(paper.authors) > 3 else ''}"
        )
        print(f"    pmid: {paper.pubmed_id}")
        if paper.doi:
            print(f"    doi: {paper.doi}")
        print()


if __name__ == "__main__":
    main()
