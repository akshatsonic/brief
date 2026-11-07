from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


class ConfigurationError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


def _expand_path(value: Any) -> Any:
    return Path(value).expanduser() if value is not None else value


ConfigPath = Annotated[Path, BeforeValidator(_expand_path)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceType(StrEnum):
    RSS = "rss"
    WEBSITE = "website"


class FetcherType(StrEnum):
    HTTP = "http"
    BROWSER = "browser"


class FeedArticleMode(StrEnum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class DiscoveryConfig(StrictModel):
    article_links: str | None = None


class ExtractionConfig(StrictModel):
    title: str | None = None
    content: str | None = None
    author: str | None = None
    date: str | None = None


class PaginationConfig(StrictModel):
    next_selector: str
    max_pages: int = Field(default=2, ge=2, le=20)


class SourceConfig(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    type: SourceType
    url: str
    category: str | None = None
    enabled: bool = True
    fetcher: FetcherType = FetcherType.HTTP
    fetch_article: FeedArticleMode = FeedArticleMode.AUTO
    discovery: DiscoveryConfig | None = None
    extraction: ExtractionConfig | None = None
    pagination: PaginationConfig | None = None
    max_articles: int | None = Field(default=None, ge=1, le=500)
    request_delay_seconds: float = Field(default=1.0, ge=0, le=60)

    @field_validator("url")
    @classmethod
    def validate_url_shape(cls, value: str) -> str:
        if not re.match(r"^https?://", value, re.IGNORECASE):
            raise ValueError("must use an http:// or https:// URL")
        if "@" in value.split("//", 1)[-1].split("/", 1)[0]:
            raise ValueError("URLs containing credentials are not allowed")
        return value

    @model_validator(mode="after")
    def validate_type_fields(self) -> SourceConfig:
        if self.type is SourceType.RSS and any((self.discovery, self.extraction, self.pagination)):
            raise ValueError("RSS sources cannot define discovery, extraction, or pagination")
        return self


class PublicationConfig(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    timezone: str = "UTC"
    schedule: str = "0 7 * * *"
    max_articles: int = Field(default=20, ge=1, le=500)
    language: str = "en"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {value}") from error
        return value

    @field_validator("schedule")
    @classmethod
    def valid_schedule(cls, value: str) -> str:
        try:
            CronTrigger.from_crontab(value)
        except ValueError as error:
            raise ValueError("must be a valid five-field cron expression") from error
        return value


class CategoryRule(StrictModel):
    category: str
    source_ids: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)


class EditorialConfig(StrictModel):
    deduplicate: bool = True
    max_age_hours: int = Field(default=36, ge=1, le=8760)
    min_content_words: int = Field(default=40, ge=0, le=10000)
    categories: list[str] = Field(default_factory=list)
    category_rules: list[CategoryRule] = Field(default_factory=list)


class OutputConfig(StrictModel):
    format: Literal["pdf"] = "pdf"
    theme: Literal["magazine"] = "magazine"
    directory: ConfigPath = Path("./output")
    template_directory: ConfigPath | None = None
    include_images: bool = True
    max_image_mb: int = Field(default=5, ge=1, le=25)


class LlmConfig(StrictModel):
    enabled: bool = True
    backend: Literal["codex-api", "codex-cli"] = "codex-api"
    model: str = Field(default="gpt-6-astra", min_length=1, max_length=120)
    api_key_env: str = Field(default="OPENAI_API_KEY", pattern=r"^[A-Z][A-Z0-9_]*$")
    timeout_seconds: float = Field(default=120, ge=10, le=600)
    max_input_articles: int = Field(default=60, ge=1, le=200)
    codex_command: str = Field(default="codex", pattern=r"^[a-zA-Z0-9._/-]+$")
    codex_model: str | None = Field(default=None, min_length=1, max_length=120)


class DeliveryConfig(StrictModel):
    provider: Literal["local", "kindle"] = "local"
    kindle_email: str | None = None
    max_attachment_mb: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_kindle(self) -> DeliveryConfig:
        if self.provider == "kindle" and not self.kindle_email:
            raise ValueError("kindle_email is required for Kindle delivery")
        return self


class DatabaseConfig(StrictModel):
    path: ConfigPath = Path("./.brief/brief.db")


class NetworkConfig(StrictModel):
    timeout_seconds: float = Field(default=30, ge=1, le=120)
    max_response_mb: int = Field(default=10, ge=1, le=100)
    retries: int = Field(default=3, ge=0, le=10)
    max_concurrent_sources: int = Field(default=4, ge=1, le=32)
    user_agent: str = "Brief/0.1 (+https://github.com/brief)"
    respect_robots: bool = True


class SchedulerConfig(StrictModel):
    misfire_grace_seconds: int = Field(default=3600, ge=1)
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [60, 300, 900])
    lease_seconds: int = Field(default=7200, ge=60)


class AppConfig(StrictModel):
    publication: PublicationConfig
    sources: list[SourceConfig]
    editorial: EditorialConfig = Field(default_factory=EditorialConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    config_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def unique_sources(self) -> AppConfig:
        identifiers = [source.id for source in self.sources]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate source IDs: {', '.join(duplicates)}")
        known = set(identifiers)
        for rule in self.editorial.category_rules:
            unknown = set(rule.source_ids) - known
            if unknown:
                raise ValueError(f"category rule references unknown sources: {', '.join(unknown)}")
        return self

    def resolve_paths(self, config_path: Path) -> AppConfig:
        base = config_path.resolve().parent
        self.config_path = config_path.resolve()
        if not self.output.directory.is_absolute():
            self.output.directory = (base / self.output.directory).resolve()
        if self.output.template_directory and not self.output.template_directory.is_absolute():
            self.output.template_directory = (base / self.output.template_directory).resolve()
        if not self.database.path.is_absolute():
            self.database.path = (base / self.database.path).resolve()
        return self


def load_config(path: Path) -> AppConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file not found: {path}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be a YAML mapping")
    forbidden = {"password", "secret", "smtp_password", "api_key"}
    serialized_keys = {str(key).lower() for key in _walk_keys(raw)}
    present = sorted(forbidden & serialized_keys)
    if present:
        raise ConfigurationError(f"secrets are not allowed in YAML ({', '.join(present)}); use environment variables")
    try:
        return AppConfig.model_validate(raw).resolve_paths(path)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)
