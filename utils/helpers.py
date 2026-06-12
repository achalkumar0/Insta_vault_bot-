import random
import string
import asyncio
from datetime import datetime
from functools import partial

import pytz

from config import TIMEZONE


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def get_ist_now() -> datetime:
    """Return the current datetime in the configured timezone (IST by default)."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


def format_timestamp(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format a datetime object as a human-readable IST string."""
    if dt is None:
        return "N/A"
    tz = pytz.timezone(TIMEZONE)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz).strftime(fmt)


# ---------------------------------------------------------------------------
# Unique ID generators
# ---------------------------------------------------------------------------

def generate_vault_id(numeric_part: int | None = None) -> str:
    """
    Generate a Vault ID in the format VLT-XXXXX.
    If numeric_part is provided (e.g. a counter), it is used; otherwise random.
    """
    if numeric_part is not None:
        return f"VLT-{numeric_part:05d}"
    return f"VLT-{random.randint(10000, 99999)}"


def generate_referral_code(vault_id: str) -> str:
    """
    Derive a referral code from a vault_id.
    VLT-00847  →  ref_VLT00847
    """
    stripped = vault_id.replace("-", "")
    return f"ref_{stripped}"


def generate_short_code(length: int = 8) -> str:
    """Generate a random alphanumeric code (fallback / misc use)."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


# ---------------------------------------------------------------------------
# Async executor helper
# ---------------------------------------------------------------------------

async def run_sync(func, *args, **kwargs):
    """
    Run a synchronous (blocking) function inside the default thread executor
    so it does not block the asyncio event loop.

    Usage:
        result = await run_sync(some_blocking_call, arg1, arg2)
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))
    return await loop.run_in_executor(None, func, *args)


# ---------------------------------------------------------------------------
# Spark / rank helpers
# ---------------------------------------------------------------------------

RANK_THRESHOLDS: dict[str, int] = {
    "rookie":    0,
    "rising":    500,
    "hustler":   2000,
    "elite":     6000,
    "vaultking": 15000,
}


def get_rank_tier(rank_points: int) -> str:
    """Return the rank tier string for a given rank_points value."""
    tier = "rookie"
    for name, threshold in RANK_THRESHOLDS.items():
        if rank_points >= threshold:
            tier = name
    return tier


def get_daily_limit(streak_days: int) -> int:
    """
    Return the daily order limit based on streak days.
    DAILY_LIMITS keys are minimum streak thresholds.
    """
    from config import DAILY_LIMITS
    limit = 1
    for min_streak, allowed in sorted(DAILY_LIMITS.items()):
        if streak_days >= min_streak:
            limit = allowed
    return limit
