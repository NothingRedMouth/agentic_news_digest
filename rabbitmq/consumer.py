import asyncio
import json
import logging
from os import getenv

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_HOST = getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = getenv("RABBITMQ_PASSWORD")


async def run_worker(
    queue_name: str, callback, prefetch_count: int = 1, dlx_name: str = None
):
    """
    Запускает consumer с ручным подтверждением.
    callback – асинхронная функция, принимающая один аргумент (словарь с данными).
    При успешной обработке вызывается ack, при ошибке – nack с отправкой в DLX (если указан).
    """
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
        # Очередь для мёртвых сообщений
        dlq_queue = await channel.declare_queue(f"{queue_name}.dlq", durable=True)
        await dlq_queue.bind(dlx_name, routing_key="")
        # Основная очередь с параметром x-dead-letter-exchange
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
        await asyncio.Future()  # бесконечное ожидание
    finally:
        await connection.close()
