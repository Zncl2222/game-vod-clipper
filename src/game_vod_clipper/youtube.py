"""Shared YouTube downloader setup for the CLI and background worker."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Literal

from .process import ToolMissingError, resolve_tool_command

DownloadQuality = Literal["best", "2160", "1440", "1080", "720", "480"]

# Select the container AFTER selecting the best streams. In particular, do not
# filter out high-resolution VP9/AV1 to obtain an H.264 MP4. yt-dlp stream-copies
# compatible pairs into WebM/MP4; uncommon pairs retain the lossless MKV fallback.
BROWSER_MERGE_FORMATS = "webm/mp4/mkv"


def quality_format(quality: DownloadQuality = "best") -> str:
    """Keep the best source, or the best format at/below the selected height."""
    if quality == "best":
        return "bv*+ba/b"
    if quality not in {"2160", "1440", "1080", "720", "480"}:
        raise ValueError("不支援的下載畫質，請重新選擇。")
    return f"bv*[height<={quality}]+ba/b[height<={quality}]"


def javascript_runtime() -> str:
    """Select a supported runtime, including Node in the development container."""
    too_old = []
    for name, minimum in (("deno", (2, 3, 0)), ("node", (22, 0, 0))):
        path = shutil.which(name)
        if path is None:
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = re.search(r"(?:^|\s)v?(\d+)\.(\d+)\.(\d+)", result.stdout)
        if (
            result.returncode == 0
            and version
            and tuple(map(int, version.groups())) >= minimum
        ):
            return f"{name}:{path}"
        if version:
            too_old.append(f"{path}（{'.'.join(version.groups())}）")
    # Naming the stale runtime makes an inherited PATH (e.g. an old nvm
    # version kept by a terminal) visible instead of a vague "install it".
    found = f"後端目前找到的是 {'、'.join(too_old)}，版本太舊。" if too_old else ""
    raise ToolMissingError(
        "YouTube 下載需要 Deno >= 2.3 或 Node.js >= 22。"
        f"{found}請安裝其中一個，確認位於後端的 PATH，再重試。"
    )


def youtube_command() -> list[str]:
    return resolve_tool_command("yt-dlp") + [
        "--no-js-runtimes",
        "--js-runtimes",
        javascript_runtime(),
    ]
