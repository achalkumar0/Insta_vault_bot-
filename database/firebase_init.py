import os
import logging

import firebase_admin
from firebase_admin import credentials, firestore_async
from google.cloud.firestore import AsyncClient

logger = logging.getLogger(__name__)

_db: AsyncClient | None = None


def init_firebase() -> AsyncClient:
    """
    Initialize the Firebase Admin SDK and return an async Firestore client.
    Safe to call multiple times — subsequent calls return the existing client.
    Uses firebase_admin's firestore_async module so credentials are picked up
    automatically from the initialized app.
    """
    global _db

    if _db is not None:
        return _db

    creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "../firebase_credentials.json")
    abs_path = os.path.abspath(creds_path)

    if not os.path.exists(abs_path):
        raise FileNotFoundError(
            f"Firebase credentials file not found at: {abs_path}\n"
            "Set FIREBASE_CREDENTIALS_PATH in your .env to point to the JSON file."
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(abs_path)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialised. Project: %s", cred.project_id)
    else:
        logger.info("Firebase Admin SDK already initialised.")

    # firestore_async.client() is bound to the initialized firebase_admin app —
    # no need to pass project ID or credentials manually.
    _db = firestore_async.client()
    return _db


def get_db() -> AsyncClient:
    """Return the already-initialised Firestore client (call init_firebase first)."""
    if _db is None:
        raise RuntimeError("Firebase has not been initialised. Call init_firebase() first.")
    return _db
