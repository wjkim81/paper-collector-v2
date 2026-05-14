# paper-collector-v2

A modular, AI-assisted paper collection pipeline for researchers who 
spend more time finding papers than reading them.

**Status:** 🚧 Early development. Foundation phase.

## Why this exists

I built a paper collector in 2018 using raw `urllib` calls to IEEE, PubMed, 
and DBLP. It worked but was held together by quirks I learned the hard way 
(including `time.sleep(1)` to handle rate limits I didn't yet know had a 
name).

The original tool is preserved as `paper-collector` (private archive). 
This is the rewrite.

What changed: AI now fills the gap that was always missing — turning a list 
of search hits into actual structured understanding before they slip into 
the to-read graveyard.

## Goals

- **Multi-source search**: arXiv, IEEE Xplore, PubMed, DBLP, Semantic 
  Scholar, OpenAlex, CrossRef
- **Unified Paper representation** across all sources
- **Deduplication** based on DOI, arXiv ID, and fuzzy title matching
- **AI-assisted screening** based on personal research context
- **Structured comparison fields** (dataset, architecture, loss, etc.) — 
  the "Excel literature review" pattern, automated
- **Notion integration** for persistent paper archives
- **BibTeX export** via CrossRef content negotiation

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project foundation, `Paper` dataclass, base abstractions | 🚧 |
| 2 | arXiv source | ✅ |
| 3 | CrossRef (DOI → BibTeX) | ✅ |
| 4 | DBLP / PubMed / IEEE sources (in progress: DBLP ✅, PubMed ✅) | 🚧 |
| 5 | Semantic Scholar / OpenAlex | ⏳ |
| 6 | Deduplication | ⏳ |
| 7 | CLI | ⏳ |
| 8 | Notion export | ⏳ |
| 9 | AI screening & summarization | ⏳ |

## Installation

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/wjkim81/paper-collector-v2.git
cd paper-collector-v2
uv sync
```

## Usage

Search arXiv from Python:

```python
from paper_collector.sources.arxiv import ArxivSource

source = ArxivSource()
for paper in source.search("local conditional neural fields", max_results=5):
    print(paper.title, paper.arxiv_id)
```

Search DBLP from Python:

```python
from paper_collector.sources.dblp import DBLPSource

dblp = DBLPSource()
for paper in dblp.search("attention is all you need", max_results=5):
    print(paper.title, paper.venue, paper.year)
```

Search PubMed from Python:

```python
from paper_collector.sources.pubmed import PubMedSource

pubmed = PubMedSource()
for paper in pubmed.search("optical coherence tomography", max_results=5):
    print(paper.title, paper.year)
```

Export results to a BibTeX file via CrossRef:

```python
from paper_collector.enrich.bibtex import papers_to_bibfile

papers = list(source.search("neural fields", max_results=10))
written, failures = papers_to_bibfile(papers, "references.bib")
print(f"Wrote {written} entries; {len(failures)} failures.")
```

Enrich a Paper with publisher metadata (journal, year, etc.) when only
a DOI is known:

```python
from paper_collector.core.paper import Paper
from paper_collector.enrich.metadata import enrich_paper

paper = Paper(doi="10.1038/s41586-021-03819-2")
paper = enrich_paper(paper)
print(paper.title, paper.venue, paper.year)
```

## License

MIT — see [LICENSE](./LICENSE).