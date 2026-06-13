import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, cooldown: float = 3.0):
        self.cooldown = cooldown
        self.users: Dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        user_id = None
        is_start = False
        if isinstance(event, Message):
            if event.from_user: user_id = event.from_user.id
            if event.text and event.text.startswith('/start'): is_start = True
        elif isinstance(event, CallbackQuery):
            if event.from_user: user_id = event.from_user.id
            if event.data and event.data.startswith('ob_beat_3'): is_start = True
        
        if is_start and user_id:
            now = time.time()
            if now - self.users.get(user_id, 0.0) < self.cooldown:
                return None
            self.users[user_id] = now
        return await handler(event, data)
