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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ===========================================================================
# Phase 2 — 3-Beat Onboarding keyboards
# ===========================================================================

def onboarding_beat1_keyboard(ref_code: str = "none") -> InlineKeyboardMarkup:
    """Beat 1: initial greeting CTA. ref_code is carried stateless in callback_data."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Haan, mujhe Free Views chahiye! →",
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
                    text="🎁 Apna Welcome Bonus Claim Karo",
                    callback_data=f"ob_beat_3:{ref_code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📖 Yeh kya hota hai? (How it Works)",
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
                    text="🚀 Aaj ka Mission Complete Karo",
                    callback_data="nav_mission",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Mera Dashboard",
                    callback_data="nav_dashboard",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤝 Dost ko Refer Karo (Bonus Sparks)",
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
                    text="🚀 Aaj ka Mission — 400 Sparks Kamao",
                    callback_data="nav_mission",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Views Order Karo",
                    callback_data="nav_order",
                ),
                InlineKeyboardButton(
                    text="🎁 Rewards",
                    callback_data="nav_rewards",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Mera Profile",
                    callback_data="nav_profile",
                ),
                InlineKeyboardButton(
                    text="🤝 Refer Karo",
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
                    text="🚀 App Mein Jaao (Coming Soon)",
                    callback_data="dummy_app_link",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Dashboard pe Wapas",
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌱 Starter Boost — 1,000 Views | 500 Sparks",
                    callback_data="order_pkg_starter",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔥 Growth Pack — 3,000 Views | 1,200 Sparks ⭐ BEST",
                    callback_data="order_pkg_growth",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Pro Blast — 7,000 Views | 2,500 Sparks",
                    callback_data="order_pkg_pro",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def order_keyboard_empty() -> InlineKeyboardMarkup:
    """Empty-state keyboard — not enough Sparks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 Mission Karo — Sparks Kamao",
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
                    text="⬅️ Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


def rewards_keyboard(shields: int = 0) -> InlineKeyboardMarkup:
    """Rewards center."""
    buttons = [
        [
            InlineKeyboardButton(
                text="🎰 Mystery Box (100 Sparks)",
                callback_data="action_mystery_box",
            )
        ]
    ]

    if shields < 3:
        buttons.append([
            InlineKeyboardButton(
                text="🛡️ Buy Streak Shield (200 Sparks)",
                callback_data="action_buy_shield",
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="🛡️ Streak Shields Full (Max 3)",
                callback_data="action_shields_full",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Dashboard",
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
                    text="📦 Order History Dekho",
                    callback_data="nav_order_history",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Dashboard",
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
                    text="⬅️ Dashboard",
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
                    text="⬅️ Dashboard",
                    callback_data="go_dashboard",
                )
            ],
        ]
    )


# ===========================================================================
# Order confirmation keyboard (used by orders.py confirm flow)
# ===========================================================================

def confirm_order_keyboard(package_type: str) -> InlineKeyboardMarkup:
    """Confirm / cancel an order before deducting Sparks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm Order",
                    callback_data=f"order_confirm:{package_type}",
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
                    text="⬅️ Dashboard",
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
    rows.append([InlineKeyboardButton(text="⬅️ Profile", callback_data="nav_profile")])
    rows.append([InlineKeyboardButton(text="🏠 Dashboard", callback_data="go_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    """Help center navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Contact Support", callback_data="contact_support")],
            [InlineKeyboardButton(text="📋 FAQ", callback_data="faq")],
            [InlineKeyboardButton(text="⬅️ Dashboard", callback_data="go_dashboard")],
        ]
    )
