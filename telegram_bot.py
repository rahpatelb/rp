#!/usr/bin/env python3
"""
ClassPlus Telegram Bot
Login via OTP  —OR—  paste your ClassPlus token directly.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from database import Database
from download_manager import DownloadManager

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
# OTP flow
ORG_CODE, MOBILE, OTP = range(3)
# Token flow
TOKEN_INPUT = 3


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bot(context: ContextTypes.DEFAULT_TYPE) -> "ClassplusBot":
    return context.application.bot_data["classplus"]


def _keyboard(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(list(rows))


# ── API client ─────────────────────────────────────────────────────────────────

class ClassplusBot:

    def __init__(self, db: Database, dl: DownloadManager) -> None:
        self.db      = db
        self.dl      = dl
        self.session = requests.Session()

    @staticmethod
    def _device_id(context: ContextTypes.DEFAULT_TYPE) -> str:
        if "device_id" not in context.user_data:
            context.user_data["device_id"] = f"web_{uuid.uuid4().hex[:16]}"
        return context.user_data["device_id"]

    def _headers(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        token: str = "",
    ) -> dict:
        return {
            "Api-Version":    config.CLASSPLUS_API_VERSION,
            "Content-Type":   "application/json",
            "Device-Id":      self._device_id(context),
            "User-Agent":     (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
            "Origin":         "https://web.classplusapp.com",
            "Referer":        "https://web.classplusapp.com/",
            "Region":         config.CLASSPLUS_REGION,
            "Accept":         "application/json, text/plain, */*",
            "x-access-token": token,
        }

    # ── Auth: OTP ──────────────────────────────────────────────────────────────

    def send_otp(
        self,
        mobile: str,
        org_code: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> tuple[Optional[str], Optional[str], str]:
        """Returns (session_id, org_id, message)."""
        try:
            r = self.session.get(
                f"{config.CLASSPLUS_BASE_URL}/orgs/{org_code}",
                headers=self._headers(context),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return None, None, config.ERROR_MESSAGES["invalid_org"]

            org_id = r.json().get("data", {}).get("orgId")
            payload = {
                "countryExt": "91",
                "mobile":     mobile,
                "orgCode":    org_code,
                "orgId":      org_id,
                "viaSms":     1,
            }
            r = self.session.post(
                f"{config.CLASSPLUS_BASE_URL}/otp/generate",
                json=payload,
                headers=self._headers(context),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                session_id = r.json().get("data", {}).get("sessionId")
                return (
                    session_id,
                    str(org_id),
                    config.SUCCESS_MESSAGES["otp_sent"].format(mobile=mobile),
                )
            return None, None, config.ERROR_MESSAGES["login_failed"]

        except requests.RequestException as exc:
            logger.error("send_otp error: %s", exc)
            return None, None, config.ERROR_MESSAGES["network_error"]

    def verify_otp(
        self,
        mobile: str,
        org_code: str,
        session_id: str,
        org_id: str,
        otp: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> tuple[Optional[str], Optional[int], str]:
        """Returns (token, classplus_user_id, message)."""
        try:
            payload = {
                "otp":           otp,
                "countryExt":    "91",
                "sessionId":     session_id,
                "orgId":         org_id,
                "mobile":        mobile,
                "fingerprintId": str(uuid.uuid4()),
            }
            r = self.session.post(
                f"{config.CLASSPLUS_BASE_URL}/users/verify",
                json=payload,
                headers=self._headers(context),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                res = r.json()
                if res.get("status") == "success":
                    token  = res["data"]["token"]
                    cp_uid = res["data"]["user"]["id"]
                    return token, cp_uid, config.SUCCESS_MESSAGES["login_success"]
                return None, None, f"❌ {res.get('message', 'Verification failed')}"
            return None, None, config.ERROR_MESSAGES["invalid_otp"]

        except requests.RequestException as exc:
            logger.error("verify_otp error: %s", exc)
            return None, None, config.ERROR_MESSAGES["network_error"]

    # ── Auth: Token ────────────────────────────────────────────────────────────

    def verify_token(
        self,
        token: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> tuple[bool, Optional[int], str]:
        """
        Validate a raw ClassPlus token by calling the profile endpoint.
        Returns (valid, classplus_user_id, message).
        """
        try:
            r = self.session.get(
                f"{config.CLASSPLUS_BASE_URL}/profiles/users/data",
                params={"tabCategoryId": 3},
                headers=self._headers(context, token),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                # Pull user ID from profile response
                cp_uid = (
                    data.get("responseData", {})
                        .get("basicProfile", {})
                        .get("id")
                )
                return True, cp_uid, config.SUCCESS_MESSAGES["login_success"]

            elif r.status_code in (401, 403):
                return False, None, "❌ Token invalid or expired. Please try again."
            else:
                return False, None, f"❌ Server returned {r.status_code}. Try again."

        except requests.RequestException as exc:
            logger.error("verify_token error: %s", exc)
            return False, None, config.ERROR_MESSAGES["network_error"]

    # ── Courses ────────────────────────────────────────────────────────────────

    def get_courses(
        self,
        token: str,
        cp_user_id: int,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> list[dict]:
        try:
            r = self.session.get(
                f"{config.CLASSPLUS_BASE_URL}/profiles/users/data",
                params={"userId": cp_user_id, "tabCategoryId": 3},
                headers=self._headers(context, token),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return (
                    r.json()
                    .get("data", {})
                    .get("responseData", {})
                    .get("coursesData", [])
                )
        except requests.RequestException as exc:
            logger.error("get_courses error: %s", exc)
        return []

    def get_course_content(
        self,
        token: str,
        course_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        folder_id: int = 0,
        _depth: int = 0,
    ) -> list[dict]:
        """Recursively fetch course content (max depth 10)."""
        if _depth > 10:
            logger.warning("Max folder depth reached for course %s", course_id)
            return []

        contents: list[dict] = []
        try:
            r = self.session.get(
                f"{config.CLASSPLUS_BASE_URL}/course/content/get",
                params={"courseId": course_id, "folderId": folder_id},
                headers=self._headers(context, token),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return contents

            for item in r.json().get("data", {}).get("courseContent", []):
                c_type = item.get("contentType")
                c_id   = str(item.get("id"))
                name   = item.get("name", "Unnamed")

                if c_type == 1:    # Folder
                    contents.extend(
                        self.get_course_content(
                            token, course_id, context, c_id, _depth + 1
                        )
                    )
                elif c_type == 2:  # Video
                    h_id = item.get("contentHashId", "")
                    contents.append({
                        "name":       name,
                        "identifier": h_id or c_id,
                        "type":       "video",
                        "numeric_id": c_id,
                    })
                elif c_type == 3:  # PDF
                    contents.append({
                        "name":       name,
                        "url":        item.get("url", ""),
                        "type":       "pdf",
                        "numeric_id": c_id,
                    })

        except requests.RequestException as exc:
            logger.error("get_course_content error: %s", exc)

        return contents

    def get_download_url(
        self,
        token: str,
        numeric_id: str,
        identifier: Optional[str],
        context: ContextTypes.DEFAULT_TYPE,
    ) -> Optional[str]:
        headers  = self._headers(context, token)
        attempts = [
            (
                "https://api.classplusapp.com/cams/uploader/video/jw-signed-url",
                {"contentId": numeric_id},
            ),
        ]
        if identifier and identifier != numeric_id:
            attempts.append((
                "https://api.classplusapp.com/cams/uploader/video/jw-signed-url",
                {"contentId": identifier},
            ))
        attempts.append((
            f"{config.CLASSPLUS_BASE_URL}/course/content/get-signed-url",
            {"contentId": numeric_id},
        ))

        for endpoint, params in attempts:
            try:
                r = self.session.get(
                    endpoint, params=params, headers=headers, timeout=10
                )
                if r.status_code == 200:
                    data = r.json()
                    url  = data.get("url") or data.get("data", {}).get("url")
                    if url:
                        return url
            except requests.RequestException as exc:
                logger.debug("get_download_url attempt failed (%s): %s", endpoint, exc)

        logger.warning("No download URL found for content %s", numeric_id)
        return None


# ── Shared menu ────────────────────────────────────────────────────────────────

async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cp   = _bot(context)
    uid  = update.effective_user.id
    user = cp.db.get_user(uid)
    text = config.UI_TEXTS["main_menu"]

    if user:
        kb = _keyboard(
            [InlineKeyboardButton("📚 Your Courses",  callback_data="view_courses")],
            [InlineKeyboardButton("🔄 Login Again",   callback_data="login_otp")],
            [InlineKeyboardButton("🔑 Change Token",  callback_data="login_token")],
            [InlineKeyboardButton("❌ Logout",         callback_data="logout")],
            [InlineKeyboardButton("ℹ️ Help",           callback_data="help")],
        )
    else:
        kb = _keyboard(
            [InlineKeyboardButton("📱 Login with OTP",   callback_data="login_otp")],
            [InlineKeyboardButton("🔑 Login with Token", callback_data="login_token")],
            [InlineKeyboardButton("ℹ️ Help",              callback_data="help")],
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_main_menu(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        config.UI_TEXTS["help_text"], parse_mode="Markdown"
    )


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _bot(context).db.delete_user(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text(config.SUCCESS_MESSAGES["logout_success"])
    await _show_main_menu(update, context)


# ── OTP Login ConversationHandler ──────────────────────────────────────────────

async def otp_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📱 *Login with OTP*\n\nEnter your organisation code:\n_(e.g. BYJUS, VEDANTU)_",
        parse_mode="Markdown",
    )
    return ORG_CODE


async def otp_org_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["org_code"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "📱 Enter your 10-digit mobile number:",
        reply_markup=_keyboard(
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")]
        ),
    )
    return MOBILE


async def otp_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mobile = update.message.text.strip()[-10:]
    if not mobile.isdigit() or len(mobile) != 10:
        await update.message.reply_text(config.ERROR_MESSAGES["invalid_mobile"])
        return MOBILE

    org_code = context.user_data["org_code"]
    context.user_data["mobile"] = mobile

    await update.message.reply_text(f"⏳ Sending OTP to +91{mobile}…")
    session_id, org_id, msg = _bot(context).send_otp(mobile, org_code, context)

    if not session_id:
        await update.message.reply_text(f"{msg}\n\nEnter organisation code again:")
        return ORG_CODE

    context.user_data["session_id"] = session_id
    context.user_data["org_id"]     = org_id
    await update.message.reply_text(f"{msg}\n\n🔐 Enter the OTP:")
    return OTP


async def otp_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp = update.message.text.strip()
    if not otp.isdigit() or not (4 <= len(otp) <= 6):
        await update.message.reply_text(config.ERROR_MESSAGES["invalid_otp"])
        return OTP

    cp  = _bot(context)
    uid = update.effective_user.id
    token, cp_uid, msg = cp.verify_otp(
        context.user_data["mobile"],
        context.user_data["org_code"],
        context.user_data["session_id"],
        context.user_data["org_id"],
        otp,
        context,
    )

    if not token:
        await update.message.reply_text(f"{msg}\n\nEnter OTP again:")
        return OTP

    cp.db.add_user(uid, token, cp_uid, context.user_data["org_code"], context.user_data["mobile"])
    for key in ("session_id", "org_id", "mobile", "org_code"):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        msg,
        reply_markup=_keyboard(
            [InlineKeyboardButton("📚 View Courses", callback_data="view_courses")]
        ),
    )
    return ConversationHandler.END


# ── Token Login ConversationHandler ───────────────────────────────────────────

async def token_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Login with Token*\n\n"
        "Paste your ClassPlus API token below.\n\n"
        "📌 *How to get your token:*\n"
        "1. Open ClassPlus web: https://web.classplusapp.com\n"
        "2. Login to your account\n"
        "3. Open DevTools → Network tab\n"
        "4. Find any API request → Headers\n"
        "5. Copy the `x-access-token` value\n\n"
        "⚠️ Token starts with `eyJ...` (JWT format)",
        parse_mode="Markdown",
        reply_markup=_keyboard(
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")]
        ),
    )
    return TOKEN_INPUT


async def token_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()

    # Basic JWT format check  (eyJ...)
    if not token.startswith("eyJ") or len(token) < 50:
        await update.message.reply_text(
            "❌ That doesn't look like a valid token.\n"
            "It should start with `eyJ` and be quite long.\n\n"
            "Try again or tap Cancel.",
            parse_mode="Markdown",
            reply_markup=_keyboard(
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")]
            ),
        )
        return TOKEN_INPUT

    await update.message.reply_text("⏳ Verifying token…")

    cp  = _bot(context)
    uid = update.effective_user.id
    valid, cp_uid, msg = cp.verify_token(token, context)

    if not valid:
        await update.message.reply_text(
            f"{msg}\n\nPaste a different token or tap Cancel.",
            reply_markup=_keyboard(
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")]
            ),
        )
        return TOKEN_INPUT

    # Save — org_code & mobile unknown in token flow, store as empty strings
    cp.db.add_user(uid, token, cp_uid or 0, "", "")

    await update.message.reply_text(
        f"{msg}\n\n✅ Token saved! You're all set.",
        reply_markup=_keyboard(
            [InlineKeyboardButton("📚 View Courses", callback_data="view_courses")]
        ),
    )
    return ConversationHandler.END


# ── Shared cancel for both flows ───────────────────────────────────────────────

async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for key in ("session_id", "org_id", "mobile", "org_code"):
        context.user_data.pop(key, None)
    await _show_main_menu(update, context)
    return ConversationHandler.END


# ── Course / download callbacks ────────────────────────────────────────────────

async def cb_view_courses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cp   = _bot(context)
    uid  = update.effective_user.id
    user = cp.db.get_user(uid)

    if not user:
        await query.edit_message_text("❌ Please login first.")
        return

    courses = cp.get_courses(user["token"], user["user_id_classplus"], context)
    if not courses:
        await query.edit_message_text(config.ERROR_MESSAGES["no_courses"])
        return

    context.user_data["courses"] = courses
    rows = [
        [InlineKeyboardButton(
            f"📚 {c.get('name', 'Unknown')[:28]}",
            callback_data=f"course_{c['id']}",
        )]
        for c in courses[:config.MAX_COURSES_PER_PAGE]
    ]
    rows.append([InlineKeyboardButton("« Back", callback_data="main_menu")])

    await query.edit_message_text(
        "📚 *Your Courses:*",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )


async def cb_course_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    context.user_data["selected_course"] = course_id

    kb = _keyboard(
        [InlineKeyboardButton("📋 Extract List",  callback_data=f"extract_{course_id}")],
        [InlineKeyboardButton("⬇️ Download All",  callback_data=f"download_{course_id}")],
        [InlineKeyboardButton("« Back",           callback_data="view_courses")],
    )
    await query.edit_message_text(
        "🎯 *Select Action:*", reply_markup=kb, parse_mode="Markdown"
    )


async def cb_extract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    cp   = _bot(context)
    user = cp.db.get_user(update.effective_user.id)

    await query.edit_message_text("⏳ Fetching course content…")
    contents = cp.get_course_content(user["token"], course_id, context)

    if not contents:
        await query.edit_message_text(config.ERROR_MESSAGES["no_content"])
        return

    lines = []
    for i, item in enumerate(contents[:config.MAX_CONTENT_ITEMS_PER_MESSAGE], 1):
        emoji = "🎬" if item["type"] == "video" else "📄"
        lines.append(f"{i}. {emoji} {item['name'][:45]}")

    text = "📋 *Course Content:*\n\n" + "\n".join(lines)
    if len(contents) > config.MAX_CONTENT_ITEMS_PER_MESSAGE:
        text += f"\n\n…and {len(contents) - config.MAX_CONTENT_ITEMS_PER_MESSAGE} more"

    await query.edit_message_text(
        text,
        reply_markup=_keyboard(
            [InlineKeyboardButton("⬇️ Download All", callback_data=f"download_{course_id}")],
            [InlineKeyboardButton("« Back",           callback_data="view_courses")],
        ),
        parse_mode="Markdown",
    )


async def cb_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    cp   = _bot(context)
    uid  = update.effective_user.id
    user = cp.db.get_user(uid)

    await query.edit_message_text("⏳ Fetching content list…")
    contents = cp.get_course_content(user["token"], course_id, context)

    if not contents:
        await query.edit_message_text(config.ERROR_MESSAGES["no_content"])
        return

    total    = len(contents)
    done     = 0
    failed   = 0
    progress = await query.edit_message_text(
        f"📊 *Download Progress:*\n0 / {total}", parse_mode="Markdown"
    )

    for item in contents:
        try:
            if item["type"] == "video":
                url = cp.get_download_url(
                    user["token"], item["numeric_id"], item.get("identifier"), context
                )
            else:
                url = item.get("url")

            if url:
                filename = "{}.{}".format(
                    item["name"], "mp4" if item["type"] == "video" else "pdf"
                )
                result = (
                    cp.dl.download_m3u8(url, filename)
                    if ".m3u8" in url
                    else cp.dl.download_file(url, filename)
                )
                status = "completed" if result.success else "failed"
                if not result.success:
                    failed += 1
                    logger.warning("Failed: %s — %s", item["name"], result.message)
            else:
                status = "failed"
                failed += 1

            done += 1
            cp.db.add_download(uid, item["name"], item["type"], status)

        except Exception:
            failed += 1
            done   += 1
            logger.exception("Unexpected error downloading %s", item["name"])
            cp.db.add_download(uid, item["name"], item["type"], "failed")

        if done % config.DOWNLOAD_PROGRESS_UPDATE_INTERVAL == 0 or done == total:
            try:
                await progress.edit_text(
                    f"📊 *Download Progress:*\n{done} / {total}"
                    + (f"\n⚠️ {failed} failed" if failed else ""),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    summary = f"✅ *Done!* {done - failed}/{total} downloaded"
    if failed:
        summary += f"\n⚠️ {failed} items failed — check logs."
    await progress.edit_text(summary, parse_mode="Markdown")


async def cb_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _bot(context).db.delete_user(update.effective_user.id)
    context.user_data.clear()
    await query.edit_message_text(config.SUCCESS_MESSAGES["logout_success"])
    await _show_main_menu(update, context)


async def cb_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        config.UI_TEXTS["help_text"],
        reply_markup=_keyboard(
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ),
        parse_mode="Markdown",
    )


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _show_main_menu(update, context)


# ── Application setup ──────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=config.LOG_FORMAT,
    )

    db  = Database(str(config.DATABASE_PATH))
    dl  = DownloadManager(str(config.DOWNLOAD_DIR))
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["classplus"] = ClassplusBot(db, dl)

    # ── OTP login conversation ─────────────────────────────────────────────────
    otp_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(otp_login_start, pattern="^login_otp$")],
        states={
            ORG_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_org_code)],
            MOBILE:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, otp_mobile),
                CallbackQueryHandler(login_cancel, pattern="^cancel_login$"),
            ],
            OTP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_verify)],
        },
        fallbacks=[CallbackQueryHandler(login_cancel, pattern="^cancel_login$")],
    )

    # ── Token login conversation ───────────────────────────────────────────────
    token_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(token_login_start, pattern="^login_token$")],
        states={
            TOKEN_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, token_input),
                CallbackQueryHandler(login_cancel, pattern="^cancel_login$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(login_cancel, pattern="^cancel_login$")],
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(otp_conv)
    app.add_handler(token_conv)

    app.add_handler(CallbackQueryHandler(cb_view_courses,  pattern="^view_courses$"))
    app.add_handler(CallbackQueryHandler(cb_course_action, pattern=r"^course_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_extract,       pattern=r"^extract_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_download,      pattern=r"^download_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_logout,        pattern="^logout$"))
    app.add_handler(CallbackQueryHandler(cb_help,          pattern="^help$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu,     pattern="^main_menu$"))

    logger.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
