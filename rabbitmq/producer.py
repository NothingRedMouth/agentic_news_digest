import json
import logging
from os import getenv

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_HOST = getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = getenv("RABBITMQ_PASSWORD")


async def publish_digest_task():
    connection = await aio_pika.connect_robust(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        login=RABBITMQ_USER,
        password=RABBITMQ_PASSWORD,
    )
    async with connection:
        channel = await connection.channel()
        args = {"x-dead-letter-exchange": "digest_tasks.dlx"}
        await channel.declare_queue("digest_tasks", durable=True, arguments=args)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps({"action": "generate_digest"}).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key="digest_tasks",
        )
        logger.info("Задача на генерацию дайджеста опубликована")
