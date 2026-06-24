from __future__ import annotations

import math


def parse_timecode(value: str) -> float:
    """Parse SS, MM:SS, or HH:MM:SS into seconds."""
    text = value.strip()
    if not text:
        raise ValueError("timecode cannot be empty")

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid timecode: {value!r}")

    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"invalid timecode: {value!r}") from exc

    if any(math.isnan(number) or number < 0 for number in numbers):
        raise ValueError(f"invalid timecode: {value!r}")

    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        minutes, seconds = numbers
        _validate_clock_part(minutes, "minutes", value)
        _validate_clock_part(seconds, "seconds", value, allow_fraction=True)
        return minutes * 60 + seconds

    hours, minutes, seconds = numbers
    _validate_clock_part(minutes, "minutes", value)
    _validate_clock_part(seconds, "seconds", value, allow_fraction=True)
    return hours * 3600 + minutes * 60 + seconds


def format_timecode(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm for ffmpeg-compatible arguments."""
    if math.isnan(seconds) or seconds < 0:
        raise ValueError("seconds must be a non-negative number")

    whole_seconds = int(seconds)
    milliseconds = int(round((seconds - whole_seconds) * 1000))
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0

    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    remaining_seconds = whole_seconds % 60
    if milliseconds:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}.{milliseconds:03d}"
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"


def format_timecode_for_filename(seconds: float) -> str:
    return format_timecode(seconds).replace(":", "-").replace(".", "-")


def _validate_clock_part(
    number: float,
    label: str,
    original: str,
    *,
    allow_fraction: bool = False,
) -> None:
    if number >= 60:
        raise ValueError(f"{label} must be less than 60 in timecode: {original!r}")
    if not allow_fraction and not number.is_integer():
        raise ValueError(f"{label} must be a whole number in timecode: {original!r}")
