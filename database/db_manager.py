"""
db_manager.py
~~~~~~~~~~~~~
All Firestore CRUD operations for InstaVault.

Every public method is a native async coroutine using the firebase-admin
AsyncClient, so no run_in_executor wrappers are needed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from google.cloud.firestore import Increment, async_transactional
from google.cloud.firestore_v1 import AsyncDocumentReference
from google.cloud.firestore_v1.base_query import FieldFilter


class InsufficientSparksError(Exception):
    """Raised when a user doesn't have enough Sparks for an operation."""
    pass


class UserNotFoundError(Exception):
    """Raised when a user document is not found in Firestore."""
    pass


class CooldownActiveError(Exception):
    """Raised when a user attempts to open a mystery box during cooldown."""
    pass


class MaxShieldsReachedError(Exception):
    """Raised when a user already has the maximum allowed streak shields."""
    pass


import config
from database.firebase_init import get_db
from utils.helpers import (
    generate_referral_code,
    generate_vault_id,
    get_ist_now,
    get_rank_tier,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------
USERS_COL = "users"
ORDERS_COL = "orders"
TRANSACTIONS_COL = "transactions"
WAITLIST_COL = "waitlist"


# ===========================================================================
# USER OPERATIONS
# ===========================================================================

async def user_exists(user_id: int | str) -> bool:
    """Return True if the user document exists in Firestore."""
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    return doc.exists


async def get_user(user_id: int | str) -> dict[str, Any] | None:
    """Fetch a user document. Returns None if not found."""
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict()
    return None


async def create_user(
    user_id: int,
    first_name: str,
    username: str | None = None,
    referred_by: str | None = None,
    source_tag: str = "direct",
    onboarding_time: str = "unknown",
    action_speed_ms: int = 0,
) -> dict[str, Any]:
    """
    Create a new user document with default field values.

    Phase 2: FSM onboarding segmentation fields.
    Phase 4: last_mystery_box_date (None = never opened).
    """
    db = get_db()
    now = get_ist_now()

    vault_id = generate_vault_id(user_id % 100000)
    referral_code = generate_referral_code(vault_id)

    user_data: dict[str, Any] = {
        # Identity
        "first_name": first_name,
        "username": username or "",
        "vault_id": vault_id,
        "join_date": now,
        "status": "active",

        # Economy
        "spark_balance": config.WELCOME_BONUS,
        "lifetime_sparks": config.WELCOME_BONUS,

        # Rank
        "rank_points": 0,
        "rank_tier": "Rookie Vaulter",

        # Streak — Day 1 on account creation
        "streak_days": 1,
        "last_login": now,
        "streak_shields": 0,
        "last_daily_reset": now,

        # Missions
        "daily_level_count": 0,
        "daily_limit": 1,

        # Mystery Box (Phase 4) — None means never opened
        "last_mystery_box_date": None,

        # Referrals
        "referral_code": referral_code,
        "referred_by": referred_by,
        "referral_count": 0,

        # Orders
        "total_orders": 0,
        "total_views_recv": 0,
        "instagram_handle": None,
        "first_order_date": None,

        # Gamification
        "power_score": 0,
        "jackpot_tickets": 0,

        # Preferences
        "notif_preference": "all",
        "is_vip_member": False,
        "community_invited": False,
        "waitlist_pos": None,

        # Segmentation (Phase 2)
        "source_tag": source_tag,
        "onboarding_time": onboarding_time,
        "action_speed_ms": action_speed_ms,
    }

    await db.collection(USERS_COL).document(str(user_id)).set(user_data)
    logger.info("Created user %s (%s) | source=%s", user_id, vault_id, source_tag)
    return user_data


async def update_user(user_id: int | str, fields: dict[str, Any]) -> None:
    """Partially update fields on an existing user document."""
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update(fields)


async def increment_spark_balance(user_id: int | str, amount: int) -> None:
    """
    Atomically increment spark_balance and lifetime_sparks.
    Uses Firestore Increment sentinel to avoid read-modify-write races.
    """
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update(
        {
            "spark_balance": Increment(amount),
            "lifetime_sparks": Increment(amount),
        }
    )


async def deduct_spark_balance(user_id: int | str, amount: int) -> None:
    """Atomically deduct from spark_balance (does NOT touch lifetime_sparks)."""
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update(
        {"spark_balance": Increment(-amount)}
    )


async def update_last_login(user_id: int | str) -> None:
    """Stamp last_login with the current IST datetime."""
    await update_user(user_id, {"last_login": get_ist_now()})


# ===========================================================================
# LEADERBOARD (Phase 4)
# ===========================================================================

async def get_user_by_referral_code(referral_code: str) -> dict[str, Any] | None:
    """
    Find a user document by their referral_code field.
    Returns the user dict (with '_uid' key set to document ID) or None if not found.
    """
    db = get_db()
    query = (
        db.collection(USERS_COL)
        .where(filter=FieldFilter("referral_code", "==", referral_code))
        .limit(1)
    )
    async for doc in query.stream():
        data = doc.to_dict()
        data["_uid"] = doc.id
        return data
    return None


async def reward_referrer(referrer_id: int | str) -> None:
    """
    Atomically credit a referrer 500 Sparks and increment their referral_count by 1.
    Uses Firestore Increment sentinels to avoid read-modify-write races.
    """
    db = get_db()
    await db.collection(USERS_COL).document(str(referrer_id)).update(
        {
            "spark_balance": Increment(config.REFERRAL_JOIN_BONUS),
            "lifetime_sparks": Increment(config.REFERRAL_JOIN_BONUS),
            "referral_count": Increment(1),
        }
    )
    logger.info("Referrer %s rewarded: +%s Sparks, referral_count +1", referrer_id, config.REFERRAL_JOIN_BONUS)


async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    """
    Return the top `limit` users ordered by spark_balance descending.
    Requires a Firestore single-field index on spark_balance (auto-created).
    """
    db = get_db()
    query = (
        db.collection(USERS_COL)
        .order_by("spark_balance", direction="DESCENDING")
        .limit(limit)
    )
    results: list[dict[str, Any]] = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["_uid"] = doc.id
        results.append(data)
    return results


# ===========================================================================
# ORDER OPERATIONS
# ===========================================================================

async def create_order(
    user_id: int | str,
    package_type: str,
    sparks_spent: int,
    views_ordered: int,
    instagram_url: str,
) -> str:
    """
    Create a new order document (auto-ID).
    Returns the generated document ID.
    """
    db = get_db()
    now = get_ist_now()

    order_data: dict[str, Any] = {
        "user_id": str(user_id),
        "package_type": package_type,
        "sparks_spent": sparks_spent,
        "views_ordered": views_ordered,
        "instagram_url": instagram_url,
        "status": "pending",
        "created_at": now,
        "delivered_at": None,
        "compensation_given": False,
    }

    _ref: AsyncDocumentReference
    _, _ref = await db.collection(ORDERS_COL).add(order_data)
    logger.info("Order created: %s for user %s", _ref.id, user_id)
    return _ref.id


async def place_order_transactional(
    user_id: int | str,
    package_type: str,
    sparks_spent: int,
    views_ordered: int,
    instagram_url: str,
) -> str:
    """
    Atomically verify user has enough balance, deduct Sparks, log the
    transaction, and place the order using a Firestore transaction.
    This prevents double-spending / race conditions.

    Returns the generated order ID.
    Raises UserNotFoundError if user document does not exist.
    Raises InsufficientSparksError if the user's spark balance is too low.
    """
    db = get_db()
    transaction = db.transaction()

    @async_transactional
    async def _run_in_tx(tx) -> str:
        user_ref = db.collection(USERS_COL).document(str(user_id))
        user_snap = await tx.get(user_ref)

        if not user_snap.exists:
            raise UserNotFoundError(f"User {user_id} not found in database.")

        user_data = user_snap.to_dict() or {}
        current_balance = user_data.get("spark_balance", 0)

        if current_balance < sparks_spent:
            raise InsufficientSparksError(
                f"Insufficient Sparks: user has {current_balance}, need {sparks_spent}."
            )

        new_balance = current_balance - sparks_spent
        new_total_orders = user_data.get("total_orders", 0) + 1

        # Pre-generate IDs for order and transaction logs
        order_ref = db.collection(ORDERS_COL).document()
        tx_ref = db.collection(TRANSACTIONS_COL).document()

        now = get_ist_now()

        order_data: dict[str, Any] = {
            "user_id": str(user_id),
            "package_type": package_type,
            "sparks_spent": sparks_spent,
            "views_ordered": views_ordered,
            "instagram_url": instagram_url,
            "status": "pending",
            "created_at": now,
            "delivered_at": None,
            "compensation_given": False,
        }

        tx_data: dict[str, Any] = {
            "user_id": str(user_id),
            "type": "spend",
            "amount": sparks_spent,
            "source": f"order_{package_type}",
            "created_at": now,
        }

        # Queue updates/writes in transaction
        tx.update(user_ref, {
            "spark_balance": new_balance,
            "total_orders": new_total_orders
        })
        tx.set(order_ref, order_data)
        tx.set(tx_ref, tx_data)

        logger.info(
            "Transaction successful for user %s: deducted %s Sparks, order %s created.",
            user_id, sparks_spent, order_ref.id
        )
        return order_ref.id

    return await _run_in_tx(transaction)


async def open_mystery_box_transactional(
    user_id: int | str,
    cost_sparks: int,
    won_sparks: int,
) -> tuple[int, int]:
    """
    Atomically verify cooldown is clear, verify user has enough Sparks to open,
    deduct the cost, add the won Sparks, update cooldown date, and log transactions.

    Returns a tuple of (cost_sparks, won_sparks).
    Raises UserNotFoundError, InsufficientSparksError, or CooldownActiveError.
    """
    db = get_db()
    transaction = db.transaction()
    today_str = get_ist_now().strftime("%Y-%m-%d")

    @async_transactional
    async def _run_in_tx(tx) -> tuple[int, int]:
        user_ref = db.collection(USERS_COL).document(str(user_id))
        user_snap = await tx.get(user_ref)

        if not user_snap.exists:
            raise UserNotFoundError(f"User {user_id} not found in database.")

        user_data = user_snap.to_dict() or {}

        # 1. Cooldown check inside transaction
        last_box_date = user_data.get("last_mystery_box_date")
        if last_box_date == today_str:
            raise CooldownActiveError("Mystery Box already opened today.")

        # 2. Balance check
        current_balance = user_data.get("spark_balance", 0)
        if current_balance < cost_sparks:
            raise InsufficientSparksError(
                f"Insufficient Sparks: user has {current_balance}, need {cost_sparks} to open."
            )

        # 3. Compute balances
        new_balance = current_balance - cost_sparks + won_sparks
        new_lifetime = user_data.get("lifetime_sparks", 0) + won_sparks

        # 4. Queue updates
        tx.update(user_ref, {
            "spark_balance": new_balance,
            "lifetime_sparks": new_lifetime,
            "last_mystery_box_date": today_str
        })

        # 5. Log double ledger entries for auditability
        now = get_ist_now()

        # Spend Log
        tx_spend_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_spend_ref, {
            "user_id": str(user_id),
            "type": "spend",
            "amount": cost_sparks,
            "source": "mystery_box_open",
            "created_at": now,
        })

        # Win Log
        tx_win_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_win_ref, {
            "user_id": str(user_id),
            "type": "bonus",
            "amount": won_sparks,
            "source": "mystery_box_reward",
            "created_at": now,
        })

        logger.info(
            "Mystery box opened successfully for user %s: spent %s, won %s.",
            user_id, cost_sparks, won_sparks
        )
        return cost_sparks, won_sparks

    return await _run_in_tx(transaction)


