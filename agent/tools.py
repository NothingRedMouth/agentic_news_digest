import os
import time
import asyncio
import logging
import re
import cloudscraper
from bs4 import BeautifulSoup
from trafilatura import extract
from telethon import TelegramClient
from telethon.tl.types import Message
from newspaper import Article, Config
from typing import Dict

logger = logging.getLogger(__name__)

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
telegram_client = TelegramClient("session", API_ID, API_HASH)


def clean_text(text: str) -> str:
    if not text:
        return text
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if re.match(
            r"^\s*(import|from|def|class|print|return|\w+\s*=|if\s|for\s|while\s|try\s|except\s|raise\s|with\s|async\s|await\s)",
            line,
        ):
            continue
        if "```" in line or "`" in line:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


class FetchArticle:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "mobile": False,
            }
        )
        self.scraper.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        self.timeout = 30
        self.max_retries = 3

    async def run(self, url: str) -> Dict[str, str]:
        if url.lower().endswith(".pdf"):
            return {"text": "", "title": "", "image": ""}
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_with_retries, url)

    def _fetch_with_retries(self, url: str) -> Dict[str, str]:
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.scraper.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    html = resp.text
                    if html and len(html) > 100:
                        title = self._extract_title(html)
                        image = self._extract_image(html)
                        text = extract(
                            html, include_comments=False, include_tables=False
                        )
                        if text and len(text) > 200:
                            return {
                                "text": clean_text(text[:8000]),
                                "title": title or "",
                                "image": image or "",
                            }
                        fallback = self._parse_with_fallback(html, url, title)
                        fallback["image"] = image or ""
                        return fallback
                    else:
                        logger.warning(
                            f"Empty or too short HTML for {url} (attempt {attempt})"
                        )
                else:
                    logger.warning(
                        f"HTTP {resp.status_code} for {url} (attempt {attempt})"
                    )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
            except Exception as e:
                logger.warning(f"Request error for {url} (attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                else:
                    logger.error(f"All retries failed for {url}: {e}")
        return {"text": "", "title": "", "image": ""}

    def _parse_with_fallback(self, html: str, url: str, title: str) -> Dict[str, str]:
        try:
            config = Config()
            config.browser_user_agent = self.scraper.headers["User-Agent"]
            config.request_timeout = self.timeout
            article = Article(url, config=config)
            article.download(input_html=html)
            article.parse()
            if article.text and len(article.text) > 200:
                return {
                    "text": clean_text(article.text[:8000]),
                    "title": article.title or title or "",
                }
        except Exception as e:
            logger.debug(f"Newspaper failed for {url}: {e}")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        if paragraphs:
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if len(text) > 200:
                return {"text": clean_text(text[:8000]), "title": title or ""}
        logger.warning(f"No meaningful text extracted from {url}")
        return {"text": "", "title": title or ""}

    def _extract_title(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.find("meta", property="og:title"):
                return soup.find("meta", property="og:title").get("content", "").strip()
            if soup.find("meta", property="twitter:title"):
                return (
                    soup.find("meta", property="twitter:title")
                    .get("content", "")
                    .strip()
                )
            if soup.title:
                return soup.title.string.strip()
        except:
            pass
        return ""

    def _extract_image(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.find("meta", property="og:image"):
                return soup.find("meta", property="og:image").get("content", "").strip()
            if soup.find("meta", property="twitter:image"):
                return (
                    soup.find("meta", property="twitter:image")
                    .get("content", "")
                    .strip()
                )
            img = soup.find("img")
            if img and img.get("src"):
                src = img.get("src")
                if src.startswith("//"):
                    src = "https:" + src
                return src
        except:
            pass
        return ""


class FetchTelegramPost:
    @staticmethod
    async def get_post_text(url: str) -> str:
        match = re.match(r"https?://t\.me/(?:c/)?([^/]+)/(\d+)", url)
        if not match:
            logger.warning(f"Не удалось разобрать URL: {url}")
            return ""

        entity, post_id = match.groups()
        post_id = int(post_id)

        if url.find("/c/") != -1:
            try:
                entity = int(entity)
            except ValueError:
                logger.warning(f"Некорректный ID канала в URL: {url}")
                return ""
        else:
            entity = entity.lstrip("@")

        if not telegram_client.is_connected():
            logger.warning("Telegram client не подключён, пробуем подключить...")
            await telegram_client.connect()

        try:
            messages = await telegram_client.get_messages(entity, ids=post_id)
            if not messages:
                logger.warning(f"Нет сообщения по ID {post_id} в {entity}")
                async for msg in telegram_client.iter_messages(entity, ids=post_id):
                    if msg:
                        messages = [msg]
                        break
                if not messages:
                    return ""

            msg = messages[0] if isinstance(messages, list) else messages
            if not isinstance(msg, Message):
                logger.warning(f"Получен не Message для {url}: {type(msg)}")
                return ""

            text = msg.text or msg.caption or ""
            if not text:
                logger.info(f"Пост {url} не содержит текста")
            return clean_text(text[:8000])

        except Exception as e:
            logger.warning(f"Ошибка получения поста {url}: {type(e).__name__}: {e}")
            return ""
