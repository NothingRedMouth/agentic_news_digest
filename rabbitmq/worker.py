import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict
import aiofiles
from newspaper import Article
from telethon import TelegramClient
from agent.llm_agent import LLMAgent
from rabbitmq.consumer import run_worker
from utils.google_sheets_logger import get_global_logger
from configs.digest_config import (
    TELEGRAM_CHANNELS,
    DAYS_BACK,
    MAX_POSTS_PER_CHANNEL,
    KEYWORDS,
    CATEGORIES,
    MAX_TOP_ARTICLES,
    MAX_EXTRA_ARTICLES,
    MAX_CONCURRENT_FETCHES,
    STATUS_FILE,
)

logger = logging.getLogger(__name__)
gs_logger = get_global_logger()

# --- Telegram client (один на весь воркер) ---
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
client = TelegramClient("session_worker", API_ID, API_HASH)


# ------------------- Вспомогательные функции -------------------
async def update_status(posts_count: int, error: str = None):
    """Асинхронно записывает статус в JSON-файл."""
    status = {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_processed": posts_count,
        "error": error or "Ошибок нет",
    }
    async with aiofiles.open(STATUS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(status, ensure_ascii=False, indent=4))


def extract_links(text: str) -> List[str]:
    """Извлекает все URL из текста."""
    return re.findall(r"https?://[^\s]+", text)


