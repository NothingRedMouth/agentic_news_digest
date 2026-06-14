import pytest
import datetime
from unittest.mock import AsyncMock, MagicMock

from tools.telegram_search_news import TelegramSearchNews
from db.chroma_db_manager import ChromaDBManager


@pytest.mark.asyncio
async def test_text_and_caption_extraction(mocker):
    """Проверяем, что парсер берет message.text, а если его нет — message.caption."""
    
    mock_db = MagicMock(spec=ChromaDBManager)
    mock_db.save_posts.side_effect = lambda posts: posts
    mocker.patch('tools.telegram_search_news.ChromaDBManager', return_value=mock_db)

    msg_text = MagicMock()
    msg_text.id = 101
    msg_text.text = "Обычный текст новости"
    msg_text.caption = None
    msg_text.date = datetime.datetime.now(datetime.timezone.utc)

    msg_caption = MagicMock()
    msg_caption.id = 102
    msg_caption.text = None
    msg_caption.caption = "Подпись к фотографии"
    msg_caption.date = datetime.datetime.now(datetime.timezone.utc)

    msg_text_and_caption = MagicMock()
    msg_text_and_caption.id = 103
    msg_text_and_caption.text = "Обычный текст новости"
    msg_text_and_caption.caption = "Подпись к фотографии"
    msg_text_and_caption.date = datetime.datetime.now(datetime.timezone.utc)

    mock_iter = AsyncMock()
    mock_iter.__aiter__.return_value = [msg_text, msg_caption, msg_text_and_caption]
    
    mocker.patch('tools.telegram_search_news.client.iter_messages', return_value=mock_iter)
    mocker.patch('tools.telegram_search_news.client.is_connected', return_value=True)

    parser = TelegramSearchNews(channels=["test_channel"], max_results_per_channel=3, search_days=1)
    results = await parser.run()

    posts = results["test_channel"]
    
    assert len(posts) == 3
    assert posts[0]["text"] == "Обычный текст новости"
    assert posts[1]["text"] == "Подпись к фотографии"
    assert posts[2]["text"] == "Обычный текст новости"


@pytest.mark.asyncio
async def test_post_link_generation(mocker):
    """Проверяем, что ссылка на пост генерируется корректно, без лишних символов '@'."""
    
    mock_db = MagicMock(spec=ChromaDBManager)
    mock_db.save_posts.side_effect = lambda posts: posts
    mocker.patch('tools.telegram_search_news.ChromaDBManager', return_value=mock_db)

    msg = MagicMock()
    msg.id = 777
    msg.text = "Тестовый пост"
    msg.caption = None
    msg.date = datetime.datetime.now(datetime.timezone.utc)

    mock_iter = AsyncMock()
    mock_iter.__aiter__.return_value = [msg]
    mocker.patch('tools.telegram_search_news.client.iter_messages', return_value=mock_iter)
    mocker.patch('tools.telegram_search_news.client.is_connected', return_value=True)

    parser = TelegramSearchNews(channels=["@kommersant"], max_results_per_channel=1, search_days=1)
    results = await parser.run()

    expected_link = "https://t.me/kommersant/777"
    assert results["@kommersant"][0]["link"] == expected_link
