from datetime import datetime, timedelta, timezone
from asyncio import sleep as asyncio_sleep
from json import load, dump
from os import getenv
from asyncio import run as asyncio_run
from pathlib import Path
from random import random
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from telethon import TelegramClient
from dotenv import load_dotenv

from db.chroma_db_manager import ChromaDBManager


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ID, HASH официальные, поэтому env не нужен 
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
STATUS_FILE = Path("configs/bot_status.json")

BOT_TOKEN = getenv("TELEGRAM_BOT_TOKEN")

client = TelegramClient('session_name', API_ID, API_HASH)


def update_status(posts_count: int, error: str = None):
    status = {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_processed": posts_count,
        "error": error or "Ошибок нет"
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        dump(status, f, ensure_ascii=False, indent=4)

    
class TelegramSearchNews(BaseModel):
    """Поиск новостей через Telegram."""

    channels: List[str] = Field(..., description="ТГ каналы для парсинга")
    max_results_per_channel: int = Field(5, description="Максимум результатов")
    search_days: int = Field(2, description="Сколько смотрим дней для джайстета")

    model_config = {"arbitrary_types_allowed": True}

    async def run(self, **kwargs) -> Dict[str, Any]:
        if not client.is_connected():
            await client.connect()
        
        time_threshold = datetime.now(timezone.utc) - timedelta(days=self.search_days)
        
        db = ChromaDBManager()
        results = {}
        total_posts_parsed = 0

        for idx, channel in enumerate(self.channels):
            channel_posts = []
            if idx > 0:
                # задержка опциональна, если мы не хотим бан аккаунта и у нас нет своих API_ID, API_HASH
                await asyncio_sleep(random() * 4 + 2)
            try:
                clean_channel = channel.lstrip('@')
                
                async for message in client.iter_messages(
                    clean_channel,
                    limit=self.max_results_per_channel
                ):
                    text = message.text or message.caption
                    if not text and message.date < time_threshold:
                        continue
                    
                    link = f"https://t.me/{clean_channel}/{message.id}"
                    
                    channel_posts.append({
                        "id": message.id,
                        "date": message.date.strftime("%Y-%m-%d %H:%M:%S"),
                        "text": text,
                        "link": link
                    })
                    
                new_posts = db.save_posts(clean_channel, channel_posts)
                
                total_posts_parsed += len(new_posts)
                results[channel] = new_posts

            except Exception as e:
                results[channel] = [{"title": f"Ошибка чтения канала {channel}: {str(e)}"}]
                update_status(total_posts_parsed, error=f"Ошибка в {channel}: {str(e)}")
        
        update_status(total_posts_parsed)
        return results
    

## Пример работы

async def test():
    await client.start()
    
    try:
        with open("./configs/channels.json", "r", encoding="utf-8") as f:
            config = load(f)
            target_channels = config.get("news_channels", [])
    except FileNotFoundError:
        print("Ошибка: Файл channels.json не найден! Использую список по умолчанию.")
        target_channels = ["durov"]

    search_tool = TelegramSearchNews(
        channels=target_channels,
        max_results_per_channel=10,
        search_days=2
    )
    res = await search_tool.run()
    await client.disconnect()
    return res

if __name__ == "__main__":
    print(asyncio_run(test()))
