from datetime import UTC, date, datetime

from brief.models import Article, Edition
from brief.rendering import PdfRenderer


def edition() -> Edition:
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Fixture story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_text="A concise summary of the fixture story.",
        summary="A concise summary of the fixture story.",
        image_url="https://example.test/story.png",
        image_media_type="image/png",
        image_data=b"\x89PNG\r\n\x1a\nfixture",
        category="Technology",
        important_points=["The first important point is supported by the source."],
        watchouts=["The reported figure has not been independently verified."],
        llm_curated=True,
    )
    return Edition(
        id="e" * 64,
        publication_name="The Brief",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[article],
        created_at=datetime.now(UTC),
    )


async def test_builds_kindle_sized_pdf_from_magazine_template(tmp_path) -> None:
    rendered = {}

    async def write_pdf(html, path):
        rendered["html"] = html
        path.write_bytes(b"%PDF-1.7 fixture")

    artifact = await PdfRenderer(pdf_writer=write_pdf).render(edition(), tmp_path)

    assert artifact.name == "the-brief-2026-11-07.pdf"
    assert artifact.read_bytes().startswith(b"%PDF")
    assert "Fixture story" in rendered["html"]
    assert "Important points" in rendered["html"]
    assert "Watchouts" in rendered["html"]
    assert "data:image/png;base64," in rendered["html"]
    assert "size: 6in 9in" in rendered["html"]


async def test_custom_stylesheet_overrides_pdf_theme(tmp_path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "style.css").write_text("body { color: #123456; }", encoding="utf-8")
    rendered = {}

    async def write_pdf(html, path):
        rendered["html"] = html
        path.write_bytes(b"%PDF-1.7 fixture")

    await PdfRenderer(template_directory=templates, pdf_writer=write_pdf).render(edition(), tmp_path)
    assert "#123456" in rendered["html"]
