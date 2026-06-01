"""
Configuration module for ClassPlus Telegram Bot
"""

import os
import sys
import logging
from pathlib import Path
from typing import Final
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR: Final[Path] = Path(__file__).parent
DATABASE_PATH: Final[Path] = BASE_DIR / os.getenv("DATABASE_PATH", "classplus_bot.db")
DOWNLOAD_DIR: Final[Path] = BASE_DIR / os.getenv("DOWNLOAD_DIR", "downloads")

# ── Bot ────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: Final[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── API ────────────────────────────────────────────────────────────────────────
CLASSPLUS_BASE_URL: Final[str] = os.getenv(
    "CLASSPLUS_BASE_URL", "https://api.classplusapp.com/v2"
)
CLASSPLUS_API_VERSION: Final[str] = os.getenv("CLASSPLUS_API_VERSION", "52")
CLASSPLUS_REGION: Final[str] = "IN"
REQUEST_TIMEOUT: Final[int] = 30  # seconds

# ── Download ───────────────────────────────────────────────────────────────────
MAX_CONCURRENT_DOWNLOADS: Final[int] = 5
CHUNK_SIZE: Final[int] = 8 * 1024          # 8 KB
MAX_FILE_SIZE: Final[int] = 5 * 1024 ** 3  # 5 GB

ALLOWED_EXTENSIONS: Final[dict[str, tuple[str, ...]]] = {
    "video":   (".mp4", ".mov", ".avi", ".mkv", ".flv"),
    "pdf":     (".pdf",),
    "archive": (".zip", ".rar", ".7z"),
}

# ── UI / Pagination ────────────────────────────────────────────────────────────
MAX_COURSES_PER_PAGE: Final[int] = 10
MAX_CONTENT_ITEMS_PER_MESSAGE: Final[int] = 50
DOWNLOAD_PROGRESS_UPDATE_INTERVAL: Final[int] = 5  # seconds

# ── Session ────────────────────────────────────────────────────────────────────
SESSION_TIMEOUT: Final[int] = 60 * 60        # 1 hour
TOKEN_REFRESH_INTERVAL: Final[int] = 24 * 60 * 60  # 24 hours

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ── Messages ───────────────────────────────────────────────────────────────────
ERROR_MESSAGES: Final[dict[str, str]] = {
    "invalid_org":    "❌ Invalid organisation code. Please check and try again.",
    "invalid_mobile": "❌ Invalid mobile number. Enter 10 digits only.",
    "invalid_otp":    "❌ Invalid OTP. Please enter 4-6 digits.",
    "login_failed":   "❌ Login failed. Please try again.",
    "no_courses":     "❌ No courses found in your account.",
    "no_content":     "❌ No content found in this course.",
    "download_failed":"❌ Download failed. Please retry.",
    "token_expired":  "❌ Session expired. Please /start and login again.",
    "network_error":  "❌ Network error. Check your connection and retry.",
}

SUCCESS_MESSAGES: Final[dict[str, str]] = {
    "otp_sent":            "✅ OTP sent to {mobile}",
    "login_success":       "✅ Login successful!",
    "extraction_complete": "✅ Extraction complete!",
    "download_complete":   "✅ Download complete!",
    "logout_success":      "✅ Logged out successfully!",
}

# ── UI Text ────────────────────────────────────────────────────────────────────
_BANNER = (
    "╔════════════════════════════════╗\n"
    "║  🎓 CLASSPLUS DOWNLOADER BOT   ║\n"
    "╠════════════════════════════════╣\n"
    "║  Download courses with ease!   ║\n"
    "╚════════════════════════════════╝"
)

UI_TEXTS: Final[dict[str, str]] = {
    "main_menu": _BANNER,
    "help_text": (
        "📖 **HOW TO USE THIS BOT:**\n\n"
        "1️⃣ **Login** — Click \"Login with ClassPlus\"\n"
        "2️⃣ **Select Course** — Choose from your list\n"
        "3️⃣ **Choose Action:**\n"
        "   • Extract List — See all videos/PDFs\n"
        "   • Download All — Download everything\n\n"
        "⚠️ **NOTES:**\n"
        "• Large files may take time\n"
        "• Keep the bot running during downloads\n"
        "• Credentials are stored locally only\n\n"
        "💡 **COMMANDS:**\n"
        "/start — Main menu\n"
        "/help — This message\n"
        "/logout — Clear session"
    ),
}


# ── Validation ─────────────────────────────────────────────────────────────────
def validate_config() -> None:
    """
    Validate required config and set up directories.
    Exits the process immediately on failure.
    """
    errors: list[str] = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append(
            "TELEGRAM_BOT_TOKEN is missing.\n"
            "  → Add it to your .env file:  TELEGRAM_BOT_TOKEN=your_token"
        )

    if errors:
        for msg in errors:
            print(f"❌ CONFIG ERROR: {msg}", file=sys.stderr)
        sys.exit(1)

    # Ensure directories exist
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


validate_config()
