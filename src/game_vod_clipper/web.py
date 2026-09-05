"""Local, single-user POC API. Run one Uvicorn process bound to loopback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
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


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)


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
                self.store.patch("jobs", job_id, status="running")
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
            self.store.patch("jobs", job_id, status="cancelled", stage="已取消")
        except Exception as exc:
            logger.exception("Media job %s failed", job_id)
            self.store.patch("jobs", job_id, status="failed", error=str(exc))

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or Path(os.environ.get("GAME_VOD_ROOT", "."))).resolve()
    store = Store(root)
    jobs = Jobs(store)

    @asynccontextmanager
    async def lifespan(app):
        for job in store.all("jobs"):
            if job["status"] in ACTIVE:
                store.patch(
                    "jobs", job["id"], status="interrupted", stage="服務重啟，請重試"
                )
        yield
        await jobs.close()

    app = FastAPI(title="BossCut local POC", lifespan=lifespan)
    app.state.store = store
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
    def codex_status():
        executable = shutil.which("codex")
        if not executable:
            return {
                "available": False,
                "model": "gpt-5.6-luna",
                "detail": "後端環境尚未安裝 Codex CLI。",
            }
        try:
            status = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            logged_in = status.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            logged_in = False
        return {
            "available": logged_in,
            "model": "gpt-5.6-luna",
            "detail": "使用現有 Codex CLI 登入狀態；模型權限將於執行時確認。"
            if logged_in
            else "請先在後端環境執行 codex login。",
        }

    @app.post("/api/projects/{project_id}/analyze", status_code=202)
    async def analyze(project_id: str, body: AnalysisRequest):
        project = get("projects", project_id)
        if not project["ready"]:
            raise HTTPException(409, "請先完成影片預覽。")
        if (
            not body.start < body.end <= project["duration"]
            or body.end - body.start > 1800
        ):
            raise HTTPException(422, "分析範圍須位於原片內，且每次最多 30 分鐘。")
        if any(
            j["project_id"] == project_id
            and j["kind"] == "analyze"
            and j["status"] in ACTIVE
            for j in store.all("jobs")
        ):
            raise HTTPException(409, "此影片已有 Codex 分析任務。")
        if len([j for j in store.all("jobs") if j["status"] in ACTIVE]) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        return jobs.submit(project_id, "analyze", analysis=body.model_dump())

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
        if job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise HTTPException(409, "此任務不需要重試。")
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
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
