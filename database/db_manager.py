"""
database/db_manager.py
~~~~~~~~~~~~~~~~~~~~~~
Centralised Firestore data-access layer for InstaVault Bot.

Architecture:
  • Every public function is an async coroutine backed by the
    firebase-admin AsyncClient — no ``run_in_executor`` wrappers needed.
  • Balance-modifying operations that span multiple reads/writes use
    ``@async_transactional`` Firestore transactions to prevent race
    conditions and double-spend exploits.
  • Simple additive changes use ``Increment()`` sentinels for lock-free
    atomic updates.

Collections:
  users          – One document per Telegram user (keyed by user_id).
  orders         – One document per views-order (auto-generated ID).
  transactions   – Immutable append-only ledger of Spark movements.
  waitlist       – Pre-launch waitlist entries (keyed by user_id).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from google.cloud.firestore import Increment, async_transactional
from google.cloud.firestore_v1 import AsyncDocumentReference
from google.cloud.firestore_v1.base_query import FieldFilter

import config
from database.firebase_init import get_db
from utils.helpers import generate_referral_code, generate_vault_id, get_ist_now

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firestore collection name constants
# ---------------------------------------------------------------------------
USERS_COL = "users"
ORDERS_COL = "orders"
TRANSACTIONS_COL = "transactions"
WAITLIST_COL = "waitlist"


# ===========================================================================
# Custom Exceptions
# ===========================================================================

class DuplicateOrderError(Exception):
    """Raised when a duplicate order nonce is detected (double-tap protection)."""


class InsufficientSparksError(Exception):
    """Raised when a user doesn't have enough Sparks for an operation."""


class UserNotFoundError(Exception):
    """Raised when a user document is not found in Firestore."""


class CooldownActiveError(Exception):
    """Raised when a user attempts to open a mystery box during cooldown."""


class MaxShieldsReachedError(Exception):
    """Raised when a user already has the maximum number of streak shields."""


# ===========================================================================
# USER OPERATIONS — Core CRUD
# ===========================================================================

async def user_exists(user_id: int | str) -> bool:
    """Return ``True`` if a user document exists in Firestore."""
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    return doc.exists


async def get_user(user_id: int | str) -> dict[str, Any] | None:
    """Fetch a user document as a dict.  Returns ``None`` if not found."""
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None


async def update_user(user_id: int | str, fields: dict[str, Any]) -> None:
    """Partially update fields on an existing user document."""
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update(fields)


async def update_last_login(user_id: int | str) -> None:
    """Stamp ``last_login`` with the current IST datetime."""
    await update_user(user_id, {"last_login": get_ist_now()})


# ===========================================================================
# USER OPERATIONS — Spark Balance (Atomic)
# ===========================================================================

async def increment_spark_balance(user_id: int | str, amount: int) -> None:
    """Atomically increment ``spark_balance`` and ``lifetime_sparks``.

    Uses Firestore ``Increment`` sentinel to avoid read-modify-write races.
    """
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update({
        "spark_balance": Increment(amount),
        "lifetime_sparks": Increment(amount),
    })


async def deduct_spark_balance(user_id: int | str, amount: int) -> None:
    """Atomically deduct from ``spark_balance`` (does NOT touch ``lifetime_sparks``)."""
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update({
        "spark_balance": Increment(-amount),
    })


# ===========================================================================
# USER OPERATIONS — Transactional Account Creation
# ===========================================================================

def _build_default_user_data(
    *,
    first_name: str,
    username: str | None,
    vault_id: str,
    referral_code: str,
    now: datetime,
    initial_sparks: int,
    referrer_uid: str | None,
    source_tag: str,
    onboarding_time: str,
    action_speed_ms: int,
) -> dict[str, Any]:
    """Build the default Firestore document for a newly created user.

    Centralised here so both the transactional and non-transactional
    creation paths share the same schema — preventing field drift.
    """
    return {
        # Identity
        "first_name": first_name,
        "username": username or "",
        "vault_id": vault_id,
        "join_date": now,
        "status": "active",

        # Economy
        "spark_balance": initial_sparks,
        "lifetime_sparks": initial_sparks,

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

        # Mystery Box — None means never opened
        "last_mystery_box_date": None,

        # Referrals
        "referral_code": referral_code,
        "referred_by": referrer_uid,
        "referral_count": 0,

        # Orders
        "total_orders": 0,
        "total_views_recv": 0,
        "instagram_handle": None,
        "first_order_date": None,
        "last_order_nonce": None,

        # Gamification
        "power_score": 0,
        "jackpot_tickets": 0,

        # Preferences
        "notif_preference": "all",
        "is_vip_member": False,
        "community_invited": False,
        "waitlist_pos": None,

        # Segmentation
        "source_tag": source_tag,
        "onboarding_time": onboarding_time,
        "action_speed_ms": action_speed_ms,
    }


