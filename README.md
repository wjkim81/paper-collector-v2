# paper-collector-v2

A modular, AI-assisted paper collection pipeline for researchers who 
spend more time finding papers than reading them.

**Status:** 🚧 Active development. 4 working sources + BibTeX/metadata enrichment.

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

## Architecture

```
paper_collector/
├── core/        Paper dataclass — the universal interface across sources
├── sources/     One module per source (arXiv, DBLP, PubMed, Semantic Scholar)
├── enrich/      Transformations that operate on Paper objects
│                (CrossRef BibTeX, metadata enrichment)
└── config.py    .env-based settings for optional API keys
```

Every source returns `Paper` objects with normalized fields and a
`source_raw` payload preserving the original response for debugging
or later re-parsing. This means new sources, new export formats, and
new enrichment passes all compose without changes to existing code.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project foundation, `Paper` dataclass, base abstractions | ✅ |
| 2 | arXiv source | ✅ |
| 3 | CrossRef enrichment (DOI → BibTeX, metadata) | ✅ |
| 4a | DBLP source | ✅ (search) / ⏳ (fetch_by_id — needs XML endpoint) |
| 4b | PubMed source via NCBI E-utilities | ✅ |
| 4c | IEEE Xplore source | ⏳ (API key activation pending) |
| 5a | Semantic Scholar source (with AI TLDR) | ✅ |
| 5b | OpenAlex source | ⏳ |
| 6 | Deduplication across sources (DOI > arxiv > fuzzy title) | ⏳ |
| 7 | CLI (`paper-collector search ...`) | ⏳ |
| 8 | Notion integration (read + write) | ⏳ |
| 9 | AI screening and summarization | ⏳ |

**Current state:** 4 working sources (arXiv, DBLP, PubMed, Semantic Scholar)
+ 1 enrichment module (CrossRef). 111 unit tests, 13 integration tests.
End-to-end pipelines working: search → Paper → BibTeX export.

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

Fetch from Semantic Scholar by DOI, arXiv ID, or PMID (useful for
cross-source enrichment; includes an AI-generated TLDR):

```python
from paper_collector.sources.semantic_scholar import SemanticScholarSource

ss = SemanticScholarSource()
# Fetch by DOI, arXiv ID, or PMID prefix — useful for enriching results.
paper = ss.fetch_by_id("ARXIV:2307.06207")
print(paper.title, paper.ai_summary)  # Includes AI-generated TLDR
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