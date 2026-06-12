"""
keyboards/reply.py
~~~~~~~~~~~~~~~~~~
Persistent reply keyboards (bottom of the screen).
"""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Primary navigation keyboard shown after onboarding."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🏠 Dashboard"),
                KeyboardButton(text="🎯 Mission"),
            ],
            [
                KeyboardButton(text="📦 Order Views"),
                KeyboardButton(text="🏆 Rewards"),
            ],
            [
                KeyboardButton(text="👤 Profile"),
                KeyboardButton(text="👥 Refer & Earn"),
            ],
            [
                KeyboardButton(text="❓ Help"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an option…",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Simple cancel keyboard for multi-step flows."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True,
    )


def share_contact_keyboard() -> ReplyKeyboardMarkup:
    """Used during onboarding to optionally share phone contact."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Share Contact", request_contact=True)],
            [KeyboardButton(text="⏭ Skip")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
