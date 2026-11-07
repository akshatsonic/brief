from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Protocol

from ebooklib import epub
from jinja2 import Environment, PackageLoader, select_autoescape

from daily_signal.models import Edition


class Renderer(Protocol):
    def render(self, edition: Edition, destination: Path) -> Path: ...


class EpubRenderer:
    def __init__(self) -> None:
        self.environment = Environment(
            loader=PackageLoader("daily_signal", "templates"),
            autoescape=select_autoescape(["html", "xhtml", "xml"]),
        )

    def render(self, edition: Edition, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / f"{_slug(edition.publication_name)}-{edition.publication_date}.epub"
        book = epub.EpubBook()
        book.set_identifier(edition.id)
        book.set_title(edition.publication_name)
        book.set_language(edition.language)
        book.add_metadata("DC", "date", edition.publication_date.isoformat())
        css = epub.EpubItem(
            uid="classic",
            file_name="styles/classic.css",
            media_type="text/css",
            content=self.environment.get_template("classic.css").render().encode(),
        )
        book.add_item(css)
        cover = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=edition.language)
        cover.content = self.environment.get_template("cover.xhtml").render(edition=edition)
        cover.add_item(css)
        book.add_item(cover)
        spine: list = ["nav", cover]
        toc: list = []
        grouped: dict[str, list] = defaultdict(list)
        for article in edition.articles:
            grouped[article.category or "uncategorized"].append(article)
        for category, articles in grouped.items():
            section = epub.EpubHtml(
                title=category.title(), file_name=f"sections/{_slug(category)}.xhtml", lang=edition.language
            )
            section.content = self.environment.get_template("section.xhtml").render(
                category=category, articles=articles
            )
            section.add_item(css)
            book.add_item(section)
            spine.append(section)
            chapters = []
            for article in articles:
                chapter = epub.EpubHtml(
                    title=article.title,
                    file_name=f"articles/{article.id[:16]}.xhtml",
                    lang=article.language or edition.language,
                )
                chapter.content = self.environment.get_template("article.xhtml").render(article=article)
                chapter.add_item(css)
                book.add_item(chapter)
                spine.append(chapter)
                chapters.append(chapter)
            toc.append((epub.Section(category.title(), href=section.file_name), tuple(chapters)))
        book.toc = tuple(toc)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine
        epub.write_epub(str(artifact), book, {"epub3_pages": True})
        return artifact


def artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "edition"

