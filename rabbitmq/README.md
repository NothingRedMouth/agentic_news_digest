# RabbitMQ модуль

- **producer.py** – отправка задания `digest_tasks`.
- **consumer.py** – базовый асинхронный консьюмер с acknowledgements и dead-letter при ошибках.
- **worker.py** – основной обработчик: парсинг → оценка релевантности → суммаризация → отправка дайджеста.

Очередь `digest_tasks` объявляется как durable (сообщения не теряются при падении RabbitMQ).
