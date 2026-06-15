import pytest
from unittest.mock import patch, AsyncMock
from scheduler.scheduler import scheduled_digest, setup_scheduler


@pytest.mark.asyncio
async def test_scheduled_digest():
    with patch("scheduler.scheduler.publish_digest_task", new=AsyncMock()) as mock_pub:
        await scheduled_digest()
        mock_pub.assert_called_once()


def test_setup_scheduler_with_interval():
    with patch.dict("os.environ", {"DIGEST_INTERVAL_DAYS": "3"}):
        from scheduler.scheduler import scheduler

        setup_scheduler()
        assert scheduler.get_job("digest_job") is not None


def test_setup_scheduler_disabled():
    with patch.dict("os.environ", {"DIGEST_INTERVAL_DAYS": "0"}):
        from scheduler.scheduler import scheduler

        setup_scheduler()
        assert scheduler.get_job("digest_job") is None
