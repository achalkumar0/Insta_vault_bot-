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

import hashlib
import logging
from datetime import datetime
from typing import Any

from google.cloud.firestore import Increment, async_transactional, Query
from google.cloud.firestore_v1 import AsyncDocumentReference
from google.cloud.firestore_v1.base_query import FieldFilter

import json
import config
from database.firebase_init import get_db
from database.redis_manager import get_redis, cache_user_data, get_cached_user_data, invalidate_user_cache
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
ACTIVE_LINK_LOCKS_COL = "active_link_locks"


# ===========================================================================
# Custom Exceptions
# ===========================================================================

class DuplicateOrderError(Exception):
    """Raised when a duplicate order nonce is detected (double-tap protection)."""


class DuplicateLinkError(Exception):
    """Raised when an order for the same Instagram link is already processing."""


class InsufficientSparksError(Exception):
    """Raised when a user doesn't have enough Sparks for an operation."""


class UserNotFoundError(Exception):
    """Raised when a user document is not found in Firestore."""


class CooldownActiveError(Exception):
    """Raised when a user attempts to open a mystery box during cooldown."""




# ===========================================================================
# USER OPERATIONS — Core CRUD
# ===========================================================================

async def user_exists(user_id: int | str) -> bool:
    """Return ``True`` if a user document exists in Firestore."""
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    return doc.exists


async def get_user(user_id: int | str) -> dict[str, Any] | None:
    """Fetch a user document as a dict.  Returns ``None`` if not found.
    Reads from Redis cache first; falls back to Firestore on miss.
    """
    # 1. Try Redis Cache (Fail-Safe Read-Through)
    cached = await get_cached_user_data(user_id)
    if cached is not None:
        logger.info("Cache hit for user %s", user_id)
        return cached

    # 2. Cache Miss - Fetch from Firestore
    logger.info("Cache miss for user %s. Fetching from Firestore.", user_id)
    db = get_db()
    doc = await db.collection(USERS_COL).document(str(user_id)).get()
    
    if doc.exists:
        data = doc.to_dict()
        # 3. Save back to Cache
        await cache_user_data(user_id, data)
        return data
    return None


async def update_user(user_id: int | str, fields: dict[str, Any]) -> None:
    """Partially update fields on an existing user document."""
    db = get_db()
    try:
        await db.collection(USERS_COL).document(str(user_id)).update(fields)
        await invalidate_user_cache(user_id)
    except Exception as e:
        logger.warning("Attempted to update non-existent user %s: %s", user_id, e)


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
    await invalidate_user_cache(user_id)


async def deduct_spark_balance(user_id: int | str, amount: int) -> None:
    """Atomically deduct from ``spark_balance`` (does NOT touch ``lifetime_sparks``)."""
    db = get_db()
    await db.collection(USERS_COL).document(str(user_id)).update({
        "spark_balance": Increment(-amount),
    })
    await invalidate_user_cache(user_id)


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

        # Login
        "last_login": now,
        "last_daily_reset": now,


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

        # Preferences
        "notif_preference": "all",
        "is_vip_member": False,
        "community_invited": False,
        "waitlist_pos": None,

        # Segmentation
        "source_tag": source_tag,
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

    result = await _create_user_tx(
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
    )
    if result:
        await cache_user_data(user_id, result)
        if referrer_uid:
            await invalidate_user_cache(referrer_uid)
    return result


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
    await invalidate_user_cache(referrer_id)
    logger.info(
        "Referrer %s rewarded: +%s Sparks, referral_count +1",
        referrer_id, config.REFERRAL_JOIN_BONUS,
    )


# ===========================================================================
# LEADERBOARD
# ===========================================================================

