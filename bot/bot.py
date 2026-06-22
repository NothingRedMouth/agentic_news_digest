import logging
import re
from os import getenv
from pathlib import Path
from aiogram.filters import Command, CommandObject
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from json import load

from utils.unisender_client import UnisenderClient
from bot.auth_ware import Authware
from rabbitmq.producer import publish_digest_task

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "configs" / "channels.json"
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
load_dotenv(dotenv_path=BASE_DIR / ".env")


class NewsDigestBot:
    def __init__(self):
        self.bot_token = getenv("TELEGRAM_BOT_TOKEN")
        self.target_channel_id = getenv("TELEGRAM_CHANNEL_ID")
        self.bot = Bot(
            token=self.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self.dp.message.middleware(Authware())

        self.unisender = UnisenderClient(
            api_key=getenv("UNISENDER_API_KEY"),
            sender_email=getenv("UNISENDER_SENDER_EMAIL"),
            sender_name=getenv("UNISENDER_SENDER_NAME"),
            list_id=int(getenv("UNISENDER_LIST_ID"))
        )
        self._register_handlers()

    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_status, Command("status"))
        self.dp.message.register(self.cmd_digest_now, Command("digest_now"))
        self.dp.message.register(self.cmd_subscribe_email, Command("subscribe_email"))
        self.dp.message.register(self.cmd_unsubscribe_email, Command("unsubscribe_email"))
        self.dp.message.register(self.cmd_get_emails, Command("get_emails"))

    async def cmd_start(self, message: Message):
        await message.answer(
            f"Привет, {html.bold(message.from_user.full_name)}!\n"
            "Я бот-интерфейс твоего новостного ИИ-агента.\n\n"
            "<b>Доступные команды:</b>\n"
            "🚀 /digest_now — Запустить ручную генерацию дайджеста\n"
            "📊 /status — Посмотреть логи последнего запуска\n"
            "📧 /subscribe_email — Подписаться на email-рассылку\n"
            "🚫 /unsubscribe_email — Отписаться от email-рассылки\n"
            "🔍 /get_emails — Посмотреть привязанные email\n"
            "ℹ️ /help — Справка по командам"
        )

    async def cmd_help(self, message: Message):
        await message.answer(
            "ℹ️ <b>Как устроен бот:</b>\n\n"
            "/digest_now — запускает полный цикл парсинга и генерации дайджеста.\n\n"
            "/status — отображает метаданные из файла логов."
            "<b>отправка Email</b>\n"
            "/subscribe_email user@example.com — добавляет почту в таблицу email для рассылки через Unisender.\n"
            "/unsubscribe_email user@example.com — удаляет почту из рассылки"
            "/get_emails - показывает привязанные к рассылке почты"
        )

    async def cmd_status(self, message: Message):
        status_file = Path("configs/bot_status.json")
        if status_file.exists():
            with open(status_file, "r", encoding="utf-8") as f:
                status = load(f)
            text = (
                f"<b>Статус последнего запуска:</b>\n\n"
                f"Время: <code>{status['last_run']}</code>\n"
                f"Найдено новых постов: <code>{status['posts_processed']}</code>\n"
                f"Отправлено писем: <code>{status_file['email_processed']}</code>\n"
                f"Ошибки: <code>{status['error']}</code>"
            )
        else:
            text = "📊 Логи отсутствуют. Запусков еще не было."
        await message.answer(text)

    async def cmd_digest_now(self, message: Message):
        logger.info(f"Команда /digest_now от {message.from_user.id}")
        try:
            await publish_digest_task()
            await message.answer(
                "✅ Запрос принят! Задача на генерацию дайджеста поставлена в очередь."
            )
        except Exception as e:
            logger.error(f"Ошибка при публикации задачи: {e}", exc_info=True)
            await message.answer(
                "❌ Ошибка: не удалось поставить задачу в очередь. Подробности в логах."
            )

    async def cmd_subscribe_email(self, message: Message, command: CommandObject):
        """Подписка email на дайджест"""
        if not command.args or not EMAIL_REGEX.match(command.args.strip()):
            await message.answer("❌ Использование: <code>/admin_add_email test@example.com</code>")
            return

        email = command.args.strip().lower()
        await message.answer("⏳ Добавление контакта в Unisender...")
        
        res = await self.unisender.subscribe(email)
        
        if res["success"]:
            await message.answer(f"✅ Email <code>{email}</code> успешно добавлен в базу рассылки!")
        else:
            await message.answer(f"❌ Ошибка Unisender: <code>{res.get('error')}</code>")

    async def cmd_unsubscribe_email(self, message: Message, command: CommandObject):
        """Отписка email от дайджеста"""
        if not command.args:
            await message.answer("❌ Использование: <code>/admin_del_email test@example.com</code>")
            return

        email = command.args.strip().lower()
        await message.answer("⏳ Удаление контакта из Unisender...")
        
        res = await self.unisender.unsubscribe(email)
        
        if res["success"]:
            await message.answer(f"🚫 Email <code>{email}</code> успешно отписан.")
        else:
            await message.answer(f"❌ Ошибка Unisender: <code>{res.get('error')}</code>")

    async def cmd_get_emails(self, message: Message):
        """Показать текущий привязанный email"""
        await message.answer("⏳ Запрашиваю список контактов из Unisender...")
    
        emails = await self.unisender.get_registered_emails()
        
        if not emails:
            await message.answer("📋 В списке рассылки Unisender нет активных подписчиков (или произошла ошибка).")
            return

        text = f"📋 <b>Всего активных подписчиков: {len(emails)}</b>\n\n"
        for idx, email in enumerate(emails, 1):
            text += f"{idx}. <code>{email}</code>\n"

        await message.answer(text)

    async def start(self):
        print("Бот запущен и слушает команды...")
        await self.dp.start_polling(self.bot)
