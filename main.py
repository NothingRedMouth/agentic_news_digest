import asyncio
import logging
from dotenv import load_dotenv

from bot.bot import NewsDigestBot
from rabbitmq.worker import start_worker
from scheduler.scheduler import start_scheduler

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Запуск оркестратора...")
    await asyncio.gather(
        start_scheduler(),
        NewsDigestBot().start(),
        start_worker(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Оркестратор остановлен.")
