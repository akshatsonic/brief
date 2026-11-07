from __future__ import annotations

import json
import re
from pathlib import Path

from brief.models import Edition


def write_normalized_articles(edition: Edition, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{_slug(edition.publication_name)}-{edition.publication_date}.articles.json"
    articles = []
    for article in edition.articles:
        normalized = article.model_dump(mode="json", exclude={"image_data"})
        normalized["image_embedded"] = bool(article.image_data and article.image_media_type)
        articles.append(normalized)
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
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "edition"
