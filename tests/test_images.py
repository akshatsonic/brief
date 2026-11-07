from datetime import UTC, datetime
from types import SimpleNamespace

from brief.config import AppConfig
from brief.models import Article
from brief.service import _embed_article_images


class ImageFetcher:
    async def fetch(self, url, source):
        return SimpleNamespace(
            body=b"\x89PNG\r\n\x1a\nfixture",
            headers={"content-type": "image/png"},
        )


async def test_selected_image_is_validated_and_embedded() -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "Morning"},
            "sources": [{"id": "news", "name": "News", "type": "rss", "url": "https://example.test/rss"}],
        }
    )
    article = Article(
        id="a" * 64,
        source_id="news",
        title="Story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_text="content",
        image_url="https://example.test/story.png",
    )
    diagnostics = []
    result = await _embed_article_images([article], config, ImageFetcher(), diagnostics)
    assert diagnostics == []
    assert result[0].image_media_type == "image/png"
    assert result[0].image_data.startswith(b"\x89PNG")


async def test_invalid_selected_image_is_omitted() -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "Morning"},
            "sources": [{"id": "news", "name": "News", "type": "rss", "url": "https://example.test/rss"}],
        }
    )
    article = Article(
        id="a" * 64,
        source_id="news",
        title="Story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_text="content",
        image_url="https://example.test/not-an-image",
    )
    fetcher = ImageFetcher()
    fetcher.fetch = _invalid_fetch
    diagnostics = []
    result = await _embed_article_images([article], config, fetcher, diagnostics)
    assert result[0].image_data is None
    assert diagnostics and "image skipped" in diagnostics[0]


async def _invalid_fetch(url, source):
    return SimpleNamespace(body=b"not an image", headers={"content-type": "text/html"})