async def buy_streak_shield_transactional(
    user_id: int | str,
    cost_sparks: int = 200,
    max_shields: int = 3,
) -> tuple[int, int]:
    """
    Atomically buy a streak shield.
    Verifies user exists, checks balance, checks if shields are below max_shields,
    deducts cost, increments streak_shields, and logs transaction.

    Returns a tuple of (new_shields, new_balance).
    Raises UserNotFoundError, InsufficientSparksError, or MaxShieldsReachedError.
    """
    db = get_db()
    transaction = db.transaction()

    @async_transactional
    async def _run_in_tx(tx) -> tuple[int, int]:
        user_ref = db.collection(USERS_COL).document(str(user_id))
        user_snap = await tx.get(user_ref)

        if not user_snap.exists:
            raise UserNotFoundError(f"User {user_id} not found in database.")

        user_data = user_snap.to_dict() or {}

        # 1. Shields check
        current_shields = int(user_data.get("streak_shields", 0))
        if current_shields >= max_shields:
            raise MaxShieldsReachedError(f"Already have max shields ({max_shields}).")

        # 2. Balance check
        current_balance = int(user_data.get("spark_balance", 0))
        if current_balance < cost_sparks:
            raise InsufficientSparksError(
                f"Insufficient Sparks: user has {current_balance}, need {cost_sparks} to buy shield."
            )

        # 3. Compute new values
        new_shields = current_shields + 1
        new_balance = current_balance - cost_sparks

        # 4. Queue updates
        tx.update(user_ref, {
            "streak_shields": new_shields,
            "spark_balance": new_balance,
        })

        # 5. Log transaction
        tx_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_ref, {
            "user_id": str(user_id),
            "type": "spend",
            "amount": cost_sparks,
            "source": "buy_streak_shield",
            "created_at": get_ist_now(),
        })

        logger.info(
            "Streak shield bought successfully for user %s: spent %s, new shields: %s.",
            user_id, cost_sparks, new_shields
        )
        return new_shields, new_balance

    return await _run_in_tx(transaction)


