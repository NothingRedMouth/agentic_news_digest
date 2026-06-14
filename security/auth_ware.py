from os import getenv
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

class Authware(BaseMiddleware):
    """Великий китайский фаервол к боту по списку ID из .env."""
    
    def __init__(self):
        super().__init__()
        raw_users = getenv("ALLOWED_USERS", "")
        self.allowed_users = {
            int(user_id.strip()) 
            for user_id in raw_users.split(",") 
            if user_id.strip().isdigit()
        }

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            
            if user_id not in self.allowed_users:
                print(f"🔒 Заблокирована попытка доступа от неавторизованного ID: {user_id}")
                await event.answer("⛔ <b>Доступ ограничен.</b> Вы не входите в пул администраторов этого ИИ-сервиса.")
                return
                
        return await handler(event, data)
