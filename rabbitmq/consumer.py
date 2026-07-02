import asyncio
import json
import logging
from os import getenv
import aio_pika

from utils.unisender_client import UnisenderClient

logger = logging.getLogger(__name__)

RABBITMQ_HOST = getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = getenv("RABBITMQ_PASSWORD")

unisender = UnisenderClient(
    api_key=getenv("UNISENDER_API_KEY", ""),
    sender_email=getenv("UNISENDER_SENDER_EMAIL", ""),
    sender_name=getenv("UNISENDER_SENDER_NAME", ""),
    list_id=int(getenv("UNISENDER_LIST_ID"))
)


async def run_worker(
    queue_name: str, callback, prefetch_count: int = 1, dlx_name: str = None
):
    connection = await aio_pika.connect_robust(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        login=RABBITMQ_USER,
        password=RABBITMQ_PASSWORD,
    )
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch_count)

    if dlx_name:
        await channel.declare_exchange(
            dlx_name, type=aio_pika.ExchangeType.DIRECT, durable=True
        )
        dlq_queue = await channel.declare_queue(f"{queue_name}.dlq", durable=True)
        await dlq_queue.bind(dlx_name, routing_key="")
        args = {"x-dead-letter-exchange": dlx_name}
        queue = await channel.declare_queue(queue_name, durable=True, arguments=args)
    else:
        queue = await channel.declare_queue(queue_name, durable=True)

    async def on_message(message: aio_pika.IncomingMessage):
        try:
            data = json.loads(message.body.decode())
            await callback(data)
            await message.ack()
            logger.info(f"Сообщение обработано и подтверждено: {data}")
        except Exception as e:
            logger.error(f"Ошибка обработки, отправляем в DLX (если настроен): {e}")
            await message.nack(requeue=False)

    await queue.consume(on_message)
    logger.info(f"Consumer для очереди {queue_name} запущен. Ожидание сообщений...")
    try:
        await asyncio.Future()
    finally:
        await connection.close()
