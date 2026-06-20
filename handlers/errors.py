import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent

router = Router(name="errors_router")
logger = logging.getLogger(__name__)


@router.errors()
async def global_error_handler(event: ErrorEvent):
    """
    Global error handler to catch and silently swallow specific errors,
    preventing log spam.
    """
    if isinstance(event.exception, TelegramBadRequest):
        if "message is not modified" in str(event.exception).lower():
            # Silently swallow the double-click "not modified" error
            return True

    # For all other errors, we can log them or let them propagate
    logger.exception("Update %s caused error: %s", event.update.update_id, event.exception)
    return None
