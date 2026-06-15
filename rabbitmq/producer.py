import asyncio
import json
import pika
from os import getenv

RABBITMQ_HOST = getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(getenv("RABBITMQ_PORT"))
RABBITMQ_USER = getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = getenv("RABBITMQ_PASSWORD")


async def publish_digest_task():
    """Отправляет команду на запуск полного цикла дайджеста."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_publish)


def _sync_publish():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials
    )
    conn = pika.BlockingConnection(params)
    channel = conn.channel()
    channel.queue_declare(queue="digest_tasks", durable=True)
    channel.basic_publish(
        exchange="",
        routing_key="digest_tasks",
        body=json.dumps({"action": "generate_digest"}),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    conn.close()
