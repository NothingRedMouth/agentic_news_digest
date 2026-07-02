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


async def publish_email_task(digest_html: str, subject: str) -> bool:
    """
    Публикует задачу на массовую email-рассылку.
    Очередь должна быть объявлена в consumer, здесь только публикация.
    """
    connection = await aio_pika.connect_robust(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        login=RABBITMQ_USER,
        password=RABBITMQ_PASSWORD,
    )
    async with connection:
        channel = await connection.channel()
        args = {"x-dead-letter-exchange": "email_digest.dlx"}
        await channel.declare_queue("email_digest", durable=True, arguments=args)

        payload = {"html_body": digest_html, "subject": subject}

        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key="email_digest",
        )
        logger.info(
            "Задача на массовую email-рассылку успешно опубликована в RabbitMQ."
        )
        return True
