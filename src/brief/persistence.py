from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from brief.config import SourceConfig
from brief.models import Article, Edition, EditionStatus
from brief.processing import content_fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    content_html TEXT,
    content_text TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    summary TEXT,
    category TEXT,
    language TEXT,
    UNIQUE(source_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS articles_url_idx ON articles(canonical_url);
CREATE INDEX IF NOT EXISTS articles_fingerprint_idx ON articles(content_fingerprint);
CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    publication_name TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    timezone TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    artifact_path TEXT,
    artifact_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(publication_name, publication_date)
);
CREATE TABLE IF NOT EXISTS edition_articles (
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    article_id TEXT NOT NULL REFERENCES articles(id),
    position INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY(edition_id, article_id),
    UNIQUE(edition_id, position)
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    edition_id TEXT REFERENCES editions(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error_summary TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS delivery_attempts (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id),
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error_summary TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_successful_delivery
ON delivery_attempts(edition_id, provider) WHERE status = 'succeeded';
CREATE TABLE IF NOT EXISTS leases (
    name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (_now(),),
            )

    def sync_sources(self, sources: list[SourceConfig]) -> None:
        with self.connect() as connection:
            for source in sources:
                connection.execute(
                    """INSERT INTO sources(id,type,name,url,config_json,updated_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,name=excluded.name,url=excluded.url,
                    config_json=excluded.config_json,updated_at=excluded.updated_at""",
                    (
                        source.id,
                        source.type.value,
                        source.name,
                        source.url,
                        source.model_dump_json(),
                        _now(),
                    ),
                )

    def save_article(self, article: Article) -> None:
        values = (
            article.id,
            article.source_id,
            article.title,
            article.url,
            article.url,
            article.author,
            _dt(article.published_at),
            _dt(article.fetched_at),
            article.content_html,
            article.content_text,
            content_fingerprint(article.content_text),
            article.summary,
            article.category,
            article.language,
        )
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO articles(
                id,source_id,title,url,canonical_url,author,published_at,fetched_at,
                content_html,content_text,content_fingerprint,summary,category,language
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,url=excluded.url,canonical_url=excluded.canonical_url,
                author=excluded.author,published_at=excluded.published_at,
                fetched_at=excluded.fetched_at,content_html=excluded.content_html,
                content_text=excluded.content_text,content_fingerprint=excluded.content_fingerprint,
                summary=excluded.summary,category=excluded.category,language=excluded.language""",
                values,
            )

    def save_edition(self, edition: Edition) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO editions(
                id,publication_name,publication_date,timezone,language,status,
                artifact_path,artifact_sha256,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,artifact_path=excluded.artifact_path,
                artifact_sha256=excluded.artifact_sha256,updated_at=excluded.updated_at""",
                (
                    edition.id,
                    edition.publication_name,
                    edition.publication_date.isoformat(),
                    edition.timezone,
                    edition.language,
                    edition.status.value,
                    str(edition.artifact_path) if edition.artifact_path else None,
                    edition.artifact_sha256,
                    _dt(edition.created_at),
                    _now(),
                ),
            )
            connection.execute("DELETE FROM edition_articles WHERE edition_id = ?", (edition.id,))
            connection.executemany(
                "INSERT INTO edition_articles(edition_id,article_id,position,category) VALUES(?,?,?,?)",
                [
                    (edition.id, article.id, index, article.category or "uncategorized")
                    for index, article in enumerate(edition.articles)
                ],
            )

    def find_edition(self, publication_name: str, publication_date: date) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM editions WHERE publication_name=? AND publication_date=?",
                (publication_name, publication_date.isoformat()),
            ).fetchone()

    def load_edition(self, publication_name: str, publication_date: date) -> Edition | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM editions WHERE publication_name=? AND publication_date=?",
                (publication_name, publication_date.isoformat()),
            ).fetchone()
            if row is None:
                return None
            article_rows = connection.execute(
                """SELECT a.* FROM articles a JOIN edition_articles ea ON ea.article_id=a.id
                WHERE ea.edition_id=? ORDER BY ea.position""",
                (row["id"],),
            ).fetchall()
        articles = [
            Article(
                id=item["id"],
                source_id=item["source_id"],
                title=item["title"],
                url=item["canonical_url"],
                author=item["author"],
                published_at=datetime.fromisoformat(item["published_at"]) if item["published_at"] else None,
                fetched_at=datetime.fromisoformat(item["fetched_at"]),
                content_html=item["content_html"],
                content_text=item["content_text"],
                summary=item["summary"],
                category=item["category"],
                language=item["language"],
            )
            for item in article_rows
        ]
        return Edition(
            id=row["id"],
            publication_name=row["publication_name"],
            publication_date=date.fromisoformat(row["publication_date"]),
            timezone=row["timezone"],
            language=row["language"],
            articles=articles,
            created_at=datetime.fromisoformat(row["created_at"]),
            status=EditionStatus(row["status"]),
            artifact_path=Path(row["artifact_path"]) if row["artifact_path"] else None,
            artifact_sha256=row["artifact_sha256"],
        )

    def begin_run(self, kind: str, edition_id: str | None = None) -> str:
        run_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO runs(id,kind,edition_id,started_at,status) VALUES(?,?,?,?,?)",
                (run_id, kind, edition_id, _now(), "running"),
            )
        return run_id

    def finish_run(self, run_id: str, status: str, *, error: str | None = None, stats: dict | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE runs SET finished_at=?,status=?,error_summary=?,stats_json=? WHERE id=?",
                (_now(), status, error, json.dumps(stats or {}), run_id),
            )

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall())

    def successful_delivery_exists(self, edition_id: str, provider: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM delivery_attempts WHERE edition_id=? AND provider=? AND status='succeeded'",
                (edition_id, provider),
            ).fetchone()
            return row is not None

    def record_delivery(self, edition_id: str, provider: str, status: str, error: str | None = None) -> str:
        attempt_id = uuid.uuid4().hex
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO delivery_attempts(
                id,edition_id,provider,started_at,finished_at,status,error_summary
                ) VALUES(?,?,?,?,?,?,?)""",
                (attempt_id, edition_id, provider, now, now, status, error),
            )
        return attempt_id

    def acquire_lease(self, name: str, owner: str, seconds: int) -> bool:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=seconds)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM leases WHERE name=? AND expires_at < ?", (name, _dt(now)))
            try:
                connection.execute(
                    "INSERT INTO leases(name,owner,expires_at) VALUES(?,?,?)",
                    (name, owner, _dt(expires)),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def release_lease(self, name: str, owner: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM leases WHERE name=? AND owner=?", (name, owner))


def _dt(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _now() -> str:
    return datetime.now(UTC).isoformat()
