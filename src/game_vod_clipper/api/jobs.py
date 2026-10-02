"""Jobs HTTP routes and request operations."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..codex.connection import MODEL
from ..jobs.scheduler import ACTIVE
from ..storage.locations import project_work
from .analysis import enqueue_analysis
from .context import WorkspaceDep
from .schemas import AnalysisRequest

router = APIRouter()


@router.post("/api/jobs/{job_id}/cancel")
async def cancel(ctx: WorkspaceDep, job_id: str):
    return await ctx.cancel_job(job_id)


@router.post("/api/jobs/{job_id}/retry", status_code=202)
async def retry(ctx: WorkspaceDep, job_id: str):
    job = ctx.get("jobs", job_id)
    ctx.get("projects", job["project_id"])
    if job.get("progress_reset"):
        raise HTTPException(409, "此分析的查看進度已重置，請重新搜尋。")
    if job["status"] not in {"failed", "cancelled", "interrupted"} and not (
        job["kind"] == "analyze" and job["status"] == "succeeded"
        and (job.get("result") or {}).get("can_continue")
    ):
        raise HTTPException(409, "此任務不需要重試。")
    if job["kind"] == "analyze":
        bounds = job["analysis"]
        checkpoint = project_work(ctx.root, ctx.get("projects", job["project_id"])) / "codex" / job["id"] / "checkpoint.json"
        return ctx.public_job(await enqueue_analysis(ctx, job["project_id"], AnalysisRequest(
            start=bounds["start"], end=bounds["end"], model=bounds.get("model", MODEL), effort=bounds.get("effort"),
            candidate_id=bounds.get("candidate_id")), uuid4().hex,
            resume_job=job if checkpoint.is_file() else None))
    if any(
        j["project_id"] == job["project_id"] and j["status"] in ACTIVE
        for j in ctx.store.all("jobs")
    ):
        raise HTTPException(409, "此專案已有任務執行中。")
    if job["kind"] == "prepare" and ctx.get("projects", job["project_id"])["ready"]:
        raise HTTPException(409, "此專案的原片已就緒，無需重新準備。")
    if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in ctx.store.all("jobs")) >= 8:
        raise HTTPException(429, "任務佇列已滿。")
    return ctx.jobs.submit(
        job["project_id"], job["kind"], job.get("draft"), job.get("analysis"), job.get("source_job_id"),
        job.get("export_quality", "high") if job["kind"] == "export" else None,
    )
