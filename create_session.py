import os
import asyncio
from telethon import TelegramClient

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")


async def main():
    client = TelegramClient(
        "session_name",
        API_ID,
        API_HASH,
        device_model="PC",  # Имитация ПК
        system_version="Windows 10",  # Имитация ОС
        app_version="4.15.2",  # Версия приложения
        lang_code="ru",  # Язык
        system_lang_code="ru-RU",  # Язык системы
    )

    await client.start()
    print("Сессия успешно создана!")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
