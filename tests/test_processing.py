from datetime import UTC, datetime, timedelta

import pytest

from brief.config import AppConfig
from brief.models import Article
from brief.processing import (
    EditorialPipeline,
    ProcessingContext,
    content_fingerprint,
    normalize_image_url,
    normalize_text,
    sanitize_html,
)
from brief.security import UnsafeUrlError, canonicalize_url, validate_public_url


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    assert canonicalize_url("HTTPS://Example.com:443/a?utm_source=x&b=2&a=1#part") == "https://example.com/a?a=1&b=2"


def test_rejects_private_destination() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("http://example.test", resolver=lambda _: ["127.0.0.1"])


def test_sanitizes_unsafe_markup() -> None:
    result = sanitize_html(
        '<p onclick="bad()">Hi<script>bad()</script><a href="javascript:x">x</a></p>',
        "https://example.test/story",
    )
    assert "script" not in result
    assert "onclick" not in result
    assert "javascript" not in result


def test_normalization_and_fingerprint_are_stable() -> None:
    assert normalize_text("  Hello\t world \n\n Again ") == "Hello world\nAgain"
    assert content_fingerprint("Hello   world") == content_fingerprint("Hello world")


def test_image_url_is_absolute_or_none() -> None:
    assert normalize_image_url("/images/story.jpg", "https://example.test/article") == (
        "https://example.test/images/story.jpg"
    )
    assert normalize_image_url("javascript:alert(1)", "https://example.test/article") is None
    assert normalize_image_url(None, "https://example.test/article") is None


def test_pipeline_deduplicates_and_orders() -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "Paper", "max_articles": 10},
            "sources": [
                {"id": "one", "name": "One", "type": "rss", "url": "https://one.test"},
                {"id": "two", "name": "Two", "type": "rss", "url": "https://two.test"},
            ],
            "editorial": {"min_content_words": 1, "categories": ["tech"]},
        }
    )
    now = datetime(2026, 1, 2, tzinfo=UTC)
    articles = [
        Article(
            id="x",
            source_id=source,
            title=title,
            url=url,
            fetched_at=now,
            published_at=now,
            content_text="same content",
            category="tech",
        )
        for source, title, url in [
            ("two", "Later source", "https://two.test/x"),
            ("one", "Preferred source", "https://one.test/x"),
        ]
    ]
    result = EditorialPipeline().process(articles, ProcessingContext(config, now))
    assert [article.source_id for article in result] == ["one"]


def test_pipeline_filters_stale_articles() -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "Paper"},
            "sources": [{"id": "one", "name": "One", "type": "rss", "url": "https://one.test"}],
            "editorial": {"min_content_words": 1, "max_age_hours": 24},
        }
    )
    now = datetime(2026, 1, 2, tzinfo=UTC)
    stale = Article(
        id="x",
        source_id="one",
        title="Old",
        url="https://one.test/old",
        fetched_at=now,
        published_at=now - timedelta(hours=25),
        content_text="content",
    )
    assert EditorialPipeline().process([stale], ProcessingContext(config, now)) == []


def test_llm_genre_allowlist_applies_after_model_categorization() -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "Morning", "max_articles": 10},
            "sources": [{"id": "feed", "name": "Feed", "type": "rss", "url": "https://feed.test/rss"}],
            "editorial": {"categories": ["technology"], "min_content_words": 1},
            "llm": {"enabled": True},
        }
    )
    now = datetime.now(UTC)
    article = Article(
        id="story-id",
        source_id="feed",
        title="Technology story",
        url="https://feed.test/story",
        fetched_at=now,
        content_text="A story body with enough words for processing.",
        category="engineering",
    )
    pipeline = EditorialPipeline()
    candidates = pipeline.process([article], ProcessingContext(config, now, selection_limit=10))
    edited = candidates[0].model_copy(update={"category": "Technology"})
    assert EditorialPipeline.filter_categories([edited], config.editorial.categories) == [edited]
