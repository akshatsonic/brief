from datetime import UTC, date, datetime
from zipfile import ZipFile

from brief.models import Article, Edition
from brief.rendering import EpubRenderer


def test_builds_epub_with_navigation_and_article(tmp_path) -> None:
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Fixture story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_html="<p>Safe content</p>",
        content_text="Safe content",
        summary="A short fixture summary.",
        image_url="https://example.test/story.png",
        image_media_type="image/png",
        image_data=b"\x89PNG\r\n\x1a\nfixture",
        category="news",
    )
    edition = Edition(
        id="e" * 64,
        publication_name="Fixture Paper",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[article],
        created_at=datetime.now(UTC),
    )
    artifact = EpubRenderer(theme="magazine").render(edition, tmp_path)
    assert artifact.exists()
    with ZipFile(artifact) as archive:
        names = archive.namelist()
        assert "mimetype" in names
        article_name = next(name for name in names if name.endswith("articles/aaaaaaaaaaaaaaaa.xhtml"))
        article_markup = archive.read(article_name)
        assert b"Fixture story" in article_markup
        assert b"A short fixture summary" in article_markup
        assert b"../images/aaaaaaaaaaaaaaaa.png" in article_markup
        image_name = next(name for name in names if name.endswith("images/aaaaaaaaaaaaaaaa.png"))
        assert archive.read(image_name).startswith(b"\x89PNG")


def test_custom_stylesheet_overrides_theme(tmp_path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "style.css").write_text("body { color: #123456; }", encoding="utf-8")
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Fixture story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_text="Safe content",
    )
    edition = Edition(
        id="e" * 64,
        publication_name="Fixture Paper",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[article],
        created_at=datetime.now(UTC),
    )
    artifact = EpubRenderer(template_directory=templates).render(edition, tmp_path)
    with ZipFile(artifact) as archive:
        stylesheet = next(name for name in archive.namelist() if name.endswith("styles/theme.css"))
        assert b"#123456" in archive.read(stylesheet)
