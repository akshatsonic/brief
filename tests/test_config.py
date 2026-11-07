from pathlib import Path

import pytest
import yaml

from brief.config import ConfigurationError, load_config


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "brief.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_loads_defaults_and_resolves_paths(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        {
            "publication": {"name": "Morning", "timezone": "Asia/Kolkata"},
            "sources": [{"id": "news", "name": "News", "type": "rss", "url": "https://x.test/rss"}],
        },
    )
    config = load_config(path)
    assert config.publication.max_articles == 20
    assert config.output.directory == tmp_path / "output"
    assert config.database.path == tmp_path / ".brief/brief.db"


def test_rejects_duplicate_sources(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        {
            "publication": {"name": "Morning"},
            "sources": [
                {"id": "same", "name": "One", "type": "rss", "url": "https://x.test/a"},
                {"id": "same", "name": "Two", "type": "rss", "url": "https://x.test/b"},
            ],
        },
    )
    with pytest.raises(ConfigurationError, match="duplicate source IDs"):
        load_config(path)


def test_rejects_secrets(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        {
            "publication": {"name": "Morning"},
            "sources": [],
            "delivery": {"provider": "local", "password": "bad"},
        },
    )
    with pytest.raises(ConfigurationError, match="secrets are not allowed"):
        load_config(path)
