"""
handlers/start.py
~~~~~~~~~~~~~~~~~
3-Beat Psychological Onboarding Flow — Phase 2

Beat 1: /start          → Greeting (FSM timestamp stored, no DB write yet)
Beat 2: ob_beat_2       → Value proposition (edit message)
Beat 3: ob_beat_3       → Account creation + segmentation + Dashboard
Trust:  ob_how_it_works → Safety explainer (can branch back to Beat 2)

Returning users skip the flow entirely and land directly on the Dashboard.

Bug Fixes (P1/P2):
  - Returning user path no longer calls update_last_login; the lazy streak
    engine in show_dashboard handles last_login stamping and streak logic.
  - ReplyKeyboardMarkup removed from every code path (ReplyKeyboardRemove
    used to clear any stale reply keyboard from older sessions).
  - nav_mission now edits in-place with Phase 3 content.
  - nav_refer now edits in-place (no new message spam).
"""

import logging
import time

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from config import REFEREE_BONUS
from database.db_manager import (
    create_user,
    get_user,
    get_user_by_referral_code,
    increment_spark_balance,
    log_transaction,
    reward_referrer,
    update_user,
    user_exists,
)
from keyboards.inline import (
    mission_keyboard,
    onboarding_beat1_keyboard,
    onboarding_beat2_keyboard,
    onboarding_beat3_keyboard,
    onboarding_trust_keyboard,
    referral_keyboard,
)
from utils.helpers import get_ist_now

logger = logging.getLogger(__name__)
router = Router(name="start")


# ---------------------------------------------------------------------------
# FSM state group — tracks a user mid-onboarding
# ---------------------------------------------------------------------------

class OnboardingState(StatesGroup):
    in_progress = State()


# ---------------------------------------------------------------------------
# Segmentation helpers
# ---------------------------------------------------------------------------

def _time_slot(hour: int) -> str:
    """Categorise an IST hour into a named time slot."""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"


# ---------------------------------------------------------------------------
# Beat 1 — /start (no DB write)
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return

    user_id = user.id
    first_name = user.first_name or "Vault Member"

    # ── Returning user: clear any stale reply keyboard + go straight to dashboard
    if await user_exists(user_id):
        await state.clear()

        # Remove any leftover reply keyboard from old sessions
        await message.answer(
            f"👋 <b>Welcome back, {first_name}!</b> Tera Vault ready hai. 🔥",
            reply_markup=ReplyKeyboardRemove(),
        )

        # Lazy streak engine inside show_dashboard handles last_login stamp
        from handlers.main_menu import show_dashboard
        await show_dashboard(user_id, first_name, message, edit=False)
        logger.info("Returning user login: %s", user_id)
        return

    # ── New user: parse referral deep-link ───────────────────────────────
    referred_by: str | None = None
    if message.text and len(message.text.split()) > 1:
        deep_arg = message.text.split(maxsplit=1)[1].strip()
        if deep_arg.startswith("ref_"):
            referred_by = deep_arg

    # ref_code carried stateless through callback_data — no FSM storage needed
    ref_code = referred_by if referred_by else "none"

    # Store onboarding context in FSM (identity & timing only, NOT referred_by)
    await state.set_state(OnboardingState.in_progress)
    await state.update_data(
        start_ts=int(time.time() * 1000),
        user_id=user_id,
        first_name=first_name,
        username=user.username,
    )
    logger.info("New user started onboarding: %s (%s) ref=%s", user_id, first_name, ref_code)

    # Beat 1 message — ref_code embedded in button callback_data
    await message.answer(
        f"👋 Arre <b>{first_name} bhai</b>, finally aa gaye!\n\n"
        "Main hoon <b>InstaVault</b> — India ka sabse bada "
        "Free Instagram Growth Network.\n\n"
        "Aaj tak <b>1,00,000+ creators</b> ne apna account grow kiya hai "
        "bina ek bhi rupaya kharch kiye.\n\n"
        "Ab teri baari hai. 🚀",
        reply_markup=onboarding_beat1_keyboard(ref_code),
    )


