"""
handlers/admin.py
~~~~~~~~~~~~~~~~~
Admin Group "Human-in-the-Loop" Control Panel.

Responsibilities:
  - Send order alert tickets to the Admin Telegram Group.
  - Handle ✅ Approve and ❌ Cancel callbacks from admin buttons.
  - Security: All callbacks are verified against ADMIN_GROUP_ID to
    prevent forwarded-message exploit attacks.

Architecture Note:
  The _send_admin_alert() helper is called from handlers/orders.py
  after a successful order placement. It is imported there, NOT
  called via router — keeping the alert logic centralised here.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
from database.db_manager import (
    cancel_order_and_refund,
    get_order,
    update_order_status,
    delete_link_lock,
)
from keyboards.inline import admin_order_alert_keyboard, admin_check_status_keyboard

logger = logging.getLogger(__name__)
router = Router(name="admin")


# ===========================================================================
# ADMIN ALERT — Send Order Ticket to Group
# ===========================================================================

async def send_admin_alert(
    bot,
    order_id: str,
    user_id: int,
    username: str | None,
    package_ui_name: str,
    views: int,
    cost: int,
    instagram_url: str,
) -> None:
    """Send a formatted order ticket to the admin group.

    Called from handlers/orders.py after successful order placement.
    Silently skips if ADMIN_GROUP_ID is not configured (dev/test env).
    """
    if not config.ADMIN_GROUP_ID:
        logger.warning("ADMIN_GROUP_ID not set — skipping admin alert for order %s", order_id)
        return

    user_display = f"@{username}" if username else "No username"
    display_url = instagram_url if len(instagram_url) <= 45 else instagram_url[:45] + "..."

    text = (
        f"🚨 <b>NAYA ORDER AAYA HAI!</b> 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Order ID: <code>{order_id[:12]}</code>\n"
        f"👤 User: {user_display} (ID: <code>{user_id}</code>)\n"
        f"📦 Package: <b>{package_ui_name}</b>\n"
        f"👁 Views: <b>{views:,}</b>\n"
        f"💰 Cost: <b>{cost:,} Sparks</b>\n"
        f"🔗 Link: {display_url}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    try:
        await bot.send_message(
            chat_id=config.ADMIN_GROUP_ID,
            text=text,
            reply_markup=admin_order_alert_keyboard(order_id, user_id),
            disable_web_page_preview=True,
        )
        logger.info("Admin alert sent for order %s", order_id)
    except Exception as e:
        logger.error("Failed to send admin alert for order %s: %s", order_id, e, exc_info=True)


# ===========================================================================
# ADMIN CALLBACKS — Approve / Cancel
# ===========================================================================

def _verify_admin_group(query: CallbackQuery) -> bool:
    """Security lock: ensure the callback came from the admin group."""
    if not config.ADMIN_GROUP_ID:
        return False
    return query.message.chat.id == config.ADMIN_GROUP_ID


# ---------------------------------------------------------------------------
# ❌ Cancel & Refund
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("admin_cancel:"))
async def cb_admin_cancel(query: CallbackQuery) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    """Admin cancels an order — refund Sparks, release link lock, notify user."""
    if not _verify_admin_group(query):
        await query.answer("⛔ This button only works in the Admin Group.", show_alert=True)
        return

    await query.answer("⏳ Cancelling & Refunding...")
    order_id = query.data.split(":", 1)[1]

    try:
        order_data = await cancel_order_and_refund(order_id)
    except ValueError as e:
        await query.answer(f"⚠️ {e}", show_alert=True)
        return
    except Exception as e:
        logger.error("Admin cancel failed for order %s: %s", order_id, e, exc_info=True)
        await query.answer("⚠️ Error processing cancellation.", show_alert=True)
        return

    # Update admin group message — remove buttons, show cancelled status
    admin_name = query.from_user.first_name or "Admin"
    await query.message.edit_text(
        query.message.text + f"\n\n❌ <b>Cancelled & Refunded</b>\nBy: {admin_name}",
        reply_markup=None,
    )

    # Notify the user via DM
    user_id = int(order_data["user_id"])
    sparks = order_data["sparks_spent"]
    try:
        await query.bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ <b>Order Cancelled</b>\n\n"
                f"🆔 Order: <code>{order_id[:12]}</code>\n"
                f"Aapka order cancel ho gaya hai.\n"
                f"💰 <b>{sparks:,} Sparks</b> aapke account mein wapas aa gaye hain.\n\n"
                f"Koi sawal ho toh admin se contact karein."
            ),
        )
    except Exception as e:
        logger.warning("Could not notify user %s about cancellation: %s", user_id, e)


# ---------------------------------------------------------------------------
# ✅ Approve — Place order on SMM Panel
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("admin_approve:"))
async def cb_admin_approve(query: CallbackQuery) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    """Admin approves an order — hit SMM API, save smm_order_id, notify user."""
    if not _verify_admin_group(query):
        await query.answer("⛔ This button only works in the Admin Group.", show_alert=True)
        return

    await query.answer("⏳ Approving & placing on SMM Panel...")
    order_id = query.data.split(":", 1)[1]

    # Fetch order to verify it's still pending_approval
    order_data = await get_order(order_id)
    if not order_data:
        await query.answer("⚠️ Order not found.", show_alert=True)
        return

    if order_data.get("status") != "pending_approval":
        await query.answer(
            f"⚠️ Order already {order_data.get('status')}",
            show_alert=True,
        )
        return

    # Hit the SMM Panel API
    from services.smm_api import place_order as smm_place_order, SMMApiError, SMMApiConfigError

    smm_order_id = None
    api_note = ""

    try:
        smm_order_id = await smm_place_order(
            service_id=order_data["smm_service_id"],
            link=order_data["instagram_url"],
            quantity=order_data["views_ordered"],
        )
        api_note = f"\n🔢 SMM ID: <code>{smm_order_id}</code>"
    except SMMApiConfigError:
        # API not configured yet — approve anyway but warn admin
        logger.warning("SMM API not configured — approving order %s without API call.", order_id)
        api_note = "\n⚠️ <i>SMM API not configured — manual fulfillment needed</i>"
    except SMMApiError as e:
        logger.error("SMM API failed for order %s: %s", order_id, e)
        await query.message.edit_text(
            query.message.text
            + f"\n\n❌ <b>SMM API Failed</b>\nError: {e}\n\n<i>Order still pending. Try again or Cancel.</i>",
        )
        return

    # Update Firestore: status → processing, save smm_order_id
    await update_order_status(
        order_id,
        status="processing",
        smm_order_id=smm_order_id,
    )

    # Update admin group message — remove old buttons, show approved status
    admin_name = query.from_user.first_name or "Admin"
    await query.message.edit_text(
        query.message.text
        + f"\n\n✅ <b>Approved & Processing</b>"
        + api_note
        + f"\nBy: {admin_name}",
        reply_markup=admin_check_status_keyboard(order_id),
    )

    # Notify the user via DM
    user_id = int(order_data["user_id"])
    try:
        await query.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>Order Approved!</b>\n\n"
                f"🆔 Order: <code>{order_id[:12]}</code>\n"
                f"Aapka order accept ho gaya hai aur processing mein hai!\n"
                f"Views jaldi deliver ho jayenge. 🚀"
            ),
        )
    except Exception as e:
        logger.warning("Could not notify user %s about approval: %s", user_id, e)


# ---------------------------------------------------------------------------
# 🔄 Check Status — Lazy Polling from Admin Group
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("admin_check:"))
async def cb_admin_check_status(query: CallbackQuery) -> None:
    if not query.message or not hasattr(query.message, 'edit_text'):
        return
    """Admin checks order status — fetch live status from SMM Panel API."""
    if not _verify_admin_group(query):
        await query.answer("⛔ This button only works in the Admin Group.", show_alert=True)
        return

    await query.answer("⏳ Checking SMM Panel...")
    order_id = query.data.split(":", 1)[1]

    # Fetch order from Firestore
    order_data = await get_order(order_id)
    if not order_data:
        await query.answer("⚠️ Order not found.", show_alert=True)
        return

    smm_order_id = order_data.get("smm_order_id")
    current_status = order_data.get("status", "")

    # If already completed/cancelled, just show status
    if current_status in ("completed", "cancelled"):
        await query.answer(f"Order already {current_status}", show_alert=True)
        return

    # If no SMM order ID, can't check
    if not smm_order_id:
        await query.answer(
            "⚠️ No SMM Order ID found — API was not configured at approval time.",
            show_alert=True,
        )
        return

    # Hit SMM Panel API for live status
    from services.smm_api import check_status as smm_check_status, SMMApiError

    try:
        api_data = await smm_check_status(smm_order_id)
    except SMMApiError as e:
        logger.error("SMM status check failed for order %s: %s", order_id, e)
        await query.answer(f"⚠️ API Error: {e}", show_alert=True)
        return

    # Parse the SMM Panel's status response
    smm_status = str(api_data.get("status", "")).lower().strip()
    remains = api_data.get("remains", "?")

    # Conditional Branching (as per hello.md Phase 4)
    if smm_status in ("completed", "complete"):
        # ORDER COMPLETED — update DB, notify user, update admin UI
        from utils.helpers import get_ist_now
        await update_order_status(
            order_id,
            status="completed",
            delivered_at=get_ist_now(),
        )

        # Release the link lock so the URL can be reused
        ig_url = order_data.get("instagram_url", "")
        if ig_url:
            await delete_link_lock(ig_url)

        # Update admin message — permanent completion
        await query.message.edit_text(
            query.message.text.split("\n\n✅")[0]  # Keep original order info
            + f"\n\n🟢 <b>COMPLETED</b>"
            + f"\n🔢 SMM ID: <code>{smm_order_id}</code>",
            reply_markup=None,
        )

        # Notify user
        user_id = int(order_data["user_id"])
        try:
            await query.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 <b>Order Completed!</b>\n\n"
                    f"🆔 Order: <code>{order_id[:12]}</code>\n"
                    f"Aapke views successfully deliver ho gaye hain! 🟢\n\n"
                    f"Naya order karne ke liye /order use karein."
                ),
            )
        except Exception as e:
            logger.warning("Could not notify user %s about completion: %s", user_id, e)

    elif smm_status in ("canceled", "cancelled", "refunded"):
        # SMM Panel ne khud cancel kar diya — refund user
        try:
            order_data = await cancel_order_and_refund(order_id)
        except ValueError:
            pass  # Already cancelled

        await query.message.edit_text(
            query.message.text.split("\n\n✅")[0]
            + f"\n\n🔴 <b>SMM Panel Cancelled/Refunded</b>"
            + f"\n🔢 SMM ID: <code>{smm_order_id}</code>",
            reply_markup=None,
        )

        user_id = int(order_data["user_id"])
        sparks = order_data.get("sparks_spent", 0)
        try:
            await query.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ <b>Order Refunded</b>\n\n"
                    f"🆔 Order: <code>{order_id[:12]}</code>\n"
                    f"SMM Panel ne is order ko cancel kar diya hai.\n"
                    f"💰 <b>{sparks:,} Sparks</b> aapke account mein wapas aa gaye hain."
                ),
            )
        except Exception as e:
            logger.warning("Could not notify user %s about SMM cancellation: %s", user_id, e)

    else:
        # Still processing — show live status, keep Check Status button
        await query.answer(
            f"📊 Status: {smm_status.upper()} | Remains: {remains}",
            show_alert=True,
        )
