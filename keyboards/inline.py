"""
keyboards/inline.py
~~~~~~~~~~~~~~~~~~~
Inline keyboards for all bot screens.

Phase 2: Onboarding keyboards (ob_*)
Phase 3: Core navigation keyboards (dashboard, mission, order, rewards, profile)
Phase 4: Mystery Box result, Leaderboard

P3 Cleanup: Removed unused `from config import PACKAGES` import.
            Removed deprecated packages_keyboard() (Phase 1 colon-format).
            Single consolidated order flow using order_keyboard_full/empty.
"""

import config
from config.packages import PACKAGES
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ===========================================================================
# Phase 2 — 3-Beat Onboarding keyboards
# ===========================================================================

def onboarding_beat1_keyboard(ref_code: str = "none") -> InlineKeyboardMarkup:
    """Beat 1: initial greeting CTA. ref_code is carried stateless in callback_data."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Get Free Views Now →",
                    callback_data=f"ob_beat_2:{ref_code}",
                )
            ],
        ]
    )


def onboarding_beat2_keyboard(ref_code: str = "none") -> InlineKeyboardMarkup:
    """Beat 2: claim bonus or learn more. ref_code carried forward stateless."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Claim Welcome Bonus",
                    callback_data=f"ob_beat_3:{ref_code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📖 How It Works",
                    callback_data=f"ob_how_it_works:{ref_code}",
                )
            ],
        ]
    )


def onboarding_beat3_keyboard() -> InlineKeyboardMarkup:
    """Beat 3: post-account-creation navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Complete Daily Mission",
                    callback_data="nav_mission",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Dashboard",
                    callback_data="nav_dashboard",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤝 Refer & Earn Bonus",
                    callback_data="nav_refer",
                )
            ],
        ]
    )


def onboarding_trust_keyboard(ref_code: str = "none") -> InlineKeyboardMarkup:
    """Trust architecture screen — back to Beat 2, carrying ref_code stateless."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Back to Welcome Bonus",
                    callback_data=f"ob_beat_2:{ref_code}",
                )
            ],
        ]
    )


# ===========================================================================
# Phase 3 — Core Screen keyboards
# ===========================================================================

def dashboard_keyboard() -> InlineKeyboardMarkup:
    """Main dashboard navigation inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 Daily Mission (Earn 400 Sparks)",
                    callback_data="nav_mission",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 New Order",
                    callback_data="nav_order",
                ),
                InlineKeyboardButton(
                    text="🎁 Rewards",
                    callback_data="nav_rewards",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👤 Profile",
                    callback_data="nav_profile",
                ),
                InlineKeyboardButton(
                    text="🤝 Refer & Earn",
                    callback_data="nav_refer",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Leaderboard",
                    callback_data="nav_leaderboard",
                ),
            ],
        ]
    )


def mission_keyboard() -> InlineKeyboardMarkup:
    """Mission screen."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬇️ Download APK",
                    callback_data="action_download_apk",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def order_keyboard_full() -> InlineKeyboardMarkup:
    """
    Package selection — user has enough Sparks (>= 500).
    Underscore callback format — exclusively handled by orders.py.
    """
    builder = InlineKeyboardBuilder()
    
    for pkg_key, pkg_data in PACKAGES.items():
        btn_text = f"{pkg_data['ui_name']} | {pkg_data['cost']:,} Sparks"
        builder.button(
            text=btn_text,
            callback_data=f"order_pkg_{pkg_key}"
        )
    
    # Add back button
    builder.button(
        text="🏠 Back to Dashboard",
        callback_data="go_dashboard"
    )
    
    # 1 button per row
    builder.adjust(1)
    
    return builder.as_markup()


def order_keyboard_empty() -> InlineKeyboardMarkup:
    """Empty-state keyboard — not enough Sparks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 Complete Missions & Earn",
                    callback_data="nav_mission",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Rewards Center",
                    callback_data="nav_rewards",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def rewards_keyboard() -> InlineKeyboardMarkup:
    """Rewards center."""
    buttons = [
        [
            InlineKeyboardButton(
                text="🎁 Daily Reward Box",
                callback_data="action_mystery_box",
            )
        ]
    ]

    buttons.append([
        InlineKeyboardButton(
            text="🏠 Back to Dashboard",
            callback_data="go_dashboard",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def profile_keyboard(ig_linked: bool = False) -> InlineKeyboardMarkup:
    """Profile management. Button label changes based on whether IG is already linked."""
    link_text = "✏️ Edit IG Handle" if ig_linked else "🔗 Link Instagram"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=link_text,
                    callback_data="action_link_ig",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 My Orders",
                    callback_data="nav_order_history",
                ),
                InlineKeyboardButton(
                    text="🤝 Invite Friends",
                    callback_data="nav_refer",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Daily Reward",
                    callback_data="action_mystery_box",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


# ===========================================================================
# Phase 4 — Mystery Box & Leaderboard keyboards
# ===========================================================================

def mystery_box_result_keyboard() -> InlineKeyboardMarkup:
    """Shown after Mystery Box is opened."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def back_to_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Simple single-button keyboard to navigate back to the dashboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def leaderboard_keyboard() -> InlineKeyboardMarkup:
    """Leaderboard screen navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


# ===========================================================================
# Order confirmation keyboard (used by orders.py confirm flow)
# ===========================================================================

def confirm_order_keyboard(package_type: str, nonce: str) -> InlineKeyboardMarkup:
    """Confirm / cancel an order before deducting Sparks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm Order",
                    callback_data=f"order_confirm:{package_type}:{nonce}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="order_cancel",
                )
            ],
        ]
    )


def admin_order_alert_keyboard(order_id: str, user_id: int) -> InlineKeyboardMarkup:
    """Admin group inline keyboard for order approval/cancellation.

    Three buttons:
      ✅ Approve  — triggers admin_approve:{order_id}
      ❌ Cancel   — triggers admin_cancel:{order_id}
      💬 Message  — URL button opens DM with the user
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=f"admin_approve:{order_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"admin_cancel:{order_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Message User",
                    url=f"tg://user?id={user_id}",
                ),
            ],
        ]
    )


def admin_check_status_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Post-approval keyboard with a Check Status button.

    Replaces the Approve/Cancel buttons after an order is approved.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Check Status",
                    callback_data=f"admin_check:{order_id}",
                ),
            ],
        ]
    )


# ===========================================================================
# Referral & Help keyboards
# ===========================================================================

def referral_keyboard(referral_code: str) -> InlineKeyboardMarkup:
    """Referral screen with share button."""
    bot_username = config.BOT_USERNAME or "InstaVaultBot"
    share_text = (
        f"Join InstaVault aur pao 500 FREE Sparks!\n"
        f"Mera code use karo: {referral_code}\n"
        f"Start here 👉 https://t.me/{bot_username}?start={referral_code}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Share My Link",
                    switch_inline_query=share_text,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Back to Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def order_history_keyboard(has_prev: bool = False, has_next: bool = False, page: int = 0) -> InlineKeyboardMarkup:
    """Order history navigation keyboard."""
    rows = []
    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"order_history_page:{page - 1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"order_history_page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="👤 Profile", callback_data="nav_profile")])
    rows.append([InlineKeyboardButton(text="🏠 Back to Dashboard", callback_data="go_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    """Help center navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Contact Support", callback_data="contact_support")],
            [InlineKeyboardButton(text="📋 FAQ", callback_data="faq")],
            [InlineKeyboardButton(text="🏠 Back to Dashboard", callback_data="go_dashboard")],
        ]
    )
