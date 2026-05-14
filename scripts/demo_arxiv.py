"""Quick demo: search arXiv and print the first few results.

Run with: uv run python scripts/demo_arxiv.py
"""

from __future__ import annotations

import logging

from paper_collector.sources.arxiv import ArxivSource


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    source = ArxivSource()
    print("Searching arXiv for: 'local conditional neural fields'\n")
    for i, paper in enumerate(
        source.search("local conditional neural fields", max_results=3), start=1
    ):
        print(f"[{i}] {paper.title}")
        print(f"    arXiv: {paper.arxiv_id}")
        print(
            f"    Authors: {', '.join(paper.authors[:3])}{'...' if len(paper.authors) > 3 else ''}"
        )
        print(f"    Year: {paper.year}  Venue: {paper.venue}")
        print(f"    URL: {paper.paper_url}")
        print()


if __name__ == "__main__":
    main()
