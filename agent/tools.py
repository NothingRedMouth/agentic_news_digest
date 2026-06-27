import os
import hashlib
import time
from typing import List, Dict
from datetime import datetime, timedelta, timezone
import asyncio
from telethon import TelegramClient
from exa_py import Exa
from os import getenv
from newspaper import Article
from db.chroma_db_manager import ChromaDBManager
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
telegram_client = TelegramClient("session_agent", API_ID, API_HASH)


class RelevanceCache:
    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def get(self, text: str) -> bool | None:
        key = self._hash(text)
        entry = self.cache.get(key)
        if entry and entry["expires"] > time.time():
            return entry["value"]
        return None

    def set(self, text: str, value: bool):
        key = self._hash(text)
        self.cache[key] = {"value": value, "expires": time.time() + self.ttl}


class TelegramSearch:
    def __init__(self, channels: List[str], max_per_channel=10, search_days=10):
        self.channels = channels
        self.max_per_channel = max_per_channel
        self.time_threshold = datetime.now(timezone.utc) - timedelta(days=search_days)
        self.db = ChromaDBManager()

    async def _fetch_channel(self, channel: str) -> List[Dict]:
        clean = channel.lstrip("@")
        posts = []
        try:
            async for message in telegram_client.iter_messages(
                clean, limit=self.max_per_channel
            ):
                text = message.text or message.caption
                if not text:
                    continue
                if message.date < self.time_threshold:
                    continue
                posts.append(
                    {
                        "id": message.id,
                        "channel": clean,
                        "date": message.date.strftime("%Y-%m-%d %H:%M:%S"),
                        "text": text,
                        "link": f"https://t.me/{clean}/{message.id}",
                    }
                )
        except Exception as e:
            print(f"Ошибка канала {channel}: {e}")
        return posts

    async def run(self) -> List[Dict]:
        if not telegram_client.is_connected():
            await telegram_client.connect()
        semaphore = asyncio.Semaphore(3)

        async def limited_fetch(ch):
            async with semaphore:
                return await self._fetch_channel(ch)

        tasks = [limited_fetch(ch) for ch in self.channels]
        results = await asyncio.gather(*tasks)
        all_posts = [post for sublist in results for post in sublist]
        new_posts = self.db.save_posts(all_posts)
        return new_posts


class WebSearchExa:
    def __init__(self, query: str, max_results=5):
        self.query = query
        self.max_results = max_results
        self.exa = Exa(api_key=getenv("EXA_API_KEY"))

    async def run(self) -> List[Dict]:
        loop = asyncio.get_event_loop()

        def search():
            response = self.exa.search_and_contents(
                self.query, num_results=self.max_results, text=True
            )
            return [
                {"title": r.title, "url": r.url, "text": r.text[:5000]}
                for r in response.results
            ]

        return await loop.run_in_executor(None, search)


class FetchArticle:
    async def run(self, url: str) -> str:
        loop = asyncio.get_event_loop()

        def fetch():
            try:
                article = Article(url)
                article.download()
                article.parse()
                return article.text[:8000]
            except Exception as e:
                return f"Ошибка: {e}"

        return await loop.run_in_executor(None, fetch)
