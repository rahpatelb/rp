#!/usr/bin/env python3
"""
Entry point for ClassPlus Telegram Bot.
Run this file to start the bot: python run.py
"""

import asyncio
import logging
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit(
        f"❌ Python 3.10+ required. You are running {sys.version}.\n"
        "   Download: https://python.org/downloads"
    )

_BANNER = (
    "╔═══════════════════════════════════════╗\n"
    "║  🚀 CLASSPLUS TELEGRAM BOT            ║\n"
    "╠═══════════════════════════════════════╣\n"
    "║  Starting...                          ║\n"
    "╚═══════════════════════════════════════╝"
)


def _check_env() -> bool:
    env_path = Path(".env")
    if not env_path.exists():
        print(
            "❌ .env file not found.\n"
            "   Copy the template:  cp .env.example .env\n"
            "   Then add your token."
        )
        return False

    content = env_path.read_text(encoding="utf-8")
    if "TELEGRAM_BOT_TOKEN=" not in content:
        print("❌ TELEGRAM_BOT_TOKEN not found in .env.")
        return False

    return True


def _check_requirements() -> bool:
    missing = []
    packages = {
        "telegram": "python-telegram-bot",
        "requests": "requests",
        "aiofiles": "aiofiles",
        "dotenv":   "python-dotenv",
    }
    for module, pip_name in packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(
            "❌ Missing dependencies:\n"
            + "\n".join(f"   • {p}" for p in missing)
            + "\n\n   Fix:  pip install -r requirements.txt"
        )
        return False
    return True


def main() -> None:
    print(_BANNER)

    if not _check_env() or not _check_requirements():
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        from telegram_bot import main as bot_main

        if asyncio.iscoroutinefunction(bot_main):
            asyncio.run(bot_main())
        else:
            bot_main()

    except KeyboardInterrupt:
        print("\n✅ Bot stopped.")
        sys.exit(0)
    except Exception:
        logging.exception("Bot crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
