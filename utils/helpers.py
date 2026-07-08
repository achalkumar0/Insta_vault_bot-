"""
utils/helpers.py
~~~~~~~~~~~~~~~~
Shared utility functions used across the InstaVault Bot project.

Responsibilities:
  - Timezone-aware datetime helpers (IST by default)
  - Deterministic ID generators (Vault ID, referral codes)
  - Rank tier calculation from rank points
"""

from datetime import datetime

import pytz
from config import TIMEZONE

# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def get_ist_now() -> datetime:
    """Return the current datetime in the configured timezone (IST by default)."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


def format_timestamp(dt: datetime | str | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format a datetime object as a human-readable IST string. Supports ISO strings."""
    if dt is None:
        return "N/A"
    
    if isinstance(dt, str):
        try:
            # Handle ISO strings (e.g. from JSON/Redis cache)
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt

    tz = pytz.timezone(TIMEZONE)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz).strftime(fmt)


# ---------------------------------------------------------------------------
# Unique ID generators
# ---------------------------------------------------------------------------

def generate_vault_id(user_id: int | str) -> str:
    """
    Generate a Vault ID using the Telegram user_id.
    """
    return f"VLT-{user_id}"


def generate_referral_code(vault_id: str) -> str:
    """
    Derive a referral code from a vault_id.
    VLT-00847  →  ref_VLT00847
    """
    stripped = vault_id.replace("-", "")
    return f"ref_{stripped}"


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
