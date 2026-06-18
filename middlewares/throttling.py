"""
middlewares/throttling.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Rate-limiting middleware for critical bot entry-points.

Only /start commands and ob_beat_3 callbacks are throttled — all other
events pass through unmodified.  A periodic cleanup sweeps stale entries
from the internal timestamp dict to prevent unbounded memory growth.
"""

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    """
    Per-user cooldown guard for /start and onboarding-finish events.

    Parameters
    ----------
    cooldown : float
        Minimum seconds between throttled events for the same user.
    cleanup_interval : int
        Number of throttled events between automatic stale-entry sweeps.
    """

    def __init__(
        self,
        cooldown: float = 3.0,
        cleanup_interval: int = 100,
    ) -> None:
        self.cooldown = cooldown
        self.cleanup_interval = cleanup_interval
        self._users: Dict[int, float] = {}
        self._event_counter: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self, now: float) -> None:
        """Remove entries older than the cooldown period."""
        cutoff = now - self.cooldown
        self._users = {
            uid: ts for uid, ts in self._users.items() if ts >= cutoff
        }

    # ------------------------------------------------------------------
    # Middleware entry-point
    # ------------------------------------------------------------------

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        is_throttled_event = False

        if isinstance(event, Message):
            if event.from_user:
                user_id = event.from_user.id
            if event.text and event.text.startswith("/start"):
                is_throttled_event = True

        elif isinstance(event, CallbackQuery):
            if event.from_user:
                user_id = event.from_user.id
            if event.data and event.data.startswith("ob_beat_3"):
                is_throttled_event = True

        if is_throttled_event and user_id:
            now = time.time()

            # Periodic cleanup to bound memory usage
            self._event_counter += 1
            if self._event_counter >= self.cleanup_interval:
                self._cleanup(now)
                self._event_counter = 0

            if now - self._users.get(user_id, 0.0) < self.cooldown:
                return None

            self._users[user_id] = now

        return await handler(event, data)