def is_older_than_days(date_str: str, days: int) -> bool:
    """Проверяет, что дата старше указанного числа дней."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days > days
    except:
        return True  # если дата не распарсилась, считаем старой


def filter_by_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


# ------------------- Шаг 1: получение постов -------------------
async def fetch_posts_from_telegram() -> List[Dict]:
    """Получает посты за последние DAYS_BACK дней из всех каналов."""
    await client.connect()
    time_threshold = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    all_posts = []
    for channel in TELEGRAM_CHANNELS:
        try:
            async for msg in client.iter_messages(channel, limit=MAX_POSTS_PER_CHANNEL):
                if msg.date < time_threshold:
                    break
                text = msg.text or msg.caption
                if text:
                    all_posts.append(
                        {
                            "channel": channel,
                            "date": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                            "text": text,
                        }
                    )
        except Exception as e:
            logger.error(f"Ошибка получения канала {channel}: {e}")
            gs_logger.log(step="Telegram fetch error", channel=channel, status=str(e))
    await client.disconnect()
    return all_posts


# ------------------- Шаги 2-3: извлечение и дедупликация ссылок -------------------
def extract_and_deduplicate_links(posts: List[Dict]) -> List[Dict]:
    """
    Извлекает все ссылки из постов и удаляет дубли.
    Возвращает список уникальных ссылок с информацией о канале и дате поста.
    """
    seen = set()
    unique_links = []
    for post in posts:
        for link in extract_links(post["text"]):
            if link not in seen:
                seen.add(link)
                unique_links.append(
                    {"channel": post["channel"], "post_date": post["date"], "url": link}
                )
    return unique_links


# ------------------- Шаг 4: загрузка статьи -------------------
async def fetch_article(url: str) -> Dict:
    """Загружает статью и извлекает метаданные, текст, изображение."""
    try:
        article = Article(url)
        await asyncio.to_thread(article.download)
        await asyncio.to_thread(article.parse)
        return {
            "url": url,
            "title": article.title or "",
            "date": article.publish_date.strftime("%Y-%m-%d %H:%M:%S")
            if article.publish_date
            else None,
            "text": article.text[:8000] if article.text else "",
            "image": article.top_image or "",
        }
    except Exception as e:
        logger.warning(f"Не удалось загрузить статью {url}: {e}")
        return None


# ------------------- Шаги 5-6: фильтрация по дате и ключевым словам -------------------
def is_article_valid(article: Dict) -> bool:
    if not article or not article.get("text"):
        return False
    if article.get("date"):
        if is_older_than_days(article["date"], DAYS_BACK):
            return False
    else:
        return False
    if not filter_by_keywords(article["text"] + " " + article.get("title", "")):
        return False
    return True


# ------------------- Шаги 7,10,11,12,13: обработка одной статьи через LLM -------------------
async def process_article(article_data: Dict, agent: LLMAgent) -> Dict:
    """
    Выполняет все AI-шаги для одной статьи.
    Возвращает обогащённый словарь или None при ошибке.
    """
    text = article_data.get("text", "")
    title = article_data.get("title", "")
    url = article_data.get("url", "")
    channel = article_data.get("channel", "unknown")

    try:
        summary = await agent.summarize(text)
        gs_logger.log(
            step="Summarize",
            channel=channel,
            url=url,
            summary=summary[:100],
            status="OK",
        )

        verified = await agent.verify_summary(summary)
        gs_logger.log(
            step="Verify", channel=channel, url=url, summary=verified[:100], status="OK"
        )

        formatted = await agent.highlight_key_elements(verified)
        gs_logger.log(
            step="Highlight",
            channel=channel,
            url=url,
            summary=formatted[:100],
            status="OK",
        )

        category = await agent.determine_category(formatted)
        if category not in CATEGORIES:
            category = "Другое"
        gs_logger.log(
            step="Category", channel=channel, url=url, category=category, status="OK"
        )

        significance_str = await agent.assess_significance(formatted)
        try:
            significance = float(significance_str)
        except:
            significance = 0.0
        gs_logger.log(
            step="Significance",
            channel=channel,
            url=url,
            significance=str(significance),
            status="OK",
        )

        return {
            "url": url,
            "title": title,
            "date": article_data.get("date"),
            "image": article_data.get("image", ""),
            "summary": formatted,
            "category": category,
            "significance": significance,
            "channel": channel,
        }
    except Exception as e:
        logger.error(f"Ошибка обработки статьи {url}: {e}")
        gs_logger.log(step="Processing error", channel=channel, url=url, status=str(e))
        return None


# ------------------- Шаг 9: удаление смысловых дублей -------------------
async def remove_semantic_duplicates(
    articles: List[Dict], agent: LLMAgent
) -> List[Dict]:
    if len(articles) < 2:
        return articles
    summaries = [a["summary"] for a in articles]
    groups = await agent.find_duplicates(summaries)
    to_remove = set()
    for group in groups:
        if len(group) > 1:
            for idx in group[1:]:
                to_remove.add(idx)
    return [a for i, a in enumerate(articles) if i not in to_remove]


# ------------------- Шаг 17: формирование выпуска -------------------
def generate_digest_html(top_articles: List[Dict], extra_articles: List[Dict]) -> str:
    lines = [
        "<b>📰 Еженедельный дайджест по биометрии и компьютерному зрению (РФ)</b>\n"
    ]
    for art in top_articles:
        lines.append(f"<b>Категория:</b> {art['category']}")
        lines.append(f"<b>{art['title']}</b>")
        lines.append(art["summary"])
        lines.append(f"<a href='{art['url']}'>🔗 Источник</a>\n")
    if extra_articles:
        lines.append("<b>📌 Что ещё произошло?</b>")
        for art in extra_articles:
            lines.append(f"• {art['title']} – <a href='{art['url']}'>читать</a>")
    return "\n".join(lines)


# ------------------- Основной обработчик задачи (вызывается из consumer) -------------------
async def process_digest_task(data: Dict):
    """Полный пайплайн дайджеста. Вызывается consumer'ом при получении сообщения."""
    logger.info("Начинаем полный пайплайн дайджеста")
    agent = LLMAgent()

    try:
        # Шаг 1
        posts = await fetch_posts_from_telegram()
        gs_logger.log(step="Posts fetched", status=f"Count {len(posts)}")

        # Шаги 2-3
        unique_links = extract_and_deduplicate_links(posts)
        gs_logger.log(step="Links extracted", status=f"Unique {len(unique_links)}")
        if not unique_links:
            logger.info("Нет ссылок для обработки")
            await update_status(0)
            return

        # Шаги 4-7,10-13 – параллельная обработка статей
        sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async def process_one(link_item):
            async with sem:
                article = await fetch_article(link_item["url"])
                if not article:
                    return None
                article["channel"] = link_item["channel"]
                if not is_article_valid(article):
                    return None
                return await process_article(article, agent)

        tasks = [process_one(item) for item in unique_links]
        raw_results = await asyncio.gather(*tasks)
        processed = [r for r in raw_results if r is not None]
        logger.info(f"Обработано статей: {len(processed)}")
        gs_logger.log(step="Articles processed", status=f"Count {len(processed)}")

        if not processed:
            logger.info("Нет статей, прошедших обработку")
            await update_status(0)
            return

        # Шаг 9: удаление смысловых дублей
        deduped = await remove_semantic_duplicates(processed, agent)
        gs_logger.log(step="Semantic dedup", status=f"After dedup {len(deduped)}")

        # Шаг 15: ранжирование по значимости
        ranked = sorted(deduped, key=lambda x: x["significance"], reverse=True)

        # Шаг 16: выбор TOP 10 и дополнительных
        top10 = ranked[:MAX_TOP_ARTICLES]
        extra = ranked[MAX_TOP_ARTICLES : MAX_TOP_ARTICLES + MAX_EXTRA_ARTICLES]

        # Шаг 17: формирование выпуска
        digest_html = generate_digest_html(top10, extra)
        gs_logger.log(step="Digest generated", summary=digest_html[:200], status="OK")

        # Шаг 18: отправка через Telegram бота
        from bot.bot import NewsDigestBot

        bot = NewsDigestBot()
        await bot.bot.send_message(
            chat_id=bot.target_channel_id, text=digest_html, parse_mode="HTML"
        )
        gs_logger.log(step="Digest sent", status="OK")

        await update_status(len(deduped))

    except Exception as e:
        logger.exception("Ошибка в пайплайне")
        gs_logger.log(step="Pipeline error", status=str(e))
        await update_status(0, error=str(e))


# ------------------- Точка входа для запуска воркера -------------------
async def main():
    """Запускает одного consumer'а для очереди digest_tasks."""
    await run_worker(
        queue_name="digest_tasks",
        callback=process_digest_task,
        prefetch_count=1,
        dlx_name="digest_tasks.dlx",
    )


if __name__ == "__main__":
    asyncio.run(main())
