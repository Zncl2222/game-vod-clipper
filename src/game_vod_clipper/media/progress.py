"""Structured yt-dlp / FFmpeg progress, without exposing source URLs or paths."""

from __future__ import annotations

import json
import math
import queue
import subprocess
import threading
import time
from collections import deque

DOWNLOAD_PREFIX = "__BOSSCUT_DOWNLOAD__"
POSTPROCESS_PREFIX = "__BOSSCUT_POSTPROCESS__"
DOWNLOAD_TEMPLATE = ("download:" + DOWNLOAD_PREFIX
                     + "%(progress.{status,downloaded_bytes,total_bytes,total_bytes_estimate,speed,eta})j"
                     + "\t%(info.{vcodec,acodec})j")
POSTPROCESS_TEMPLATE = "postprocess:" + POSTPROCESS_PREFIX + "%(progress.{status,postprocessor})j"


def streamed_command(args, on_line, *, timeout=6 * 3600):
    """Drain both output streams while keeping progress live and the timeout bounded."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    lines = queue.Queue()
    tail = deque(maxlen=100)

    def read():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("媒體處理逾時，請重試。")
            try:
                line = lines.get(timeout=min(1, remaining))
            except queue.Empty:
                continue
            if line is None:
                break
            if not on_line(line.strip()):
                tail.append(line[-4000:])
        code = process.wait(timeout=max(.01, deadline - time.monotonic()))
        if code:
            raise RuntimeError("".join(tail)[-1800:] or "Media command failed")
        return "".join(tail)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join(timeout=1)
        if not reader.is_alive():
            process.stdout.close()


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


class MediaProgress:
    def __init__(self, update):
        self.update = update

    def emit(self, stage, phase, percent=None, **values):
        self.update(stage, percent, {"phase": phase, "percent": percent, "updated_at": time.time(), **values})

    def download(self, line):
        if line.startswith(POSTPROCESS_PREFIX):
            self.emit("合併影音與整理檔案", "merge")
            return True
        if not line.startswith(DOWNLOAD_PREFIX):
            return False
        try:
            raw, info = line[len(DOWNLOAD_PREFIX):].split("\t", 1)
            data, info = json.loads(raw), json.loads(info)
            if not isinstance(data, dict) or not isinstance(info, dict):
                return True
        except (ValueError, TypeError):
            return True
        downloaded = number(data.get("downloaded_bytes"))
        total = number(data.get("total_bytes")) or number(data.get("total_bytes_estimate"))
        percent = min(100, round(downloaded / total * 100, 1)) if downloaded is not None and total else None
        stream = "audio" if info.get("vcodec") == "none" else "video" if info.get("vcodec") else "media"
        label = {"audio": "音訊", "video": "影像", "media": "影片"}[stream]
        finished = data.get("status") == "finished"
        self.emit(f"{label}下載完成" if finished else f"下載 YouTube {label}", "download", 100 if finished else percent,
                  stream=stream, downloaded_bytes=downloaded, total_bytes=total,
                  total_is_estimate=not bool(number(data.get("total_bytes"))) and bool(total),
                  speed_bps=None if finished else number(data.get("speed")),
                  eta_seconds=None if finished else number(data.get("eta")))
        return True

    def ffmpeg(self, stage, phase, duration):
        values = {}

        def line_received(line):
            key, sep, value = line.partition("=")
            if not sep or key not in {"frame", "fps", "stream_0_0_q", "bitrate", "total_size", "out_time_us",
                                      "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress"}:
                return False
            values[key] = value
            if key == "progress":
                try:
                    seconds = max(0, float(values.get("out_time_us", "0")) / 1_000_000)
                    percent = min(100, round(seconds / duration * 100, 1))
                    if not math.isfinite(percent):
                        return True
                except (ValueError, ZeroDivisionError):
                    return True
                try:
                    speed = number(float(values.get("speed", "").rstrip("x")))
                except ValueError:
                    speed = None
                done = value == "end"
                self.emit(stage, phase, 100 if done else percent,
                          processed_seconds=round(min(seconds, duration), 1), total_seconds=round(duration, 1),
                          speed_ratio=None if done else speed,
                          eta_seconds=None if done or not speed else round(max(0, duration - seconds) / speed, 1))
            return True

        return line_received
