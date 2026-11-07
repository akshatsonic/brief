from datetime import UTC, date, datetime
from zipfile import ZipFile

from daily_signal.models import Article, Edition
from daily_signal.rendering import EpubRenderer


def test_builds_epub_with_navigation_and_article(tmp_path) -> None:
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Fixture story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_html="<p>Safe content</p>",
        content_text="Safe content",
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
    artifact = EpubRenderer().render(edition, tmp_path)
    assert artifact.exists()
    with ZipFile(artifact) as archive:
        names = archive.namelist()
        assert "mimetype" in names
        article_name = next(name for name in names if name.endswith("articles/aaaaaaaaaaaaaaaa.xhtml"))
        assert b"Fixture story" in archive.read(article_name)
