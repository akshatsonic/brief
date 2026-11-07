from datetime import UTC, date, datetime

from brief.config import AppConfig
from brief.models import Article, DiscoveredItem
from brief.service import NewspaperService


class FixtureAdapter:
    async def discover(self):
        return [DiscoveredItem(source_id="fixture", url="https://example.test/story")]

    async def extract(self, item):
        return Article(
            id="a" * 64,
            source_id="fixture",
            title="Fixture story",
            url=item.url,
            fetched_at=datetime.now(UTC),
            content_text="A sufficiently detailed fixture article for the end-to-end build test.",
        )


class FixtureEditorialProcessor:
    def process(self, articles, max_articles):
        return [
            articles[0].model_copy(
                update={
                    "title": "Edited fixture story",
                    "summary": "A concise edited summary based only on the fixture article.",
                    "content_text": "A concise edited summary based only on the fixture article.",
                    "category": "Technology",
                    "important_points": ["The fixture demonstrates the complete pipeline."],
                    "watchouts": [],
                    "llm_curated": True,
                }
            )
        ]


class FixtureRenderer:
    async def render(self, edition, destination):
        artifact = destination / f"the-brief-{edition.publication_date}.pdf"
        artifact.write_bytes(b"%PDF-1.7 fixture")
        return artifact


async def test_build_runs_scraper_editorial_export_and_pdf_pipeline(tmp_path, monkeypatch) -> None:
    config = AppConfig.model_validate(
        {
            "publication": {"name": "The Brief", "max_articles": 10},
            "sources": [{"id": "fixture", "name": "Fixture", "type": "rss", "url": "https://example.test/rss"}],
            "editorial": {"min_content_words": 0},
            "output": {"directory": tmp_path / "output", "include_images": False},
            "database": {"path": tmp_path / "brief.db"},
        }
    )
    monkeypatch.setattr("brief.service.adapter_for", lambda source, fetcher: FixtureAdapter())
    service = NewspaperService(
        config,
        renderer=FixtureRenderer(),
        editorial_processor=FixtureEditorialProcessor(),
    )

    result = await service.build(date(2026, 11, 7))

    assert result.artifact and result.artifact.read_bytes().startswith(b"%PDF")
    assert result.normalized_articles and result.normalized_articles.name.endswith(".scraped.json")
    assert result.final_articles and result.final_articles.name.endswith(".articles.json")
    assert result.edition and result.edition.articles[0].llm_curated is True
