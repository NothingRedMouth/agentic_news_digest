# Telegram-бот (aiogram)

Обрабатывает команды:

- `/start`, `/help` – приветствие и справка.
- `/status` – показывает статус последнего запуска (из `configs/bot_status.json`).
- `/digest_now` – отправляет задание в RabbitMQ на генерацию дайджеста.

Использует middleware `auth_ware` для ограничения доступа по списку `ALLOWED_USERS`.
