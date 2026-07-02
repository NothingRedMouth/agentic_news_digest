import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import aiofiles
import markdown
from agent.llm_agent import LLMAgent
from agent.tools import FetchArticle, FetchTelegramPost, telegram_client
from rabbitmq.consumer import run_worker
from rabbitmq.producer import publish_email_task
from utils.google_sheets_logger import get_global_logger
from utils.unisender_client import UnisenderClient
from configs.digest_config import (
    TELEGRAM_CHANNELS,
    DAYS_BACK,
    MAX_POSTS_PER_CHANNEL,
    MAX_CONCURRENT_FETCHES,
    STATUS_FILE,
)
from ytelegraph import TelegraphAPI
from os import getenv

logger = logging.getLogger(__name__)
gs_logger = get_global_logger()

_agent: Optional[LLMAgent] = None
TELEGRAM_URL_PATTERN = re.compile(r"https?://t\.me/")

unisender = UnisenderClient(
    api_key=getenv("UNISENDER_API_KEY", ""),
    sender_email=getenv("UNISENDER_SENDER_EMAIL", ""),
    sender_name=getenv("UNISENDER_SENDER_NAME", ""),
    list_id=int(getenv("UNISENDER_LIST_ID", 0)),
)


def get_agent() -> LLMAgent:
    global _agent
    if _agent is None:
        _agent = LLMAgent()
    return _agent


async def update_status(posts_count: int, error: str = None):
    status = {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_processed": posts_count,
        "error": error or "Ошибок нет",
    }
    async with aiofiles.open(STATUS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(status, ensure_ascii=False, indent=4))


def extract_links(text: str) -> List[str]:
    raw_links = re.findall(r"https?://[^\s]+", text)
    cleaned = []
    for link in raw_links:
        cleaned_link = re.sub(r"[.,;:!?)]+$", "", link)
        if cleaned_link:
            cleaned.append(cleaned_link)
    return cleaned


async def fetch_posts_from_telegram() -> List[Dict]:
    time_threshold = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    all_posts = []
    for channel in TELEGRAM_CHANNELS:
        try:
            async for msg in telegram_client.iter_messages(
                channel, limit=MAX_POSTS_PER_CHANNEL
            ):
                if msg.date < time_threshold:
                    break
                text = msg.text or (msg.caption if hasattr(msg, "caption") else None)
                if text:
                    all_posts.append(
                        {
                            "channel": channel,
                            "date": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                            "text": text,
                            "id": msg.id,
                        }
                    )
        except Exception as e:
            logger.error(f"Ошибка получения канала {channel}: {e}")
            gs_logger.log(
                step="Ошибка получения Telegram",
                status="ERROR",
                message=f"Канал {channel}: {e}",
            )
    return all_posts


async def fetch_article_wrapper(link_item: Dict) -> Optional[Dict]:
    url = link_item["url"]
    if TELEGRAM_URL_PATTERN.match(url):
        text = await FetchTelegramPost.get_post_text(url)
        title = ""
        image = ""
        if not text:
            logger.warning(
                f"Не удалось получить текст из Telegram-поста {url}, пробуем как веб-страницу"
            )
            fetcher = FetchArticle()
            result = await fetcher.run(url)
            text = result.get("text", "")
            title = result.get("title", "")
            image = result.get("image", "")
    else:
        fetcher = FetchArticle()
        result = await fetcher.run(url)
        text = result.get("text", "")
        title = result.get("title", "")
        image = result.get("image", "")

    if not text:
        return None

    return {
        "url": url,
        "title": title,
        "date": None,
        "text": text,
        "image": image,
        "channel": link_item["channel"],
        "post_date": link_item["post_date"],
    }


async def publish_to_telegraph(title: str, content: str) -> Optional[str]:
    try:
        telegraph = TelegraphAPI()
        page_url = telegraph.create_page_md(title, content)
        logger.info(f"Статья опубликована на Telegra.ph: {page_url}")
        return page_url
    except Exception as e:
        logger.error(f"Ошибка публикации на Telegra.ph: {e}")
        return None


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
        gs_logger.log(step="Email sending start", status=f"Attempt {attempt}")
        res = await unisender.send_mass_digest(subject, html_body)

        if res["success"]:
            logger.info(f"Рассылка успешно запущена! Campaign ID: {res['campaign_id']}")
            gs_logger.log(
                step="Email distribution success",
                status=f"Campaign {res['campaign_id']}",
            )
            return
        else:
            last_error = res.get("error", "Unknown error")
            logger.warning(f"⚠️ Попытка {attempt} не удалась: {last_error}")
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)

    logger.error(f"❌ Не удалось отправить email-рассылку после {max_retries} попыток.")
    gs_logger.log(
        step="Processing error",
        status=f"Campaign crashed after {max_retries} attempts.",
    )
    raise Exception(f"Unisender API failed: {last_error}")