@async_transactional
async def _create_user_tx(
    tx,
    user_ref: AsyncDocumentReference,
    user_id: int,
    first_name: str,
    username: str | None,
    vault_id: str,
    referral_code: str,
    now: datetime,
    referrer_uid: str | None,
    source_tag: str,
    onboarding_time: str,
    action_speed_ms: int,
) -> dict[str, Any] | None:
    """Inner transactional function for atomic user creation + referral rewards.

    Returns the created user data dict, or ``None`` if the user already exists
    (idempotent guard against double-tap).
    """
    # Idempotency guard — prevent double-creation on rapid taps
    user_snap = await user_ref.get(transaction=tx)
    if user_snap.exists:
        return None

    # Calculate initial balance (welcome bonus + referee bonus if applicable)
    initial_sparks = config.WELCOME_BONUS
    if referrer_uid:
        initial_sparks += config.REFEREE_BONUS

    # Build and write user document
    user_data = _build_default_user_data(
        first_name=first_name,
        username=username,
        vault_id=vault_id,
        referral_code=referral_code,
        now=now,
        initial_sparks=initial_sparks,
        referrer_uid=referrer_uid,
        source_tag=source_tag,
        onboarding_time=onboarding_time,
        action_speed_ms=action_speed_ms,
    )
    tx.set(user_ref, user_data)

    # Log welcome bonus transaction
    db = get_db()
    welcome_tx_ref = db.collection(TRANSACTIONS_COL).document()
    bonus_source = "welcome_bonus_and_referee" if referrer_uid else "welcome_bonus"
    tx.set(welcome_tx_ref, {
        "user_id": str(user_id),
        "type": "bonus",
        "amount": initial_sparks,
        "source": bonus_source,
        "created_at": now,
    })

    # Reward referrer atomically within the same transaction
    if referrer_uid:
        referrer_ref = db.collection(USERS_COL).document(referrer_uid)
        tx.update(referrer_ref, {
            "spark_balance": Increment(config.REFERRAL_JOIN_BONUS),
            "lifetime_sparks": Increment(config.REFERRAL_JOIN_BONUS),
            "referral_count": Increment(1),
        })

        referrer_tx_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(referrer_tx_ref, {
            "user_id": str(referrer_uid),
            "type": "referral",
            "amount": config.REFERRAL_JOIN_BONUS,
            "source": f"referral_bonus_{user_id}",
            "created_at": now,
        })

        user_data["_referrer_uid"] = referrer_uid

    return user_data


async def create_user_transactional(
    user_id: int,
    first_name: str,
    username: str | None = None,
    referrer_uid: str | None = None,
    source_tag: str = "direct",
    onboarding_time: str = "unknown",
    action_speed_ms: int = 0,
) -> dict[str, Any] | None:
    """Create a new user account with full referral handling in a single
    Firestore transaction.

    This is the **only** user-creation path used in production. It
    atomically:
      1. Checks if the user already exists (idempotent).
      2. Creates the user document with welcome bonus.
      3. Logs the welcome bonus transaction.
      4. Rewards the referrer (if any) with bonus Sparks.

    Returns:
        The created user data dict, or ``None`` if user already existed.

    Raises:
        google.api_core.exceptions: On Firestore connectivity failures.
    """
    db = get_db()
    transaction = db.transaction()
    now = get_ist_now()

    vault_id = generate_vault_id(user_id)
    referral_code = generate_referral_code(vault_id)
    user_ref = db.collection(USERS_COL).document(str(user_id))

    return await _create_user_tx(
        transaction,
        user_ref,
        user_id,
        first_name,
        username,
        vault_id,
        referral_code,
        now,
        referrer_uid,
        source_tag,
        onboarding_time,
        action_speed_ms,
    )


# ===========================================================================
# USER OPERATIONS — Streak Milestones (Transactional)
# ===========================================================================

@async_transactional
async def _process_streak_milestone_txn(
    transaction,
    user_ref: AsyncDocumentReference,
    tx_ref: AsyncDocumentReference,
    new_streak: int,
    milestone_bonus: int,
    now_ist: str,
    shield_used: bool,
    shields: int,
    user_id: int | str,
) -> None:
    """Inner transactional function for atomic streak + milestone processing."""
    update_fields: dict[str, Any] = {
        "streak_days": new_streak,
        "last_login": now_ist,
    }

    if shield_used:
        update_fields["streak_shields"] = shields - 1

    if milestone_bonus > 0:
        update_fields["spark_balance"] = Increment(milestone_bonus)
        update_fields["lifetime_sparks"] = Increment(milestone_bonus)

    transaction.update(user_ref, update_fields)

    if milestone_bonus > 0:
        transaction.set(tx_ref, {
            "user_id": str(user_id),
            "type": "bonus",
            "amount": milestone_bonus,
            "source": f"streak_milestone_day_{new_streak}",
            "created_at": now_ist,
        })


