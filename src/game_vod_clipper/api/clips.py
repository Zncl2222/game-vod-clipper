"""Clips HTTP routes and request operations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ..jobs.scheduler import ACTIVE
from ..storage.locations import LocationError, export_path, media_path
from .context import Workspace, WorkspaceDep
from .schemas import Draft, ExportRequest

router = APIRouter()


def clip_for_edit(ctx: Workspace, project_id: str, job_id: str):
    job = ctx.get("jobs", job_id)
    if (job["project_id"] != project_id or job["kind"] != "export"
            or job["status"] != "succeeded" or not job.get("draft")):
        raise HTTPException(404, "找不到這個專案的已完成片段。")
    return job


def editable_clip_draft(job: dict):
    # Editing never changes the immutable range used by an existing MP4.
    return job.get("edit_draft") or {**job["draft"], "revision": 0, "reviewed": False}


def validate_draft(project: dict, body: Draft):
    if not project["ready"]:
        raise HTTPException(409, "原片尚未就緒。")
    if (
        not body.start < body.victory
        or body.victory + body.postroll > project["duration"]
    ):
        raise HTTPException(
            422, "開始必須早於勝利，且勝利後須保留完整 5–10 秒，不可超出原片。"
        )


@router.put("/api/projects/{project_id}/clips/{job_id}/draft")
async def save_clip_draft(ctx: WorkspaceDep, project_id: str, job_id: str, body: Draft):
    project = ctx.get("projects", project_id)
    job = clip_for_edit(ctx, project_id, job_id)
    validate_draft(project, body)
    if body.revision != editable_clip_draft(job)["revision"]:
        raise HTTPException(409, "片段草稿已更新，請重新載入專案。")
    draft = body.model_dump(exclude_none=True) | {"revision": body.revision + 1}
    ctx.store.patch("jobs", job_id, edit_draft=draft)
    return draft


def remove_clip(ctx: Workspace, project_id: str, job: dict):
    """Delete one finished export; callers hold the upload lock."""
    job_id = job["id"]
    if any(item["export_id"] == job_id and (item["id"] in ctx.youtube.uploads.tasks
           or item["status"] in {"queued", "uploading", "processing", "adding_to_playlist"})
           for item in ctx.youtube.uploads.all().values()):
        raise HTTPException(409, "這個成品正在上傳 YouTube，請先暫停上傳再刪除。")
    # Delete only an MP4 and receipt with the worker's layout, never through symlinks.
    try:
        output = export_path(ctx.root, job)
    except LocationError:
        raise HTTPException(409, "成品檔案位置異常，未刪除資料。") from None
    files = (output, output.with_suffix(".json"))
    if any(path.is_symlink() or path.resolve() != path for path in files):
        raise HTTPException(409, "成品檔案位置異常，未刪除資料。")
    if any(p.get("source") and media_path(ctx.root, p["source"]).resolve() in files for p in ctx.store.all("projects")):
        raise HTTPException(409, "這個成品正被用作專案原片，請先移除使用它的專案。")
    size = output.stat().st_size if output.is_file() else 0
    try:
        for path in files:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(500, "成品檔案刪除未完成，請重試。") from error
    ctx.store.delete_clip(project_id, job_id)
    return size


@router.delete("/api/projects/{project_id}/clips/{job_id}")
async def delete_clip(ctx: WorkspaceDep, project_id: str, job_id: str):
    # Serialize with upload startup, which hashes the file before queuing it.
    async with ctx.youtube.uploads.lock:
        ctx.get("projects", project_id)
        remove_clip(ctx, project_id, clip_for_edit(ctx, project_id, job_id))
        return {"deleted": True, "id": job_id}


@router.post("/api/projects/{project_id}/clips/remove-published")
async def remove_published_clips(ctx: WorkspaceDep, project_id: str):
    async with ctx.youtube.uploads.lock:
        ctx.get("projects", project_id)
        uploads = ctx.clip_uploads()
        deleted, freed = [], 0
        for job in ctx.store.all("jobs"):
            if (job["project_id"] == project_id and job["kind"] == "export" and job["status"] == "succeeded"
                    and job.get("draft") and uploads.get(job["id"], {}).get("published")):
                freed += remove_clip(ctx, project_id, job)
                deleted.append(job["id"])
        return {"deleted": deleted, "bytes": freed}


@router.put("/api/projects/{project_id}/draft")
async def save_draft(ctx: WorkspaceDep, project_id: str, body: Draft):
    project = ctx.get("projects", project_id)
    validate_draft(project, body)
    if body.revision != project["draft"]["revision"]:
        raise HTTPException(409, "草稿已更新，請重新載入專案。")
    draft = body.model_dump(exclude_none=True) | {"revision": body.revision + 1}
    ctx.store.patch("projects", project_id, draft=draft)
    return draft


@router.post("/api/projects/{project_id}/exports", status_code=202)
async def export(ctx: WorkspaceDep, project_id: str, body: ExportRequest):
    project = ctx.get("projects", project_id)
    draft = (editable_clip_draft(clip_for_edit(ctx, project_id, body.source_job_id))
             if body.source_job_id else project.get("draft"))
    if not draft or draft["revision"] != body.revision:
        raise HTTPException(409, "請先儲存目前草稿。")
    try:
        validate_draft(project, Draft.model_validate(draft))
    except ValidationError:
        raise HTTPException(422, "剪輯時間範圍無效，請修正後再匯出。") from None
    for job in ctx.store.all("jobs"):
        if (
            job["project_id"] == project_id
            and job["kind"] == "export"
            and job.get("source_job_id") == body.source_job_id
            and job.get("draft", {}).get("revision") == body.revision
            # Jobs from before quality presets were encoded with today's "fast" settings.
            and job.get("export_quality", "fast") == body.quality
            and job["status"] in ACTIVE | {"succeeded"}
        ):
            return ctx.public_job(job)
    if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in ctx.store.all("jobs")) >= 8:
        raise HTTPException(429, "任務佇列已滿。")
    return ctx.jobs.submit(project_id, "export", draft, source_job_id=body.source_job_id, export_quality=body.quality)
