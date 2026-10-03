"""Projects HTTP routes and request operations."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..analysis.candidates import project_candidates
from ..jobs.scheduler import ACTIVE
from ..process import ToolMissingError
from ..storage.locations import record_path
from ..youtube.downloader import youtube_command
from .context import WorkspaceDep, public_project
from .schemas import (
    CandidateEditRequest,
    CandidateReviewRequest,
    ImportRequest,
    ProjectUpdate,
)
from .sources import EXTENSIONS, local_source, youtube_url

router = APIRouter()


@router.get("/api/sources")
async def sources(ctx: WorkspaceDep):
    result, seen = [], set()
    for kind in ("sources", "exports"):
        for path in sorted(ctx.locations.folder(kind).rglob("*")):
            if path.suffix.lower() in EXTENSIONS and path.is_file():
                try:
                    resolved = local_source(ctx.root, str(path))
                except ValueError:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                result.append(
                    {
                        "path": record_path(ctx.root, resolved),
                        "name": path.stem,
                        "size": path.stat().st_size,
                    }
                )
            if len(result) >= 200:
                return result
    return result


@router.post("/api/projects", status_code=202)
async def import_project(ctx: WorkspaceDep, body: ImportRequest):
    try:
        source = (
            record_path(ctx.root, local_source(ctx.root, body.source))
            if body.kind == "local"
            else None
        )
        url = youtube_url(body.source) if body.kind == "youtube" else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.kind == "youtube":
        # Check the downloader up front so the import itself reports a
        # missing tool, instead of leaving a project that never starts.
        try:
            await asyncio.to_thread(youtube_command)
        except ToolMissingError as exc:
            raise HTTPException(422, str(exc)) from exc
    if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in ctx.store.all("jobs")) >= 8:
        raise HTTPException(429, "任務佇列已滿，請稍後再試。")
    project_id = uuid4().hex
    project = {
        "id": project_id,
        "title": Path(source).stem if source else "YouTube · " + url.split("v=")[1],
        "source": source,
        "url": url,
        "work": record_path(ctx.root, ctx.locations.project_folder("cache", project_id)),
        "ready": False,
        "created": time.time(),
        "thumbnails": [],
        **({"download_quality": body.download_quality} if body.kind == "youtube" else {}),
    }
    ctx.store.put("projects", project)
    return {
        "project": public_project(project),
        "job": ctx.jobs.submit(project["id"], "prepare"),
    }


@router.get("/api/projects/{project_id}")
async def project_details(ctx: WorkspaceDep, project_id: str):
    project = ctx.get("projects", project_id)
    return public_project(project) | {
        "source": project.get("source"), "url": project.get("url"),
    }


@router.patch("/api/projects/{project_id}")
async def rename_project(ctx: WorkspaceDep, project_id: str, body: ProjectUpdate):
    ctx.get("projects", project_id)
    if any(ord(char) < 32 for char in body.title):
        raise HTTPException(422, "專案名稱不能包含換行或控制字元。")
    return public_project(ctx.store.patch("projects", project_id, title=body.title))


@router.delete("/api/projects/{project_id}")
async def delete_project(ctx: WorkspaceDep, project_id: str):
    # Serialize with upload start/resume/restart, including their hash await.
    # Once deletion starts, no new uploader may slip past the cancellation.
    async with ctx.youtube.lock, ctx.analysis_lock:
        ctx.get("projects", project_id)
        ctx.deleting_projects.add(project_id)
        try:
            for upload in ctx.youtube.uploads.all().values():
                if upload["project_id"] == project_id:
                    await ctx.youtube.uploads.pause(upload["id"])
            related = [job for job in ctx.store.all("jobs") if job["project_id"] == project_id]
            tasks = [ctx.jobs.tasks[job["id"]] for job in related if job["id"] in ctx.jobs.tasks]
            for task in tasks:
                task.cancel()
            # Workers must finish cancellation before their database rows go.
            await asyncio.gather(*tasks, return_exceptions=True)
            ctx.store.delete_project(project_id)
        finally:
            ctx.deleting_projects.discard(project_id)
    return {"id": project_id, "deleted": True}


@router.put("/api/projects/{project_id}/candidate-review")
async def review_candidate(ctx: WorkspaceDep, project_id: str, body: CandidateReviewRequest):
    project = ctx.get("projects", project_id)
    if body.analysis_generation != project.get("analysis_generation", 0):
        raise HTTPException(409, "影片分析已重置，請重新選取片段。")
    if not any(c["id"] == body.candidate_id for c in project_candidates(project, ctx.store.all("jobs"))):
        raise HTTPException(404, "找不到這個影片的候選片段。")
    try:
        ctx.store.set_candidate_review(project_id, body.candidate_id, body.review, body.analysis_generation)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return {"candidate_id": body.candidate_id, "review": body.review}


@router.put("/api/projects/{project_id}/candidate-edit")
async def edit_candidate(ctx: WorkspaceDep, project_id: str, body: CandidateEditRequest):
    project = ctx.get("projects", project_id)
    if not project.get("ready"):
        raise HTTPException(409, "原片尚未就緒。")
    if not body.start < body.victory or body.victory + body.postroll > project["duration"]:
        raise HTTPException(422, "開始必須早於勝利，且勝利後須保留完整 5–10 秒，不可超出原片。")
    try:
        return ctx.store.set_candidate_edit(project_id, body.candidate_id, body.model_dump())
    except KeyError:
        raise HTTPException(404, "找不到這個影片的候選片段。") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/api/projects/{project_id}/review-packet")
async def review_packet(ctx: WorkspaceDep, project_id: str):
    project = ctx.get("projects", project_id)
    if not project["ready"]:
        raise HTTPException(409, "原片尚未就緒。")
    return {
        "schema_version": 1,
        "project_id": project_id,
        "source": project["source"],
        "duration": project["duration"],
        "instruction": "Follow skills/game-vod-boss-clipper/SKILL.md. Return start, victory, postroll as seconds. Visual review is required; timeline thumbnails alone are insufficient.",
        "draft": project["draft"],
    }
