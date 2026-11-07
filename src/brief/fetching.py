from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from scrapling.fetchers import AsyncStealthySession, FetcherSession

from brief.config import FetcherType, NetworkConfig, SourceConfig
from brief.security import validate_public_url


class FetchError(RuntimeError):
    """A safe, user-facing fetch failure."""


class RobotsDeniedError(FetchError):
    """robots.txt does not allow this request."""


@dataclass
class SafeFetcher:
    config: NetworkConfig
    url_validator: Callable[[str], str] = validate_public_url
    _robots: dict[str, RobotFileParser] = field(default_factory=dict)
    _last_request: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def fetch(self, url: str, source: SourceConfig, *, check_robots: bool = True):
        safe_url = self.url_validator(url)
        if check_robots and self.config.respect_robots:
            await self._check_robots(safe_url, source)
        origin = _origin(safe_url)
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_request.get(origin, 0)
            if elapsed < source.request_delay_seconds:
                await asyncio.sleep(source.request_delay_seconds - elapsed)
            try:
                response = await self._request(safe_url, source.fetcher)
            except Exception as error:
                raise FetchError(f"request failed for {safe_url}: {type(error).__name__}: {error}") from error
            finally:
                self._last_request[origin] = time.monotonic()
        return self._validate_response(response, safe_url)

    async def _request(self, url: str, fetcher: FetcherType):
        if fetcher is FetcherType.BROWSER:

            async def guard_request(route) -> None:
                target = route.request.url
                if urlsplit(target).scheme in {"http", "https"}:
                    try:
                        self.url_validator(target)
                    except Exception:
                        await route.abort("blockedbyclient")
                        return
                await route.continue_()

            async def setup_page(page) -> None:
                await page.route("**/*", guard_request)

            async with AsyncStealthySession(
                headless=True,
                disable_resources=True,
                timeout=int(self.config.timeout_seconds * 1000),
                google_search=False,
                solve_cloudflare=False,
            ) as session:
                return await session.fetch(url, page_setup=setup_page)
        async with FetcherSession(
            timeout=self.config.timeout_seconds,
            retries=self.config.retries,
            follow_redirects="safe",
            headers={"User-Agent": self.config.user_agent},
        ) as session:
            return await session.get(url)

    def _validate_response(self, response, requested_url: str):
        status = int(response.status)
        if status < 200 or status >= 300:
            raise FetchError(f"HTTP {status} for {requested_url}")
        final_url = str(response.url)
        self.url_validator(final_url)
        body = response.body
        limit = self.config.max_response_mb * 1024 * 1024
        content_length = response.headers.get("content-length") or response.headers.get("Content-Length")
        if content_length and int(content_length) > limit:
            raise FetchError(f"response exceeds {self.config.max_response_mb} MiB limit")
        if len(body) > limit:
            raise FetchError(f"response exceeds {self.config.max_response_mb} MiB limit")
        return response

    async def _check_robots(self, url: str, source: SourceConfig) -> None:
        origin = _origin(url)
        parser = self._robots.get(origin)
        if parser is None:
            robots_url = urljoin(origin, "/robots.txt")
            try:
                response = await self._request(self.url_validator(robots_url), FetcherType.HTTP)
                self._last_request[origin] = time.monotonic()
                if len(response.body) > self.config.max_response_mb * 1024 * 1024:
                    raise FetchError("robots.txt exceeds response size limit")
                if response.status == 404:
                    lines: list[str] = []
                elif response.status in {401, 403}:
                    raise RobotsDeniedError(f"robots.txt denies access to {origin}")
                elif 200 <= response.status < 300:
                    lines = response.body.decode(response.encoding or "utf-8", errors="replace").splitlines()
                else:
                    raise FetchError(f"could not read robots.txt: HTTP {response.status}")
            except RobotsDeniedError:
                raise
            except Exception as error:
                raise FetchError(f"could not verify robots.txt for {origin}: {error}") from error
            parser = RobotFileParser(robots_url)
            parser.parse(lines)
            self._robots[origin] = parser
        if not parser.can_fetch(self.config.user_agent, url):
            raise RobotsDeniedError(f"robots.txt disallows {url}")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
