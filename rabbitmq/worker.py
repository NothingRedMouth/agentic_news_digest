import os
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import aiofiles
from telethon import TelegramClient
from agent.llm_agent import LLMAgent
from agent.tools import FetchArticle
from rabbitmq.consumer import run_worker, unisender
from utils.google_sheets_logger import get_global_logger
from rabbitmq.producer import publish_email_task
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

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
client = TelegramClient("session_worker", API_ID, API_HASH)

_agent: Optional[LLMAgent] = None


def get_agent() -> LLMAgent:
    global _agent
    if _agent is None:
        _agent = LLMAgent()
    return _agent


async def update_status(posts_count: int, emails_count: int, error: str = None):
    status = {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_processed": posts_count,
        "email_processed": emails_count,
        "error": error or "Ошибок нет",
    }
    async with aiofiles.open(STATUS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(status, ensure_ascii=False, indent=4))


def extract_links(text: str) -> List[str]:
    return re.findall(r"https?://[^\s]+", text)


def is_older_than_days(date_str: str, days: int) -> bool:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days > days
    except:
        return True


def filter_by_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


async def fetch_posts_from_telegram() -> List[Dict]:
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


def extract_and_deduplicate_links(posts: List[Dict]) -> List[Dict]:
    seen = set()
    unique_links = []
    for post in posts:
        if not filter_by_keywords(post["text"]):
            continue
        for link in extract_links(post["text"]):
            if link not in seen:
                seen.add(link)
                unique_links.append(
                    {
                        "channel": post["channel"],
                        "post_date": post["date"],
                        "url": link,
                    }
                )
    return unique_links


async def fetch_article_wrapper(link_item: Dict) -> Optional[Dict]:
    fetcher = FetchArticle()
    text = await fetcher.run(link_item["url"])
    if not text or text.startswith("Ошибка:"):
        return None
    return {
        "url": link_item["url"],
        "title": "",
        "date": None,
        "text": text,
        "image": "",
        "channel": link_item["channel"],
        "post_date": link_item["post_date"],
    }


def is_article_valid(article: Dict) -> bool:
    if not article or not article.get("text"):
        return False
    date_to_check = article.get("date") or article.get("post_date")
    if not date_to_check:
        return False
    if is_older_than_days(date_to_check, DAYS_BACK):
        return False
    combined = article.get("text", "") + " " + article.get("title", "")
    if not filter_by_keywords(combined):
        return False
    return True


async def process_article(article_data: Dict, agent: LLMAgent) -> Optional[Dict]:
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


async def process_email_task(data: Dict):
    """
    Callback-обработчик для очереди 'email_digest'.
    Делает до 3-х попыток отправки через Unisender.
    """
    subject = data.get("subject", "Новостной дайджест")
    html_body = data.get("html_body", "")

    max_retries = 3
    last_error = ""

    for attempt in range(1, max_retries + 1):
        logger.info(f" Попытка массовой отправки email {attempt}/{max_retries}...")
        res = await unisender.send_mass_digest(subject, html_body)

        if res["success"]:
            logger.info(f"🚀 Рассылка успешно запущена! Campaign ID: {res['campaign_id']}")
            gs_logger.log(step="Email distribution success", status=f"Campaign {res['campaign_id']}")
            return
        else:
            last_error = res.get("error", "Unknown error")
            logger.warning(f"⚠️ Попытка {attempt} не удалась: {last_error}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)

    logger.error(f"❌ Не удалось отправить email-рассылку после {max_retries} попыток.")

    raise Exception(f"Unisender API failed: {last_error}")


async def process_digest_task(data: Dict):
    logger.info("Начинаем полный пайплайн дайджеста")
    agent = get_agent()

    try:
        posts = await fetch_posts_from_telegram()
        gs_logger.log(step="Posts fetched", status=f"Count {len(posts)}")
        unique_links = extract_and_deduplicate_links(posts)
        gs_logger.log(step="Links extracted", status=f"Unique {len(unique_links)}")
        if not unique_links:
            logger.info("Нет ссылок для обработки")
            await update_status(0)
            return

        sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async def process_one(link_item):
            async with sem:
                article = await fetch_article_wrapper(link_item)
                if not article:
                    return None
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

        deduped = await remove_semantic_duplicates(processed, agent)
        gs_logger.log(step="Semantic dedup", status=f"After dedup {len(deduped)}")
        ranked = sorted(deduped, key=lambda x: x["significance"], reverse=True)
        top10 = ranked[:MAX_TOP_ARTICLES]
        extra = ranked[MAX_TOP_ARTICLES : MAX_TOP_ARTICLES + MAX_EXTRA_ARTICLES]
        digest_html = generate_digest_html(top10, extra)
        gs_logger.log(step="Digest generated", summary=digest_html[:200], status="OK")

        from bot.bot import NewsDigestBot

        bot = NewsDigestBot()
        target_channel = bot.target_channel_id
        if not target_channel:
            logger.error("TELEGRAM_CHANNEL_ID не задан, отправка невозможна")
            await update_status(len(deduped), error="TELEGRAM_CHANNEL_ID отсутствует")
            return
        await bot.bot.send_message(
            chat_id=target_channel, text=digest_html, parse_mode="HTML"
        )

        current_date = datetime.now().strftime("%d.%m.%Y")
        subject = f"🔥 ИИ-Дайджест новостей за {current_date}"
        active_emails = await unisender.get_registered_emails()
        await publish_email_task(digest_html=digest_html, subject=subject)
        
        gs_logger.log(step="Digest sent to TG & Email Queue", status="OK")
        await update_status(len(deduped), len(active_emails))

    except Exception as e:
        logger.exception("Ошибка в пайплайне")
        gs_logger.log(step="Pipeline error", status=str(e))
        await update_status(0, 0, error=str(e))


async def start_worker():
    await run_worker(
        queue_name="digest_tasks",
        callback=process_digest_task,
        prefetch_count=1,
        dlx_name="digest_tasks.dlx",
    )
    await run_worker(
        queue_name="email_digest",
        callback=process_email_task,
        prefetch_count=1,
        dlx_name="email_digest.dlx",
    )
