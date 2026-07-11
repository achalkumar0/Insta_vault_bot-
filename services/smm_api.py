"""
services/smm_api.py
~~~~~~~~~~~~~~~~~~~
SMM Panel API Client.

Handles all communication with the external SMM Panel API.
Supports the standard SMM Panel API protocol (used by JAP, SMMPanel,
BulkFollows, and most reseller panels).

Standard API Actions:
  - add:    Place a new order
  - status: Check order status
  - balance: Check account balance

All functions use aiohttp for non-blocking HTTP requests.
"""

import logging
from typing import Any

import aiohttp

import config

logger = logging.getLogger(__name__)


class SMMApiError(Exception):
    """Raised when the SMM Panel API returns an error."""
    pass


class SMMApiConfigError(Exception):
    """Raised when SMM API credentials are not configured."""
    pass


def _ensure_configured() -> None:
    """Raise SMMApiConfigError if API credentials are missing."""
    if not config.SMM_API_URL or not config.SMM_API_KEY:
        raise SMMApiConfigError(
            "SMM_API_URL and SMM_API_KEY must be set in .env"
        )


async def _api_request(params: dict[str, Any]) -> dict[str, Any]:
    """Make a POST request to the SMM Panel API.

    All SMM panel APIs use the same pattern:
      POST to API_URL with key, action, and action-specific params.

    Returns:
        Parsed JSON response dict.

    Raises:
        SMMApiError: If the API returns an error or request fails.
    """
    _ensure_configured()

    payload = {
        "key": config.SMM_API_KEY,
        **params,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SMM_API_URL,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json(content_type=None)

                # SMM panels return {"error": "message"} on failure
                if isinstance(data, dict) and "error" in data:
                    raise SMMApiError(f"SMM API error: {data['error']}")

                return data

    except aiohttp.ClientError as e:
        logger.error("SMM API network error: %s", e, exc_info=True)
        raise SMMApiError(f"Network error: {e}") from e
    except Exception as e:
        if isinstance(e, (SMMApiError, SMMApiConfigError)):
            raise
        logger.error("SMM API unexpected error: %s", e, exc_info=True)
        raise SMMApiError(f"Unexpected error: {e}") from e


# ===========================================================================
# PUBLIC API FUNCTIONS
# ===========================================================================

async def place_order(
    service_id: int,
    link: str,
    quantity: int,
) -> int:
    """Place an order on the SMM Panel.

    Args:
        service_id: The SMM panel service ID (from config/packages.py).
        link: Instagram URL to deliver views to.
        quantity: Number of views to order.

    Returns:
        The SMM panel's order ID (int).

    Raises:
        SMMApiError: If the panel rejects the order.
        SMMApiConfigError: If API credentials are missing.
    """
    data = await _api_request({
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity,
    })

    # Standard response: {"order": 12345}
    if isinstance(data, dict) and "order" in data:
        smm_order_id = int(data["order"])
        logger.info(
            "SMM order placed: service=%s, link=%s, qty=%s → smm_order_id=%s",
            service_id, link, quantity, smm_order_id,
        )
        return smm_order_id

    raise SMMApiError(f"Unexpected API response: {data}")


async def check_status(smm_order_id: int) -> dict[str, Any]:
    """Check the status of an existing SMM order.

    Args:
        smm_order_id: The order ID returned by place_order().

    Returns:
        Dict with keys like: status, charge, start_count, remains, currency.

    Raises:
        SMMApiError: If the check fails.
    """
    data = await _api_request({
        "action": "status",
        "order": smm_order_id,
    })

    logger.info("SMM status check for order %s: %s", smm_order_id, data)
    return data


async def check_balance() -> float:
    """Check the SMM Panel account balance.

    Returns:
        Account balance as a float.

    Raises:
        SMMApiError: If the check fails.
    """
    data = await _api_request({
        "action": "balance",
    })

    # Standard response: {"balance": "100.50", "currency": "USD"}
    if isinstance(data, dict) and "balance" in data:
        balance = float(data["balance"])
        logger.info("SMM panel balance: %s %s", balance, data.get("currency", ""))
        return balance

    raise SMMApiError(f"Unexpected balance response: {data}")
