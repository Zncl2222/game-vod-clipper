from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .media import (
    check_tools,
    clip_video,
    create_contact_sheet,
    download_video,
    extract_frames,
    probe_duration,
)
from .process import ToolMissingError
from .timecode import format_timecode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="game-vod-clipper",
        description="Agent-guided CLI for clipping successful game boss fights from VODs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="verify yt-dlp, ffmpeg, and a YouTube JS runtime are available")

    download = subparsers.add_parser("download", help="download a single YouTube VOD")
    download.add_argument("url", help="YouTube URL")
    download.add_argument("-o", "--output-dir", type=Path, default=Path("downloads"))
    download.add_argument("-f", "--format", dest="format_selector")
    download.add_argument("--output-template")

    probe = subparsers.add_parser("probe", help="print video duration")
    probe.add_argument("video", type=Path)

    sample = subparsers.add_parser("sample", help="extract timestamped review frames")
    sample.add_argument("video", type=Path)
    sample.add_argument("--start", required=True, help="start time as SS, MM:SS, or HH:MM:SS")
    sample.add_argument("--end", required=True, help="end time as SS, MM:SS, or HH:MM:SS")
    sample.add_argument("--every", type=float, default=30.0, help="seconds between frames")
    sample.add_argument("-o", "--output-dir", type=Path, default=Path("runs/samples"))

    sheet = subparsers.add_parser("sheet", help="create a contact sheet from JPG frames")
    sheet.add_argument("frame_dir", type=Path)
    sheet.add_argument("-o", "--output", type=Path, required=True)
    sheet.add_argument("--columns", type=int, default=5)
    sheet.add_argument("--rows", type=int, default=4)
    sheet.add_argument("--width", type=int, default=320)

    clip = subparsers.add_parser("clip", help="cut the final victory clip")
    clip.add_argument("video", type=Path)
    clip.add_argument("--start", required=True, help="clip start time")
    clip.add_argument("--end", required=True, help="victory moment time, before postroll")
    clip.add_argument("--postroll", type=float, default=8.0, help="seconds after victory to keep")
    clip.add_argument("-o", "--output", type=Path, required=True)
    clip.add_argument("--copy", action="store_true", help="stream copy instead of re-encoding")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            tools = check_tools()
            for name, path in tools.items():
                print(f"{name}: {path}")
            return 0

        if args.command == "download":
            path = download_video(
                args.url,
                args.output_dir,
                format_selector=args.format_selector,
                output_template=args.output_template,
            )
            print(path)
            return 0

        if args.command == "probe":
            seconds = probe_duration(args.video)
            print(format_timecode(seconds))
            return 0

        if args.command == "sample":
            manifest = extract_frames(
                args.video,
                args.output_dir,
                start=args.start,
                end=args.end,
                every=args.every,
            )
            print(manifest)
            return 0

        if args.command == "sheet":
            output = create_contact_sheet(
                args.frame_dir,
                args.output,
                columns=args.columns,
                rows=args.rows,
                width=args.width,
            )
            print(output)
            return 0

        if args.command == "clip":
            output = clip_video(
                args.video,
                args.output,
                start=args.start,
                end=args.end,
                postroll=args.postroll,
                stream_copy=args.copy,
            )
            print(output)
            return 0

    except (FileNotFoundError, RuntimeError, ToolMissingError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
