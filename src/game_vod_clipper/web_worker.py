"""One job per process. The web service owns the process group and cancellation."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

from .media import DEFAULT_EXPORT_QUALITY, EXPORT_QUALITY, clip_video
from .media_progress import DOWNLOAD_TEMPLATE, POSTPROCESS_TEMPLATE, MediaProgress, streamed_command
from .process import resolve_tool_command
from .web_store import Store
from .youtube import quality_format, youtube_command

SOURCE_PREFIX = "__BOSSCUT_SOURCE__"

def command(args: list[str], *, on_line=None) -> str:
    if on_line is not None:
        return streamed_command(args, on_line)
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=6 * 3600, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1800:] or "Media command failed")
    return result.stdout


def probe(path: Path) -> dict:
    data = json.loads(
        command(
            resolve_tool_command("ffprobe")
            + ["-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
        )
    )
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("來源沒有影像軌。")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or not 10 <= duration <= 21600:
        raise ValueError("POC 支援 10 秒至 6 小時的影片。")
    return {"duration": duration, "width": video["width"], "height": video["height"]}


def run(root: Path, job_id: str):
    store = Store(root)
    job = store.get("jobs", job_id)
    project = store.get("projects", job["project_id"])
    work = root / "runs" / "web" / project["id"]
    work.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, percent: float | None, detail=None):
        store.patch("jobs", job_id, stage=stage, progress=percent or 0, media_progress=detail)

    reporter = MediaProgress(progress)

    if job["kind"] == "prepare":
        progress("檢查來源", 5)
        source = root / project["source"] if project.get("source") else None
        if source is None:
            reporter.emit("正在連接 YouTube，取得影片資訊", "download")
            folder = root / "downloads" / "web" / project["id"]
            folder.mkdir(parents=True, exist_ok=True)
            output = command(
                youtube_command()
                + [
                    "--ignore-config",
                    "--no-playlist",
                    "--newline",
                    "--progress",
                    "--progress-delta", "1",
                    "--progress-template", DOWNLOAD_TEMPLATE,
                    "--progress-template", POSTPROCESS_TEMPLATE,
                    "--socket-timeout",
                    "30",
                    "--retries",
                    "3",
                    "--max-filesize",
                    "40G",
                    "--match-filter",
                    "duration <= 21600 & !is_live",
                    "-f",
                    quality_format(project.get("download_quality", "best")),
                    "-S",
                    "res,fps",
                    "--merge-output-format",
                    "mkv",
                    "--print",
                    f"after_move:{SOURCE_PREFIX}%(filepath)s",
                    "-o",
                    str(folder / "source.%(ext)s"),
                    project["url"],
                ], on_line=reporter.download,
            )
            paths = [Path(line[len(SOURCE_PREFIX):]) for line in output.splitlines() if line.startswith(SOURCE_PREFIX)]
            source = next(
                (
                    p
                    for p in reversed(paths)
                    if p.is_file() and p.resolve().is_relative_to(folder.resolve())
                ),
                None,
            )
            if source is None:
                raise ValueError(
                    "無法取得影片，請確認網址可存取、影片已結束且小於 6 小時／40 GB，或改用本機原始錄影。"
                )
            store.patch("projects", project["id"], source=str(source.relative_to(root)))
        metadata = probe(source)
        reporter.emit("製作 720p 預覽影片", "preview", 0)
        preview = work / "preview.mp4"
        command(
            resolve_tool_command("ffmpeg")
            + [
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostats", "-progress", "pipe:1", "-stats_period", "1",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-sn",
                "-dn",
                "-vf",
                "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(preview),
            ], on_line=reporter.ffmpeg("製作 720p 預覽影片", "preview", metadata["duration"]),
        )
        reporter.emit("建立時間軸縮圖", "thumbnails")
        interval = metadata["duration"] / 24
        # One decode pass, bounded output; no fixed contact sheet that can hide frames.
        command(
            resolve_tool_command("ffmpeg")
            + [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(preview),
                "-vf",
                f"fps=1/{interval}:start_time=0:round=up,scale=240:-2",
                "-frames:v",
                "24",
                "-threads",
                "1",
                str(work / "thumb-%03d.jpg"),
            ]
        )
        thumbs = [
            {"file": p.name, "time": round(i * interval, 3)}
            for i, p in enumerate(sorted(work.glob("thumb-*.jpg")))
        ]
        preview_meta = probe(preview)
        if abs(preview_meta["duration"] - metadata["duration"]) > 0.25:
            raise ValueError("預覽與來源長度不一致，請先檢查來源時間戳。")
        store.patch(
            "projects",
            project["id"],
            **metadata,
            ready=True,
            thumbnails=thumbs,
            draft={
                "start": 0,
                "victory": round(max(1, metadata["duration"] - 8), 3),
                "postroll": 8,
                "reviewed": False,
                "revision": 0,
                "origin": "manual",
            },
        )
    elif job["kind"] == "analyze":
        from .codex_analysis import run_analysis

        run_analysis(store, job, project)
    else:
        draft = job["draft"]
        quality = job.get("export_quality") or DEFAULT_EXPORT_QUALITY
        expected = draft["victory"] + draft["postroll"] - draft["start"]
        reporter.emit("重新編碼剪輯", "export", 0, processed_seconds=0, total_seconds=round(expected, 1))
        output = root / "clips" / "web" / project["id"] / f"{job_id}.mp4"
        clip_video(
            root / project["source"],
            output,
            start=str(draft["start"]),
            end=str(draft["victory"]),
            postroll=draft["postroll"],
            quality=quality,
            on_progress=reporter.ffmpeg("重新編碼剪輯", "export", expected),
        )
        reporter.emit("驗證輸出長度", "verify", 99)
        # Export may be shorter than the minimum input length accepted by probe().
        result = json.loads(
            command(
                resolve_tool_command("ffprobe")
                + [
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(output),
                ]
            )
        )
        if (
            not any(s["codec_type"] == "video" for s in result["streams"])
            or abs(float(result["format"]["duration"]) - expected) > 0.3
        ):
            raise ValueError("輸出長度驗證失敗。")
        manifest = {
            "project_id": project["id"],
            "source": project["source"],
            "draft": draft,
            "output": str(output.relative_to(root)),
            "export_quality": quality,
            "encoder": {"video": "libx264", "preset": EXPORT_QUALITY[quality][0], "crf": EXPORT_QUALITY[quality][1],
                        "audio": "aac", "audio_bitrate": "192k"},
            "validation": ("human_reviewed; " if draft.get("reviewed") else "")
                          + "duration_checked; no_automated_visual_validation",
        }
        output.with_suffix(".json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        store.patch("jobs", job_id, output=str(output.relative_to(root)))
    progress("完成", 100)


if __name__ == "__main__":
    root, job_id = Path(sys.argv[1]).resolve(), sys.argv[2]
    try:
        run(root, job_id)
    except Exception as exc:
        Store(root).patch("jobs", job_id, error=str(exc)[-2000:])
        raise
