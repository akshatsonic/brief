import json
from datetime import UTC, date, datetime

from brief.exporting import write_final_articles, write_normalized_articles
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
        important_points=["A major point."],
        watchouts=["A material caveat."],
        llm_curated=True,
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

    assert path.name == "the-brief-2026-11-07.scraped.json"
    assert payload["edition"]["title"] == "The Brief : 07 November 2026 - Saturday"
    assert payload["article_count"] == 1
    assert payload["articles"][0]["image_url"] == "https://example.test/story.png"
    assert "image_data" not in payload["articles"][0]
    assert "important_points" not in payload["articles"][0]

    final_path = write_final_articles(edition, tmp_path)
    final = json.loads(final_path.read_text(encoding="utf-8"))
    assert final_path.name == "the-brief-2026-11-07.articles.json"
    assert final["articles"][0] == {
        "id": "a" * 64,
        "image": "https://example.test/story.png",
        "heading": "Fixture story",
        "text_summary": "Short summary",
        "source_url": "https://example.test/story",
        "genre": "news",
        "watchouts": ["A material caveat."],
        "important_points": ["A major point."],
    }