async def process_streak_milestone_transactional(
    user_id: int | str,
    new_streak: int,
    milestone_bonus: int,
    now_ist: str,
    shield_used: bool,
    shields: int,
) -> None:
    """Atomically update streak details, consume a shield (if used),
    increment Spark balance for milestone bonus, and log the transaction.

    All writes happen in a single Firestore transaction.
    """
    db = get_db()
    transaction = db.transaction()
    user_ref = db.collection(USERS_COL).document(str(user_id))
    tx_ref = db.collection(TRANSACTIONS_COL).document()

    await _process_streak_milestone_txn(
        transaction,
        user_ref,
        tx_ref,
        new_streak,
        milestone_bonus,
        now_ist,
        shield_used,
        shields,
        user_id,
    )


# ===========================================================================
# REFERRAL OPERATIONS
# ===========================================================================

async def get_user_by_referral_code(referral_code: str) -> dict[str, Any] | None:
    """Find a user document by their ``referral_code`` field.

    Returns the user dict with an injected ``_uid`` key (document ID),
    or ``None`` if no match is found.
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
    """Atomically credit a referrer with join bonus Sparks and increment
    their ``referral_count`` by 1.

    Uses Firestore ``Increment`` sentinels to avoid read-modify-write races.
    """
    db = get_db()
    await db.collection(USERS_COL).document(str(referrer_id)).update({
        "spark_balance": Increment(config.REFERRAL_JOIN_BONUS),
        "lifetime_sparks": Increment(config.REFERRAL_JOIN_BONUS),
        "referral_count": Increment(1),
    })
    logger.info(
        "Referrer %s rewarded: +%s Sparks, referral_count +1",
        referrer_id, config.REFERRAL_JOIN_BONUS,
    )


# ===========================================================================
# LEADERBOARD
# ===========================================================================

async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    """Return the top ``limit`` users ordered by ``spark_balance`` descending.

    Relies on an auto-created single-field index on ``spark_balance``.
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
# ORDER OPERATIONS — CRUD
# ===========================================================================

async def create_order(
    user_id: int | str,
    package_type: str,
    sparks_spent: int,
    views_ordered: int,
    instagram_url: str,
) -> str:
    """Create a new order document with auto-generated ID.

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


async def get_order(order_id: str) -> dict[str, Any] | None:
    """Fetch a single order by document ID."""
    db = get_db()
    doc = await db.collection(ORDERS_COL).document(order_id).get()
    return doc.to_dict() if doc.exists else None


async def get_user_orders(
    user_id: int | str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recent orders for a user, newest first.

    Sorting is done in Python to avoid requiring a Firestore composite
    index on ``(user_id, created_at)``.
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
# ORDER OPERATIONS — Transactional Placement
# ===========================================================================

async def place_order_transactional(
    user_id: int | str,
    package_type: str,
    sparks_spent: int,
    views_ordered: int,
    instagram_url: str,
    nonce: str,
) -> str:
    """Atomically verify balance, deduct Sparks, log the transaction,
    and place the order inside a Firestore transaction.

    This prevents double-spending and race conditions.

    Returns:
        The generated order document ID.

    Raises:
        UserNotFoundError: User document does not exist.
        InsufficientSparksError: Balance is too low.
        DuplicateOrderError: Nonce matches the previous order (double-tap).
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

        # Double-tap guard via nonce
        if user_data.get("last_order_nonce") == nonce:
            raise DuplicateOrderError(f"Duplicate order: nonce {nonce} already processed.")

        # Balance verification
        current_balance = user_data.get("spark_balance", 0)
        if current_balance < sparks_spent:
            raise InsufficientSparksError(
                f"Insufficient Sparks: user has {current_balance}, need {sparks_spent}."
            )

        new_balance = current_balance - sparks_spent
        new_total_orders = user_data.get("total_orders", 0) + 1
        now = get_ist_now()

        # Pre-generate document references
        order_ref = db.collection(ORDERS_COL).document()
        tx_ref = db.collection(TRANSACTIONS_COL).document()

        # 1. Update user balance, order count, and nonce
        tx.update(user_ref, {
            "spark_balance": new_balance,
            "total_orders": new_total_orders,
            "last_order_nonce": nonce,
        })

        # 2. Create order document
        tx.set(order_ref, {
            "user_id": str(user_id),
            "package_type": package_type,
            "sparks_spent": sparks_spent,
            "views_ordered": views_ordered,
            "instagram_url": instagram_url,
            "status": "pending",
            "created_at": now,
            "delivered_at": None,
            "compensation_given": False,
        })

        # 3. Log spend transaction
        tx.set(tx_ref, {
            "user_id": str(user_id),
            "type": "spend",
            "amount": sparks_spent,
            "source": f"order_{package_type}",
            "created_at": now,
        })

        logger.info(
            "Order placed for user %s: -%s Sparks, order %s created.",
            user_id, sparks_spent, order_ref.id,
        )
        return order_ref.id

    return await _run_in_tx(transaction)


