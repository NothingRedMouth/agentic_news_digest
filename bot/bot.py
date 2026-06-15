from os import getenv
from pathlib import Path
from aiogram.filters import Command
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from json import load

from bot.auth_ware import Authware
from rabbitmq.producer import publish_digest_task

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "configs" / "channels.json"
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
        self._register_handlers()

    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_status, Command("status"))
        self.dp.message.register(self.cmd_digest_now, Command("digest_now"))

    async def cmd_start(self, message: Message):
        await message.answer(
            f"Привет, {html.bold(message.from_user.full_name)}!\n"
            "Я бот-интерфейс твоего новостного ИИ-агента.\n\n"
            "<b>Доступные команды:</b>\n"
            "🚀 /digest_now — Запустить ручную генерацию дайджеста\n"
            "📊 /status — Посмотреть логи последнего запуска\n"
            "ℹ️ /help — Справка по командам"
        )

    async def cmd_help(self, message: Message):
        await message.answer(
            "ℹ️ <b>Как устроен бот:</b>\n\n"
            "/digest_now — запускает полный цикл парсинга и генерации дайджеста.\n\n"
            "/status — отображает метаданные из файла логов."
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
                f"Ошибки: <code>{status['error']}</code>"
            )
        else:
            text = "📊 Логи отсутствуют. Запусков еще не было."
        await message.answer(text)

    async def cmd_digest_now(self, message: Message):
        await message.answer(
            "Запрос принят! Задача на генерацию дайджеста поставлена в очередь."
        )
        await publish_digest_task()

    async def start(self):
        print("Бот запущен и слушает команды...")
        await self.dp.start_polling(self.bot)
