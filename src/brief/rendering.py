from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Protocol

from ebooklib import epub
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, TemplateNotFound, select_autoescape

from brief.models import Edition


class Renderer(Protocol):
    def render(self, edition: Edition, destination: Path) -> Path: ...


class EpubRenderer:
    def __init__(self, theme: str = "magazine", template_directory: Path | None = None) -> None:
        loaders = []
        if template_directory is not None:
            loaders.append(FileSystemLoader(template_directory))
        loaders.append(PackageLoader("brief", "templates"))
        self.environment = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xhtml", "xml"]),
        )
        self.theme = theme

    def render(self, edition: Edition, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / f"{_slug(edition.publication_name)}-{edition.publication_date}.epub"
        book = epub.EpubBook()
        book.set_identifier(edition.id)
        book.set_title(edition.publication_name)
        book.set_language(edition.language)
        book.add_metadata("DC", "date", edition.publication_date.isoformat())
        css = epub.EpubItem(
            uid=f"theme-{self.theme}",
            file_name="styles/theme.css",
            media_type="text/css",
            content=self._style_template().render().encode(),
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
                category=category,
                articles=articles,
                article_hrefs={article.id: f"../articles/{article.id[:16]}.xhtml" for article in articles},
            )
            section.add_item(css)
            book.add_item(section)
            spine.append(section)
            chapters = []
            for article in articles:
                image_href = None
                if article.image_data and article.image_media_type in _IMAGE_EXTENSIONS:
                    extension = _IMAGE_EXTENSIONS[article.image_media_type]
                    image_name = f"images/{article.id[:16]}.{extension}"
                    book.add_item(
                        epub.EpubImage(
                            uid=f"image-{article.id[:16]}",
                            file_name=image_name,
                            media_type=article.image_media_type,
                            content=article.image_data,
                        )
                    )
                    image_href = f"../{image_name}"
                chapter = epub.EpubHtml(
                    title=article.title,
                    file_name=f"articles/{article.id[:16]}.xhtml",
                    lang=article.language or edition.language,
                )
                chapter.content = self.environment.get_template("article.xhtml").render(
                    article=article,
                    image_href=image_href,
                )
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

    def _style_template(self):
        try:
            return self.environment.get_template("style.css")
        except TemplateNotFound:
            return self.environment.get_template(f"{self.theme}.css")


def artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "edition"


_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
}
