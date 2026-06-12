import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Auto-detect webhook URL: prefer explicit WEBHOOK_URL, fall back to Replit dev domain
_replit_domain = os.getenv("REPLIT_DEV_DOMAIN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or (
    f"https://{_replit_domain}" if _replit_domain else None
)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}" if BOT_TOKEN else "/webhook/UNSET_TOKEN"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("BOT_PORT", 8099))

FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "firebase_credentials.json")
)

# Economy
WELCOME_BONUS = 500
DAILY_MISSION_REWARD = 400
AD_WATCH_REWARD = 150
MYSTERY_BOX_MIN = 25
MYSTERY_BOX_MAX = 2000
SPARK_EXPIRY_DAYS = 90

# Packages
PACKAGES = {
    "starter": {"sparks": 500,  "views": 1000},
    "growth":  {"sparks": 1200, "views": 3000},
    "pro":     {"sparks": 2500, "views": 7000},
    "mega":    {"sparks": 5000, "views": 15000},
}

# Limits & VIPs
DAILY_LIMITS = {0: 1, 3: 2, 10: 3, 25: 4, 50: 999}
VIP_SLOTS = 1000

# Delivery & Compensation
DELIVERY_PROMISE_MINUTES = 45
COMPENSATION_TRIGGER_MINUTES = 60
COMPENSATION_AMOUNT = 200

# Referral
REFERRAL_JOIN_BONUS = 500
REFERRAL_MISSION_BONUS = 300
REFEREE_BONUS = 400
PASSIVE_PERCENT = 5
PASSIVE_MONTHLY_CAP = 500

# Time
TIMEZONE = "Asia/Kolkata"

# Runtime cache — populated once at bot startup via bot.get_me()
BOT_USERNAME: str = ""
