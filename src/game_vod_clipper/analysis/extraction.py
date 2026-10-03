"""Extract bounded frame packets and assemble timestamped review images."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ..process import resolve_tool_command
from .sampling import PACKET_SIZE


def extract_packet(
    source: Path, work: Path, request: tuple[float, float, float],
    *, on_frame: Callable[[int, int], None] | None = None,
    timeout: float = 120,
) -> tuple[list[Path], dict]:
    start, end, every = request
    if not all(math.isfinite(x) for x in request) or start < 0 or end < start or every <= 0:
        raise ValueError("Invalid sampling request")
    count = math.floor((end - start) / every + 1e-6) + 1
    if count > PACKET_SIZE:
        raise ValueError("抽樣封包超出畫面上限。")
    work.mkdir(parents=True, exist_ok=True)
    # A repeated invocation must never mistake old output for a successful seek.
    for old in work.glob("frame-*.jpg"):
        old.unlink()
    command = resolve_tool_command("ffmpeg")
    deadline = time.monotonic() + timeout
    frames: list[Path] = []

    def run(at: float, output: Path, filters: str, amount: int, duration: float | None = None):
        remaining = deadline - time.monotonic()
        detail = f"抽樣畫面擷取逾時（已完成 {len(frames)}/{count} 張），尚未進入本輪 AI 判讀。請稍後重試或縮小搜尋範圍。"
        if remaining <= 0:
            raise RuntimeError(detail)
        args = command + ["-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-threads", "2", "-ss", str(at), "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-filter_threads", "1"]
        if duration is not None:
            args += ["-t", str(duration)]
        args += ["-vf", filters, "-frames:v", str(amount), "-threads", "2", str(output)]
        try:
            completed = subprocess.run(args, capture_output=True, text=True,
                                       timeout=min(30, remaining) if amount == 1 else remaining,
                                       check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(detail) from None
        if completed.returncode:
            (work / "extraction-error.log").write_text(completed.stderr or "", encoding="utf-8")
            raise RuntimeError("無法擷取影片畫面，請確認來源可讀取；詳細原因已記錄於任務資料夾。")

    if every >= 5:
        # Input seeking decodes only from the preceding seek point to each target,
        # instead of decoding the entire intervening multi-minute interval.
        for i in range(count):
            frame = work / f"frame-{i + 1:03d}.jpg"
            run(start + i * every, frame, "scale=1920:-2", 1)
            if not frame.is_file() or not frame.stat().st_size:
                raise ValueError(f"來源在 {start + i * every:.2f} 秒沒有可供分析的畫面。")
            frames.append(frame)
            if on_frame:
                on_frame(len(frames), count)
    else:
        # Dense, short windows are cheaper to decode in one bounded pass.
        run(start, work / "frame-%03d.jpg",
            f"fps=1/{every}:start_time=0:round=up,scale=1920:-2", count, end - start + every)
        frames = sorted(work.glob("frame-*.jpg"))
        if len(frames) != count or any(not frame.stat().st_size for frame in frames):
            raise ValueError("抽樣畫面不完整，未送交 AI 判讀；請縮小範圍或確認來源。")
        if on_frame:
            on_frame(len(frames), count)
    manifest = {
        "start": start,
        "end": end,
        "every": every,
        "timestamps": [round(start + i * every, 4) for i in range(len(frames))],
    }
    # Exact byte duplicates carry no new visual information (e.g. a paused menu).
    # Never use perceptual similarity: small HUD/reward changes must remain visible.
    unique, first_by_hash, repeats = [], {}, {}
    for index, frame in enumerate(frames):
        digest = hashlib.sha256(frame.read_bytes()).digest()
        if digest in first_by_hash:
            representative = first_by_hash[digest]
            repeats.setdefault(str(manifest["timestamps"][representative]), []).append(manifest["timestamps"][index])
        else:
            first_by_hash[digest] = index
            unique.append((index, frame))
    if repeats:
        manifest["identical_frames"] = repeats
    manifest["unique_frames"] = len(unique)
    images = []
    # Every distinct frame remains visible in order. High-resolution anchors preserve small
    # HUD/reward text that overview grids alone can make unreadable.
    columns, cells, width, height = (
        (1, 1, 1920, 1108) if len(unique) <= 6 else (3, 12, 480, 300)
    )
    for offset in range(0, len(unique), cells):
        batch = unique[offset : offset + cells]
        sheet = Image.new(
            "RGB",
            (width * columns, height * math.ceil(len(batch) / columns)),
            "#111811",
        )
        draw = ImageDraw.Draw(sheet)
        for i, (index, frame) in enumerate(batch):
            x, y = (i % columns) * width, (i // columns) * height
            with Image.open(frame) as picture:
                tile = ImageOps.contain(picture, (width, height - 28))
                sheet.paste(tile, (x + (width - tile.width) // 2, y + 28))
            draw.text(
                (x + 8, y + 6),
                f"FRAME {index + 1:03d} | SOURCE {manifest['timestamps'][index]:.4f} sec",
                fill="white",
                font_size=17,
            )
        path = work / f"sheet-{offset // cells:02d}.jpg"
        sheet.save(path, quality=92)
        images.append(path)
    if len(unique) > 6:
        for index in sorted({unique[0][0], unique[len(unique) // 2][0], unique[-1][0]}):
            with Image.open(frames[index]) as frame:
                detail = Image.new("RGB", (frame.width, frame.height + 36), "#111811")
                detail.paste(frame, (0, 36))
                ImageDraw.Draw(detail).text((8, 6),
                    f"DETAIL | SOURCE {manifest['timestamps'][index]:.4f} sec | same frame, clearer HUD",
                    fill="white", font_size=22)
                path = work / f"detail-{index + 1:03d}.jpg"
                detail.save(path, quality=95)
                images.append(path)
    (work / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return images, manifest