async def get_order(order_id: str) -> dict[str, Any] | None:
    """Fetch a single order by document ID."""
    db = get_db()
    doc = await db.collection(ORDERS_COL).document(order_id).get()
    return doc.to_dict() if doc.exists else None


async def get_user_orders(
    user_id: int | str, limit: int = 10
) -> list[dict[str, Any]]:
    """Return the most recent orders for a user, newest first.

    Sorting is done in Python (not Firestore) to avoid requiring a
    composite index on (user_id, created_at).
    """
    db = get_db()
    query = (
        db.collection(ORDERS_COL)
        .where(filter=FieldFilter("user_id", "==", str(user_id)))
    )
    results: list[dict[str, Any]] = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["order_id"] = doc.id
        results.append(data)
    # Sort newest-first in Python — no composite index needed
    results.sort(key=lambda d: d.get("created_at") or 0, reverse=True)
    return results[:limit]


async def update_order_status(
    order_id: str,
    status: str,
    delivered_at: datetime | None = None,
    compensation_given: bool | None = None,
) -> None:
    """Update an order's status and optional delivery metadata."""
    db = get_db()
    fields: dict[str, Any] = {"status": status}
    if delivered_at is not None:
        fields["delivered_at"] = delivered_at
    if compensation_given is not None:
        fields["compensation_given"] = compensation_given
    await db.collection(ORDERS_COL).document(order_id).update(fields)


