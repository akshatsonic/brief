from unittest.mock import AsyncMock

import pytest

from daily_signal.scheduling import publish_with_retries


@pytest.mark.asyncio
async def test_scheduler_retries_then_succeeds() -> None:
    service = AsyncMock()
    service.publish.side_effect = [RuntimeError("temporary"), (None, None)]
    sleep = AsyncMock()
    await publish_with_retries(service, [1], sleep=sleep)
    assert service.publish.await_count == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_scheduler_exhausts_retries() -> None:
    service = AsyncMock()
    service.publish.side_effect = RuntimeError("still broken")
    with pytest.raises(RuntimeError, match="still broken"):
        await publish_with_retries(service, [1, 2], sleep=AsyncMock())
    assert service.publish.await_count == 3
