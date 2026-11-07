from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from brief.config import AppConfig, FetcherType
from brief.delivery import DeliveryError, provider_for
from brief.exporting import write_final_articles, write_normalized_articles
from brief.fetching import SafeFetcher
from brief.llm import EditorialError, EditorialProcessor, processor_for
from brief.models import BuildResult, Edition, EditionStatus
from brief.persistence import Database
from brief.processing import EditorialPipeline, ProcessingContext
from brief.rendering import PdfRenderer, Renderer, artifact_sha256
from brief.sources import adapter_for


class BuildError(RuntimeError):
    """An edition could not be built."""


class NewspaperService:
    def __init__(
        self,
        config: AppConfig,
        database: Database | None = None,
        fetcher: SafeFetcher | None = None,
        renderer: Renderer | None = None,
        editorial_processor: EditorialProcessor | None = None,
        editorial_backend: str | None = None,
    ):
        self.config = config
        self.database = database or Database(config.database.path)
        self.fetcher = fetcher or SafeFetcher(config.network)
        self.renderer = renderer or PdfRenderer(template_directory=config.output.template_directory)
        self.editorial_processor = editorial_processor or processor_for(config.llm, editorial_backend)

    async def build(self, publication_date: date | None = None, *, dry_run: bool = False) -> BuildResult:
        zone = ZoneInfo(self.config.publication.timezone)
        today = datetime.now(zone).date()
        target_date = publication_date or today
        cutoff = _cutoff(target_date, zone)
        if not dry_run:
            self.database.migrate()
            existing = self.database.load_edition(self.config.publication.name, target_date)
            if existing is not None and existing.articles and all(article.llm_curated for article in existing.articles):
                image_diagnostics: list[str] = []
                retried_images = False
                if self.config.output.include_images:
                    missing_images = [
                        article for article in existing.articles if article.image_url and not article.image_data
                    ]
                    if missing_images:
                        refreshed = await _embed_article_images(
                            missing_images, self.config, self.fetcher, image_diagnostics
                        )
                        by_id = {article.id: article for article in refreshed}
                        retried_images = any(article.image_data for article in refreshed)
                        existing = existing.model_copy(
                            update={
                                "articles": [by_id.get(article.id, article) for article in existing.articles]
                            }
                        )
                        if retried_images:
                            for article in refreshed:
                                self.database.save_article(article)
                            self.database.save_edition(existing)
                final_articles = write_final_articles(existing, self.config.output.directory)
                if (
                    existing.artifact_path
                    and existing.artifact_path.suffix.casefold() == ".pdf"
                    and existing.artifact_path.is_file()
                    and not retried_images
                ):
                    return BuildResult(
                        edition=existing,
                        discovered_count=0,
                        selected_count=len(existing.articles),
                        artifact=existing.artifact_path,
                        final_articles=final_articles,
                        diagnostics=["reused persisted edition", *image_diagnostics],
                    )
                if existing.articles:
                    artifact = await self.renderer.render(existing, self.config.output.directory)
                    existing = existing.model_copy(
                        update={
                            "artifact_path": artifact,
                            "artifact_sha256": artifact_sha256(artifact),
                        }
                    )
                    self.database.save_edition(existing)
                    return BuildResult(
                        edition=existing,
                        discovered_count=0,
                        selected_count=len(existing.articles),
                        artifact=artifact,
                        final_articles=final_articles,
                        diagnostics=["regenerated artifact from persisted edition", *image_diagnostics],
                    )
        diagnostics: list[str] = []
        articles = []
        enabled_sources = [source for source in self.config.sources if source.enabled]
        source_semaphore = asyncio.Semaphore(self.config.network.max_concurrent_sources)

        async def scrape_source(source):
            adapter = adapter_for(source, self.fetcher)
            async with source_semaphore:
                try:
                    items = await adapter.discover()
                    limited_items = items[: source.max_articles] if source.max_articles is not None else items
                    outcomes = await _extract_items(adapter, limited_items)
                    source_articles = []
                    source_diagnostics = []
                    for outcome in outcomes:
                        if isinstance(outcome, BaseException):
                            source_diagnostics.append(f"{source.id}: {type(outcome).__name__}: {outcome}")
                        else:
                            source_articles.append(outcome)
                    return len(items), source_articles, source_diagnostics
                except Exception as error:
                    return 0, [], [f"{source.id}: {type(error).__name__}: {error}"]

        source_results = await asyncio.gather(*(scrape_source(source) for source in enabled_sources))
        discovered_count = 0
        for source_discovered, source_articles, source_diagnostics in source_results:
            discovered_count += source_discovered
            articles.extend(source_articles)
            diagnostics.extend(source_diagnostics)
        selection_limit = max(self.config.publication.max_articles, self.config.llm.max_input_articles)
        selected = EditorialPipeline().process(
            articles,
            ProcessingContext(config=self.config, cutoff=cutoff, selection_limit=selection_limit),
        )
        if dry_run:
            return BuildResult(
                edition=None,
                discovered_count=discovered_count,
                selected_count=len(selected),
                diagnostics=diagnostics,
            )
        if not selected:
            raise BuildError("no qualifying articles were found; " + "; ".join(diagnostics[:3]))
        edition_id = hashlib.sha256(f"{self.config.publication.name}\n{target_date.isoformat()}".encode()).hexdigest()
        created_at = datetime.now(UTC)
        scraped_edition = Edition(
            id=edition_id,
            publication_name=self.config.publication.name,
            publication_date=target_date,
            timezone=self.config.publication.timezone,
            language=self.config.publication.language,
            articles=selected,
            created_at=created_at,
        )
        normalized_articles = write_normalized_articles(scraped_edition, self.config.output.directory)
        try:
            selected = await asyncio.to_thread(
                self.editorial_processor.process,
                selected,
                self.config.publication.max_articles,
            )
        except EditorialError as error:
            raise BuildError(str(error)) from error
        if not selected:
            raise BuildError(
                "the editorial model returned no articles from "
                f"{discovered_count} discovered items and "
                f"{len(scraped_edition.articles)} eligible candidates. "
                "Check the scraped JSON, source content quality, configured genre allowlist, and selected backend."
            )
        if self.config.editorial.categories:
            selected = EditorialPipeline.filter_categories(selected, self.config.editorial.categories)
            if not selected:
                raise BuildError(
                    "the editorial model selected stories, but none matched editorial.categories: "
                    + ", ".join(self.config.editorial.categories)
                    + ". Update the allowlist in brief.yaml or clear it to include all genres."
                )
        if self.config.output.include_images:
            selected = await _embed_article_images(selected, self.config, self.fetcher, diagnostics)
        self.database.migrate()
        self.database.sync_sources(self.config.sources)
        edition = Edition(
            id=edition_id,
            publication_name=self.config.publication.name,
            publication_date=target_date,
            timezone=self.config.publication.timezone,
            language=self.config.publication.language,
            articles=selected,
            created_at=created_at,
        )
        for article in selected:
            self.database.save_article(article)
        self.database.save_edition(edition)
        final_articles = write_final_articles(edition, self.config.output.directory)
        run_id = self.database.begin_run("build", edition_id)
        try:
            artifact = await self.renderer.render(edition, self.config.output.directory)
            edition = edition.model_copy(
                update={
                    "status": EditionStatus.BUILT,
                    "artifact_path": artifact,
                    "artifact_sha256": artifact_sha256(artifact),
                }
            )
            self.database.save_edition(edition)
            self.database.finish_run(
                run_id,
                "succeeded",
                stats={"discovered": discovered_count, "selected": len(selected)},
            )
        except Exception as error:
            self.database.finish_run(run_id, "failed", error=str(error))
            raise
        return BuildResult(
            edition=edition,
            discovered_count=discovered_count,
            selected_count=len(selected),
            artifact=artifact,
            normalized_articles=normalized_articles,
            final_articles=final_articles,
            diagnostics=diagnostics,
        )

    async def publish(
        self, publication_date: date | None = None, *, dry_run: bool = False
    ) -> tuple[BuildResult, object | None]:
        if dry_run:
            return await self.build(publication_date, dry_run=True), None
        self.database.migrate()
        owner = uuid.uuid4().hex
        if not self.database.acquire_lease("publish", owner, self.config.scheduler.lease_seconds):
            raise BuildError("another publication run is already active")
        run_id = self.database.begin_run("publish")
        try:
            result = await self.build(publication_date)
            assert result.edition is not None and result.artifact is not None
            edition = result.edition
            provider_name = self.config.delivery.provider
            if self.database.successful_delivery_exists(edition.id, provider_name):
                edition = edition.model_copy(update={"status": EditionStatus.DELIVERED})
                self.database.save_edition(edition)
                self.database.finish_run(run_id, "skipped", stats={"reason": "already delivered"})
                return result.model_copy(update={"edition": edition}), None
            try:
                delivery = provider_for(self.config.delivery).deliver(result.artifact, edition)
            except DeliveryError as error:
                self.database.record_delivery(edition.id, provider_name, "failed", str(error))
                raise
            self.database.record_delivery(edition.id, provider_name, delivery.status.value)
            edition = edition.model_copy(update={"status": EditionStatus.DELIVERED})
            self.database.save_edition(edition)
            self.database.finish_run(run_id, "succeeded")
            return result.model_copy(update={"edition": edition}), delivery
        except Exception as error:
            self.database.finish_run(run_id, "failed", error=str(error))
            raise
        finally:
            self.database.release_lease("publish", owner)


