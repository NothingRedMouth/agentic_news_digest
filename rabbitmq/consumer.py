import asyncio
import json
import pika
from os import getenv
import logging

logger = logging.getLogger(__name__)

RABBITMQ_HOST = getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(getenv("RABBITMQ_PORT"))
RABBITMQ_USER = getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = getenv("RABBITMQ_PASSWORD")


class AsyncConsumer:
    def __init__(self, queue_name, callback, prefetch_count=1):
        self.queue_name = queue_name
        self.callback = callback
        self.prefetch_count = prefetch_count
        self._connection = None
        self._channel = None

    async def start(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_start)

    def _sync_start(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials
        )
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=self.queue_name, durable=True)
        self._channel.basic_qos(prefetch_count=self.prefetch_count)
        self._channel.basic_consume(
            queue=self.queue_name, on_message_callback=self._on_message
        )
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            self._channel.stop_consuming()
            self._connection.close()

    def _on_message(self, ch, method, properties, body):
        try:
            data = json.loads(body)
            asyncio.run_coroutine_threadsafe(
                self.callback(data), asyncio.get_event_loop()
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
