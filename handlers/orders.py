"""
handlers/orders.py
~~~~~~~~~~~~~~~~~~
Handles /order command and package selection callbacks.

Phase 3 consolidation:
  - All package callbacks now use underscore format (order_pkg_starter, etc.)
    matching order_keyboard_full() — no more colon-format duplicates.
  - /order command and F.text == "📦 Order Views" are exclusively here;
    main_menu.py only owns the nav_order inline callback.
  - IG handle guard enforced on the /order command entry point.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import PACKAGES
from database.db_manager import (
    get_user,
    place_order_transactional,
    InsufficientSparksError,
    UserNotFoundError,
)
from keyboards.inline import (
    confirm_order_keyboard,
    order_keyboard_empty,
    order_keyboard_full,
)

logger = logging.getLogger(__name__)
router = Router(name="orders")

# ---------------------------------------------------------------------------
# Callback → package_type mapping (underscore format, Phase 3 standard)
# ---------------------------------------------------------------------------
_PKG_CALLBACK_MAP: dict[str, str] = {
    "order_pkg_starter": "starter",
    "order_pkg_growth":  "growth",
    "order_pkg_pro":     "pro",
}

_PKG_DISPLAY: dict[str, str] = {
    "starter": "🌱 Starter Boost",
    "growth":  "🔥 Growth Pack",
    "pro":     "💎 Pro Blast",
    "mega":    "⚡ Mega",
}


# ---------------------------------------------------------------------------
# /order  |  📦 Order Views
# Exclusively handled here — main_menu.py owns only the nav_order callback.
# ---------------------------------------------------------------------------

@router.message(Command("order"))
@router.message(F.text == "📦 Order Views")
async def cmd_order(message: Message) -> None:
    """Show the package selection menu (with IG handle guard)."""
    user = message.from_user
    if not user:
        return

    user_data = await get_user(user.id)
    if not user_data:
        await message.answer("⚠️ Please use /start first to set up your Vault.")
        return

    sparks = user_data.get("spark_balance", 0)
    ig = user_data.get("instagram_handle")

    if not ig:
        await message.answer(
            "📸 <b>Instagram handle not set!</b>\n\n"
            "Please link your Instagram in 👤 <b>Profile</b> before ordering.",
        )
        return

    if sparks < 500:
        await message.answer(
            "😅 <b>Yaar, Sparks thode kam hain!</b>\n\n"
            "Minimum needed: <b>500 Sparks</b>\n\n"
            "Mission complete kar ya Mystery Box khol aur Sparks kamao!",
            reply_markup=order_keyboard_empty(),
        )
        return

    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 <b>VIEWS ORDER KARO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Tera Balance:</b> {sparks:,} Sparks\n\n"
        "🛒 <b>Package Select Karo:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=order_keyboard_full(),
    )


# ---------------------------------------------------------------------------
# Package selection callback (underscore format)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.in_(_PKG_CALLBACK_MAP))
async def cb_select_package(query: CallbackQuery) -> None:
    """User tapped a package — show confirmation with cost breakdown."""
    await query.answer()
    package_type = _PKG_CALLBACK_MAP[query.data]

    pkg = PACKAGES.get(package_type)
    if not pkg:
        await query.message.answer("⚠️ Unknown package. Please try again.")
        return

    user_data = await get_user(query.from_user.id)
    sparks = user_data.get("spark_balance", 0) if user_data else 0
    affordable = sparks >= pkg["sparks"]
    display_name = _PKG_DISPLAY.get(package_type, package_type.title())

    if not affordable:
        shortage = pkg["sparks"] - sparks
        await query.message.edit_text(
            f"❌ <b>Insufficient Sparks</b>\n\n"
            f"Package: {display_name}\n"
            f"Cost: <b>{pkg['sparks']:,} Sparks</b>\n"
            f"Your Balance: <b>{sparks:,} Sparks</b>\n"
            f"Shortfall: <b>{shortage:,} Sparks</b>\n\n"
            f"Complete more missions to earn Sparks! 🎯",
            reply_markup=order_keyboard_empty(),
        )
        return

    await query.message.edit_text(
        f"🛒 <b>Order Confirmation</b>\n\n"
        f"Package: <b>{display_name}</b>\n"
        f"Views: <b>{pkg['views']:,}</b>\n"
        f"Cost: <b>{pkg['sparks']:,} Sparks</b>\n"
        f"Balance After: <b>{sparks - pkg['sparks']:,} Sparks</b>\n\n"
        f"Confirm your order?",
        reply_markup=confirm_order_keyboard(package_type),
    )


# ---------------------------------------------------------------------------
# Order confirm / cancel callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("order_confirm:"))
async def cb_confirm_order(query: CallbackQuery) -> None:
    """
    Confirm order: deduct Sparks, create Firestore order document.
    Full delivery tracking will be implemented in Phase 5.
    """
    await query.answer("⏳ Processing…", show_alert=False)
    package_type = query.data.split(":")[1]

    pkg = PACKAGES.get(package_type)
    if not pkg:
        await query.message.edit_text("⚠️ Unknown package. Please try again.")
        return

    user_id = query.from_user.id
    user_data = await get_user(user_id)
    ig = (user_data or {}).get("instagram_handle", "")

    try:
        order_id = await place_order_transactional(
            user_id=user_id,
            package_type=package_type,
            sparks_spent=pkg["sparks"],
            views_ordered=pkg["views"],
            instagram_url=ig or "",
        )
    except InsufficientSparksError:
        await query.message.edit_text(
            "❌ <b>Insufficient Sparks.</b>\n\nYour balance may have changed. Please try again.",
            reply_markup=order_keyboard_empty(),
        )
        return
    except UserNotFoundError:
        await query.message.edit_text(
            "⚠️ Please use /start first to set up your Vault."
        )
        return
    except Exception as e:
        logger.error("Failed to place order for user %s: %s", user_id, e, exc_info=True)
        await query.message.edit_text(
            "⚠️ An error occurred while processing your order. Please try again later."
        )
        return

    display_name = _PKG_DISPLAY.get(package_type, package_type.title())
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    await query.message.edit_text(
        f"✅ <b>Order Placed!</b>\n\n"
        f"Package: <b>{display_name}</b>\n"
        f"Views: <b>{pkg['views']:,}</b>\n"
        f"Order ID: <code>{order_id[:8]}…</code>\n\n"
        f"Views will be delivered within <b>45 minutes</b>. 🚀\n\n"
        f"<i>Full delivery tracking coming in Phase 5.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Dashboard", callback_data="go_dashboard")],
        ]),
    )


@router.callback_query(F.data == "order_cancel")
async def cb_cancel_order(query: CallbackQuery) -> None:
    await query.answer("Order cancelled.")
    await query.message.edit_text(
        "❌ <b>Order cancelled.</b>\n\n"
        "Tap 📦 <b>Views Order Karo</b> on your Dashboard to start again.",
        reply_markup=order_keyboard_full(),
    )
