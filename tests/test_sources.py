from pathlib import Path

from scrapling.parser import Selector

from brief.config import SourceConfig
from brief.models import DiscoveredItem
from brief.sources import RssSourceAdapter, WebsiteSourceAdapter

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, content: bytes | str, url: str):
        self.selector = Selector(content=content, url=url)
        self.body = content if isinstance(content, bytes) else content.encode()
        self.url = url

    def css(self, selector):
        return self.selector.css(selector)


class FakeFetcher:
    def __init__(self, pages: dict[str, bytes | str]):
        self.pages = pages

    async def fetch(self, url, source):
        return FakeResponse(self.pages[url], url)


async def test_rss_discovery_and_embedded_extraction() -> None:
    source = SourceConfig(
        id="feed",
        name="Feed",
        type="rss",
        url="https://example.test/feed.xml",
        fetch_article="never",
    )
    adapter = RssSourceAdapter(
        source,
        FakeFetcher({source.url: (FIXTURES / "feed.xml").read_bytes()}),
    )
    items = await adapter.discover()
    article = await adapter.extract(items[0])
    assert article.title == "A useful story"
    assert article.published_at is not None
    assert "complete fixture article" in article.content_text
    assert article.image_url == "https://example.test/images/story.jpg"


async def test_website_discovery_and_extraction() -> None:
    listing = "https://example.test/blog"
    story = "https://example.test/story"
    source = SourceConfig(
        id="site",
        name="Site",
        type="website",
        url=listing,
        discovery={"article_links": "article h2 a"},
        extraction={"content": "article", "date": "time"},
    )
    adapter = WebsiteSourceAdapter(
        source,
        FakeFetcher(
            {
                listing: (FIXTURES / "listing.html").read_text(),
                story: (FIXTURES / "article.html").read_text(),
            }
        ),
    )
    items = await adapter.discover()
    article = await adapter.extract(items[0])
    assert article.title == "Fixture Story"
    assert article.author == "Reporter"
    assert "clean local content" in article.content_text
    assert article.image_url == "https://example.test/images/fixture-story.jpg"


async def test_malformed_html_is_extracted_without_scripts() -> None:
    story = "https://example.test/broken"
    source = SourceConfig(
        id="broken",
        name="Broken",
        type="website",
        url="https://example.test",
        extraction={"content": "article", "title": "h1"},
    )
    adapter = WebsiteSourceAdapter(
        source,
        FakeFetcher({story: (FIXTURES / "malformed.html").read_text()}),
    )
    article = await adapter.extract(DiscoveredItem(source_id="broken", url=story))
    assert article.title == "Malformed story"
    assert "window.bad" not in (article.content_html or "")
    assert article.image_url is None
