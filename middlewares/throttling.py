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
        micro_cooldown: float = 0.5,
        cleanup_interval: int = 100,
    ) -> None:
        self.cooldown = cooldown
        self.micro_cooldown = micro_cooldown
        self.cleanup_interval = cleanup_interval
        self._users: Dict[str, float] = {}
        self._event_counter: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self, now: float) -> None:
        """Remove entries older than the maximum cooldown period."""
        cutoff = now - max(self.cooldown, self.micro_cooldown)
        self._users = {
            key: ts for key, ts in self._users.items() if ts >= cutoff
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
        throttle_type: str | None = None
        cooldown_to_apply: float = 0.0

        if isinstance(event, Message):
            if event.from_user:
                user_id = event.from_user.id
            if event.text and event.text.startswith("/start"):
                throttle_type = "macro"
                cooldown_to_apply = self.cooldown

        elif isinstance(event, CallbackQuery):
            if event.from_user:
                user_id = event.from_user.id
            if event.data and event.data.startswith("ob_beat_3"):
                throttle_type = "macro"
                cooldown_to_apply = self.cooldown
            else:
                throttle_type = "micro"
                cooldown_to_apply = self.micro_cooldown

        if throttle_type and user_id:
            now = time.time()

            # Periodic cleanup to bound memory usage
            self._event_counter += 1
            if self._event_counter >= self.cleanup_interval:
                self._cleanup(now)
                self._event_counter = 0

            key = f"{user_id}:{throttle_type}"
            if now - self._users.get(key, 0.0) < cooldown_to_apply:
                return None

            self._users[key] = now

        return await handler(event, data)