async def process_digest_task(data: Dict):
    logger.info("Начинаем упрощённый пайплайн дайджеста")
    agent = get_agent()

    await telegram_client.connect()
    try:
        posts = await fetch_posts_from_telegram()
        gs_logger.log(
            step="Получение постов",
            status="OK",
            message=f"Количество постов: {len(posts)}",
        )

        all_sources = []
        MAX_LINKS_PER_POST = 3
        for post in posts:
            all_sources.append(
                {
                    "title": f"Пост из {post['channel']}",
                    "text": post["text"],
                    "date": post["date"],
                    "url": f"https://t.me/{post['channel']}/{post['id']}",
                    "image": "",
                }
            )
            links = extract_links(post["text"])
            if links:
                links = links[:MAX_LINKS_PER_POST]
                sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

                async def process_link(link):
                    async with sem:
                        article = await fetch_article_wrapper(
                            {
                                "url": link,
                                "channel": post["channel"],
                                "post_date": post["date"],
                            }
                        )
                        if article and article.get("text"):
                            return {
                                "title": article.get("title", "Без заголовка"),
                                "text": article["text"],
                                "date": article.get("date") or post["date"],
                                "url": link,
                                "image": article.get("image", ""),
                            }
                        return None

                tasks = [process_link(link) for link in links]
                results = await asyncio.gather(*tasks)
                for res in results:
                    if res:
                        all_sources.append(res)

        all_sources.sort(key=lambda x: x["date"], reverse=True)
        MAX_SOURCES = 40
        if len(all_sources) > MAX_SOURCES:
            all_sources = all_sources[:MAX_SOURCES]

        logger.info(f"Собрано источников: {len(all_sources)}")
        gs_logger.log(
            step="Сбор контента",
            status="OK",
            message=f"Всего источников: {len(all_sources)}",
        )

        if not all_sources:
            logger.info("Нет источников для дайджеста")
            gs_logger.log(
                step="Завершение пайплайна",
                status="EMPTY",
                message="Нет данных для генерации.",
            )
            await update_status(0)
            return

        digest = await agent.generate_digest_from_raw(all_sources)
        gs_logger.log(
            step="Генерация дайджеста",
            status="OK",
            message="Дайджест создан",
        )

        from bot.bot import NewsDigestBot

        bot = NewsDigestBot()
        target_channel = bot.target_channel_id
        if not target_channel:
            logger.error("TELEGRAM_CHANNEL_ID не задан, отправка невозможна")
            gs_logger.log(
                step="Ошибка отправки",
                status="ERROR",
                message="TELEGRAM_CHANNEL_ID отсутствует",
            )
            await update_status(
                len(all_sources), error="TELEGRAM_CHANNEL_ID отсутствует"
            )
            return

        telegraph_url = await publish_to_telegraph(
            title="Еженедельный дайджест по биометрии и компьютерному зрению",
            content=digest,
        )

        if telegraph_url:
            await bot.bot.send_message(
                chat_id=target_channel,
                text=f"Опубликован новый еженедельный дайджест!\n\nЧитать полностью: {telegraph_url}",
                parse_mode="HTML",
            )
            gs_logger.log(
                step="Отправка дайджеста",
                status="OK",
                message=f"Опубликован на Telegra.ph: {telegraph_url}",
            )
        else:
            logger.warning(
                "Не удалось опубликовать на Telegra.ph, отправляем как есть (обрезано)"
            )
            await bot.bot.send_message(
                chat_id=target_channel, text=digest[:4000], parse_mode="HTML"
            )
            gs_logger.log(
                step="Отправка дайджеста",
                status="WARNING",
                message="Отправлен обрезанный текст из-за ошибки Telegra.ph",
            )

        digest_fixed = re.sub(r"^\s*[•·]\s*", "- ", digest, flags=re.MULTILINE)
        html_body = markdown.markdown(digest_fixed, extensions=["extra"])
        current_date = datetime.now().strftime("%d.%m.%Y")
        subject = f"ИИ-Дайджест новостей за {current_date}"
        await publish_email_task(digest_html=html_body, subject=subject)
        gs_logger.log(
            step="Email task published",
            status="OK",
            message="Задача на email-рассылку отправлена в очередь",
        )

        tg_links = [f"https://t.me/{post['channel']}/{post['id']}" for post in posts]
        source_links = [item["url"] for item in all_sources if item.get("url")]
        gs_logger.log_links(tg_links, source_links)

        await update_status(len(all_sources))

    except Exception as e:
        logger.exception("Ошибка в пайплайне")
        gs_logger.log(
            step="Ошибка пайплайна",
            status="ERROR",
            message=str(e),
        )
        await update_status(0, error=str(e))
    finally:
        await telegram_client.disconnect()


async def start_worker():
    await asyncio.gather(
        run_worker(
            queue_name="digest_tasks",
            callback=process_digest_task,
            prefetch_count=1,
            dlx_name="digest_tasks.dlx",
        ),
        run_worker(
            queue_name="email_digest",
            callback=process_email_task,
            prefetch_count=1,
            dlx_name="email_digest.dlx",
        ),
    )
