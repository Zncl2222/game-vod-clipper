"""Connect YouTube callbacks to the shared import and analysis operations."""

from __future__ import annotations

from ..youtube.account import YouTubeError
from ..youtube.downloader import DownloadQuality
from .analysis import enqueue_analysis
from .context import Workspace
from .projects import import_project
from .schemas import AnalysisRequest, ImportRequest


async def youtube_import(ctx: Workspace, video_id: str, download_quality: DownloadQuality = "best"):
    return await import_project(ctx, ImportRequest(kind="youtube", source=f"https://www.youtube.com/watch?v={video_id}",
                                              download_quality=download_quality))


async def youtube_check_model(ctx: Workspace, model: str):
    if not model:
        raise YouTubeError("請選擇 AI 模型，或取消匯入後自動找片段。", 422)
    status = await ctx.codex.status()
    if not status["available"]:
        raise YouTubeError("請先連接 AI 帳號，或取消匯入後自動找片段。", 422)
    selected = next((m for m in await ctx.codex.models() if m["id"] == model), None)
    if not selected or "image" not in selected.get("input_modalities", []):
        raise YouTubeError("請選擇支援畫面判讀的 AI 模型。", 422)
    return selected


async def youtube_analyze(ctx: Workspace, project: dict, model: str, request_id: str):
    selected = await youtube_check_model(ctx, model)
    # This entry point has no effort picker. Use the visual-review policy,
    # rather than silently inheriting the model's general chat default.
    supported = set(selected.get("supported_efforts", [])) | {selected.get("effort")}
    effort = next((value for value in ("xhigh", "high") if value in supported), selected.get("effort"))
    return await enqueue_analysis(ctx, project["id"], AnalysisRequest(
        start=0, end=project["duration"], model=model, effort=effort), request_id)
