"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_collector.config import Settings


def test_settings_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no env vars set and no .env, all settings are None."""
    monkeypatch.chdir(tmp_path)
    for key in [
        "IEEE_API_KEY",
        "NCBI_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        "ANTHROPIC_API_KEY",
        "NOTION_TOKEN",
        "NOTION_DATABASE_ID",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings()
    assert settings.ieee_api_key is None
    assert settings.ncbi_api_key is None
    assert settings.anthropic_api_key is None


def test_settings_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings picks up environment variables."""
    monkeypatch.setenv("IEEE_API_KEY", "test-key-123")
    settings = Settings()
    assert settings.ieee_api_key == "test-key-123"


def test_settings_reads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads from a local .env file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IEEE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("IEEE_API_KEY=from-dotenv\n")

    settings = Settings()
    assert settings.ieee_api_key == "from-dotenv"
