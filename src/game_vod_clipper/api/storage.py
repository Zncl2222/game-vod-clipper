"""Storage HTTP routes and request operations."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..storage.inventory import video_inventory, video_storage
from ..storage.locations import LocationError, media_path
from .clips import remove_clip
from .context import Workspace, WorkspaceDep
from .schemas import DeleteStoredVideo, DeleteStoredVideos, LocationUpdate

router = APIRouter()


@router.get("/api/storage")
def storage(ctx: WorkspaceDep):
    return video_storage(ctx.root, ctx.store)


@router.get("/api/storage/files")
def stored_videos(ctx: WorkspaceDep):
    return video_inventory(ctx.store, ctx.youtube.uploads.all().values(), ctx.youtube.uploads.tasks)


def remove_stored_video(ctx: Workspace, item):
    if item is None:
        raise HTTPException(409, "檔案已變更或已刪除，請重新整理清單後確認。")
    if item["blocked"]:
        raise HTTPException(409, item["blocked"])
    if item["job_id"]:
        freed = remove_clip(ctx, item["project_id"], ctx.get("jobs", item["job_id"]))
    else:
        try:
            media_path(ctx.root, item["path"]).unlink()
        except OSError:
            raise HTTPException(409, "檔案無法刪除，請確認權限並重新整理清單。") from None
        freed = item["bytes"]
    return {"id": item["id"], "bytes": freed, "job_id": item["job_id"], "project_id": item["project_id"]}


@router.post("/api/storage/delete")
async def delete_stored_video(ctx: WorkspaceDep, body: DeleteStoredVideo):
    # No await between revalidation and unlink: new imports/exports cannot
    # start using this file while deletion is in progress.
    async with ctx.youtube.lock, ctx.youtube.uploads.lock, ctx.analysis_lock:
        inventory = video_inventory(ctx.store, ctx.youtube.uploads.all().values(), ctx.youtube.uploads.tasks)
        item = next((item for item in inventory["items"] if item["id"] == body.id), None)
        result = remove_stored_video(ctx, item)
        return {"deleted": True, **{key: value for key, value in result.items() if key != "id"}}


@router.post("/api/storage/delete-batch")
async def delete_stored_videos(ctx: WorkspaceDep, body: DeleteStoredVideos):
    # Scan once for the whole batch. Hold the same locks and do not await
    # between validation and deletion, just like the single-file endpoint.
    async with ctx.youtube.lock, ctx.youtube.uploads.lock, ctx.analysis_lock:
        inventory = video_inventory(ctx.store, ctx.youtube.uploads.all().values(), ctx.youtube.uploads.tasks)
        by_id = {item["id"]: item for item in inventory["items"]}
        deleted, failed = [], []
        for key in body.ids:
            try:
                deleted.append(remove_stored_video(ctx, by_id.get(key)))
            except HTTPException as error:
                # Filesystem changes cannot be rolled back: report each
                # outcome explicitly instead of claiming an atomic batch.
                failed.append({"id": key, "detail": str(error.detail)})
        return {"deleted": deleted, "failed": failed, "bytes": sum(item["bytes"] for item in deleted)}


@router.get("/api/locations")
async def read_locations(ctx: WorkspaceDep):
    return ctx.locations.status()


@router.put("/api/locations")
async def update_locations(ctx: WorkspaceDep, body: LocationUpdate):
    changes = {kind: getattr(body, kind) for kind in body.model_fields_set}
    try:
        return await asyncio.to_thread(ctx.locations.update, changes)
    except LocationError as error:
        raise HTTPException(422, str(error)) from None
