"""Demo: search arXiv, then export BibTeX via CrossRef.

This script demonstrates the full Phase 3 pipeline:
  1. Search arXiv for a query.
  2. For each result, fetch a BibTeX entry from CrossRef
     (using the arXiv DOI shadow when no publisher DOI is set).
  3. Write everything to references.bib.

Run with: uv run python scripts/demo_bibtex.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from paper_collector.enrich.bibtex import papers_to_bibfile
from paper_collector.sources.arxiv import ArxivSource


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    source = ArxivSource()
    query = "local conditional neural fields"
    print(f"Searching arXiv for: {query!r}")
    papers = list(source.search(query, max_results=3))
    print(f"Got {len(papers)} papers.\n")

    out = Path("references.bib")
    written, failures = papers_to_bibfile(papers, out)
    print(f"Wrote {written} BibTeX entries to {out}")
    if failures:
        print(f"({len(failures)} failures:)")
        for paper, reason in failures:
            print(f"  - {paper.title!r}: {reason}")

    print("\nFirst entry preview:")
    text = out.read_text(encoding="utf-8")
    print(text[:500] + ("..." if len(text) > 500 else ""))


if __name__ == "__main__":
    main()
