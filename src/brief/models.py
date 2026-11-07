from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Article(Model):
    id: str
    source_id: str
    title: str
    url: str
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    content_html: str | None = None
    content_text: str
    summary: str | None = None
    image_url: str | None = None
    image_media_type: str | None = None
    image_data: bytes | None = None
    watchouts: list[str] = Field(default_factory=list)
    important_points: list[str] = Field(default_factory=list)
    llm_curated: bool = False
    category: str | None = None
    language: str | None = None

    @field_validator("published_at", "fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("article datetimes must include a timezone")
        return value


class DiscoveredItem(Model):
    source_id: str
    url: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    content_html: str | None = None
    summary: str | None = None
    image_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EditionStatus(StrEnum):
    BUILDING = "building"
    BUILT = "built"
    DELIVERED = "delivered"
    FAILED = "failed"


class Edition(Model):
    id: str
    publication_name: str
    publication_date: date
    timezone: str
    language: str = "en"
    articles: list[Article]
    created_at: datetime
    status: EditionStatus = EditionStatus.BUILDING
    artifact_path: Path | None = None
    artifact_sha256: str | None = None

    @property
    def display_title(self) -> str:
        date_and_day = self.publication_date.strftime("%d %B %Y - %A")
        return f"{self.publication_name} : {date_and_day}"


class DeliveryStatus(StrEnum):
    DRY_RUN = "dry_run"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryResult(Model):
    provider: str
    status: DeliveryStatus
    message: str
    submitted_at: datetime | None = None


class BuildResult(Model):
    edition: Edition | None
    discovered_count: int
    selected_count: int
    artifact: Path | None = None
    normalized_articles: Path | None = None
    final_articles: Path | None = None
    diagnostics: list[str] = Field(default_factory=list)
