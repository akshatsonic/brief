from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import feedparser

from daily_signal.config import FeedArticleMode, SourceConfig
from daily_signal.fetching import SafeFetcher
from daily_signal.models import Article, DiscoveredItem
from daily_signal.processing import deterministic_article_id, normalize_text, sanitize_html
from daily_signal.security import canonicalize_url


class SourceAdapter(Protocol):
    async def discover(self) -> list[DiscoveredItem]: ...

    async def extract(self, item: DiscoveredItem) -> Article: ...


class RssSourceAdapter:
    def __init__(self, source: SourceConfig, fetcher: SafeFetcher):
        self.source = source
        self.fetcher = fetcher

    async def discover(self) -> list[DiscoveredItem]:
        response = await self.fetcher.fetch(self.source.url, self.source)
        feed = feedparser.parse(response.body)
        if feed.bozo and not feed.entries:
            raise ValueError(f"invalid feed: {feed.bozo_exception}")
        items: list[DiscoveredItem] = []
        for entry in feed.entries:
            link = entry.get("link")
            if not link:
                continue
            content = _entry_content(entry)
            items.append(
                DiscoveredItem(
                    source_id=self.source.id,
                    url=urljoin(str(response.url), link),
                    title=entry.get("title"),
                    author=entry.get("author"),
                    published_at=_entry_date(entry),
                    content_html=content,
                    summary=entry.get("summary"),
                )
            )
        return items

    async def extract(self, item: DiscoveredItem) -> Article:
        html = item.content_html
        text = _html_text(html or "")
        should_fetch = self.source.fetch_article is FeedArticleMode.ALWAYS or (
            self.source.fetch_article is FeedArticleMode.AUTO and len(text.split()) < 80
        )
        title = item.title
        author = item.author
        published = item.published_at
        if should_fetch and self.source.fetch_article is not FeedArticleMode.NEVER:
            response = await self.fetcher.fetch(item.url, self.source)
            selected = _select_article_content(response, None)
            if selected:
                html = selected.html_content
                text = str(selected.get_all_text(separator="\n", strip=True))
            title = title or _select_text(response, "h1") or _meta(response, "og:title")
            author = author or _meta(response, "author")
            published = published or _extract_date(response, None)
        canonical = canonicalize_url(item.url)
        return Article(
            id=deterministic_article_id(self.source.id, canonical),
            source_id=self.source.id,
            title=normalize_text(title or canonical),
            url=canonical,
            author=author,
            published_at=published,
            fetched_at=datetime.now(UTC),
            content_html=sanitize_html(html, canonical),
            content_text=normalize_text(text or _html_text(item.summary or "")),
            summary=_html_text(item.summary or "") or None,
            category=self.source.category,
        )