async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    """Return the top ``limit`` users ordered by ``lifetime_sparks`` descending.
    Uses Redis as the primary data source with Cache-Aside fallback to Firestore.
    """
    cache_key = "leaderboard:lifetime"
    redis = None
    
    # 1. Try fetching from Redis first
    try:
        redis = get_redis()
        cached_data = await redis.get(cache_key)
        if cached_data:
            if isinstance(cached_data, bytes):
                cached_data = cached_data.decode("utf-8")
            return json.loads(cached_data)[:limit]
    except Exception as e:
        logger.warning("Leaderboard cache miss/error, falling back to Firestore: %s", e)

    # 2. Fallback to Firestore if Cache Miss
    try:
        db = get_db()
        query = (
            db.collection(USERS_COL)
            .order_by("lifetime_sparks", direction="DESCENDING")
            .limit(limit)
        )
        
        results: list[dict[str, Any]] = []
        async for doc in query.stream():
            data = doc.to_dict() or {}
            # PRO-TIP: Maintain strict schema consistency with the Cloudflare Worker
            # to avoid large payload writes and ensure uniform UI rendering.
            results.append({
                "_uid": doc.id,
                "first_name": data.get("first_name", "Anonymous"),
                "lifetime_sparks": int(data.get("lifetime_sparks", 0))
            })
            
        # 3. Update Redis cache so subsequent hits are fast
        if redis is not None and results:
            try:
                await redis.setex(cache_key, 900, json.dumps(results))
            except Exception as e:
                logger.error("Failed to update leaderboard cache: %s", e)
                
        return results

    except Exception as e:
        logger.error("Firestore leaderboard fallback failed: %s", e)
        return []  # Graceful degradation (shows empty leaderboard instead of crashing bot)


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
    page: int = 0,
) -> list[dict[str, Any]]:
    """Return the most recent orders for a user, newest first.

    Uses Firestore native order_by and offset for pagination.
    Note: Requires a Composite Index on (user_id ASC, created_at DESC).
    """
    db = get_db()
    offset_val = page * limit

    query = (
        db.collection(ORDERS_COL)
        .where(filter=FieldFilter("user_id", "==", str(user_id)))
        .order_by("created_at", direction=Query.DESCENDING)
        .offset(offset_val)
        .limit(limit)
    )

    results: list[dict[str, Any]] = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["order_id"] = doc.id
        results.append(data)

    return results


async def update_order_status(
    order_id: str,
    status: str,
    delivered_at: datetime | None = None,
    compensation_given: bool | None = None,
    smm_order_id: int | None = None,
) -> None:
    """Update an order's status and optional delivery metadata."""
    db = get_db()
    fields: dict[str, Any] = {"status": status}
    if delivered_at is not None:
        fields["delivered_at"] = delivered_at
    if compensation_given is not None:
        fields["compensation_given"] = compensation_given
    if smm_order_id is not None:
        fields["smm_order_id"] = smm_order_id
    await db.collection(ORDERS_COL).document(order_id).update(fields)


# ===========================================================================
# ORDER OPERATIONS — Transactional Placement
# ===========================================================================

async def place_order_transactional(
    user_id: int,
    package_type: str,
    smm_service_id: int,
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
        user_snap = await user_ref.get(transaction=tx)

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

        # Generate MD5 hash for the link to use as the lock Document ID
        md5_hash = hashlib.md5(instagram_url.encode("utf-8")).hexdigest()
        link_lock_ref = db.collection(ACTIVE_LINK_LOCKS_COL).document(md5_hash)
        
        # Read the lock document inside the transaction
        link_lock_snap = await link_lock_ref.get(transaction=tx)
        if link_lock_snap.exists:
            raise DuplicateLinkError(f"Link {instagram_url} is already processing.")

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
            "smm_service_id": smm_service_id,
            "sparks_spent": sparks_spent,
            "views_ordered": views_ordered,
            "instagram_url": instagram_url,
            "status": "pending_approval",
            "smm_order_id": None,
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
            "order_id": order_ref.id,
            "created_at": now,
        })

        # 4. Create the link lock
        tx.set(link_lock_ref, {
            "instagram_url": instagram_url,
            "order_id": order_ref.id,
            "user_id": str(user_id),
            "created_at": now,
        })

        logger.info(
            "Order placed for user %s: -%s Sparks, order %s created.",
            user_id, sparks_spent, order_ref.id,
        )
        return order_ref.id

    order_id = await _run_in_tx(transaction)
    await invalidate_user_cache(user_id)
    return order_id


# ===========================================================================
# ADMIN ORDER OPERATIONS — Cancel/Refund & Link Lock Cleanup
# ===========================================================================

