"""Demo: search DBLP and print the first few results.

Run with: uv run python scripts/demo_dblp.py
"""

from __future__ import annotations

import logging

from paper_collector.sources.dblp import DBLPSource


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    source = DBLPSource()
    query = "attention is all you need"
    print(f"Searching DBLP for: {query!r}\n")
    for i, paper in enumerate(source.search(query, max_results=5), start=1):
        print(f"[{i}] {paper.title}")
        print(
            f"    venue: {paper.venue} ({paper.year})  type: {paper.publication_type}"
        )
        print(
            f"    authors: {', '.join(paper.authors[:3])}"
            f"{'...' if len(paper.authors) > 3 else ''}"
        )
        print(f"    dblp_key: {paper.dblp_key}")
        if paper.doi:
            print(f"    doi: {paper.doi}")
        print()


if __name__ == "__main__":
    main()
