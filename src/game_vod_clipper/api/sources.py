"""Validation of local sources and YouTube URLs."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..storage.locations import Locations, media_path

EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}


def youtube_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("請使用有效的 HTTPS YouTube 影片網址。")
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/live/", "/shorts/")):
            video_id = parsed.path.split("/")[2]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("只接受單一 YouTube 影片網址。")
    return f"https://www.youtube.com/watch?v={video_id}"


def local_source(root: Path, source: str) -> Path:
    path = media_path(root, source).resolve()
    locations = Locations(root)
    if not any(path.is_relative_to(locations.folder(kind)) for kind in ("sources", "exports")):
        raise ValueError("本機影片必須位於原始影片或輸出成品資料夾，且不能連結到資料夾外。")
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        raise ValueError("找不到支援的本機影片。")
    return path