async def get_order(order_id: str) -> dict[str, Any] | None:
    """Fetch a single order document by its ID."""
    db = get_db()
    snap = await db.collection(ORDERS_COL).document(order_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


async def delete_link_lock(instagram_url: str) -> None:
    """Delete the active link lock for a given Instagram URL.

    Uses the same MD5 hashing scheme as place_order_transactional
    to derive the document ID deterministically.
    """
    md5_hash = hashlib.md5(instagram_url.encode("utf-8")).hexdigest()
    db = get_db()
    await db.collection(ACTIVE_LINK_LOCKS_COL).document(md5_hash).delete()
    logger.info("Link lock deleted for URL hash: %s", md5_hash)


async def cancel_order_and_refund(order_id: str) -> dict[str, Any]:
    """Cancel an order, refund Sparks to the user, and release the link lock.

    This is NOT a Firestore transaction because it spans multiple
    independent operations (order update, balance increment, transaction
    log, link lock delete). Each operation is individually atomic via
    Firestore sentinels (Increment). In the unlikely event of a partial
    failure, the order status will already be 'cancelled' preventing
    double-refunds on retry.

    Returns:
        The order data dict (for UI messages).

    Raises:
        ValueError: If order not found or already processed.
    """
    db = get_db()
    order_ref = db.collection(ORDERS_COL).document(order_id)
    order_snap = await order_ref.get()

    if not order_snap.exists:
        raise ValueError(f"Order {order_id} not found.")

    order_data = order_snap.to_dict() or {}

    if order_data.get("status") != "pending_approval":
        raise ValueError(
            f"Order {order_id} cannot be cancelled — current status: {order_data.get('status')}"
        )

    user_id = order_data["user_id"]
    sparks = order_data["sparks_spent"]
    ig_url = order_data.get("instagram_url", "")
    now = get_ist_now()

    # 1. Mark order as cancelled (first — prevents double-refund on retry)
    await order_ref.update({
        "status": "cancelled",
        "cancelled_at": now,
    })

    # 2. Refund Sparks to user (atomic increment)
    await increment_spark_balance(user_id, sparks)

    # 3. Log refund in transaction ledger
    await log_transaction(
        user_id=user_id,
        tx_type="refund",
        amount=sparks,
        source=f"order_cancelled_{order_id[:8]}",
    )

    # 4. Release the link lock so same URL can be used again
    if ig_url:
        await delete_link_lock(ig_url)

    logger.info(
        "Order %s cancelled & refunded: +%s Sparks to user %s",
        order_id, sparks, user_id,
    )

    order_data["id"] = order_id
    return order_data


# ===========================================================================
# MYSTERY BOX — Transactional Open
# ===========================================================================

async def open_mystery_box_transactional(
    user_id: int | str,
    won_sparks: int,
) -> int:
    """Atomically open a free daily mystery box: verify cooldown,
    add winnings, and log the transaction.

    Returns:
        ``won_sparks`` (int).

    Raises:
        UserNotFoundError: User document does not exist.
        CooldownActiveError: Box was already opened today.
    """
    db = get_db()
    transaction = db.transaction()

    @async_transactional
    async def _run_in_tx(tx) -> int:
        user_ref = db.collection(USERS_COL).document(str(user_id))
        user_snap = await user_ref.get(transaction=tx)

        if not user_snap.exists:
            raise UserNotFoundError(f"User {user_id} not found.")

        user_data = user_snap.to_dict() or {}
        today_str = get_ist_now().strftime("%Y-%m-%d")

        # 1. Cooldown check
        if user_data.get("last_mystery_box_date") == today_str:
            raise CooldownActiveError("Mystery box already opened today.")

        # 2. Compute new balances
        current_balance = int(user_data.get("spark_balance", 0))
        new_balance = current_balance + won_sparks
        new_lifetime = int(user_data.get("lifetime_sparks", 0)) + won_sparks

        # 3. Update user
        tx.update(user_ref, {
            "spark_balance": new_balance,
            "lifetime_sparks": new_lifetime,
            "last_mystery_box_date": today_str,
        })

        # 4. Log transaction (Free Bonus)
        tx_reward_ref = db.collection(TRANSACTIONS_COL).document()
        tx.set(tx_reward_ref, {
            "user_id": str(user_id),
            "type": "daily_free_bonus",
            "source": "mystery_box",
            "amount": won_sparks,
            "created_at": get_ist_now(),
        })

        logger.info(
            "Mystery box for user %s: +%s Sparks (Free Daily Bonus).",
            user_id, won_sparks,
        )
        return won_sparks

    won_sparks_amount = await _run_in_tx(transaction)
    await invalidate_user_cache(user_id)
    return won_sparks_amount


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
