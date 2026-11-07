from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from daily_signal.config import AppConfig
from daily_signal.service import NewspaperService

log = logging.getLogger(__name__)


async def publish_with_retries(
    service: NewspaperService,
    delays: list[int],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    attempts = len(delays) + 1
    for attempt in range(attempts):
        try:
            await service.publish()
            return
        except Exception:
            if attempt == attempts - 1:
                raise
            delay = delays[attempt]
            log.exception("scheduled publication attempt %s failed; retrying in %ss", attempt + 1, delay)
            await sleep(delay)


def serve(config: AppConfig) -> None:
    zone = ZoneInfo(config.publication.timezone)
    scheduler = BlockingScheduler(timezone=zone)
    trigger = CronTrigger.from_crontab(config.publication.schedule, timezone=zone)

    def job() -> None:
        asyncio.run(
            publish_with_retries(
                NewspaperService(config), config.scheduler.retry_delays_seconds
            )
        )

    scheduler.add_job(
        job,
        trigger=trigger,
        id="daily-signal-publish",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=config.scheduler.misfire_grace_seconds,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=True)

