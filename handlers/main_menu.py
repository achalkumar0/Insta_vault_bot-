"""
handlers/main_menu.py
~~~~~~~~~~~~~~~~~~~~~
Phase 3 — Five Core Screens & Navigation
Phase 4 — Engagement Engine: Lazy Streak, Mystery Box, Leaderboard

Screens:
  1. 🏠  Dashboard    (show_dashboard / go_dashboard / /dashboard)
  2. 🚀  Mission      (/mission — nav_mission handled by start.py)
  3. 📦  Order        (nav_order — /order handled exclusively by orders.py)
  4. 🎁  Rewards      (nav_rewards / /rewards)
  5. 📊  Profile      (nav_profile / /profile)
  6. 🎰  Mystery Box  (action_mystery_box)
  7. 🏆  Leaderboard  (nav_leaderboard)

Bug Fixes (P0/P1/P2):
  - P0: cb_mystery_box no longer double-answers the callback query.
  - P1: _run_lazy_streak returns (user_data, popup_shown: bool) so the query
        is answered exactly once per callback.
  - P1: cb_go_dashboard does NOT pre-answer; show_dashboard answers after
        rendering (so milestone popup can still show via query.answer()).
  - P1: Duplicate /order and F.text handlers removed — orders.py owns those.
"""

import html
import logging
import random
import re
from typing import Any
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.db_manager import (
    get_leaderboard,
    get_user,
    get_user_orders,
    increment_spark_balance,
    log_transaction,
    update_user,
    open_mystery_box_transactional,
    CooldownActiveError,
    InsufficientSparksError,
)
from keyboards.inline import (
    back_to_dashboard_keyboard,
    dashboard_keyboard,
    help_keyboard,
    leaderboard_keyboard,
    mission_keyboard,
    mystery_box_result_keyboard,
    order_history_keyboard,
    order_keyboard_empty,
    order_keyboard_full,
    profile_keyboard,
    referral_keyboard,
    rewards_keyboard,
)
from utils.helpers import format_timestamp, get_ist_now

logger = logging.getLogger(__name__)
router = Router(name="main_menu")


# ---------------------------------------------------------------------------
# Phase 6 — Instagram Handle Linking FSM
# ---------------------------------------------------------------------------

class ProfileState(StatesGroup):
    waiting_for_ig_handle = State()


def _clean_ig_handle(raw: str) -> str:
    """
    Strip URL noise and return only the raw Instagram username.
    Handles:
      https://www.instagram.com/achal_123/?hl=en  →  achal_123
      @achal_123                                   →  achal_123
      achal_123                                    →  achal_123
    """
    handle = raw.strip()
    handle = html.unescape(handle)
    handle = re.sub(r"https?://(www\.)?instagram\.com/", "", handle, flags=re.IGNORECASE)
    handle = re.sub(r"[/?].*", "", handle)
    handle = handle.lstrip("@").strip()

    if not re.match(r'^[A-Za-z0-9._]{1,30}$', handle):
        return ""
    return handle


# ===========================================================================
# SCREEN 1 — 🏠 Dashboard  (with Lazy Streak)
# ===========================================================================

async def show_dashboard(
    user_id: int,
    first_name: str,
    message: Message,
    edit: bool = False,
    query: CallbackQuery | None = None,
) -> None:
    """
    Render the dashboard.
    """
    user_data = await get_user(user_id)
    if user_data is None:
        err = "⚠️ Profile not found. Please send /start to set up your Vault."
        if query:
            await query.answer()
        if edit:
            await message.edit_text(err)
        else:
            await message.answer(err)
        return

    sparks = user_data.get("spark_balance", 0)
    rank   = user_data.get("rank_tier", "Rookie Vaulter")
    views  = user_data.get("total_views_recv", 0)

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>InstaVault Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Namaste, <b>{first_name}</b> 👋\n\n"
        f"🪙 Balance:      <b>{sparks:,} Sparks</b>\n"
        f"⚡ Rank:         <b>{rank}</b>\n"
        f"📦 Total Views:  <b>{views:,} delivered</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔴 <b>LIVE ALERT:</b> Aaj ka Mission complete karo aur Sparks kamao!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if edit:
        await message.edit_text(text, reply_markup=dashboard_keyboard())
    else:
        await message.answer(text, reply_markup=dashboard_keyboard())

    if query is not None:
        await query.answer()