# ---------------------------------------------------------------------------
# Beat 2 — Value proposition (edit Beat 1 message)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("ob_beat_2"))
async def cb_beat_2(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    if query.message is None:
        return

    # Extract ref_code carried stateless from Beat 1 callback_data
    parts = query.data.split(":", 1)
    ref_code = parts[1] if len(parts) > 1 else "none"

    await query.message.edit_text(
        "💎 <b>Yeh kaam kaise karta hai?</b>\n\n"
        "✅ Tu ek simple task complete karta hai <i>(sirf 2-3 minutes)</i>\n"
        "✅ Tujhe milte hain <b>\"Sparks\" ⚡</b>\n"
        "✅ Sparks se tu order karta hai <b>Real Instagram Views</b>\n\n"
        "📌 <b>Rate:</b> 500 Sparks = 1,000 Real Views\n"
        "<i>(Bilkul Free. Koi catch nahi.)</i>\n\n"
        "Abhi tere account mein hain:\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Sparks Balance: 500 Sparks</b>\n"
        "<i>(Welcome Bonus — sirf tere liye!)</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=onboarding_beat2_keyboard(ref_code),
    )


# ---------------------------------------------------------------------------
# Trust Architecture — branches off Beat 2, returns to Beat 2
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("ob_how_it_works"))
async def cb_how_it_works(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return

    # Carry ref_code stateless into trust screen back-button
    parts = query.data.split(":", 1)
    ref_code = parts[1] if len(parts) > 1 else "none"

    await query.message.edit_text(
        "🛡️ <b>InstaVault kyun safe hai?</b>\n\n"
        "❌ Koi hidden charges nahi\n"
        "❌ Koi ads nahi <i>(yahan Telegram pe)</i>\n"
        "❌ Teri Instagram password kabhi nahi maangte\n"
        "❌ Koi fake followers nahi\n\n"
        "✅ <b>Sirf Real Views</b> — Instagram ke algorithm ke saath "
        "100% compatible\n\n"
        "<b>Humara revenue model?</b>\n"
        "Hum ek gaming app ke through earn karte hain, aur uska faida "
        "tujhe milta hai — Free Views ki form mein. "
        "Transparent. Simple. Legit. 💎",
        reply_markup=onboarding_trust_keyboard(ref_code),
    )


# ---------------------------------------------------------------------------
# Beat 3 — Account creation + segmentation write + Dashboard reveal
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("ob_beat_3"))
async def cb_beat_3(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    if query.message is None:
        return

    # Extract ref_code from callback_data (stateless — crash-proof across restarts)
    parts = query.data.split(":", 1)
    referred_by_raw = parts[1] if len(parts) > 1 else "none"
    referred_by: str | None = None if referred_by_raw == "none" else referred_by_raw

    # Pull identity & timing from FSM (fall back to live query data if FSM cleared)
    fsm_data = await state.get_data()
    user_id: int = fsm_data.get("user_id") or query.from_user.id
    first_name: str = (
        fsm_data.get("first_name") or query.from_user.first_name or "Vault Member"
    )
    username: str | None = fsm_data.get("username") or query.from_user.username
    start_ts: int = fsm_data.get("start_ts") or int(time.time() * 1000)

    # ── Segmentation calculations ─────────────────────────────────────────
    now = get_ist_now()
    action_speed_ms = int(time.time() * 1000) - start_ts
    onboarding_time = _time_slot(now.hour)
    source_tag = referred_by if referred_by else "direct"

    # ── Guard: idempotent — don't double-create on double-tap ─────────────
    is_new_user = not await user_exists(user_id)
    if is_new_user:
        await create_user(
            user_id=user_id,
            first_name=first_name,
            username=username,
            referred_by=referred_by,
            source_tag=source_tag,
            onboarding_time=onboarding_time,
            action_speed_ms=action_speed_ms,
        )
        await log_transaction(
            user_id=user_id,
            tx_type="bonus",
            amount=500,
            source="welcome_bonus",
        )
        logger.info(
            "User %s created | speed=%dms | slot=%s | source=%s",
            user_id,
            action_speed_ms,
            onboarding_time,
            source_tag,
        )

        # ── Referral Reward Engine ─────────────────────────────────────────
        if referred_by and referred_by.startswith("ref_"):
            referrer_data = await get_user_by_referral_code(referred_by)
            if referrer_data:
                referrer_uid = referrer_data["_uid"]
                # Overwrite the raw referral code with the actual referrer's user_id
                await update_user(user_id, {"referred_by": referrer_uid})
                # Atomic Sparks + referral_count increment for referrer
                await reward_referrer(referrer_uid)
                # Transaction log for referrer
                await log_transaction(
                    user_id=referrer_uid,
                    tx_type="referral",
                    amount=500,
                    source=f"referral_bonus_{user_id}",
                )
                # Referee bonus — extra Sparks for the new user who joined via link
                await increment_spark_balance(user_id, REFEREE_BONUS)
                await log_transaction(
                    user_id=user_id,
                    tx_type="bonus",
                    amount=REFEREE_BONUS,
                    source=f"referee_bonus_{referrer_uid}",
                )
                logger.info(
                    "Referral resolved: new user %s referred by %s | referee +%d Sparks",
                    user_id,
                    referrer_uid,
                    REFEREE_BONUS,
                )
                # Live notification to referrer (gracefully handles blocked bot)
                try:
                    await query.bot.send_message(
                        int(referrer_uid),
                        "🎉 <b>Badaai ho!</b> Kisi ne tumhare link se InstaVault join kiya hai.\n"
                        "⚡ Tumhare account mein <b>500 Sparks</b> add ho gaye hain!",
                    )
                except Exception as notify_err:
                    logger.warning(
                        "Could not notify referrer %s: %s", referrer_uid, notify_err
                    )

    await state.clear()

    # Beat 3 message — account confirmed, inline navigation only (no reply keyboard)
    await query.message.edit_text(
        f"🎉 <b>Welcome to InstaVault, {first_name}!</b>\n"
        "Tera account ban gaya hai. 🏦\n\n"
        "⚡ <b>Opening Balance:</b> 500 Sparks\n"
        "📊 <b>Member Rank:</b> Rookie Vaulter\n"
        "🔥 <b>Streak:</b> Day 1\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>DAILY MISSION aaj available hai:</b>\n"
        "<i>\"Earn more Sparks aur apna FIRST FREE 1,000 views order kar!\"</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Teri journey abhi shuru hoti hai. 💪",
        reply_markup=onboarding_beat3_keyboard(),
    )


# ---------------------------------------------------------------------------
# nav_ callbacks — routed from Beat 3 inline buttons
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "nav_dashboard")
async def cb_nav_dashboard(query: CallbackQuery) -> None:
    from handlers.main_menu import show_dashboard
    user = query.from_user
    if query.message and user:
        await show_dashboard(user.id, user.first_name or "Member", query.message, edit=False, query=query)


