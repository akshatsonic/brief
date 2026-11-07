import json
from datetime import UTC, date, datetime

from brief.exporting import write_normalized_articles
from brief.models import Article, Edition


def test_exports_normalized_articles_without_binary_image_data(tmp_path) -> None:
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Fixture story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_html="<p>Safe content</p>",
        content_text="Safe content",
        summary="Short summary",
        image_url="https://example.test/story.png",
        image_media_type="image/png",
        image_data=b"\x89PNG fixture",
        category="news",
    )
    edition = Edition(
        id="e" * 64,
        publication_name="The Brief",
        publication_date=date(2026, 11, 7),
        timezone="Asia/Kolkata",
        articles=[article],
        created_at=datetime.now(UTC),
    )

    path = write_normalized_articles(edition, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "the-brief-2026-11-07.articles.json"
    assert payload["edition"]["title"] == "The Brief : 07 November 2026 - Saturday"
    assert payload["article_count"] == 1
    assert payload["articles"][0]["image_url"] == "https://example.test/story.png"
    assert payload["articles"][0]["image_embedded"] is True
    assert "image_data" not in payload["articles"][0]
