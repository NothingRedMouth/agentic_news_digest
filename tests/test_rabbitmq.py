import pytest
from unittest.mock import patch, AsyncMock
from rabbitmq.producer import publish_digest_task
from rabbitmq.worker import process_digest_task


@pytest.mark.asyncio
async def test_publish_digest_task():
    with patch("rabbitmq.producer._sync_publish") as mock_publish:
        await publish_digest_task()
        mock_publish.assert_called_once()


@pytest.mark.asyncio
async def test_process_digest_task_success(mocker):
    mock_tg = mocker.patch("rabbitmq.worker.TelegramSearch")
    mock_tg.return_value.run = AsyncMock(return_value=[{"text": "test"}])
    mock_web = mocker.patch("rabbitmq.worker.WebSearchExa")
    mock_web.return_value.run = AsyncMock(return_value=[])
    mock_agent = mocker.patch("rabbitmq.worker.LLMAgent")
    mock_agent.return_value.is_relevant = AsyncMock(return_value=True)
    mock_agent.return_value.summarize = AsyncMock(return_value="summary")
    mock_agent.return_value.create_digest = AsyncMock(return_value="digest")
    mock_bot = mocker.patch("rabbitmq.worker.NewsDigestBot")
    mock_bot.return_value.bot.send_message = AsyncMock()
    await process_digest_task({})
    mock_bot.return_value.bot.send_message.assert_called_once()
