from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    category: str | None = None
    language: str | None = None


class DiscoveredItem(Model):
    source_id: str
    url: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    content_html: str | None = None
    summary: str | None = None
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
    diagnostics: list[str] = Field(default_factory=list)

