"""Shared YouTube downloader setup for the CLI and background worker."""

from __future__ import annotations

import re
import shutil
import subprocess

from .process import ToolMissingError, resolve_tool_command


def javascript_runtime() -> str:
    """Select a supported runtime, including Node in the development container."""
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
    raise ToolMissingError(
        "YouTube 下載需要 Deno >= 2.3 或 Node.js >= 22。"
        "請安裝其中一個，確認位於後端的 PATH，再重試。"
    )


def youtube_command() -> list[str]:
    return resolve_tool_command("yt-dlp") + [
        "--no-js-runtimes",
        "--js-runtimes",
        javascript_runtime(),
    ]
