"""BaseSource: abstract base class for all paper sources.

Each concrete source (arXiv, IEEE, PubMed, etc.) inherits from BaseSource
and implements `search` and `fetch_by_id`. The base class provides
configuration for rate limiting and logging that subclasses use.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from paper_collector.core.paper import Paper


@dataclass
class SourceConfig:
    """Configuration shared by all sources.

    Attributes:
        name: Source name (e.g., "arxiv", "ieee"). Used in logging and
            in Paper.source.
        rate_limit_per_second: Maximum requests per second. Conservative
            default of 1.0.
        max_retries: How many times to retry a failed request.
        timeout_seconds: HTTP request timeout.
    """

    name: str
    rate_limit_per_second: float = 1.0
    max_retries: int = 3
    timeout_seconds: float = 30.0


class BaseSource(ABC):
    """Abstract base class for paper sources.

    Subclasses implement source-specific logic in `search` and
    `fetch_by_id`. The base provides logging and configuration.
    """

    def __init__(self, config: SourceConfig) -> None:
        """Initialize the source.

        Args:
            config: Source configuration including name and rate limiting.
        """
        self.config = config
        self.logger = logging.getLogger(f"paper_collector.sources.{config.name}")

    @abstractmethod
    def search(self, query: str, max_results: int = 100) -> Iterator[Paper]:
        """Search the source for papers matching a query.

        Args:
            query: Search query string. Source-specific syntax may apply.
            max_results: Maximum number of papers to return.

        Yields:
            Paper objects, one at a time.
        """

    @abstractmethod
    def fetch_by_id(self, identifier: str) -> Paper | None:
        """Fetch a single paper by its source-specific identifier.

        Args:
            identifier: Source-specific ID (e.g., arXiv ID, DOI, PMID).

        Returns:
            A Paper if found, None otherwise.
        """
