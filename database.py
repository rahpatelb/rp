"""
Database layer for ClassPlus Telegram Bot
Handles user authentication, downloads, and persistent cache.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised when a database operation fails."""


class Database:
    def __init__(self, db_path: str | Path = "classplus_bot.db") -> None:
        self.db_path = Path(db_path)
        self._init_database()

    # ── Connection ─────────────────────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager that yields a connection with WAL mode,
        foreign-key enforcement, and automatic commit/rollback.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_database(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id             INTEGER PRIMARY KEY,
                    token               TEXT    NOT NULL,
                    user_id_classplus   INTEGER,
                    org_code            TEXT,
                    mobile              TEXT,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    item_name       TEXT    NOT NULL,
                    item_type       TEXT    NOT NULL,
                    status          TEXT    NOT NULL,
                    downloaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS courses_cache (
                    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    course_id   INTEGER NOT NULL,
                    course_name TEXT,
                    course_data TEXT,
                    cached_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, course_id)
                );

                CREATE INDEX IF NOT EXISTS idx_downloads_user
                    ON downloads(user_id);
                CREATE INDEX IF NOT EXISTS idx_downloads_status
                    ON downloads(user_id, status);
            """)

    # ── Users ──────────────────────────────────────────────────────────────────

    def add_user(
        self,
        user_id: int,
        token: str,
        user_id_cp: int,
        org_code: str,
        mobile: str,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                        (user_id, token, user_id_classplus, org_code, mobile, last_login)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        token             = excluded.token,
                        user_id_classplus = excluded.user_id_classplus,
                        org_code          = excluded.org_code,
                        mobile            = excluded.mobile,
                        last_login        = CURRENT_TIMESTAMP
                    """,
                    (user_id, token, user_id_cp, org_code, mobile),
                )
            return True
        except Exception:
            logger.exception("add_user failed for user_id=%s", user_id)
            return False

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_user(self, user_id: int) -> bool:
        """Delete a user and all their data (CASCADE handles related rows)."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return True
        except Exception:
            logger.exception("delete_user failed for user_id=%s", user_id)
            return False

    # ── Downloads ──────────────────────────────────────────────────────────────

    def add_download(
        self, user_id: int, item_name: str, item_type: str, status: str
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO downloads (user_id, item_name, item_type, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, item_name, item_type, status),
                )
            return True
        except Exception:
            logger.exception("add_download failed for user_id=%s", user_id)
            return False

    def get_download_history(self, user_id: int, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM downloads
                WHERE user_id = ?
                ORDER BY downloaded_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Course Cache ───────────────────────────────────────────────────────────

    def cache_course(
        self,
        user_id: int,
        course_id: int,
        course_name: str,
        course_data: str,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO courses_cache
                        (user_id, course_id, course_name, course_data, cached_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, course_id) DO UPDATE SET
                        course_name = excluded.course_name,
                        course_data = excluded.course_data,
                        cached_at   = CURRENT_TIMESTAMP
                    """,
                    (user_id, course_id, course_name, course_data),
                )
            return True
        except Exception:
            logger.exception(
                "cache_course failed for user_id=%s course_id=%s", user_id, course_id
            )
            return False

    def get_cached_course(self, user_id: int, course_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT course_data FROM courses_cache
                WHERE user_id = ? AND course_id = ?
                """,
                (user_id, course_id),
            ).fetchone()
            return row[0] if row else None

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self, user_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                                               AS total_downloads,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed
                FROM downloads
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            return {
                "total_downloads": row["total_downloads"] or 0,
                "completed":       row["completed"]       or 0,
                "failed":          row["failed"]          or 0,
            }

    # ── Maintenance ────────────────────────────────────────────────────────────

    def cleanup_old_cache(self, days: int = 30) -> int:
        """Delete course cache entries older than `days` days."""
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM courses_cache
                WHERE cached_at < datetime('now', ? || ' days')
                """,
                (f"-{days}",),
            )
            return conn.execute("SELECT changes()").fetchone()[0]
