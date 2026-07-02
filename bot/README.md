# Telegram-бот (aiogram)

Обрабатывает команды:

- `/start`, `/help` – приветствие и справка.
- `/status` – показывает статус последнего запуска (из `configs/bot_status.json`).
- `/digest_now` – отправляет задание в RabbitMQ на генерацию дайджеста.
- `/subscribe_email user@example.com` — добавляет почту в таблицу email для рассылки через Unisender
- `/unsubscribe_email user@example.com` — удаляет почту из рассылки
- `/get_emails` - показывает привязанные к рассылке почты

Использует middleware `auth_ware` для ограничения доступа по списку `ALLOWED_USERS`.