@router.message(Command("dashboard"))
@router.message(F.text == "🏠 Dashboard")
async def cmd_dashboard(message: Message) -> None:
    user = message.from_user
    if user:
        await show_dashboard(user.id, user.first_name or "Member", message, edit=False)


@router.callback_query(F.data == "go_dashboard")
async def cb_go_dashboard(query: CallbackQuery) -> None:
    """
    Back-to-dashboard from any sub-screen — edits in place.
    Does NOT pre-answer the query; show_dashboard handles answering
    so milestone streak popups can show correctly.
    """
    user = query.from_user
    if query.message and user:
        await show_dashboard(
            user.id,
            user.first_name or "Member",
            query.message,
            edit=True,
            query=query,
        )


# ===========================================================================
# SCREEN 2 — 🚀 Mission
# nav_mission callback is owned by start.py (edits in-place with Phase 3 content).
# /mission command sends a fresh message.
# ===========================================================================

@router.message(Command("mission"))
@router.message(F.text == "🎯 Mission")
async def cmd_mission(message: Message) -> None:
    await message.answer(
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


# ===========================================================================
# SCREEN 3 — 📦 Views Order Karo
# /order command and F.text == "📦 Order Views" are exclusively in orders.py.
# This file only owns the nav_order inline callback.
# ===========================================================================

@router.callback_query(F.data == "nav_order")
async def cb_nav_order(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    user_id = query.from_user.id
    await _render_order_screen(user_id, query.message, edit=True)


async def _render_order_screen(
    user_id: int, message: Message, edit: bool
) -> None:
    """Shared order screen renderer with empty-state guard."""
    user_data = await get_user(user_id)
    sparks = user_data.get("spark_balance", 0) if user_data else 0

    if sparks < 500:
        text = (
            "😅 <b>Yaar, Sparks thode kam hain!</b>\n\n"
            "Minimum needed: <b>500 Sparks</b>\n\n"
            "Mission complete kar ya Mystery Box khol aur Sparks kamao!"
        )
        kb = order_keyboard_empty()
    else:
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>VIEWS ORDER KARO</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>Tera Balance:</b> {sparks:,} Sparks\n\n"
            "🛒 <b>Package Select Karo:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = order_keyboard_full()

    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


# ===========================================================================
# SCREEN 4 — 🎁 Rewards Center
# ===========================================================================

@router.message(Command("rewards"))
@router.message(F.text == "🏆 Rewards")
async def cmd_rewards(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await _render_rewards_screen(user.id, message, edit=False)


@router.callback_query(F.data == "nav_rewards")
async def cb_nav_rewards(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    await _render_rewards_screen(query.from_user.id, query.message, edit=True)


async def _render_rewards_screen(
    user_id: int, message: Message, edit: bool
) -> None:
    user_data = await get_user(user_id)
    streak = user_data.get("streak_days", 0) if user_data else 0
    shields = user_data.get("streak_shields", 0) if user_data else 0

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>REWARDS CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>Current Streak:</b> {streak} Days\n"
        f"🛡️ <b>Streak Shields:</b> {shields} / 3\n\n"
        "🎰 <b>Mystery Box:</b> Open for 100 Sparks to win up to 2,000 Sparks!\n"
        "🛡️ <b>Streak Shield:</b> Buy for 200 Sparks to protect your streak from resetting if you miss a day!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if edit:
        await message.edit_text(text, reply_markup=rewards_keyboard(shields=shields))
    else:
        await message.answer(text, reply_markup=rewards_keyboard(shields=shields))


# ===========================================================================
# SCREEN 5 — 📊 Mera Profile
# ===========================================================================

@router.message(Command("profile"))
@router.message(F.text == "👤 Profile")
async def cmd_profile(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await _render_profile_screen(
        user.id, user.first_name or "Member", message, edit=False
    )


@router.callback_query(F.data == "nav_profile")
async def cb_nav_profile(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    user = query.from_user
    await _render_profile_screen(
        user.id, user.first_name or "Member", query.message, edit=True
    )


async def _render_profile_screen(
    user_id: int, first_name: str, message: Message, edit: bool
) -> None:
    user_data = await get_user(user_id)
    if not user_data:
        err = "⚠️ Profile not found. Please send /start."
        if edit:
            await message.edit_text(err)
        else:
            await message.answer(err)
        return

    vault_id     = user_data.get("vault_id", "—")
    join_date    = user_data.get("join_date")
    total_orders = user_data.get("total_orders", 0)
    ref_count    = user_data.get("referral_count", 0)
    sparks       = user_data.get("spark_balance", 0)
    rank         = user_data.get("rank_tier", "Rookie Vaulter")
    streak       = user_data.get("streak_days", 0)
    ig_handle    = user_data.get("instagram_handle")
    join_fmt     = format_timestamp(join_date, fmt="%d %b %Y")

    ig_line = f"📸 <b>Instagram:</b>      @{ig_handle}" if ig_handle else "📸 <b>Instagram:</b>      ❌ Not Linked"

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>TERA VAULT PROFILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Name:</b>         {first_name}\n"
        f"🆔 <b>Vault ID:</b>     <code>{vault_id}</code>\n"
        f"📅 <b>Member Since:</b> {join_fmt}\n"
        f"{ig_line}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Sparks Balance:</b>   {sparks:,}\n"
        f"👑 <b>Current Rank:</b>     {rank}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Total Orders:</b>     {total_orders}\n"
        f"🤝 <b>Total Referrals:</b>  {ref_count}\n"
        f"🔥 <b>Best Streak:</b>      {streak}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if edit:
        await message.edit_text(text, reply_markup=profile_keyboard(ig_linked=bool(ig_handle)))
    else:
        await message.answer(text, reply_markup=profile_keyboard(ig_linked=bool(ig_handle)))


# ===========================================================================
# SCREEN 6 — 🎰 Mystery Box  (Phase 4)
# P0 Fix: query is answered exactly once per code path.
# ===========================================================================

_BOX_TIERS = [
    (25,   75,   50),   # 50% — Common
    (100,  300,  30),   # 30% — Uncommon
    (350,  750,  15),   # 15% — Rare
    (1000, 2000,  5),   #  5% — Legendary
]


@router.callback_query(F.data == "action_mystery_box")
async def cb_mystery_box(query: CallbackQuery) -> None:
    """
    Mystery Box handler.
    query.answer() is called exactly once:
      - With show_alert=True on cooldown hit or profile-not-found.
      - With silent answer() on success (before editing the message).
    """
    if query.message is None:
        await query.answer()
        return

    user_id = query.from_user.id
    user_data = await get_user(user_id)
    if not user_data:
        await query.answer("⚠️ Profile not found. Please use /start.", show_alert=True)
        return

    # ── Cooldown check — one box per calendar day (IST) ──────────────────
    today_str = get_ist_now().strftime("%Y-%m-%d")
    last_box_date = user_data.get("last_mystery_box_date")

    if last_box_date == today_str:
        await query.answer(
            "😅 Aaj ka box khul chuka hai! Kal wapas aana. 🌙",
            show_alert=True,
        )
        return

    # ── Weighted prize draw ───────────────────────────────────────────────
    mins    = [t[0] for t in _BOX_TIERS]
    maxs    = [t[1] for t in _BOX_TIERS]
    weights = [t[2] for t in _BOX_TIERS]

    chosen_idx = random.choices(range(len(_BOX_TIERS)), weights=weights, k=1)[0]
    won_sparks = random.randint(mins[chosen_idx], maxs[chosen_idx])

    # ── Atomic DB writes ──────────────────────────────────────────────────
    try:
        await open_mystery_box_transactional(user_id, cost_sparks=100, won_sparks=won_sparks)
    except CooldownActiveError:
        await query.answer("😅 Aaj ka box khul chuka hai! Kal wapas aana. 🌙", show_alert=True)
        return
    except InsufficientSparksError:
        await query.answer("⚠️ Mystery Box kholne ke liye 100 Sparks chahiye!", show_alert=True)
        return

    # ── Answer once, then edit message ───────────────────────────────────
    await query.answer()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>Box Khul Gaya!</b>\n\n"
        "⚡ <b>100 Sparks spent!</b>\n"
        f"🎉 Tujhe mila: <b>{won_sparks} Sparks!</b> ⚡\n\n"
        "Kal bhi try karna — kal ka box aaj se bada ho sakta hai! 😄\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await query.message.edit_text(text, reply_markup=mystery_box_result_keyboard())


# ===========================================================================
# SCREEN 7 — 🏆 Leaderboard  (Phase 4)
# ===========================================================================

_RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


@router.callback_query(F.data == "nav_leaderboard")
async def cb_nav_leaderboard(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return

    top_users = await get_leaderboard(limit=10)

    if not top_users:
        await query.message.edit_text(
            "🏆 <b>Leaderboard abhi khali hai.</b>\n\n"
            "Missions complete karo aur pehle ban jao! 🚀",
            reply_markup=leaderboard_keyboard(),
        )
        return

    lines: list[str] = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "🏆 <b>INSTAVAULT LEADERBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for i, user in enumerate(top_users, start=1):
        medal  = _RANK_MEDALS.get(i, f"{i}.")
        raw_name = user.get("first_name") or "Anonymous"
        name   = html.escape(raw_name)
        sparks = int(user.get("spark_balance", 0))
        lines.append(f"{medal} {name} — <b>{sparks:,} ⚡</b>")

    lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━"]

    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=leaderboard_keyboard(),
    )


# ===========================================================================
# /help
# ===========================================================================

@router.message(Command("help"))
@router.message(F.text == "❓ Help")
async def cmd_help(message: Message) -> None:
    await message.answer(
        "❓ <b>InstaVault Help Center</b>\n\n"
        "⚡ <b>Sparks</b> — Virtual currency. Earn by doing missions.\n"
        "🎯 <b>Mission</b> — 1 daily mission (more with higher streaks).\n"
        "📦 <b>Order</b> — Spend Sparks to get real Instagram views.\n"
        "🔥 <b>Streak</b> — Log in daily to grow your streak & unlock rewards.\n"
        "👥 <b>Refer</b> — Share your link; earn Sparks for every friend.\n\n"
        "<i>Need more help? Tap the button below.</i>",
        reply_markup=help_keyboard(),
    )


# ===========================================================================
# SCREEN 8 — 📦 Order History
# ===========================================================================

_STATUS_DISPLAY = {
    "pending":   "⏳ Pending",
    "delivered": "✅ Delivered",
    "cancelled": "❌ Cancelled",
}

_PKG_NAMES = {
    "starter": "🌱 Starter Boost",
    "growth":  "🔥 Growth Pack",
    "pro":     "💎 Pro Blast",
    "mega":    "⚡ Mega",
}

_HISTORY_PAGE_SIZE = 3


async def _render_order_history(
    user_id: int,
    message: Message,
    edit: bool,
    page: int = 0,
) -> None:
    """Fetch and render paginated order history for a user."""
    orders = await get_user_orders(user_id, limit=50)

    if not orders:
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>ORDER HISTORY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "😅 <b>Abhi tak koi order nahi kiya!</b>\n\n"
            "Sparks kamao aur apna pehla order dalo. 🚀\n"
            "━━━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = order_history_keyboard()
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return

    total = len(orders)
    total_pages = max(1, (total + _HISTORY_PAGE_SIZE - 1) // _HISTORY_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_orders = orders[page * _HISTORY_PAGE_SIZE : (page + 1) * _HISTORY_PAGE_SIZE]

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "📦 <b>ORDER HISTORY</b>",
        f"<i>Page {page + 1}/{total_pages}  •  Total: {total} orders</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, order in enumerate(page_orders, start=page * _HISTORY_PAGE_SIZE + 1):
        order_id  = order.get("order_id", "—")
        pkg       = _PKG_NAMES.get(order.get("package_type", ""), order.get("package_type", "—").title())
        views     = int(order.get("views_ordered", 0))
        sparks    = int(order.get("sparks_spent", 0))
        ig        = order.get("instagram_url") or "—"
        status    = _STATUS_DISPLAY.get(order.get("status", "pending"), "🔄 Processing")
        created   = format_timestamp(order.get("created_at"), fmt="%d %b %Y, %I:%M %p")

        lines += [
            "",
            f"<b>Order #{i}  —  {pkg}</b>",
            f"🆔 ID: <code>{order_id[:12]}…</code>",
            f"📅 {created} IST",
            f"👁 Views: <b>{views:,}</b>   ⚡ Cost: <b>{sparks:,} Sparks</b>",
            f"📸 IG Handle: @{ig}",
            f"📊 Status: {status}",
        ]

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    text = "\n".join(lines)
    kb = order_history_keyboard(
        has_prev=(page > 0),
        has_next=(page < total_pages - 1),
        page=page,
    )

    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "nav_order_history")
async def cb_nav_order_history(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    await _render_order_history(query.from_user.id, query.message, edit=True, page=0)


@router.callback_query(F.data.startswith("order_history_page:"))
async def cb_order_history_page(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    try:
        page = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0
    await _render_order_history(query.from_user.id, query.message, edit=True, page=page)


# ===========================================================================
# Placeholder / Coming-Soon callbacks (anti-crash protocol)
# ===========================================================================

_COMING_SOON = {
    "dummy_app_link",
    "order_pkg_mega",       # Mega package — Phase 5
    "contact_support",
    "faq",
    "mission_start",
    "mystery_box_open",
    "jackpot_tickets",
    "notif_settings",
    "tx_history",
}


@router.callback_query(F.data.in_(_COMING_SOON))
async def cb_coming_soon(query: CallbackQuery) -> None:
    await query.answer("🚧 Coming soon! Yeh feature Phase 5 mein aayega.", show_alert=True)


# ===========================================================================
# PHASE 6 — Instagram Handle Linking (FSM)
# ===========================================================================

@router.callback_query(F.data == "action_link_ig")
async def cb_action_link_ig(query: CallbackQuery, state: FSMContext) -> None:
    """Enter FSM: prompt the user to send their Instagram handle or URL."""
    await query.answer()
    if query.message is None:
        return

    await state.set_state(ProfileState.waiting_for_ig_handle)

    await query.message.edit_text(
        "📸 <b>Instagram Handle Link Karo</b>\n\n"
        "Apna Instagram username ya profile link bhejo.\n\n"
        "<i>Example:</i>\n"
        "• <code>achal_123</code>\n"
        "• <code>@achal_123</code>\n"
        "• <code>https://www.instagram.com/achal_123/</code>\n\n"
        "<i>(Cancel karne ke liye /cancel bhejein)</i>",
    )


@router.message(ProfileState.waiting_for_ig_handle)
async def handle_ig_input(message: Message, state: FSMContext) -> None:
    """Receive user input, clean it, save to Firestore, confirm."""
    if message.text is None:
        await message.answer("⚠️ Please send your Instagram username as text.")
        return

    raw = message.text.strip()

    # Cancel shortcut via text (besides /cancel command)
    if raw.lower() in ("/cancel", "cancel"):
        await state.clear()
        await message.answer(
            "❌ Instagram linking cancelled.",
            reply_markup=back_to_dashboard_keyboard(),
        )
        return

    # Block other bot commands from being captured as an IG handle
    if raw.startswith("/"):
        await message.answer("⚠️ Please send your Instagram handle, not a command. Type /cancel to exit.")
        return

    cleaned = _clean_ig_handle(raw)

    if not cleaned:
        await message.answer(
            "⚠️ <b>Invalid username.</b> Please send a valid Instagram handle or profile link."
        )
        return

    user_id = message.from_user.id
    await update_user(user_id, {"instagram_handle": cleaned})
    await state.clear()

    logger.info("User %s linked Instagram handle: %s", user_id, cleaned)

    await message.answer(
        f"✅ <b>Tera Instagram handle (@{cleaned}) successfully link ho gaya hai</b> "
        f"aur database mein save ho chuka hai!",
        reply_markup=back_to_dashboard_keyboard(),
    )


@router.message(Command("cancel"), ProfileState.waiting_for_ig_handle)
async def cmd_cancel_link(message: Message, state: FSMContext) -> None:
    """/cancel command clears the IG linking FSM."""
    await state.clear()
    await message.answer(
        "❌ Instagram linking cancelled.",
        reply_markup=back_to_dashboard_keyboard(),
    )
