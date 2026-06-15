import logging
from os import getenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rabbitmq.producer import publish_digest_task

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_digest():
    logger.info("Запуск автоматического дайджеста по расписанию")
    await publish_digest_task()


def setup_scheduler():
    interval_days = int(getenv("DIGEST_INTERVAL_DAYS"))
    if interval_days > 0:
        scheduler.add_job(
            scheduled_digest,
            trigger=IntervalTrigger(days=interval_days),
            id="digest_job",
            replace_existing=True,
        )
        logger.info(f"Планировщик запущен: дайджест каждые {interval_days} дней")
    else:
        logger.info("Планировщик отключён (DIGEST_INTERVAL_DAYS=0 или не задано)")


async def start_scheduler():
    setup_scheduler()
    scheduler.start()
