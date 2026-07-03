import pytest
from unittest.mock import AsyncMock, patch
from utils.unisender_client import UnisenderClient

@pytest.fixture
def unisender_client():
    return UnisenderClient(
        api_key="fake_key", 
        sender_email="news@example.com", 
        sender_name="News Agent", 
        list_id=12345
    )

@pytest.mark.asyncio
async def test_subscribe_success(unisender_client):
    """Проверка успешной подписки пользователя"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": {"person_id": "999"}})
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await unisender_client.subscribe(email="test@example.com")
        
        assert result["success"] is True
        assert result["result"]["person_id"] == "999"

@pytest.mark.asyncio
async def test_unsubscribe_success(unisender_client):
    """Проверка успешной отписки пользователя"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "unsubscribed"})
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await unisender_client.unsubscribe(email="test@example.com")
        
        assert result["success"] is True
        assert result["result"] == "unsubscribed"

@pytest.mark.asyncio
async def test_send_mass_digest_success(unisender_client):
    """Проверка полного цикла генерации и отправки массовой рассылки"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response_msg = AsyncMock()
        mock_response_msg.status = 200
        mock_response_msg.json = AsyncMock(return_value={"result": {"message_id": 777}})

        mock_response_camp = AsyncMock()
        mock_response_camp.status = 200
        mock_response_camp.json = AsyncMock(return_value={"result": {"campaign_id": 888, "status": "scheduled"}})
        mock_post.return_value.__aenter__.side_effect = [mock_response_msg, mock_response_camp]

        result = await unisender_client.send_mass_digest(
            subject="Недельный дайджест ИИ", 
            html_body="<h1>Новости</h1>"
        )
        
        assert result["success"] is True
        assert result["campaign_id"] == 888
        assert result["status"] == "scheduled"

@pytest.mark.asyncio
async def test_unisender_fallback_on_error(unisender_client):
    """Проверка корректной обработки ошибки, если Unisender API недоступен (HTTP 500)"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await unisender_client.send_mass_digest(
            subject="Тест ошибки", 
            html_body="текст"
        )
        
        assert result["success"] is False
        assert "HTTP status 500" in result["error"]
