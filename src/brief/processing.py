from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import nh3

from brief.config import AppConfig, CategoryRule
from brief.models import Article
from brief.security import canonicalize_url

ALLOWED_TAGS = {
    "a",
    "abbr",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


def deterministic_article_id(source_id: str, url: str) -> str:
    value = f"{source_id}\n{canonicalize_url(url)}".encode()
    return hashlib.sha256(value).hexdigest()


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).casefold().encode()).hexdigest()


def normalize_text(text: str) -> str:
    text = unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def sanitize_html(content: str | None, base_url: str) -> str | None:
    if not content:
        return None
    cleaned = nh3.clean(
        content,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href", "title"}, "*": {"lang", "dir"}},
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    return re.sub(
        r'href="(/[^"#]*)"',
        lambda match: f'href="{urljoin(base_url, match.group(1))}"',
        cleaned,
    )


def normalize_image_url(value: object, base_url: str) -> str | None:
    if not value:
        return None
    absolute = urljoin(base_url, str(value).strip())
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ""))


@dataclass(frozen=True)
class ProcessingContext:
    config: AppConfig
    cutoff: datetime
    selection_limit: int | None = None


class Processor(Protocol):
    def process(self, articles: list[Article], context: ProcessingContext) -> list[Article]: ...


class EditorialPipeline:
    def process(self, articles: list[Article], context: ProcessingContext) -> list[Article]:
        normalized = [self._normalize(article) for article in articles]
        filtered = self._quality_and_age(normalized, context)
        categorized = [self._categorize(article, context.config) for article in filtered]
        # When LLM editorial is enabled, it assigns the canonical genre labels. Let it
        # see otherwise eligible stories first, then apply the configured genre allowlist.
        if context.config.editorial.categories and not context.config.llm.enabled:
            allowed = set(context.config.editorial.categories)
            categorized = [article for article in categorized if article.category in allowed]
        if context.config.editorial.deduplicate:
            categorized = self._deduplicate(categorized, context.config)
        ordered = sorted(categorized, key=lambda article: self._sort_key(article, context.config))
        return ordered[: context.selection_limit or context.config.publication.max_articles]

    @staticmethod
    def filter_categories(articles: list[Article], categories: list[str]) -> list[Article]:
        if not categories:
            return articles
        allowed = {category.casefold() for category in categories}
        return [article for article in articles if (article.category or "").casefold() in allowed]

    def _normalize(self, article: Article) -> Article:
        url = canonicalize_url(article.url)
        html = sanitize_html(article.content_html, url)
        return article.model_copy(
            update={
                "id": deterministic_article_id(article.source_id, url),
                "url": url,
                "title": normalize_text(article.title),
                "author": normalize_text(article.author) if article.author else None,
                "content_html": html,
                "content_text": normalize_text(article.content_text),
                "summary": normalize_text(article.summary) if article.summary else None,
                "image_url": normalize_image_url(article.image_url, url),
            }
        )

    def _quality_and_age(self, articles: Iterable[Article], context: ProcessingContext) -> list[Article]:
        oldest = context.cutoff - timedelta(hours=context.config.editorial.max_age_hours)
        minimum = context.config.editorial.min_content_words
        return [
            article
            for article in articles
            if article.title
            and len(article.content_text.split()) >= minimum
            and (
                article.published_at is None
                or oldest <= article.published_at.astimezone(context.cutoff.tzinfo) <= context.cutoff
            )
        ]

    def _categorize(self, article: Article, config: AppConfig) -> Article:
        for rule in config.editorial.category_rules:
            if _rule_matches(rule, article):
                return article.model_copy(update={"category": rule.category})
        return article.model_copy(update={"category": article.category or "uncategorized"})

    def _deduplicate(self, articles: list[Article], config: AppConfig) -> list[Article]:
        source_order = {source.id: index for index, source in enumerate(config.sources)}
        chosen: dict[str, Article] = {}
        for article in articles:
            keys = [f"url:{article.url}", f"content:{content_fingerprint(article.content_text)}"]
            duplicate = next((chosen[key] for key in keys if key in chosen), None)
            if duplicate is not None:
                candidate_key = (-len(article.content_text), source_order.get(article.source_id, 9999))
                current_key = (-len(duplicate.content_text), source_order.get(duplicate.source_id, 9999))
                if candidate_key >= current_key:
                    continue
                for key, value in list(chosen.items()):
                    if value.id == duplicate.id:
                        del chosen[key]
            for key in keys:
                chosen[key] = article
        unique = {article.id: article for article in chosen.values()}
        return list(unique.values())

    def _sort_key(self, article: Article, config: AppConfig) -> tuple:
        category_order = {name: index for index, name in enumerate(config.editorial.categories)}
        source_order = {source.id: index for index, source in enumerate(config.sources)}
        timestamp = article.published_at.timestamp() if article.published_at else float("-inf")
        return (
            category_order.get(article.category or "", len(category_order)),
            -timestamp,
            source_order.get(article.source_id, len(source_order)),
            article.title.casefold(),
            article.id,
        )


def _rule_matches(rule: CategoryRule, article: Article) -> bool:
    selectors = []
    if rule.source_ids:
        selectors.append(article.source_id in rule.source_ids)
    if rule.url_patterns:
        selectors.append(any(re.search(pattern, article.url) for pattern in rule.url_patterns))
    if rule.title_keywords:
        title = article.title.casefold()
        selectors.append(any(keyword.casefold() in title for keyword in rule.title_keywords))
    return bool(selectors) and any(selectors)