@router.callback_query(F.data == "nav_mission")
async def cb_nav_mission(query: CallbackQuery) -> None:
    """
    Mission screen from dashboard inline button — edits in-place.
    Now shows proper Phase 3 content (fixed from Phase 1 placeholder).
    """
    await query.answer()
    if query.message is None:
        return

    await query.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>AAJ KA MISSION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>Mission:</b> \"The Daily Grind\"\n"
        "Reward:  🪙 <b>400 Sparks</b>\n\n"
        "📋 <b>Kya karna hai:</b>\n"
        "→ InstaVault App kholo\n"
        "→ 2 mini-tasks complete karo\n"
        "→ Sparks automatically credit ho jayenge\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=mission_keyboard(),
    )


@router.callback_query(F.data == "nav_refer")
async def cb_nav_refer(query: CallbackQuery) -> None:
    """
    Referral screen — edits in-place.
    Phase 5: Dynamic bot username + full Viral Growth UI.
    """
    await query.answer()
    if query.message is None:
        return
    user = query.from_user
    if user is None:
        return
    user_data = await get_user(user.id)
    if not user_data:
        await query.message.edit_text("⚠️ Profile not found. Please use /start.")
        return

    referral_code = user_data.get("referral_code", "—")
    ref_count = user_data.get("referral_count", 0)

    deep_link = f"https://t.me/{config.BOT_USERNAME}?start={referral_code}"

    await query.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>REFER &amp; EARN (VIRAL GROWTH)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Apne dosto ko InstaVault pe bulao aur dono Sparks kamao!\n\n"
        f"🎁 <b>Tujhe milega:</b> {config.REFERRAL_JOIN_BONUS} Sparks <i>(Per successful signup)</i>\n"
        f"🎁 <b>Dost ko milega:</b> {config.WELCOME_BONUS} Sparks <i>(Welcome Bonus)</i>\n\n"
        "🔗 <b>Tera Unique Referral Link:</b>\n"
        f"<code>{deep_link}</code>\n"
        "<i>(Is link ko copy kar aur dosto ke saath share kar!)</i>\n\n"
        f"👥 <b>Total Referrals:</b> {ref_count}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=referral_keyboard(referral_code),
    )
