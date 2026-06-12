"""
handlers/referrals.py
~~~~~~~~~~~~~~~~~~~~~
Handles /refer command and referral-related callbacks.
Passive earning and multi-tier logic will be implemented in Phase 2.
"""

import logging

import config
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import REFERRAL_JOIN_BONUS, REFEREE_BONUS
from database.db_manager import get_user
from keyboards.inline import referral_keyboard

logger = logging.getLogger(__name__)
router = Router(name="referrals")


@router.message(Command("refer"))
@router.message(F.text == "👥 Refer & Earn")
async def cmd_refer(message: Message) -> None:
    """Display the user's referral stats and shareable link."""
    user = message.from_user
    if not user:
        return

    user_data = await get_user(user.id)
    if not user_data:
        await message.answer("⚠️ Please use /start to set up your Vault.")
        return

    referral_code = user_data.get("referral_code", "—")
    referral_count = user_data.get("referral_count", 0)
    vault_id = user_data.get("vault_id", "—")

    deep_link = f"https://t.me/{config.BOT_USERNAME}?start={referral_code}"

    await message.answer(
        f"👥 <b>Refer & Earn</b>\n\n"
        f"Share your link and earn Sparks for every friend who joins!\n\n"
        f"🔗 <b>Your Referral Code:</b> <code>{referral_code}</code>\n"
        f"🌐 <b>Your Link:</b>\n{deep_link}\n\n"
        f"📊 <b>Your Stats</b>\n"
        f"├ Friends Invited: <b>{referral_count}</b>\n"
        f"├ You earn: <b>{REFERRAL_JOIN_BONUS} Sparks</b> per invite\n"
        f"└ Friend earns: <b>{REFEREE_BONUS} Sparks</b> on joining\n\n"
        f"<i>Passive earning (5% of friend's missions) unlocks in Phase 2.</i>",
        reply_markup=referral_keyboard(referral_code),
    )
