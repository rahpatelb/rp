#!/usr/bin/env python3
"""
First-time setup for ClassPlus Telegram Bot.
Run once: python setup.py
"""

import re
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
_TOKEN_RE  = re.compile(r'^\d{8,12}:[A-Za-z0-9_-]{35}$')

_BANNER_START = (
    "╔═══════════════════════════════════════╗\n"
    "║  🎓 CLASSPLUS TELEGRAM BOT — SETUP    ║\n"
    "╠═══════════════════════════════════════╣\n"
    "║  First-time environment setup         ║\n"
    "╚═══════════════════════════════════════╝"
)

_BANNER_DONE = (
    "╔═══════════════════════════════════════╗\n"
    "║  ✅ SETUP COMPLETE!                   ║\n"
    "╠═══════════════════════════════════════╣\n"
    "║  Start the bot with:                  ║\n"
    "║    python run.py                      ║\n"
    "║                                       ║\n"
    "║  Need help? See README.md             ║\n"
    "╚═══════════════════════════════════════╝"
)


def check_python() -> None:
    print("› Checking Python version...")
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        sys.exit(
            f"❌ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required.\n"
            f"   You have {v.major}.{v.minor}.{v.micro}\n"
            "   Download: https://www.python.org/downloads/"
        )
    print(f"  ✅ Python {v.major}.{v.minor}.{v.micro}")


def install_requirements() -> None:
    req_file = Path("requirements.txt")
    if not req_file.exists():
        sys.exit("❌ requirements.txt not found. Run from the project root.")

    print("\n› Installing dependencies...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            check=True,
        )
        print("  ✅ Dependencies installed")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"❌ pip failed (exit {exc.returncode}). See output above.")


def _prompt_token() -> str:
    print(
        "\n  How to get your token:\n"
        "    1. Open Telegram → @BotFather\n"
        "    2. Send /newbot and follow the prompts\n"
        "    3. Copy the token provided\n"
    )
    while True:
        try:
            token = input("  Paste your TELEGRAM_BOT_TOKEN: ").strip()
        except EOFError:
            sys.exit("\n❌ Non-interactive mode. Create .env manually from .env.example.")

        if not token:
            print("  ⚠️  Token cannot be empty.")
            continue
        if not _TOKEN_RE.match(token):
            print(
                "  ⚠️  Doesn't look like a valid token.\n"
                "       Expected: 123456789:ABCDef... (35-char secret)"
            )
            continue
        return token


def create_env_file() -> None:
    print("\n› Setting up .env...")
    env_path = Path(".env")

    if env_path.exists():
        try:
            ow = input("  ⚠️  .env already exists. Overwrite? (y/N): ").strip().lower()
        except EOFError:
            ow = "n"
        if ow != "y":
            print("  ⏭️  Keeping existing .env")
            return

    token = _prompt_token()
    env_path.write_text(
        "# ClassPlus Telegram Bot\n\n"
        f"TELEGRAM_BOT_TOKEN={token}\n\n"
        "DATABASE_PATH=classplus_bot.db\n"
        "DOWNLOAD_DIR=downloads\n"
        "LOG_LEVEL=INFO\n",
        encoding="utf-8",
    )
    print("  ✅ .env created")


def create_directories() -> None:
    print("\n› Creating directories...")
    Path("downloads").mkdir(exist_ok=True)
    print("  ✅ downloads/")


def verify_setup() -> bool:
    print("\n› Verifying configuration...")
    env_path = Path(".env")
    if not env_path.exists():
        print("  ❌ .env missing")
        return False

    lines = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    if not _TOKEN_RE.match(lines.get("TELEGRAM_BOT_TOKEN", "")):
        print("  ❌ TELEGRAM_BOT_TOKEN missing or invalid")
        return False

    print("  ✅ Configuration looks good")
    return True


def main() -> None:
    print(_BANNER_START)
    try:
        check_python()
        install_requirements()
        create_env_file()
        create_directories()

        if verify_setup():
            print(f"\n{_BANNER_DONE}")
        else:
            sys.exit("\n⚠️  Fix errors above, then run: python setup.py")

    except KeyboardInterrupt:
        print("\n\n⚠️  Setup cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
