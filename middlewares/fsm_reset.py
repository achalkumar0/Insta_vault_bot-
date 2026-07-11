"""
middlewares/fsm_reset.py
~~~~~~~~~~~~~~~~~~~~~~~~
Global middleware to prevent FSM state leaks.
Intercepts all global navigation commands and callbacks and explicitly
clears any active FSM state before passing the event to the router.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject


class FSMResetMiddleware(BaseMiddleware):
    """
    Clears FSM state when a user attempts to navigate away from an active state 
    (e.g., clicking 'Dashboard' while waiting for an order link).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        
        state: FSMContext = data.get("state")
        
        if state:
            should_clear = False
            
            if isinstance(event, Message) and event.text:
                text = event.text.lower().strip()
                if text.startswith("/start"):
                    should_clear = True
            
            elif isinstance(event, CallbackQuery) and event.data:
                cb = event.data
                if (cb.startswith("nav_") or 
                    cb == "go_dashboard" or 
                    cb.startswith("ob_")):
                    should_clear = True
            
            if should_clear:
                current_state = await state.get_state()
                if current_state:
                    await state.clear()

        return await handler(event, data)
