"""
config/packages.py
~~~~~~~~~~~~~~~~~~
Centralized configuration for all SMM packages.
Using Service ID-Driven Architecture.
"""

PACKAGES = {
    "starter": {
        "ui_name": "🌱 Starter Boost — 1,000 Views",
        "smm_service_id": 1052,
        "cost": 500,
        "views": 1000
    },
    "growth": {
        "ui_name": "🔥 Growth Pack — 3,000 Views ⭐ BEST",
        "smm_service_id": 2108,
        "cost": 1200,
        "views": 3000
    },
    "pro": {
        "ui_name": "💎 Pro Blast — 7,000 Views",
        "smm_service_id": 3050,
        "cost": 2500,
        "views": 7000
    },
    "mega": {
        "ui_name": "⚡ Mega — 15,000 Views",
        "smm_service_id": 4012,
        "cost": 5000,
        "views": 15000
    }
}
