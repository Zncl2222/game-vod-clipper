"""Local, single-user POC API. Run one Uvicorn process bound to loopback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .web_store import Store
from .codex_connection import CodexConnection, ConnectionError, MODEL
from .codex_chat import ChatRequest, chat
from .candidates import project_candidates

ACTIVE = {"queued", "running"}
EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
logger = logging.getLogger(__name__)


class ImportRequest(BaseModel):
    kind: Literal["local", "youtube"]
    source: str = Field(min_length=1, max_length=2000)


class Draft(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    victory: float = Field(gt=0)
    postroll: float = Field(ge=5, le=10)
    reviewed: bool = False
    revision: int = Field(ge=0)
    origin: Literal["manual", "agent"] = "manual"


class ExportRequest(BaseModel):
    revision: int = Field(ge=0)


class CandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=200)
    review: Literal["pending", "keep", "reject"]
    analysis_generation: int = Field(ge=0)


class CodexLoginRequest(BaseModel):
    method: Literal["chatgpt", "chatgptDeviceCode"] = "chatgptDeviceCode"


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    model: str = Field(default=MODEL, min_length=1, max_length=120)


def youtube_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("請使用有效的 HTTPS YouTube 影片網址。")
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/live/", "/shorts/")):
            video_id = parsed.path.split("/")[2]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("只接受單一 YouTube 影片網址。")
    return f"https://www.youtube.com/watch?v={video_id}"


def local_source(root: Path, source: str) -> Path:
    path = (root / source).resolve()
    if not any(path.is_relative_to(root / folder) for folder in ("downloads", "clips")):
        raise ValueError("本機影片必須位於 downloads/ 或 clips/，且不能連結到目錄外。")
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        raise ValueError("找不到支援的本機影片。")
    return path


class Jobs:
    def __init__(self, store: Store):
        self.store = store
        self.limit = asyncio.Semaphore(1)
        self.tasks: dict[str, asyncio.Task] = {}

    def submit(
        self,
        project_id: str,
        kind: str,
        draft: dict | None = None,
        analysis: dict | None = None,
    ) -> dict:
        job = {
            "id": uuid4().hex,
            "project_id": project_id,
            "kind": kind,
            "status": "queued",
            "stage": "等待處理",
            "progress": 0,
            "created": time.time(),
            "draft": draft,
            "analysis": analysis,
            "model": analysis.get("model", MODEL) if analysis else None,
            "error": None,
        }
        self.store.put("jobs", job)
        task = asyncio.create_task(self.execute(job["id"]))
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return job

    async def execute(self, job_id: str):
        process = None
        log = self.store.root / "runs" / "web" / f"{job_id}.log"
        try:
            async with self.limit:
                self.store.patch("jobs", job_id, status="running", started_at=time.time())
                with log.open("wb") as output:
                    process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "game_vod_clipper.web_worker",
                        str(self.store.root),
                        job_id,
                        stdout=output,
                        stderr=output,
                        start_new_session=os.name == "posix",
                    )
                    code = await process.wait()
                job = self.store.get("jobs", job_id)
                self.store.patch(
                    "jobs",
                    job_id,
                    status="succeeded" if code == 0 else "failed",
                    finished_at=time.time(),
                    error=job.get("error")
                    if code == 0 or job.get("error")
                    else "處理失敗，請查看 runs/web/ 下的任務日誌。",
                )
        except asyncio.CancelledError:
            if process and process.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        killer = await asyncio.create_subprocess_exec(
                            "taskkill", "/PID", str(process.pid), "/T", "/F"
                        )
                        await killer.wait()
                except ProcessLookupError:
                    pass
                await process.wait()
            self.store.patch("jobs", job_id, status="cancelled", stage="已取消", finished_at=time.time())
        except Exception as exc:
            logger.exception("Media job %s failed", job_id)
            self.store.patch("jobs", job_id, status="failed", error=str(exc), finished_at=time.time())

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or Path(os.environ.get("GAME_VOD_ROOT", "."))).resolve()
    store = Store(root)
    jobs = Jobs(store)
    codex = CodexConnection(root)
    analysis_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        for job in store.all("jobs"):
            if job["status"] in ACTIVE:
                store.patch(
                    "jobs", job["id"], status="interrupted", stage="服務重啟，請重試", finished_at=time.time()
                )
        yield
        await jobs.close()
        await codex.close()

    app = FastAPI(title="BossCut local POC", lifespan=lifespan)
    app.state.store = store
    app.state.codex = codex

    @app.exception_handler(ConnectionError)
    async def codex_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    hosts = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    hosts += [h for h in os.environ.get("GAME_VOD_ALLOWED_HOSTS", "").split(",") if h]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in hosts:
            return JSONResponse(
                {"detail": "不允許此來源存取本機工作區。"}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "不允許跨站存取。"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def get(table: str, key: str):
        result = store.get(table, key)
        if result is None:
            raise HTTPException(404, "找不到項目。")
        return result

    def public_project(project):
        return {k: v for k, v in project.items() if k not in {"source", "url"}}

    def public_job(job):
        return {k: v for k, v in job.items() if k != "output"}

    def state():
        return {
            "projects": [public_project(p) for p in store.all("projects")],
            "jobs": [public_job(j) for j in store.all("jobs")],
        }

    @app.get("/api/state")
    async def read_state():
        return state()

    @app.get("/api/codex")
    async def codex_status():
        return await codex.status()

    @app.post("/api/codex/login")
    async def codex_login(body: CodexLoginRequest):
        return await codex.begin_login(body.method)

    @app.post("/api/codex/login/cancel")
    async def codex_cancel_login():
        return await codex.cancel_login()

    @app.post("/api/codex/test")
    async def codex_test():
        return await codex.probe()

    @app.get("/api/codex/models")
    async def codex_models():
        return {"models": await codex.models()}

    async def enqueue_analysis(project_id: str, body: AnalysisRequest, request_id: str, resume_job: dict | None = None, expected_generation: int | None = None):
        project = get("projects", project_id)
        generation = project.get("analysis_generation", 0) if expected_generation is None else expected_generation
        if not project["ready"]:
            raise HTTPException(409, "請先完成影片預覽。")
        if not body.start < body.end <= project["duration"]:
            raise HTTPException(422, "分析範圍須位於原片內。")
        status = await codex.status()
        if not status["available"]:
            raise ConnectionError(status["detail"])
        selected = next((m for m in await codex.models() if m["id"] == body.model), None)
        if not selected or "image" not in selected.get("input_modalities", []):
            raise ConnectionError("所選模型不支援畫面判讀，請在同一模型選單選擇支援影像的模型。")
        async with analysis_lock:
            if get("projects", project_id).get("analysis_generation", 0) != generation:
                raise HTTPException(409, "影片分析已重置，請重新搜尋。")
            if resume_job and not store.get("jobs", resume_job["id"]):
                raise HTTPException(409, "舊分析已清除，請重新搜尋。")
            current = store.all("jobs")
            duplicate = next((j for j in current if j["project_id"] == project_id and
                              (j.get("analysis") or {}).get("request_id") == request_id), None)
            if duplicate:
                return duplicate
            if any(j["project_id"] == project_id and j["kind"] == "analyze" and j["status"] in ACTIVE for j in current):
                raise HTTPException(409, "此影片已有搜尋任務，請先等待完成或取消。")
            if sum(j["status"] in ACTIVE for j in current) >= 8:
                raise HTTPException(429, "任務佇列已滿。")
            return jobs.submit(project_id, "analyze", analysis={**body.model_dump(),
                "effort": resume_job["analysis"].get("effort") if resume_job else selected.get("effort"),
                "request_id": request_id, **({"resume_from": resume_job["id"]} if resume_job else {})})

    @app.post("/api/codex/chat")
    async def codex_chat(body: ChatRequest):
        project = get("projects", body.context.project_id) if body.context else None
        if project:
            all_jobs = store.all("jobs")
            latest = next((j for j in all_jobs if j["project_id"] == project["id"] and j["kind"] == "analyze"), None)
            project = {**project, "candidates": project_candidates(project, all_jobs)}
            project = {**project, "latest_search": ({k: latest.get(k) for k in
                ("id", "status", "stage", "model", "frames", "rounds", "result", "error")} if latest else None)}

        async def dispatch():
            result = await chat(codex, body, project)
            action = result.get("action")
            if action and action["kind"] == "search":
                if project is None:
                    raise ConnectionError("請先選擇影片。")
                job = await enqueue_analysis(project["id"], AnalysisRequest(
                    start=action["start"], end=action["end"], model=body.model), body.request_id,
                    expected_generation=body.context.analysis_generation)
                result = {**result, "action": None, "job_id": job["id"],
                          "reply": "已建立成功挑戰搜尋任務。進度與結果會顯示在這段對話下方，你也可以繼續提問。"}
            elif action and action["kind"] == "cancel_search" and project:
                if get("projects", project["id"]).get("analysis_generation", 0) != body.context.analysis_generation:
                    raise HTTPException(409, "影片分析已重置，舊操作已忽略。")
                running = next((j for j in store.all("jobs") if j["project_id"] == project["id"]
                                and j["kind"] == "analyze" and j["status"] in ACTIVE), None)
                if running:
                    await cancel(running["id"])
                result = {**result, "action": None,
                          "reply": "已取消目前影片的搜尋任務。" if running else "目前影片沒有進行中的搜尋任務。"}
            return result

        async def stream():
            task = asyncio.create_task(dispatch())
            try:
                yield json.dumps({"type": "waiting"}) + "\n"
                while not task.done():
                    await asyncio.wait({task}, timeout=5)
                    if not task.done():
                        yield json.dumps({"type": "waiting"}) + "\n"
                yield json.dumps({"type": "reply", **task.result()}, ensure_ascii=False) + "\n"
            except ConnectionError as error:
                yield json.dumps({"type": "error", "detail": str(error)}, ensure_ascii=False) + "\n"
            except HTTPException as error:
                yield json.dumps({"type": "error", "detail": error.detail}, ensure_ascii=False) + "\n"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(stream(), media_type="application/x-ndjson",
                                 headers={"X-Accel-Buffering": "no"})

    @app.post("/api/projects/{project_id}/analyze", status_code=202)
    async def analyze(project_id: str, body: AnalysisRequest):
        # Compatibility route: same validation, model selection and queue.
        return public_job(await enqueue_analysis(project_id, body, uuid4().hex))

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = ""
            while not await request.is_disconnected():
                current = json.dumps(state(), ensure_ascii=False)
                yield (
                    f"data: {current}\n\n" if current != previous else ": heartbeat\n\n"
                )
                previous = current
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/api/sources")
    async def sources():
        result = []
        for folder in ("downloads", "clips"):
            for path in sorted((root / folder).rglob("*")):
                if path.suffix.lower() in EXTENSIONS and path.is_file():
                    try:
                        resolved = local_source(root, str(path.relative_to(root)))
                    except ValueError:
                        continue
                    result.append(
                        {
                            "path": str(resolved.relative_to(root)),
                            "name": path.stem,
                            "size": path.stat().st_size,
                        }
                    )
                if len(result) >= 200:
                    return result
        return result

    @app.post("/api/projects", status_code=202)
    async def import_project(body: ImportRequest):
        try:
            source = (
                str(local_source(root, body.source).relative_to(root))
                if body.kind == "local"
                else None
            )
            url = youtube_url(body.source) if body.kind == "youtube" else None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if len([j for j in store.all("jobs") if j["status"] in ACTIVE]) >= 8:
            raise HTTPException(429, "任務佇列已滿，請稍後再試。")
        project = {
            "id": uuid4().hex,
            "title": Path(source).stem if source else "YouTube · " + url.split("v=")[1],
            "source": source,
            "url": url,
            "ready": False,
            "created": time.time(),
            "thumbnails": [],
        }
        store.put("projects", project)
        return {
            "project": public_project(project),
            "job": jobs.submit(project["id"], "prepare"),
        }

    @app.put("/api/projects/{project_id}/candidate-review")
    async def review_candidate(project_id: str, body: CandidateReviewRequest):
        project = get("projects", project_id)
        if body.analysis_generation != project.get("analysis_generation", 0):
            raise HTTPException(409, "影片分析已重置，請重新選取片段。")
        if not any(c["id"] == body.candidate_id for c in project_candidates(project, store.all("jobs"))):
            raise HTTPException(404, "找不到這個影片的候選片段。")
        try:
            store.set_candidate_review(project_id, body.candidate_id, body.review, body.analysis_generation)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return {"candidate_id": body.candidate_id, "review": body.review}

    @app.put("/api/projects/{project_id}/draft")
    async def save_draft(project_id: str, body: Draft):
        project = get("projects", project_id)
        if not project["ready"]:
            raise HTTPException(409, "預覽尚未完成。")
        if body.revision != project["draft"]["revision"]:
            raise HTTPException(409, "草稿已更新，請重新載入專案。")
        if (
            not body.start < body.victory
            or body.victory + body.postroll > project["duration"]
        ):
            raise HTTPException(
                422, "開始必須早於勝利，且勝利後須保留完整 5–10 秒，不可超出原片。"
            )
        draft = body.model_dump() | {"revision": body.revision + 1}
        store.patch("projects", project_id, draft=draft)
        return draft

    @app.post("/api/projects/{project_id}/exports", status_code=202)
    async def export(project_id: str, body: ExportRequest):
        project = get("projects", project_id)
        draft = project.get("draft")
        if not draft or draft["revision"] != body.revision:
            raise HTTPException(409, "請先儲存目前草稿。")
        if not draft["reviewed"]:
            raise HTTPException(
                422, "請先完整檢查片段，確認同一次成功挑戰且沒有死亡、讀取或跑圖。"
            )
        for job in store.all("jobs"):
            if (
                job["project_id"] == project_id
                and job["kind"] == "export"
                and job.get("draft", {}).get("revision") == body.revision
                and job["status"] in ACTIVE | {"succeeded"}
            ):
                return public_job(job)
        if len([j for j in store.all("jobs") if j["status"] in ACTIVE]) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        return jobs.submit(project_id, "export", draft)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        job = get("jobs", job_id)
        task = jobs.tasks.get(job_id)
        if task and job["status"] in ACTIVE:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first instruction never enters execute().
            store.patch("jobs", job_id, status="cancelled", stage="已取消")
        return public_job(get("jobs", job_id))

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry(job_id: str):
        job = get("jobs", job_id)
        if job["status"] not in {"failed", "cancelled", "interrupted"} and not (
            job["kind"] == "analyze" and job["status"] == "succeeded"
            and (job.get("result") or {}).get("can_continue")
        ):
            raise HTTPException(409, "此任務不需要重試。")
        if job["kind"] == "analyze":
            bounds = job["analysis"]
            checkpoint = store.root / "runs" / "web" / job["project_id"] / "codex" / job["id"] / "checkpoint.json"
            return public_job(await enqueue_analysis(job["project_id"], AnalysisRequest(
                start=bounds["start"], end=bounds["end"], model=bounds.get("model", MODEL)), uuid4().hex,
                resume_job=job if checkpoint.is_file() else None))
        if any(
            j["project_id"] == job["project_id"] and j["status"] in ACTIVE
            for j in store.all("jobs")
        ):
            raise HTTPException(409, "此專案已有任務執行中。")
        if job["kind"] == "prepare" and get("projects", job["project_id"])["ready"]:
            raise HTTPException(409, "此專案的預覽已完成，無需重新建立。")
        if len([j for j in store.all("jobs") if j["status"] in ACTIVE]) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        return jobs.submit(
            job["project_id"], job["kind"], job.get("draft"), job.get("analysis")
        )

    @app.post("/api/projects/{project_id}/reset-analysis")
    async def reset_analysis(project_id: str):
        async with analysis_lock:
            project = get("projects", project_id)
            if not project.get("ready"):
                raise HTTPException(409, "請先完成影片預覽。")
            analysis_jobs = [j for j in store.all("jobs")
                             if j["project_id"] == project_id and j["kind"] == "analyze"]
            # Join worker cancellation before removing any checkpoint or database row.
            for job in analysis_jobs:
                await cancel(job["id"])
            work = root / "runs" / "web"
            artifacts = work / project_id / "codex"
            if artifacts.is_symlink() or not artifacts.resolve().is_relative_to(work.resolve()):
                raise HTTPException(409, "分析目錄位置異常，未清除資料。")
            try:
                if artifacts.exists():
                    await asyncio.to_thread(shutil.rmtree, artifacts)
                for job in analysis_jobs:
                    log = work / f"{job['id']}.log"
                    if log.parent.resolve() != work.resolve():
                        raise OSError("Unexpected log location")
                    log.unlink(missing_ok=True)
            except OSError as exc:
                raise HTTPException(500, "分析檔案清理未完成，請重試重置。") from exc
            return {"project": public_project(store.reset_analysis(project_id))}

    @app.get("/api/projects/{project_id}/media/{filename}")
    async def media(project_id: str, filename: str):
        project = get("projects", project_id)
        allowed = {"preview.mp4"} | {t["file"] for t in project["thumbnails"]}
        if not project["ready"] or filename not in allowed:
            raise HTTPException(404, "找不到預覽。")
        return FileResponse(root / "runs" / "web" / project_id / filename)

    @app.get("/api/jobs/{job_id}/download")
    async def download(job_id: str):
        job = get("jobs", job_id)
        if job["status"] != "succeeded" or job["kind"] != "export":
            raise HTTPException(404, "尚無可下載的剪輯。")
        return FileResponse(
            root / job["output"],
            filename=f"boss-fight-{job_id[:8]}.mp4",
            media_type="video/mp4",
        )

    @app.get("/api/projects/{project_id}/review-packet")
    async def review_packet(project_id: str):
        project = get("projects", project_id)
        if not project["ready"]:
            raise HTTPException(409, "預覽尚未完成。")
        return {
            "schema_version": 1,
            "project_id": project_id,
            "source": project["source"],
            "duration": project["duration"],
            "instruction": "Follow skills/game-vod-boss-clipper/SKILL.md. Return start, victory, postroll as seconds. Visual review is required; timeline thumbnails alone are insufficient.",
            "draft": project["draft"],
        }

    frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


def main():
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        description="Local BossCut POC (one server process)"
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    # Persistent event streams must not leave an old server hanging on restart.
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port,
                timeout_graceful_shutdown=5)
