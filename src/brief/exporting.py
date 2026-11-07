from __future__ import annotations

import json
import re
from pathlib import Path

from brief.models import Edition


def write_normalized_articles(edition: Edition, destination: Path) -> Path:
    articles = []
    for article in edition.articles:
        normalized = article.model_dump(
            mode="json",
            exclude={"image_data", "watchouts", "important_points", "llm_curated"},
        )
        articles.append(normalized)
    return _write_collection(edition, destination, "scraped", articles)


def write_final_articles(edition: Edition, destination: Path) -> Path:
    articles = [
        {
            "id": article.id,
            "image": article.image_url,
            "heading": article.title,
            "text_summary": article.summary or article.content_text,
            "source_url": article.url,
            "genre": article.category or "Other",
            "watchouts": article.watchouts,
            "important_points": article.important_points,
        }
        for article in edition.articles
    ]
    return _write_collection(edition, destination, "articles", articles)


def _write_collection(edition: Edition, destination: Path, kind: str, articles: list[dict]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{_slug(edition.publication_name)}-{edition.publication_date}.{kind}.json"
    payload = {
        "schema_version": 1,
        "edition": {
            "id": edition.id,
            "title": edition.display_title,
            "publication_name": edition.publication_name,
            "publication_date": edition.publication_date.isoformat(),
            "timezone": edition.timezone,
            "language": edition.language,
        },
        "article_count": len(articles),
        "articles": articles,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "edition"