def _cutoff(target: date, zone: ZoneInfo) -> datetime:
    next_midnight = datetime.combine(target + timedelta(days=1), time.min, zone)
    now = datetime.now(zone)
    return min(now, next_midnight - timedelta(microseconds=1))


async def _extract_items(adapter, items):
    semaphore = asyncio.Semaphore(4)

    async def extract(item):
        async with semaphore:
            return await adapter.extract(item)

    return await asyncio.gather(*(extract(item) for item in items), return_exceptions=True)


async def _embed_article_images(articles, config: AppConfig, fetcher: SafeFetcher, diagnostics: list[str]):
    sources = {source.id: source for source in config.sources}
    hydrated = []
    limit = config.output.max_image_mb * 1024 * 1024
    for article in articles:
        source = sources.get(article.source_id)
        if not article.image_url or source is None:
            hydrated.append(article)
            continue
        try:
            image_source = source.model_copy(update={"fetcher": FetcherType.HTTP})
            response = await fetcher.fetch(article.image_url, image_source)
            media_type = _supported_image_type(response)
            if media_type is None:
                raise ValueError("image must be JPEG, PNG, or GIF")
            if len(response.body) > limit:
                raise ValueError(f"image exceeds {config.output.max_image_mb} MiB limit")
            hydrated.append(
                article.model_copy(update={"image_media_type": media_type, "image_data": bytes(response.body)})
            )
        except Exception as error:
            diagnostics.append(f"{article.source_id}: image skipped: {type(error).__name__}: {error}")
            hydrated.append(article)
    return hydrated


def _supported_image_type(response) -> str | None:
    header = response.headers.get("content-type") or response.headers.get("Content-Type") or ""
    media_type = str(header).split(";", 1)[0].strip().lower()
    body = bytes(response.body[:12])
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith(b"BM"):
        return "image/bmp"
    if body.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if len(body) >= 12 and body[4:8] == b"ftyp" and body[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    if media_type in {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }:
        return media_type
    return None