# ===========================================================================
# MYSTERY BOX — Transactional Open
# ===========================================================================

async def open_mystery_box_transactional(
    user_id: int | str,
    cost_sparks: int,
    won_sparks: int,
) -> tuple[int, int]:
    """Atomically open a Mystery Box: verify cooldown, verify balance,
    deduct cost, add winnings, update cooldown date, and log a double-ledger
    (spend + win) for full auditability.

    Returns:
        ``(cost_sparks, won_sparks)`` tuple.

    Raises:
        UserNotFoundError: User document does not exist.
        CooldownActiveError: Box already opened today (IST calendar day).
        InsufficientSparksError: Balance is too low to open.
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

        # 1. Cooldown check (IST calendar day)
        if user_data.get("last_mystery_box_date") == today_str:
            raise CooldownActiveError("Mystery Box already opened today.")

        # 2. Balance check
        current_balance = user_data.get("spark_balance", 0)
        if current_balance < cost_sparks:
            raise InsufficientSparksError(
                f"Insufficient Sparks: user has {current_balance}, need {cost_sparks} to open."
            )

        # 3. Compute new balances
        new_balance = current_balance - cost_sparks + won_sparks
        new_lifetime = user_data.get("lifetime_sparks", 0) + won_sparks

        # 4. Update user document
        tx.update(user_ref, {
            "spark_balance": new_balance,
            "lifetime_sparks": new_lifetime,
            "last_mystery_box_date": today_str,
        })

        # 5. Double-ledger entries for auditability
        now = get_ist_now()

        tx_spend_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_spend_ref, {
            "user_id": str(user_id),
            "type": "spend",
            "amount": cost_sparks,
            "source": "mystery_box_open",
            "created_at": now,
        })

        tx_win_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_win_ref, {
            "user_id": str(user_id),
            "type": "bonus",
            "amount": won_sparks,
            "source": "mystery_box_reward",
            "created_at": now,
        })

        logger.info(
            "Mystery box opened for user %s: spent %s, won %s.",
            user_id, cost_sparks, won_sparks,
        )
        return cost_sparks, won_sparks

    return await _run_in_tx(transaction)


# ===========================================================================
# STREAK SHIELD — Transactional Purchase
# ===========================================================================

async def buy_streak_shield_transactional(
    user_id: int | str,
    cost_sparks: int = 200,
    max_shields: int = 3,
) -> tuple[int, int]:
    """Atomically purchase a streak shield: verify balance, verify shield
    count is below max, deduct cost, increment shields, and log the
    transaction.

    Returns:
        ``(new_shields, new_balance)`` tuple.

    Raises:
        UserNotFoundError: User document does not exist.
        MaxShieldsReachedError: Already at maximum shield count.
        InsufficientSparksError: Balance is too low.
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

        # 1. Shield limit check
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

        # 4. Update user document
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
            "Streak shield bought for user %s: -%s Sparks, shields: %s.",
            user_id, cost_sparks, new_shields,
        )
        return new_shields, new_balance

    return await _run_in_tx(transaction)


# ===========================================================================
# TRANSACTION LEDGER
# ===========================================================================

async def log_transaction(
    user_id: int | str,
    tx_type: str,
    amount: int,
    source: str,
) -> str:
    """Log a Spark transaction to the immutable ledger.

    Args:
        user_id: Telegram user ID.
        tx_type: One of ``earn``, ``spend``, ``bonus``, ``referral``, ``compensation``.
        amount: Spark amount (always positive).
        source: Event source identifier (e.g. ``welcome_bonus``, ``order_starter``).

    Returns:
        The auto-generated transaction document ID.
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
    user_id: int | str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent transactions for a user, newest first.

    Uses Firestore-side ordering via a composite index on
    ``(user_id, created_at DESC)``.
    """
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
    """Add a user to the pre-launch waitlist."""
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
    """Fetch a single waitlist entry by user ID."""
    db = get_db()
    doc = await db.collection(WAITLIST_COL).document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None


async def get_waitlist_count() -> int:
    """Return the total number of users on the waitlist."""
    db = get_db()
    count = 0
    async for _ in db.collection(WAITLIST_COL).stream():
        count += 1
    return count


async def update_waitlist_entry(user_id: int | str, fields: dict[str, Any]) -> None:
    """Partially update fields on a waitlist document."""
    db = get_db()
    await db.collection(WAITLIST_COL).document(str(user_id)).update(fields)


async def activate_waitlist_user(user_id: int | str) -> None:
    """Mark a waitlist user as activated."""
    await update_waitlist_entry(user_id, {"activated": True})
