"""Configuration loaded from environment variables.

API keys and other secrets are loaded from a `.env` file in the project
root. See `.env.example` for the expected variables.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment or `.env`.

    All API keys are optional at the type level so that sources can be
    used independently without configuring every one.

    Attributes:
        ieee_api_key: IEEE Xplore API key.
        ncbi_api_key: NCBI / PubMed API key.
        semantic_scholar_api_key: Semantic Scholar API key (optional).
        anthropic_api_key: Anthropic API key for AI screening.
        notion_token: Notion integration token.
        notion_database_id: Default Notion database for paper archive.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ieee_api_key: str | None = None
    ncbi_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    anthropic_api_key: str | None = None
    notion_token: str | None = None
    notion_database_id: str | None = None


def get_settings() -> Settings:
    """Return a fresh Settings instance."""
    return Settings()
