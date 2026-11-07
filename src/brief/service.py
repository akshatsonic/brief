from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from brief.config import AppConfig, FetcherType
from brief.delivery import DeliveryError, provider_for
from brief.fetching import SafeFetcher
from brief.models import BuildResult, Edition, EditionStatus
from brief.persistence import Database
from brief.processing import EditorialPipeline, ProcessingContext
from brief.rendering import EpubRenderer, artifact_sha256
from brief.sources import adapter_for


class BuildError(RuntimeError):
    """An edition could not be built."""


class NewspaperService:
    def __init__(
        self,
        config: AppConfig,
        database: Database | None = None,
        fetcher: SafeFetcher | None = None,
        renderer: EpubRenderer | None = None,
    ):
        self.config = config
        self.database = database or Database(config.database.path)
        self.fetcher = fetcher or SafeFetcher(config.network)
        self.renderer = renderer or EpubRenderer(
            theme=config.output.theme,
            template_directory=config.output.template_directory,
        )

    async def build(self, publication_date: date | None = None, *, dry_run: bool = False) -> BuildResult:
        zone = ZoneInfo(self.config.publication.timezone)
        today = datetime.now(zone).date()
        target_date = publication_date or today
        cutoff = _cutoff(target_date, zone)
        if not dry_run:
            self.database.migrate()
            existing = self.database.load_edition(self.config.publication.name, target_date)
            if existing is not None:
                if existing.artifact_path and existing.artifact_path.is_file():
                    return BuildResult(
                        edition=existing,
                        discovered_count=0,
                        selected_count=len(existing.articles),
                        artifact=existing.artifact_path,
                        diagnostics=["reused persisted edition"],
                    )
                if existing.articles:
                    artifact = self.renderer.render(existing, self.config.output.directory)
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
                        diagnostics=["regenerated artifact from persisted edition"],
                    )
        diagnostics: list[str] = []
        articles = []
        discovered_count = 0
        for source in self.config.sources:
            if not source.enabled:
                continue
            adapter = adapter_for(source, self.fetcher)
            try:
                items = await adapter.discover()
                discovered_count += len(items)
                outcomes = await _extract_items(adapter, items)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        diagnostics.append(f"{source.id}: {type(outcome).__name__}: {outcome}")
                    else:
                        articles.append(outcome)
            except Exception as error:
                diagnostics.append(f"{source.id}: {type(error).__name__}: {error}")
        selected = EditorialPipeline().process(articles, ProcessingContext(config=self.config, cutoff=cutoff))
        if dry_run:
            return BuildResult(
                edition=None,
                discovered_count=discovered_count,
                selected_count=len(selected),
                diagnostics=diagnostics,
            )
        if self.config.output.include_images:
            selected = await _embed_article_images(selected, self.config, self.fetcher, diagnostics)
        if not selected:
            raise BuildError("no qualifying articles were found; " + "; ".join(diagnostics[:3]))
        self.database.migrate()
        self.database.sync_sources(self.config.sources)
        edition_id = hashlib.sha256(f"{self.config.publication.name}\n{target_date.isoformat()}".encode()).hexdigest()
        edition = Edition(
            id=edition_id,
            publication_name=self.config.publication.name,
            publication_date=target_date,
            timezone=self.config.publication.timezone,
            language=self.config.publication.language,
            articles=selected,
            created_at=datetime.now(UTC),
        )
        for article in selected:
            self.database.save_article(article)
        self.database.save_edition(edition)
        run_id = self.database.begin_run("build", edition_id)
        try:
            artifact = self.renderer.render(edition, self.config.output.directory)
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
    if media_type in {"image/jpeg", "image/png", "image/gif"}:
        return media_type
    body = bytes(response.body[:12])
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None
