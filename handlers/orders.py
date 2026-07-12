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
import re
import secrets
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.packages import PACKAGES
from database.db_manager import (
    get_user,
    place_order_transactional,
    InsufficientSparksError,
    UserNotFoundError,
    DuplicateOrderError,
    DuplicateLinkError,
)
from keyboards.inline import (
    back_to_dashboard_keyboard,
    confirm_order_keyboard,
    order_keyboard_empty,
    order_keyboard_full,
)

logger = logging.getLogger(__name__)
router = Router(name="orders")

class OrderState(StatesGroup):
    waiting_for_link = State()


# ---------------------------------------------------------------------------
# Dynamic package data is now driven by config/packages.py
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# /order  |  📦 Order Views
# Exclusively handled here — main_menu.py owns only the nav_order callback.
# ---------------------------------------------------------------------------

@router.message(Command("order"))
@router.message(F.text == "📦 Order Views")
async def cmd_order(message: Message) -> None:
    """Show the package selection menu."""
    user = message.from_user
    if not user:
        return

    user_data = await get_user(user.id)
    if not user_data:
        await message.answer("⚠️ Please use /start first to set up your Vault.")
        return

    sparks = user_data.get("spark_balance", 0)
    
    # Dynamically calculate the minimum package cost
    min_cost = min(pkg["cost"] for pkg in PACKAGES.values()) if PACKAGES else 500
    
    if sparks < min_cost:
        await message.answer(
            "😅 <b>Yaar, Sparks thode kam hain!</b>\n\n"
            f"Minimum needed: <b>{min_cost:,} Sparks</b>\n\n"
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

@router.callback_query(F.data.startswith("order_pkg_"))
async def cb_select_package(query: CallbackQuery, state: FSMContext) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    """User tapped a package — ask for Instagram link."""
    await query.answer()
    
    # Extract package key (e.g. "starter", "growth")
    package_type = query.data.replace("order_pkg_", "")
    
    pkg_data = PACKAGES.get(package_type)
    if not pkg_data:
        await query.message.answer("⚠️ Unknown package. Please try again.")
        return

    user_data = await get_user(query.from_user.id)
    sparks = user_data.get("spark_balance", 0) if user_data else 0
    affordable = sparks >= pkg_data["cost"]
    display_name = pkg_data["ui_name"]

    if not affordable:
        shortage = pkg_data["cost"] - sparks
        await query.message.edit_text(
            f"❌ <b>Insufficient Sparks</b>\n\n"
            f"Package: {display_name}\n"
            f"Cost: <b>{pkg_data['cost']:,} Sparks</b>\n"
            f"Your Balance: <b>{sparks:,} Sparks</b>\n"
            f"Shortfall: <b>{shortage:,} Sparks</b>\n\n"
            f"Complete more missions to earn Sparks! 🎯",
            reply_markup=order_keyboard_empty(),
        )
        return

    # Phase 1 technical data mapping
    await state.update_data(
        package_type=package_type,
        smm_service_id=pkg_data['smm_service_id'],
        cost=pkg_data['cost'],
        views=pkg_data['views']
    )
    
    await state.set_state(OrderState.waiting_for_link)
    await query.message.edit_text(
        f"🔗 <b>Link Daalo</b>\n\n"
        f"Package: <b>{display_name}</b>\n\n"
        f"Apni Instagram Reel ya Post ka link yahan bhejo:\n"
        f"<i>(Link must contain instagram.com and start with http/https)</i>"
    )

@router.message(OrderState.waiting_for_link)
async def handle_order_link(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() in ["/cancel", "cancel"]:
        await state.clear()
        await message.answer("❌ Order cancelled.")
        return

    clean_url = text.split("?")[0].rstrip("/")
    
    # Secondary hardening: Check if user is in penalty timeout
    try:
        from database.redis_manager import get_redis
        redis = get_redis()
        penalty_key = f"penalty:link:{message.from_user.id}"
        if await redis.get(penalty_key):
            await message.answer("🛑 <b>Too many invalid attempts.</b>\n\nPlease wait 30 seconds before trying again.")
            return
    except Exception as e:
        logger.warning("Redis penalty check failed for %s: %s", message.from_user.id, e)
    
    strict_regex = r'^https?://(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/[A-Za-z0-9_-]+/?$'
    if not re.match(strict_regex, clean_url, re.IGNORECASE):
        # Track invalid attempt
        try:
            attempts_key = f"invalid_link_attempts:{message.from_user.id}"
            attempts = await redis.incr(attempts_key)
            if attempts == 1:
                await redis.expire(attempts_key, 30)
            
            if attempts >= 5:
                await redis.setex(penalty_key, 30, "1")
                await redis.delete(attempts_key)
                await message.answer("🛑 <b>Too many invalid attempts.</b>\n\nYou are temporarily blocked from sending links for 30 seconds.")
                return
        except Exception:
            pass

        await message.answer("⚠️ <b>Invalid Link.</b> Please provide a valid Instagram post/reel link.\n\n<i>Example: https://www.instagram.com/reel/xyz123</i>")
        return

    data = await state.get_data()
    package_type = data.get("package_type")
    if not package_type:
        await state.clear()
        await message.answer("⚠️ Session expired. Please try ordering again.")
        return

    pkg = PACKAGES.get(package_type)
    user_data = await get_user(message.from_user.id)
    sparks = user_data.get("spark_balance", 0) if user_data else 0
    display_name = pkg["ui_name"]
    nonce = secrets.token_hex(4)

    await state.update_data(instagram_url=clean_url)
    display_url = clean_url if len(clean_url) <= 35 else clean_url[:35] + "..."
    
    await message.answer(
        f"🛒 <b>ORDER CONFIRMATION</b>\n"
        f"---------------------------\n"
        f"📦 Package: <b>{display_name}</b>\n"
        f"🔗 Link: <code>{display_url}</code>\n"
        f"💰 Cost: <b>{pkg['cost']:,} Sparks</b>\n"
        f"---------------------------\n"
        f"Kya aap is order ko confirm karna chahte hain?",
        reply_markup=confirm_order_keyboard(package_type, nonce),
    )


# ---------------------------------------------------------------------------
# Order confirm / cancel callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("order_confirm:"))
async def cb_confirm_order(query: CallbackQuery, state: FSMContext) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    """
    Confirm order: deduct Sparks, create Firestore order document.
    """
    await query.answer("⏳ Processing…", show_alert=False)
    parts = query.data.split(":")
    package_type = parts[1]
    nonce = parts[2] if len(parts) > 2 else ""

    pkg = PACKAGES.get(package_type)
    if not pkg:
        await query.message.edit_text("⚠️ Unknown package. Please try again.")
        return

    user_id = query.from_user.id
    data = await state.get_data()
    ig_url = data.get("instagram_url", "")
    await state.clear()

    try:
        order_id = await place_order_transactional(
            user_id=user_id,
            package_type=package_type,
            smm_service_id=pkg["smm_service_id"],
            sparks_spent=pkg["cost"],
            views_ordered=pkg["views"],
            instagram_url=ig_url,
            nonce=nonce,
        )
    except InsufficientSparksError:
        await query.message.edit_text(
            "❌ <b>Insufficient Sparks.</b>\n\nYour balance may have changed. Please try again.",
            reply_markup=order_keyboard_empty(),
        )
        return
    except DuplicateOrderError:
        logger.warning("Spam/Duplicate blocked for user %s: Order nonce %s already processed.", user_id, nonce)
        await query.answer("⚠️ Order already processed!", show_alert=True)
        await query.message.edit_text("✅ This order has already been processed successfully.")
        return
    except DuplicateLinkError:
        logger.warning("Spam/Duplicate link blocked for user %s: Link already processing.", user_id)
        await query.answer("⚠️ Is link par pehle se ek order chal raha hai!", show_alert=True)
        await query.message.edit_text(
            "❌ <b>Is link par pehle se ek order chal raha hai.</b>\n\n"
            "Kripya order complete hone ka intezaar karein ya dusra link try karein.",
            reply_markup=order_keyboard_empty()
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

    display_name = pkg["ui_name"]

    # Send alert to Admin Group for approval
    from handlers.admin import send_admin_alert
    await send_admin_alert(
        bot=query.bot,
        order_id=order_id,
        user_id=user_id,
        username=query.from_user.username,
        package_ui_name=display_name,
        views=pkg["views"],
        cost=pkg["cost"],
        instagram_url=ig_url,
    )

    await query.message.edit_text(
        f"✅ <b>Order Submitted!</b>\n\n"
        f"📦 Package: <b>{display_name}</b>\n"
        f"👁 Views: <b>{pkg['views']:,}</b>\n"
        f"🆔 Order ID: <code>{order_id[:12]}</code>\n\n"
        f"Aapka order review ke liye bhej diya gaya hai.\n"
        f"Approve hote hi aapko notification milega! 🚀",
        reply_markup=back_to_dashboard_keyboard(),
    )


@router.callback_query(F.data == "order_cancel")
async def cb_cancel_order(query: CallbackQuery) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    await query.answer("Order cancelled.")
    await query.message.edit_text(
        "❌ <b>Order cancelled.</b>\n\n"
        "Tap 📦 <b>Views Order Karo</b> on your Dashboard to start again.",
        reply_markup=order_keyboard_full(),
    )
