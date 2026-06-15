import logging
import json
from datetime import datetime
from pathlib import Path
from os import getenv

from agent.llm_agent import LLMAgent
from agent.tools import TelegramSearch, WebSearchExa
from rabbitmq.consumer import AsyncConsumer

logger = logging.getLogger(__name__)
SEARCH_SCOPE = getenv("SEARCH_SCOPE", "telegram+web")
STATUS_FILE = Path("configs/bot_status.json")


def update_status(posts_count: int, error: str = None):
    status = {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_processed": posts_count,
        "error": error or "Ошибок нет",
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=4)


async def process_digest_task(data):
    logger.info("Начинаем генерацию дайджеста")
    try:
        # 1. Сбор постов в зависимости от SEARCH_SCOPE
        raw_posts = []
        if SEARCH_SCOPE in ("telegram_only", "telegram+web"):
            with open("configs/channels.json", "r") as f:
                channels_cfg = json.load(f)
                channels = channels_cfg.get("news_channels", [])
            tg = TelegramSearch(channels=channels, max_per_channel=10, search_days=2)
            tg_posts = await tg.run()
            raw_posts.extend(tg_posts)

        if SEARCH_SCOPE in ("web_only", "telegram+web"):
            queries = [
                "biometrics liveness detection",
                "deepfake identity fraud",
                "computer vision news",
            ]
            for q in queries:
                searcher = WebSearchExa(query=q, max_results=5)
                articles = await searcher.run()
                for art in articles:
                    raw_posts.append(
                        {
                            "id": f"web_{hash(art['url'])}",
                            "channel": "web",
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "text": art.get("text", ""),
                            "link": art.get("url"),
                        }
                    )

        if not raw_posts:
            logger.info("Нет новых постов для обработки")
            update_status(0)
            return

        # 2. Оценка релевантности и суммаризация
        agent = LLMAgent()
        relevant_summaries = []
        for post in raw_posts:
            text = post.get("text", "")
            if not text:
                continue
            if await agent.is_relevant(text):
                summary = await agent.summarize(text)
                relevant_summaries.append(f"**{post.get('link', '')}**\n{summary}")

        if not relevant_summaries:
            logger.info("Релевантных постов не найдено")
            update_status(0)
            return

        # 3. Генерация дайджеста
        digest = await agent.create_digest(relevant_summaries)

        # 4. Отправка в Telegram канал
        from bot.bot import NewsDigestBot

        bot_instance = NewsDigestBot()
        await bot_instance.bot.send_message(
            chat_id=bot_instance.target_channel_id, text=digest, parse_mode="HTML"
        )

        update_status(len(relevant_summaries))
        logger.info("Дайджест успешно отправлен")

    except Exception as e:
        logger.exception("Ошибка в процессе генерации дайджеста")
        update_status(0, error=str(e))


async def start_worker():
    """Запускает консьюмера очереди digest_tasks."""
    consumer = AsyncConsumer(queue_name="digest_tasks", callback=process_digest_task)
    await consumer.start()
