"""Analysis HTTP routes and request operations."""

from __future__ import annotations

import asyncio
import json
import shutil
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..analysis.candidates import project_candidates
from ..codex.chat import ChatRequest, chat, resolve_effort
from ..codex.connection import ConnectionError
from ..codex.usage import usage_summary
from ..jobs.scheduler import ACTIVE
from ..storage.locations import project_work
from .context import Workspace, WorkspaceDep, public_project
from .schemas import AnalysisRequest, CodexLoginRequest

router = APIRouter()


@router.get("/api/codex")
async def codex_status(ctx: WorkspaceDep):
    return await ctx.codex.status()


@router.get("/api/codex/usage")
async def codex_usage(ctx: WorkspaceDep, project_id: str | None = None):
    if project_id:
        ctx.get("projects", project_id)
    return usage_summary(ctx.store, project_id)


@router.get("/api/codex/rate-limits")
async def codex_rate_limits(ctx: WorkspaceDep):
    return await ctx.codex.rate_limits()


@router.post("/api/codex/login")
async def codex_login(ctx: WorkspaceDep, body: CodexLoginRequest):
    return await ctx.codex.begin_login(body.method)


@router.post("/api/codex/login/cancel")
async def codex_cancel_login(ctx: WorkspaceDep):
    return await ctx.codex.cancel_login()


@router.post("/api/codex/test")
async def codex_test(ctx: WorkspaceDep):
    return await ctx.codex.probe()


@router.get("/api/codex/models")
async def codex_models(ctx: WorkspaceDep):
    return {"models": await ctx.codex.models()}


async def enqueue_analysis(ctx: Workspace, project_id: str, body: AnalysisRequest, request_id: str, resume_job: dict | None = None, expected_generation: int | None = None):
    project = ctx.get("projects", project_id)
    generation = (expected_generation if expected_generation is not None else
                  body.analysis_generation if body.analysis_generation is not None else
                  project.get("analysis_generation", 0))
    if project.get("analysis_generation", 0) != generation:
        raise HTTPException(409, "影片分析已重置，請重新選取片段。")
    if not project["ready"]:
        raise HTTPException(409, "請先完成原片準備。")
    if not body.start < body.end <= project["duration"]:
        raise HTTPException(422, "分析範圍須位於原片內。")
    target = None
    if body.candidate_id:
        target = next((candidate for candidate in project_candidates(project, ctx.store.all("jobs"))
                       if candidate["id"] == body.candidate_id), None)
        if target is None:
            raise HTTPException(404, "找不到這個影片的候選片段。")
    status = await ctx.codex.status()
    if not status["available"]:
        raise ConnectionError(status["detail"])
    selected = next((m for m in await ctx.codex.models() if m["id"] == body.model), None)
    if not selected or "image" not in selected.get("input_modalities", []):
        raise ConnectionError("所選模型不支援畫面判讀，請在同一模型選單選擇支援影像的模型。")
    effort = resume_job["analysis"].get("effort") if resume_job else resolve_effort(selected, body.effort)
    effort_policy = resume_job["analysis"].get("effort_policy", body.effort_policy) if resume_job else body.effort_policy
    if "high" not in selected.get("supported_efforts", []) and selected.get("effort") != "high":
        effort_policy = "fixed"
    async with ctx.analysis_lock:
        if ctx.get("projects", project_id).get("analysis_generation", 0) != generation:
            raise HTTPException(409, "影片分析已重置，請重新搜尋。")
        if resume_job:
            saved_job = ctx.store.get("jobs", resume_job["id"])
            if not saved_job or saved_job.get("progress_reset"):
                raise HTTPException(409, "舊分析進度已重置，請重新搜尋。")
        current = ctx.store.all("jobs")
        duplicate = next((j for j in current if j["project_id"] == project_id and not j.get("progress_reset") and
                          (j.get("analysis") or {}).get("request_id") == request_id), None)
        if duplicate:
            return duplicate
        if any(j["project_id"] == project_id and j["kind"] == "analyze" and j["status"] in ACTIVE for j in current):
            raise HTTPException(409, "此影片已有搜尋任務，請先等待完成或取消。")
        if sum(j["status"] in ACTIVE and j["kind"] == "analyze" for j in current) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        # Resumes keep the references they started with.
        reference = (resume_job["analysis"].get("profile") if resume_job
                     else ctx.profiles.snapshot(ctx.profiles.resolve(ctx.get("projects", project_id))))
        submitted = ctx.jobs.submit(project_id, "analyze", analysis={**body.model_dump(exclude_none=True),
            **({"review_target": {key: target.get(key) for key in
                ("id", "start", "end", "victory", "kind", "boss", "summary")}} if target else {}),
            "effort": effort,
            "effort_policy": effort_policy,
            **({"profile": reference} if reference else {}),
            "request_id": request_id, **({"resume_from": resume_job["id"]} if resume_job else {})})
        if project.get("youtube_analysis_error"):
            ctx.store.patch("projects", project_id, youtube_analysis_error=None)
        return submitted


@router.post("/api/codex/chat")
async def codex_chat(ctx: WorkspaceDep, body: ChatRequest):
    project = ctx.get("projects", body.context.project_id) if body.context else None
    if project:
        all_jobs = ctx.store.all("jobs")
        latest = next((j for j in all_jobs if j["project_id"] == project["id"] and j["kind"] == "analyze" and not j.get("progress_reset")), None)
        project = {**project, "candidates": project_candidates(project, all_jobs)}
        project = {**project, "latest_search": ({k: latest.get(k) for k in
            ("id", "status", "stage", "model", "frames", "rounds", "result", "error")} if latest else None)}

    async def dispatch():
        result = await chat(ctx.codex, body, project)
        action = result.get("action")
        if action and action["kind"] == "search":
            if project is None:
                raise ConnectionError("請先選擇影片。")
            job = await enqueue_analysis(ctx, project["id"], AnalysisRequest(
                start=action["start"], end=action["end"], model=body.model, effort=body.effort), body.request_id,
                expected_generation=body.context.analysis_generation)
            result = {**result, "action": None, "job_id": job["id"],
                      "reply": "已建立成功挑戰搜尋任務。進度與結果會顯示在這段對話下方，你也可以繼續提問。"}
        elif action and action["kind"] == "cancel_search" and project:
            if ctx.get("projects", project["id"]).get("analysis_generation", 0) != body.context.analysis_generation:
                raise HTTPException(409, "影片分析已重置，舊操作已忽略。")
            running = next((j for j in ctx.store.all("jobs") if j["project_id"] == project["id"]
                            and j["kind"] == "analyze" and j["status"] in ACTIVE), None)
            if running:
                await ctx.cancel_job(running["id"])
            result = {**result, "action": None,
                      "reply": "已取消目前影片的搜尋任務。" if running else "目前影片沒有進行中的搜尋任務。"}
        return result

    async def stream():
        task = asyncio.create_task(dispatch())
        shutdown = asyncio.create_task(ctx.shutting_down.wait())
        try:
            yield json.dumps({"type": "waiting"}) + "\n"
            while not task.done() and not shutdown.done():
                await asyncio.wait({task, shutdown}, timeout=5,
                                   return_when=asyncio.FIRST_COMPLETED)
                if not task.done() and not shutdown.done():
                    yield json.dumps({"type": "waiting"}) + "\n"
            if not ctx.shutting_down.is_set():
                yield json.dumps({"type": "reply", **task.result()}, ensure_ascii=False) + "\n"
        except ConnectionError as error:
            yield json.dumps({"type": "error", "detail": str(error)}, ensure_ascii=False) + "\n"
        except HTTPException as error:
            yield json.dumps({"type": "error", "detail": error.detail}, ensure_ascii=False) + "\n"
        finally:
            task.cancel()
            shutdown.cancel()
            await asyncio.gather(task, shutdown, return_exceptions=True)

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"X-Accel-Buffering": "no"})


@router.post("/api/projects/{project_id}/analyze", status_code=202)
async def analyze(ctx: WorkspaceDep, project_id: str, body: AnalysisRequest):
    # Compatibility route: same validation, model selection and queue.
    return ctx.public_job(await enqueue_analysis(ctx, project_id, body, uuid4().hex))


async def clear_analysis(ctx: Workspace, project_id: str, *, progress_only: bool = False):
    async with ctx.analysis_lock:
        project = ctx.get("projects", project_id)
        if not project.get("ready"):
            raise HTTPException(409, "請先完成原片準備。")
        analysis_jobs = [j for j in ctx.store.all("jobs")
                         if j["project_id"] == project_id and j["kind"] == "analyze"]
        # Join worker cancellation before removing any checkpoint or database row.
        for job in analysis_jobs:
            await ctx.cancel_job(job["id"])
        work = project_work(ctx.root, project)
        artifacts = work / "codex"
        if artifacts.is_symlink() or not artifacts.resolve().is_relative_to(work.resolve()):
            raise HTTPException(409, "分析目錄位置異常，未清除資料。")
        logs = ctx.root / "runs" / "web"
        try:
            if artifacts.exists():
                await asyncio.to_thread(shutil.rmtree, artifacts)
            for job in analysis_jobs:
                log = logs / f"{job['id']}.log"
                if log.parent.resolve() != logs.resolve():
                    raise OSError("Unexpected log location")
                log.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(500, "分析檔案清理未完成，請重試重置。") from exc
        project = ctx.store.reset_analysis(project_id, progress_only=progress_only)
        remaining_jobs = ctx.store.all("jobs")
        return {"project": public_project(project) | {"review_candidates": project_candidates(project, remaining_jobs)},
                "jobs": [ctx.public_job(j) for j in remaining_jobs if j["project_id"] == project_id]}


@router.post("/api/projects/{project_id}/reset-analysis")
async def reset_analysis(ctx: WorkspaceDep, project_id: str):
    return await clear_analysis(ctx, project_id)


@router.post("/api/projects/{project_id}/reset-analysis-progress")
async def reset_analysis_progress(ctx: WorkspaceDep, project_id: str):
    return await clear_analysis(ctx, project_id, progress_only=True)
