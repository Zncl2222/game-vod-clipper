"""Media HTTP routes and request operations."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from ..storage.locations import media_path, project_work
from .context import WorkspaceDep
from .server import PREVIEW_RANGE_LIMIT, LocalFileResponse
from .sources import EXTENSIONS

router = APIRouter()


@router.get("/api/projects/{project_id}/media/{filename}")
async def media(ctx: WorkspaceDep, project_id: str, filename: str):
    project = ctx.get("projects", project_id)
    if filename == "source":
        # A fixed endpoint serves only the registered source, never a path
        # supplied by the browser. Do not re-check today's storage folders:
        # existing projects keep their original locations when settings change.
        if not project.get("ready") or not project.get("source"):
            raise HTTPException(404, "原片尚未就緒。")
        path = media_path(ctx.root, project["source"])
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXTENSIONS:
            raise HTTPException(404, "找不到原片，請確認檔案仍在原來的位置。")
        mime = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
                ".mov": "video/quicktime", ".mkv": "video/x-matroska"}[path.suffix.lower()]
        return LocalFileResponse(path, media_type=mime, range_limit=PREVIEW_RANGE_LIMIT)
    allowed = {"preview.mp4"} | {t["file"] for t in project["thumbnails"]}
    if not project["ready"] or filename not in allowed:
        raise HTTPException(404, "找不到預覽。")
    path = project_work(ctx.root, project) / filename
    if not path.is_file():
        raise HTTPException(404, "找不到預覽。")
    return LocalFileResponse(path, range_limit=PREVIEW_RANGE_LIMIT)


@router.get("/api/jobs/{job_id}/download")
async def download(ctx: WorkspaceDep, job_id: str):
    job = ctx.get("jobs", job_id)
    if job["status"] != "succeeded" or job["kind"] != "export":
        raise HTTPException(404, "尚無可下載的剪輯。")
    title = (job.get("draft", {}).get("title") or "").strip()
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", title).strip(" .")
    return LocalFileResponse(
        media_path(ctx.root, job["output"]),
        filename=f"{filename or 'boss-fight-' + job_id[:8]}.mp4",
        media_type="video/mp4",
    )
