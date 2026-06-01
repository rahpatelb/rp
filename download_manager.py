"""
Download Manager for ClassPlus Telegram Bot
Handles regular file downloads and HLS/M3U8 streams with progress tracking.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import requests

logger = logging.getLogger(__name__)


class DownloadResult(NamedTuple):
    success: bool
    filepath: str
    message: str


class DownloadManager:

    _ILLEGAL_CHARS = re.compile(r'[\\/*?:"<>|\x00-\x1f]')

    def __init__(self, download_dir: str | Path = "downloads") -> None:
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_available: Optional[bool] = None

    def sanitize_filename(self, filename: str) -> str:
        name = self._ILLEGAL_CHARS.sub("", filename)
        name = Path(name).name
        return name or "download"

    @staticmethod
    def format_size(size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024  # type: ignore[assignment]
        return f"{size_bytes:.1f} PB"

    def get_file_size(self, filepath: str | Path) -> str:
        try:
            return self.format_size(Path(filepath).stat().st_size)
        except OSError:
            return "Unknown"

    def _check_ffmpeg(self) -> bool:
        if self._ffmpeg_available is None:
            try:
                result = subprocess.run(
                    ["ffmpeg", "-version"], capture_output=True, timeout=5
                )
                self._ffmpeg_available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._ffmpeg_available = False
        return self._ffmpeg_available

    def download_file(
        self,
        url: str,
        filename: str,
        progress_callback: Optional[Callable[[float, int, int], None]] = None,
        timeout: int = 300,
        chunk_size: int = 8_192,
    ) -> DownloadResult:
        filename = self.sanitize_filename(filename)
        filepath = self.download_dir / filename

        if filepath.exists():
            return DownloadResult(True, str(filepath), "File already exists")

        tmp_path = filepath.with_suffix(filepath.suffix + ".part")

        try:
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with tmp_path.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                progress_callback(
                                    downloaded / total_size * 100,
                                    downloaded,
                                    total_size,
                                )

            tmp_path.rename(filepath)
            return DownloadResult(True, str(filepath), "Downloaded successfully")

        except requests.RequestException as exc:
            logger.error("Download error for %s: %s", url, exc)
            return DownloadResult(False, "", str(exc))
        except Exception as exc:
            logger.exception("Unexpected error downloading %s", url)
            return DownloadResult(False, "", str(exc))
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def download_m3u8(
        self,
        url: str,
        filename: str,
        progress_callback: Optional[Callable[[float, int, int], None]] = None,
        timeout: int = 3_600,
    ) -> DownloadResult:
        if not self._check_ffmpeg():
            return DownloadResult(
                False, "",
                "FFmpeg not found. Install from https://ffmpeg.org/download.html"
            )

        filename = self.sanitize_filename(filename)
        if not filename.endswith(".mp4"):
            filename += ".mp4"

        filepath = self.download_dir / filename
        if filepath.exists():
            return DownloadResult(True, str(filepath), "File already exists")

        command = [
            "ffmpeg", "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-y", str(filepath),
        ]

        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0 and filepath.exists():
                return DownloadResult(True, str(filepath), "Downloaded successfully")

            error = result.stderr.strip() or "Unknown ffmpeg error"
            logger.error("ffmpeg failed (rc=%d): %s", result.returncode, error)
            return DownloadResult(False, "", error)

        except subprocess.TimeoutExpired:
            return DownloadResult(False, "", f"ffmpeg timed out after {timeout}s")
        except Exception as exc:
            logger.exception("Unexpected error during M3U8 download")
            return DownloadResult(False, "", str(exc))
        finally:
            if filepath.exists() and filepath.stat().st_size == 0:
                filepath.unlink(missing_ok=True)

    def list_downloads(self) -> list[dict]:
        files = []
        try:
            for path in sorted(self.download_dir.iterdir()):
                if path.is_file() and not path.name.endswith(".part"):
                    files.append({
                        "name": path.name,
                        "size": self.get_file_size(path),
                        "path": str(path),
                    })
        except OSError as exc:
            logger.error("list_downloads failed: %s", exc)
        return files

    def get_total_size(self) -> str:
        try:
            total = sum(
                p.stat().st_size
                for p in self.download_dir.rglob("*")
                if p.is_file()
            )
            return self.format_size(total)
        except OSError as exc:
            logger.error("get_total_size failed: %s", exc)
            return "Unknown"

    def cleanup_old_files(self, days: int = 7) -> int:
        cutoff  = time.time() - days * 86_400
        deleted = 0
        try:
            for path in self.download_dir.iterdir():
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
        except OSError as exc:
            logger.error("cleanup_old_files failed: %s", exc)
        return deleted
