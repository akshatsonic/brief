from __future__ import annotations

import base64
import hashlib
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, TemplateNotFound, select_autoescape

from brief.models import Edition


class Renderer(Protocol):
    async def render(self, edition: Edition, destination: Path) -> Path: ...


PdfWriter = Callable[[str, Path], Awaitable[None]]


class PdfRenderer:
    def __init__(self, template_directory: Path | None = None, pdf_writer: PdfWriter | None = None) -> None:
        loaders = []
        if template_directory is not None:
            loaders.append(FileSystemLoader(template_directory))
        loaders.append(PackageLoader("brief", "templates"))
        self.environment = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.pdf_writer = pdf_writer or _write_pdf_with_chromium

    async def render(self, edition: Edition, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / f"{_slug(edition.publication_name)}-{edition.publication_date}.pdf"
        html = self.environment.get_template("magazine.html").render(
            edition=edition,
            css=self._style_template().render(),
            article_images={article.id: _image_data_uri(article) for article in edition.articles},
        )
        await self.pdf_writer(html, artifact)
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise RuntimeError("PDF renderer did not create an artifact")
        return artifact

    def _style_template(self):
        try:
            return self.environment.get_template("style.css")
        except TemplateNotFound:
            return self.environment.get_template("magazine-pdf.css")


async def _write_pdf_with_chromium(html: str, artifact: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        executable = os.getenv("BRIEF_CHROMIUM_EXECUTABLE")
        browser = await playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(artifact),
                width="6in",
                height="9in",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await browser.close()


def _image_data_uri(article) -> str | None:
    if not article.image_data or article.image_media_type not in {"image/jpeg", "image/png", "image/gif"}:
        return None
    encoded = base64.b64encode(article.image_data).decode("ascii")
    return f"data:{article.image_media_type};base64,{encoded}"


def artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "edition"
