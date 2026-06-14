import asyncio
from os import getenv
from pathlib import Path
from aiogram.filters import Command
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from json import load

from security.auth_ware import Authware
from tools.telegram_search_news import TelegramSearchNews, client as telethon_client, STATUS_FILE


BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = BASE_DIR / "configs" / "channels.json"
LOADED_STATUS_FILE = BASE_DIR / "bot_status.json"

load_dotenv(dotenv_path=BASE_DIR / ".env")

class NewsDigestBot:
    """Оболочка для управления ботом в aiogram"""

    def __init__(self):
        self.bot_token = getenv("TELEGRAM_BOT_TOKEN")
        self.target_channel_id = getenv("TELEGRAM_CHANNEL_ID")

        self.bot = Bot(
            token=self.bot_token, 
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

        self.dp = Dispatcher()

        self.dp.message.middleware(Authware())

        self._register_handlers()
    

    def _register_handlers(self):
        """Регистрация всех ручек (команд) бота."""
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_status, Command("status"))
        self.dp.message.register(self.cmd_digest_now, Command("digest_now"))


    async def run_full_digest_cycle(self, status_message: Message):
        """Фоновое выполнение полного цикла: Парсинг (с ChromaDB) -> ИИ -> Публикация."""
        try:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = load(f)
                    target_channels = config.get("news_channels", [])
            except FileNotFoundError:
                target_channels = ["durov"]

            print(f"Список каналов для парсинга: {target_channels}")

            await status_message.answer("<b>Шаг 1/3:</b> Запускаю парсинг каналов через Telethon...")
            
            if not telethon_client.is_connected():
                await telethon_client.connect()
            await telethon_client.start()

            search_tool = TelegramSearchNews(
                channels=target_channels,
                max_results_per_channel=10,
                search_days=2
            )

            raw_news = await search_tool.run()
            
            await telethon_client.disconnect()

            total_found = 0
            for posts in raw_news.values():
                if isinstance(posts, list):
                    for post in posts:
                        if "id" in post:
                            total_found += 1
            print(total_found)
            if total_found == 0:
                await status_message.answer("Новых постов не обнаружено. Все свежие публикации уже есть в ChromaDB. Дайджест отменен.")
                return

            await status_message.answer(
                f"<b>Шаг 2/3:</b> Успешно собрано новых постов: {total_found}.\n"
                f"Отправляю данные в ИИ для анализа и генерации текста..."
            )

            # --- ИНТЕГРАЦИЯ С ТВОИМИ ОСТАЛЬНЫМИ МОДУЛЯМИ ---
            # TODO: доделать интеграцию с ЛЛМ
            ai_title = "⚡ Свежий ИИ-Дайджест новостей"
            ai_content = (
                f"Мы проанализировали {total_found} новых публикаций.\n\n"
                f"• <b>Главное событие:</b> База ChromaDB успешно интегрирована в пайплайн.\n"
                f"• <b>Обновления:</b> Telethon больше не падает на медиафайлах.\n\n"
                f"• <b>Ошибки:</b> Пути опять сломались, Карл.\n\n"
                f"<i>[Этот блок будет заменен на ответ LLMки]</i>"
            )

            await status_message.answer("<b>Шаг 3/3:</b> Публикую готовый дайджест в канал...")

            full_digest_text = f"<b>{ai_title}</b>\n\n{ai_content}"

            await self.bot.send_message(chat_id=self.target_channel_id, text=full_digest_text)
            
            await status_message.answer("✅ Дайджест успешно сгенерирован и опубликован!")

        except Exception as e:
            await status_message.answer(f"❌ Критическая ошибка в фоновом потоке: {e}")


    # ручка /старт
    async def cmd_start(self, message: Message):
        await message.answer(
            f"Привет, {html.bold(message.from_user.full_name)}!\n"
            f"Я бот-интерфейс твоего новостного ИИ-агента.\n\n"
            f"<b>Доступные команды:</b>\n"
            f"🚀 /digest_now — Запустить ручную генерацию дайджеста\n"
            f"📊 /status — Посмотреть логи последнего запуска\n"
            f"ℹ️ /help — Справка по командам"
        )

    # ручка /help
    async def cmd_help(self, message: Message):
        await message.answer(
            "ℹ️ <b>Как устроен бот:</b>\n\n"
            "/digest_now — запускает полный цикл парсинга выбранных тг каналов.\n\n"
            "/status — отображает метаданные из файла логов (время запуска, ошибки, кол-во постов)."
        )

    # ручка /status
    async def cmd_status(self, message: Message):
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                status = load(f)
            
            text = (
                f"<b>Статус последнего запуска:</b>\n\n"
                f"   Время: <code>{status['last_run']}</code>\n"
                f"   Найдено новых постов: <code>{status['posts_processed']}</code>\n"
                f"   Ошибки: <code>{status['error']}</code>"
            )
        else:
            text = "📊 Логи отсутствуют. Запусков еще не было."
        
        await message.answer(text)

    # ручка /digest_now
    async def cmd_digest_now(self, message: Message):
        await message.answer("Запрос принят! Запускаю пайплайн в фоновом режиме...")
        
        asyncio.create_task(self.run_full_digest_cycle(message))


    async def start(self):
        """Точка входа для запуска бота из внешних файлов."""
        print("Бот на Aiogram запущен из класса и слушает команды...")
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    bot_app = NewsDigestBot()
    try:
        asyncio.run(bot_app.start())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