class WebsiteSourceAdapter:
    def __init__(self, source: SourceConfig, fetcher: SafeFetcher):
        self.source = source
        self.fetcher = fetcher

    async def discover(self) -> list[DiscoveredItem]:
        current = self.source.url
        seen_pages: set[str] = set()
        found: dict[str, DiscoveredItem] = {}
        max_pages = self.source.pagination.max_pages if self.source.pagination else 1
        for _ in range(max_pages):
            if current in seen_pages:
                break
            seen_pages.add(current)
            response = await self.fetcher.fetch(current, self.source)
            selector = (
                self.source.discovery.article_links
                if self.source.discovery and self.source.discovery.article_links
                else "article a[href], main a[href]"
            )
            for link in response.css(selector):
                href = str(link.attrib.get("href", ""))
                if not href:
                    continue
                absolute = urljoin(str(response.url), href)
                if urlsplit(absolute).netloc != urlsplit(self.source.url).netloc:
                    continue
                canonical = canonicalize_url(absolute)
                found[canonical] = DiscoveredItem(
                    source_id=self.source.id,
                    url=canonical,
                    title=normalize_text(str(link.get_all_text(strip=True))) or None,
                )
            if not self.source.pagination:
                break
            next_links = response.css(self.source.pagination.next_selector)
            if not next_links:
                break
            href = next_links[0].attrib.get("href")
            if not href:
                break
            current = urljoin(str(response.url), str(href))
        return list(found.values())

    async def extract(self, item: DiscoveredItem) -> Article:
        response = await self.fetcher.fetch(item.url, self.source)
        extraction = self.source.extraction
        title_selector = extraction.title if extraction else None
        content_selector = extraction.content if extraction else None
        author_selector = extraction.author if extraction else None
        date_selector = extraction.date if extraction else None
        content = _select_article_content(response, content_selector)
        if content is None:
            raise ValueError(f"no article content found at {item.url}")
        title = (
            _select_text(response, title_selector)
            if title_selector
            else _meta(response, "og:title") or _select_text(response, "h1") or item.title
        )
        author = _select_text(response, author_selector) if author_selector else _meta(response, "author")
        published = _extract_date(response, date_selector)
        canonical = _canonical_from_page(response) or canonicalize_url(str(response.url))
        html = content.html_content
        text = str(content.get_all_text(separator="\n", strip=True))
        return Article(
            id=deterministic_article_id(self.source.id, canonical),
            source_id=self.source.id,
            title=normalize_text(title or canonical),
            url=canonical,
            author=normalize_text(author) if author else None,
            published_at=published,
            fetched_at=datetime.now(UTC),
            content_html=sanitize_html(html, canonical),
            content_text=normalize_text(text),
            category=self.source.category,
            language=_page_language(response),
        )


def adapter_for(source: SourceConfig, fetcher: SafeFetcher) -> SourceAdapter:
    if source.type.value == "rss":
        return RssSourceAdapter(source, fetcher)
    return WebsiteSourceAdapter(source, fetcher)


def _entry_content(entry) -> str | None:
    contents = entry.get("content") or []
    if contents:
        return contents[0].get("value")
    return entry.get("summary")


def _entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=UTC)
    raw = entry.get("published") or entry.get("updated")
    return _parse_date(raw)


def _select_article_content(response, selector: str | None):
    if selector:
        matches = response.css(selector)
        return matches[0] if matches else None
    candidates = []
    for candidate_selector in [
        '[itemprop="articleBody"]',
        ".post-content",
        ".entry-content",
        "article",
        "main",
        "body",
    ]:
        for candidate in response.css(candidate_selector):
            length = len(str(candidate.get_all_text(strip=True)))
            candidates.append((length, candidate))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _select_text(response, selector: str | None) -> str | None:
    if not selector:
        return None
    matches = response.css(selector)
    return normalize_text(str(matches[0].get_all_text(strip=True))) if matches else None


def _meta(response, name: str) -> str | None:
    selectors = [
        f'meta[property="{name}"]::attr(content)',
        f'meta[name="{name}"]::attr(content)',
    ]
    for selector in selectors:
        value = response.css(selector).get()
        if value:
            return normalize_text(str(value))
    return None


def _extract_date(response, selector: str | None) -> datetime | None:
    values: list[str | None] = []
    if selector:
        matches = response.css(selector)
        if matches:
            values.extend([matches[0].attrib.get("datetime"), str(matches[0].get_all_text(strip=True))])
    values.extend(
        [
            _meta(response, "article:published_time"),
            _meta(response, "datePublished"),
        ]
    )
    return next((parsed for value in values if (parsed := _parse_date(value))), None)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _canonical_from_page(response) -> str | None:
    value = response.css('link[rel="canonical"]::attr(href)').get()
    return canonicalize_url(urljoin(str(response.url), str(value))) if value else None


def _page_language(response) -> str | None:
    matches = response.css("html")
    return str(matches[0].attrib.get("lang")) if matches and matches[0].attrib.get("lang") else None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def _html_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return normalize_text(" ".join(parser.parts))

