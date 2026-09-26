"""One job per process. The web service owns the process group and cancellation."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from .media import DEFAULT_EXPORT_QUALITY, EXPORT_QUALITY, clip_video
from .locations import Locations, media_path, project_work, record_path
from .media_progress import DOWNLOAD_TEMPLATE, POSTPROCESS_TEMPLATE, MediaProgress, streamed_command
from .process import resolve_tool_command
from .web_store import Store
from .youtube import BROWSER_MERGE_FORMATS, quality_format, youtube_command

SOURCE_PREFIX = "__BOSSCUT_SOURCE__"
TITLE_PREFIX = "__BOSSCUT_TITLE__"

def command(args: list[str], *, on_line=None, timeout=6 * 3600) -> str:
    if on_line is not None:
        return streamed_command(args, on_line)
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
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
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    try:
        frame_rate = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0"))
    except (ValueError, ZeroDivisionError):
        frame_rate = 0
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "frame_rate": frame_rate if math.isfinite(frame_rate) and frame_rate > 0 else None,
            "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name")}


def make_thumbnails(store: Store, project: dict, source: Path, work: Path, duration: float, reporter):
    """Seek to individual frames; never decode the entire VOD for a thumbnail strip.

    The source is already ready for playback/editing. Publish each completed image
    and treat thumbnail failures as nonfatal, without resetting the user's draft.
    """
    thumbs = []
    for index in range(24):
        at = index * duration / 24
        target = work / f"thumb-{index + 1:03d}.jpg"
        try:
            command(resolve_tool_command("ffmpeg") + [
                "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{at:.6f}", "-threads", "2", "-i", str(source),
                "-map", "0:v:0", "-an", "-sn", "-dn",
                "-frames:v", "1", "-vf", "scale=240:-2", "-threads", "1", str(target),
            ], timeout=30)
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError("未能擷取縮圖。")
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
            store.patch("projects", project["id"], thumbnail_warning="部分時間軸縮圖無法建立，仍可播放、分析與匯出原片。")
            return
        thumbs.append({"file": target.name, "time": round(at, 3)})
        store.patch("projects", project["id"], thumbnails=thumbs)
        reporter.emit("原片已就緒，背景建立時間軸縮圖", "thumbnails", (index + 1) / 24 * 100)


def run(root: Path, job_id: str):
    store = Store(root)
    job = store.get("jobs", job_id)
    project = store.get("projects", job["project_id"])
    locations = Locations(root)
    work = project_work(root, project)
    work.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, percent: float | None, detail=None):
        store.patch("jobs", job_id, stage=stage, progress=percent or 0, media_progress=detail)

    reporter = MediaProgress(progress)

    if job["kind"] == "prepare":
        progress("檢查來源", 5)
        source = media_path(root, project["source"]) if project.get("source") else None
        if source is None:
            reporter.emit("正在連接 YouTube，取得影片資訊", "download")
            folder = locations.project_folder("sources", project["id"])
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
                    BROWSER_MERGE_FORMATS,
                    "--print",
                    f"after_move:{SOURCE_PREFIX}%(filepath)s",
                    "--print",
                    f"after_move:{TITLE_PREFIX}%(title)j",
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
            title_metadata = {}
            for line in output.splitlines():
                if line.startswith(TITLE_PREFIX):
                    try:
                        title = json.loads(line[len(TITLE_PREFIX):])
                        if isinstance(title, str) and title.strip():
                            title_metadata["youtube_title"] = title[:500]
                    except ValueError:
                        pass
            # Keep the original YouTube title in history without overwriting a
            # project name the user may have changed while downloading.
            store.patch("projects", project["id"], source=record_path(root, source), **title_metadata)
        metadata = probe(source)
        store.patch(
            "projects",
            project["id"],
            **metadata,
            ready=True,
            playback="source",
            source_container=source.suffix.lower().lstrip("."),
            thumbnails=[],
            thumbnail_warning=None,
            draft=project.get("draft") or {
                "start": 0,
                "victory": round(max(1, metadata["duration"] - 8), 3),
                "postroll": 8,
                "reviewed": False,
                "revision": 0,
                "origin": "manual",
            },
        )
        reporter.emit("原片已就緒，背景建立時間軸縮圖", "thumbnails", 0)
        make_thumbnails(store, project, source, work, metadata["duration"], reporter)
    elif job["kind"] == "analyze":
        from .codex_analysis import run_analysis

        run_analysis(store, job, project)
    else:
        draft = job["draft"]
        quality = job.get("export_quality") or DEFAULT_EXPORT_QUALITY
        expected = draft["victory"] + draft["postroll"] - draft["start"]
        reporter.emit("重新編碼剪輯", "export", 0, processed_seconds=0, total_seconds=round(expected, 1))
        output = locations.project_folder("exports", project["id"]) / f"{job_id}.mp4"
        clip_video(
            media_path(root, project["source"]),
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
            "output": record_path(root, output),
            "export_quality": quality,
            "encoder": {"video": "libx264", "preset": EXPORT_QUALITY[quality][0], "crf": EXPORT_QUALITY[quality][1],
                        "audio": "aac", "audio_bitrate": "192k"},
            "validation": ("human_reviewed; " if draft.get("reviewed") else "")
                          + "duration_checked; no_automated_visual_validation",
        }
        output.with_suffix(".json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        store.patch("jobs", job_id, output=record_path(root, output))
    progress("完成", 100)


if __name__ == "__main__":
    root, job_id = Path(sys.argv[1]).resolve(), sys.argv[2]
    try:
        run(root, job_id)
    except Exception as exc:
        Store(root).patch("jobs", job_id, error=str(exc)[-2000:])
        raise
