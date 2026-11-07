from datetime import UTC, date, datetime

from brief.config import SourceConfig
from brief.models import Article, Edition, EditionStatus
from brief.persistence import Database


def test_persists_and_reloads_edition(tmp_path) -> None:
    database = Database(tmp_path / "state.db")
    database.migrate()
    source = SourceConfig(
        id="fixture", name="Fixture", type="rss", url="https://example.test/feed"
    )
    database.sync_sources([source])
    article = Article(
        id="a" * 64,
        source_id="fixture",
        title="Story",
        url="https://example.test/story",
        fetched_at=datetime.now(UTC),
        content_text="content",
    )
    edition = Edition(
        id="e" * 64,
        publication_name="Paper",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[article],
        created_at=datetime.now(UTC),
        status=EditionStatus.BUILT,
    )
    database.save_article(article)
    database.save_edition(edition)
    loaded = database.load_edition("Paper", date(2026, 11, 7))
    assert loaded is not None
    assert loaded.articles[0].title == "Story"


def test_delivery_and_lease_idempotency(tmp_path) -> None:
    database = Database(tmp_path / "state.db")
    database.migrate()
    source = SourceConfig(
        id="fixture", name="Fixture", type="rss", url="https://example.test/feed"
    )
    database.sync_sources([source])
    edition = Edition(
        id="e" * 64,
        publication_name="Paper",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[],
        created_at=datetime.now(UTC),
    )
    database.save_edition(edition)
    database.record_delivery(edition.id, "local", "succeeded")
    assert database.successful_delivery_exists(edition.id, "local")
    assert database.acquire_lease("publish", "first", 60)
    assert not database.acquire_lease("publish", "second", 60)
    database.release_lease("publish", "first")
    assert database.acquire_lease("publish", "second", 60)
