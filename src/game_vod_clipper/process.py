from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass


class ToolMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def require_tool(name: str) -> str:
    command = resolve_tool_command(name)
    return shlex.join(command)


def resolve_tool_command(name: str) -> list[str]:
    # Keep yt-dlp and its EJS dependency in the same Python environment.
    if name == "yt-dlp" and importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]

    path = shutil.which(name)
    if path is not None:
        return [path]

    if name == "ffmpeg":
        raise ToolMissingError(
            "Missing required tool: ffmpeg. Install FFmpeg from your OS package "
            "manager or from sources listed on https://ffmpeg.org/download.html, "
            "then make sure ffmpeg is on PATH."
        )

    raise ToolMissingError(
        f"Missing required tool: {name}. Install it, make sure it is on PATH, "
        "or run `uv sync` for project-managed Python tools."
    )


def check_required_tools(names: list[str]) -> dict[str, str]:
    return {name: require_tool(name) for name in names}


def run_command(
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
) -> CommandResult:
    completed = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if check and completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"Command failed: {shlex.join(args)}\n{detail}")
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )
