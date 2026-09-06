from __future__ import annotations

import json
import re
from pathlib import Path

from .process import check_required_tools, resolve_tool_command, run_command
from .timecode import format_timecode, format_timecode_for_filename, parse_timecode
from .youtube import javascript_runtime, youtube_command

REQUIRED_TOOLS = ["yt-dlp", "ffmpeg"]


def check_tools() -> dict[str, str]:
    return check_required_tools(REQUIRED_TOOLS) | {"javascript": javascript_runtime()}


def download_video(
    url: str,
    output_dir: Path,
    *,
    format_selector: str | None = None,
    output_template: str | None = None,
) -> Path:
    ytdlp = youtube_command()
    output_dir.mkdir(parents=True, exist_ok=True)

    args = ytdlp + [
        "--no-playlist",
        "--restrict-filenames",
        "--merge-output-format",
        "mp4",
        "--write-info-json",
        "--print",
        "after_move:filepath",
        "-P",
        str(output_dir),
        "-o",
        output_template or "%(title).200B_[%(id)s].%(ext)s",
    ]
    if format_selector:
        args.extend(["-f", format_selector])
    args.append(url)

    result = run_command(args, capture=True)
    candidates = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    for candidate in reversed(candidates):
        if candidate.exists():
            return candidate
    if candidates:
        return candidates[-1]
    raise RuntimeError("yt-dlp finished but did not report an output file path")


def probe_duration(video_path: Path) -> float:
    ffmpeg = resolve_tool_command("ffmpeg")
    _ensure_file(video_path)
    result = run_command(
        ffmpeg + ["-hide_banner", "-i", str(video_path)],
        capture=True,
        check=False,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)",
        result.stderr,
    )
    if match is None:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not determine duration for {video_path}\n{detail}")

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def extract_frames(
    video_path: Path,
    output_dir: Path,
    *,
    start: str,
    end: str,
    every: float,
) -> Path:
    ffmpeg = resolve_tool_command("ffmpeg")
    _ensure_file(video_path)
    if every <= 0:
        raise ValueError("--every must be greater than 0")

    start_seconds = parse_timecode(start)
    end_seconds = parse_timecode(end)
    if end_seconds <= start_seconds:
        raise ValueError("--end must be after --start")

    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, str | float]] = []
    current = start_seconds
    index = 0
    while current <= end_seconds + 0.001:
        timestamp = format_timecode(current)
        filename_time = format_timecode_for_filename(current)
        frame_path = output_dir / f"frame_{index:04d}_{filename_time}.jpg"
        run_command(
            ffmpeg
            + [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                timestamp,
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ]
        )
        frames.append(
            {
                "index": index,
                "timestamp": timestamp,
                "seconds": round(current, 3),
                "path": str(frame_path),
            }
        )
        index += 1
        current += every

    manifest_path = output_dir / "samples.json"
    manifest = {
        "video": str(video_path),
        "start": format_timecode(start_seconds),
        "end": format_timecode(end_seconds),
        "every_seconds": every,
        "frames": frames,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def create_contact_sheet(
    frame_dir: Path,
    output_path: Path,
    *,
    columns: int = 5,
    rows: int = 4,
    width: int = 320,
) -> Path:
    ffmpeg = resolve_tool_command("ffmpeg")
    if columns <= 0 or rows <= 0 or width <= 0:
        raise ValueError("columns, rows, and width must be positive")
    if not frame_dir.is_dir():
        raise FileNotFoundError(f"frame directory not found: {frame_dir}")

    frames = sorted(frame_dir.glob("*.jpg"))
    if not frames:
        raise FileNotFoundError(f"no JPG frames found in: {frame_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        ffmpeg
        + [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-pattern_type",
            "glob",
            "-i",
            str(frame_dir / "*.jpg"),
            "-vf",
            f"scale={width}:-1,tile={columns}x{rows}",
            "-frames:v",
            "1",
            str(output_path),
        ]
    )
    return output_path


def clip_video(
    video_path: Path,
    output_path: Path,
    *,
    start: str,
    end: str,
    postroll: float = 8.0,
    stream_copy: bool = False,
) -> Path:
    ffmpeg = resolve_tool_command("ffmpeg")
    _ensure_file(video_path)
    if postroll < 0:
        raise ValueError("--postroll cannot be negative")

    start_seconds = parse_timecode(start)
    end_seconds = parse_timecode(end) + postroll
    if end_seconds <= start_seconds:
        raise ValueError("clip end plus postroll must be after --start")

    duration = end_seconds - start_seconds
    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = ffmpeg + [
        "-hide_banner",
        "-y",
        "-ss",
        format_timecode(start_seconds),
        "-i",
        str(video_path),
        "-t",
        format_timecode(duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if stream_copy:
        args.extend(["-c", "copy"])
    else:
        args.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ]
        )
    args.append(str(output_path))
    run_command(args)
    return output_path


def _ensure_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