# ===========================================================================
# TRANSACTION OPERATIONS
# ===========================================================================

async def log_transaction(
    user_id: int | str,
    tx_type: str,
    amount: int,
    source: str,
) -> str:
    """
    Log a Spark transaction.
    tx_type: earn | spend | bonus | referral | compensation
    Returns the auto-generated document ID.
    """
    db = get_db()
    tx_data: dict[str, Any] = {
        "user_id": str(user_id),
        "type": tx_type,
        "amount": amount,
        "source": source,
        "created_at": get_ist_now(),
    }
    _, ref = await db.collection(TRANSACTIONS_COL).add(tx_data)
    return ref.id


async def get_user_transactions(
    user_id: int | str, limit: int = 20
) -> list[dict[str, Any]]:
    """Return recent transactions for a user, newest first."""
    db = get_db()
    query = (
        db.collection(TRANSACTIONS_COL)
        .where(filter=FieldFilter("user_id", "==", str(user_id)))
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
    )
    results: list[dict[str, Any]] = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["tx_id"] = doc.id
        results.append(data)
    return results


# ===========================================================================
# WAITLIST OPERATIONS
# ===========================================================================

async def add_to_waitlist(
    user_id: int | str,
    first_name: str,
    username: str | None,
    position: int,
) -> None:
    """Add a user to the waitlist collection."""
    db = get_db()
    data: dict[str, Any] = {
        "first_name": first_name,
        "username": username or "",
        "position": position,
        "joined_at": get_ist_now(),
        "invite_count": 0,
        "activated": False,
    }
    await db.collection(WAITLIST_COL).document(str(user_id)).set(data)


async def get_waitlist_entry(user_id: int | str) -> dict[str, Any] | None:
    """Fetch a waitlist entry."""
    db = get_db()
    doc = await db.collection(WAITLIST_COL).document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None


async def get_waitlist_count() -> int:
    """Return the total number of users on the waitlist."""
    db = get_db()
    docs = db.collection(WAITLIST_COL).stream()
    count = 0
    async for _ in docs:
        count += 1
    return count


async def update_waitlist_entry(user_id: int | str, fields: dict[str, Any]) -> None:
    """Update fields on a waitlist document."""
    db = get_db()
    await db.collection(WAITLIST_COL).document(str(user_id)).update(fields)


async def activate_waitlist_user(user_id: int | str) -> None:
    """Mark a waitlist user as activated."""
    await update_waitlist_entry(user_id, {"activated": True})
