"""Check encoded media before publishing an export as a completed MP4."""
from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path

from ..process import resolve_tool_command


def validate_export(path: Path, expected: float, *, has_audio: bool, command, on_progress=None) -> dict:
    info = json.loads(command(resolve_tool_command("ffprobe") + [
        "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]))
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(info.get("format", {}).get("duration", "nan"))
    if not video or not math.isfinite(duration) or abs(duration - expected) > .3:
        raise ValueError("成品影像或長度驗證失敗。")
    if has_audio and not audio:
        raise ValueError("成品缺少原片的音訊。")
    for stream in [video, *audio]:
        at = float(stream.get("start_time", "nan"))
        length = float(stream.get("duration", "nan"))
        if not math.isfinite(at) or abs(at) > .1 or not math.isfinite(length) or abs(length - expected) > .3:
            raise ValueError("成品影音軌的起點或長度異常。")
    # A readable header alone does not detect a truncated/corrupt later packet.
    args = resolve_tool_command("ffmpeg") + ["-v", "error", "-xerror", "-nostats", "-threads", "2", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a?", "-threads", "2"]
    if on_progress:
        args += ["-progress", "pipe:1", "-stats_period", "1"]
    errors = deque(maxlen=20)

    def check_line(line):
        if on_progress and on_progress(line):
            return True
        if line.strip():
            errors.append(line[-4000:])
        return False

    # FFmpeg 6.1 can report decoder errors yet exit successfully even with -xerror.
    # At error log level, any output not handled as progress must fail validation.
    command(args + ["-f", "null", "-"], on_line=check_line)
    if errors:
        raise RuntimeError("成品解碼驗證失敗。\n" + "\n".join(errors)[-1800:])
    return {"duration": duration, "expected_duration": expected, "video": True, "audio": bool(audio),
            "stream_timing_checked": True, "full_decode_checked": True}
