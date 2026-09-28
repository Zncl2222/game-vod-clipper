"""Local, single-user POC API. Run one Uvicorn process bound to loopback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import anyio
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .web_store import Store
from .codex_connection import CodexConnection, ConnectionError, MODEL
from .codex_chat import ChatRequest, chat, resolve_effort
from .candidates import project_candidates
from .youtube_routes import YouTubeWorkspace
from .youtube_account import YouTubeError
from .usage import quota_change, usage_summary
from .storage import video_inventory, video_storage
from .game_profiles import KINDS, GameProfiles, ProfileError
from .locations import LocationError, Locations, export_path, media_path, project_work, record_path
from .youtube import DownloadQuality, youtube_command
from .process import ToolMissingError

ACTIVE = {"queued", "running"}
EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
logger = logging.getLogger(__name__)


class ImportRequest(BaseModel):
    kind: Literal["local", "youtube"]
    source: str = Field(min_length=1, max_length=2000)
    download_quality: DownloadQuality = "best"


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)


class DeleteStoredVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeleteStoredVideos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def valid_ids(cls, values):
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in values):
            raise ValueError("影片檔案編號無效。")
        return list(dict.fromkeys(values))


def plain_text(value: str):
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("不能包含控制字元。")
    return value


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=2000)
    _text = field_validator("title", "notes")(plain_text)


class CaptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    caption: str = Field(default="", max_length=1000)
    _text = field_validator("caption")(plain_text)


class LocationUpdate(BaseModel):
    """Only the locations sent are changed; null or an empty path restores the default."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sources: str | None = Field(default=None, max_length=1000)
    exports: str | None = Field(default=None, max_length=1000)
    cache: str | None = Field(default=None, max_length=1000)
    _text = field_validator("sources", "exports", "cache")(lambda value: value and plain_text(value))


class ProfileChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "default" follows the default profile; null uses no references.
    profile_id: str | None = Field(max_length=40)


class Draft(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    title: str | None = Field(default=None, max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    start: float = Field(ge=0)
    victory: float = Field(gt=0)
    postroll: float = Field(ge=5, le=10)
    reviewed: bool = False
    revision: int = Field(ge=0)
    origin: Literal["manual", "agent"] = "manual"
    candidate_id: str | None = Field(default=None, min_length=1, max_length=200)
    candidate_revision: int | None = Field(default=None, ge=0)
    manually_adjusted: bool | None = None


ExportQuality = Literal["max", "high", "balanced", "fast"]


class ExportRequest(BaseModel):
    revision: int = Field(ge=0)
    source_job_id: str | None = Field(default=None, min_length=1, max_length=100)
    quality: ExportQuality = "high"


class CandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=200)
    review: Literal["pending", "keep", "reject"]
    analysis_generation: int = Field(ge=0)


class CandidateEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    candidate_id: str = Field(min_length=1, max_length=200)
    analysis_generation: int = Field(ge=0)
    revision: int = Field(ge=0)
    start: float = Field(ge=0)
    victory: float = Field(gt=0)
    postroll: float = Field(ge=5, le=10)


class CodexLoginRequest(BaseModel):
    method: Literal["chatgpt", "chatgptDeviceCode"] = "chatgptDeviceCode"


class AnalysisRequest(BaseModel):
    effort: str | None = Field(default=None, max_length=40)
    effort_policy: Literal["adaptive", "fixed"] = "adaptive"
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    model: str = Field(default=MODEL, min_length=1, max_length=120)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=100)
    analysis_generation: int | None = Field(default=None, ge=0)


def http_origin(value: str):
    """Compare browser origins including scheme and effective port, not just host."""
    try:
        parsed = urlparse(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None


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
    path = media_path(root, source).resolve()
    locations = Locations(root)
    if not any(path.is_relative_to(locations.folder(kind)) for kind in ("sources", "exports")):
        raise ValueError("本機影片必須位於原始影片或輸出成品資料夾，且不能連結到資料夾外。")
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        raise ValueError("找不到支援的本機影片。")
    return path


class Jobs:
    def __init__(self, store: Store, codex: CodexConnection | None = None):
        self.store = store
        self.codex = codex
        self.limit = asyncio.Semaphore(1)
        # A long AI search must not occupy the download / export worker.
        self.analysis_limit = asyncio.Semaphore(1)
        self.tasks: dict[str, asyncio.Task] = {}

    def submit(
        self,
        project_id: str,
        kind: str,
        draft: dict | None = None,
        analysis: dict | None = None,
        source_job_id: str | None = None,
        export_quality: str | None = None,
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
            "source_job_id": source_job_id,
            **({"export_quality": export_quality} if kind == "export" else {}),
            "model": analysis.get("model", MODEL) if analysis else None,
            "error": None,
        }
        self.store.put("jobs", job)
        task = asyncio.create_task(self.execute(job["id"]))
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return job

    async def execute(self, job_id: str):
        try:
            job = self.store.get("jobs", job_id)
            async with self.analysis_limit if job["kind"] == "analyze" else self.limit:
                job = self.store.get("jobs", job_id)
                before = None
                if job["kind"] == "analyze" and self.codex:
                    before = await self.codex.rate_limits()
                    self.store.patch("jobs", job_id, quota_before=before,
                                     quota_change={"status": "pending", "windows": []})
                try:
                    await self.run(job_id)
                finally:
                    if before is not None:
                        after = await self.codex.rate_limits()
                        self.store.patch("jobs", job_id, quota_after=after,
                                         quota_change=quota_change(before, after))
        except asyncio.CancelledError:
            # Cancellation during the trailing metadata read must not turn a
            # completed analysis into a cancelled result.
            current = self.store.get("jobs", job_id)
            if current and current["status"] in ACTIVE:
                self.store.patch("jobs", job_id, status="cancelled", stage="已取消", finished_at=time.time())
            if current and (current.get("quota_change") or {}).get("status") == "pending":
                self.store.patch("jobs", job_id, quota_change={"status": "unavailable", "windows": []})
        except Exception as exc:
            logger.exception("Job %s could not complete dispatch", job_id)
            current = self.store.get("jobs", job_id)
            if current and current["status"] in ACTIVE:
                self.store.patch("jobs", job_id, status="failed", error=str(exc), finished_at=time.time())
            if current and (current.get("quota_change") or {}).get("status") == "pending":
                self.store.patch("jobs", job_id, quota_change={"status": "unavailable", "windows": []})

    async def run(self, job_id: str):
        process = None
        log = self.store.root / "runs" / "web" / f"{job_id}.log"
        try:
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
                "jobs", job_id, status="succeeded" if code == 0 else "failed",
                finished_at=time.time(), error=job.get("error")
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


PREVIEW_RANGE_LIMIT = 8 * 1024 * 1024
OPEN_RANGE = re.compile(r"\s*bytes\s*=\s*(\d+)\s*-\s*")


class LocalFileResponse(FileResponse):
    def __init__(self, *args, range_limit: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.range_limit = range_limit

    async def __call__(self, scope, receive, send):
        scope["game_vod_clipper.file_response"] = True
        if self.range_limit:
            # Players open with "bytes=0-" and re-request as they need more.
            # Answering that with the whole multi-GB file lets proxies (e.g.
            # VS Code port forwarding) buffer it all in memory while paused.
            headers = []
            for key, value in scope["headers"]:
                match = key == b"range" and OPEN_RANGE.fullmatch(value.decode("latin-1"))
                if match:
                    start = int(match[1])
                    value = f"bytes={start}-{start + self.range_limit - 1}".encode()
                headers.append((key, value))
            scope["headers"] = headers

        async def disconnected():
            while True:
                if (await receive())["type"] == "http.disconnect":
                    group.cancel_scope.cancel()
                    return

        # Stop disk reads when a player disconnects or the server closes its
        # transport. FileResponse otherwise keeps reading the entire file.
        async with anyio.create_task_group() as group:
            group.start_soon(disconnected)
            await super().__call__(scope, receive, send)
            group.cancel_scope.cancel()


class LocalServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, shutdown_event: asyncio.Event):
        super().__init__(config)
        self.shutdown_event = shutdown_event

    async def shutdown(self, sockets=None):
        # Uvicorn drains HTTP requests BEFORE sending lifespan.shutdown. Notify
        # our persistent streams here so they can finish before that drain.
        self.shutdown_event.set()
        for connection in list(self.server_state.connections):
            if getattr(connection, "scope", {}).get("game_vod_clipper.file_response"):
                # A paused player may never drain a large Range response. Closing
                # with buffered bytes would still wait; abort releases it now and
                # LocalFileResponse's disconnect listener stops the file reader.
                connection.transport.abort()
        await super().shutdown(sockets=sockets)


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or Path(os.environ.get("GAME_VOD_ROOT", "."))).resolve()
    store = Store(root)
    locations = Locations(root)
    profiles = GameProfiles(root)
    codex = CodexConnection(root, store)
    jobs = Jobs(store, codex)
    analysis_lock = asyncio.Lock()
    deleting_projects: set[str] = set()
    shutting_down = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app):
        shutting_down.clear()
        for job in store.all("jobs"):
            if job["status"] in ACTIVE:
                store.patch(
                    "jobs", job["id"], status="interrupted", stage="服務重啟，請重試", finished_at=time.time()
                )
            if (job.get("quota_change") or {}).get("status") == "pending":
                store.patch("jobs", job["id"], quota_change={"status": "unavailable", "windows": []})
        youtube.start()
        try:
            yield
        finally:
            shutting_down.set()
            await youtube.close()
            await jobs.close()
            await codex.close()

    app = FastAPI(title="BossCut local POC", lifespan=lifespan)
    app.state.store = store
    app.state.jobs = jobs
    app.state.codex = codex
    app.state.shutting_down = shutting_down

    @app.exception_handler(ConnectionError)
    async def codex_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(ProfileError)
    async def profile_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    hosts = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    hosts += [h for h in os.environ.get("GAME_VOD_ALLOWED_HOSTS", "").split(",") if h]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        oauth_callback = request.method == "GET" and request.url.path == "/api/youtube/callback"
        source_origin = http_origin(origin) if origin else None
        if origin and (source_origin is None or source_origin != http_origin(str(request.base_url))) and not oauth_callback:
            return JSONResponse(
                {"detail": "不允許此來源存取本機工作區。"}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site" and not oauth_callback:
            return JSONResponse({"detail": "不允許跨站存取。"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def get(table: str, key: str):
        if table == "projects" and key in deleting_projects:
            raise HTTPException(409, "專案正在刪除，請稍候。")
        result = store.get(table, key)
        if result is None:
            raise HTTPException(404, "找不到項目。")
        return result

    def public_project(project):
        return {k: v for k, v in project.items() if k not in {"source", "url", "work"}}

    def public_job(job):
        public = {k: v for k, v in job.items() if k != "output"}
        if job.get("output"):
            public["output_path"] = str(media_path(root, job["output"]))
        return public

    def published(upload: dict):
        # Safe to drop the local MP4 only once YouTube holds the video and any
        # requested playlist placement has been confirmed.
        return upload["status"] == "succeeded" and (not upload.get("playlist_id") or upload.get("playlist_status") == "added")

    def clip_uploads():
        result = {}
        for upload in youtube.uploads.all().values():
            current = result.get(upload.get("export_id"))
            if not current or (published(upload), upload.get("created", 0)) > (published(current), current.get("created", 0)):
                result[upload.get("export_id")] = upload
        return {key: {"status": item["status"], "video_id": item.get("video_id"), "playlist_title": item.get("playlist_title"),
                      "playlist_status": item.get("playlist_status"), "published": published(item)}
                for key, item in result.items()}

    def state():
        all_jobs = store.all("jobs")
        uploads = clip_uploads()
        return {
            "projects": [public_project(p) | {"review_candidates": project_candidates(p, all_jobs)} for p in store.all("projects")],
            "jobs": [public_job(j) | ({"youtube_upload": uploads[j["id"]]} if j["id"] in uploads else {}) for j in all_jobs],
        }

    @app.get("/api/health")
    def health():
        """Local readiness only; never start Codex or contact an external API."""
        if shutting_down.is_set():
            raise HTTPException(503, "Service is shutting down")
        try:
            with store.connect() as db:
                db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
        except sqlite3.Error:
            raise HTTPException(503, "Workspace database is unavailable") from None
        return {"status": "ok"}

    @app.get("/api/state")
    async def read_state():
        return state()

    def profile_listing():
        return {"default_id": profiles.default_id(), "kinds": KINDS,
                "profiles": profiles.all()}

    @app.get("/api/profiles")
    async def list_profiles():
        return profile_listing()

    @app.post("/api/profiles")
    async def create_profile(body: ProfileBody):
        return profiles.create(body.title, body.notes)

    @app.patch("/api/profiles/{profile_id}")
    async def update_profile(profile_id: str, body: ProfileBody):
        return profiles.update(profile_id, title=body.title, notes=body.notes)

    @app.delete("/api/profiles/{profile_id}")
    async def delete_profile(profile_id: str):
        profiles.delete(profile_id)
        for project in store.all("projects"):
            if project.get("profile_id") == profile_id:
                store.patch("projects", project["id"], profile_id="default")
        return profile_listing()

    @app.put("/api/profiles/default")
    async def set_default_profile(body: ProfileChoice):
        profiles.set_default(body.profile_id)
        return profile_listing()

    @app.post("/api/profiles/{profile_id}/images")
    async def add_profile_image(profile_id: str, request: Request, kind: str, caption: str = ""):
        if len(caption) > 1000:
            raise HTTPException(422, "說明過長。")
        data = await request.body()
        return await asyncio.to_thread(profiles.add_image, profile_id, kind, plain_text(caption.strip()), data)

    @app.patch("/api/profiles/{profile_id}/images/{image_id}")
    async def update_profile_image(profile_id: str, image_id: str, body: CaptionBody):
        return profiles.update_image(profile_id, image_id, body.caption)

    @app.delete("/api/profiles/{profile_id}/images/{image_id}")
    async def remove_profile_image(profile_id: str, image_id: str):
        return profiles.remove_image(profile_id, image_id)

    @app.get("/api/profiles/{profile_id}/images/{image_id}")
    async def profile_image(profile_id: str, image_id: str):
        return FileResponse(profiles.image_path(profile_id, image_id), media_type="image/jpeg")

    @app.put("/api/projects/{project_id}/profile")
    async def choose_project_profile(project_id: str, body: ProfileChoice):
        get("projects", project_id)
        if body.profile_id not in {None, "default"}:
            profiles.get(body.profile_id)
        if body.profile_id != "default":
            # The last game picked also applies to later imports, so a new
            # YouTube import does not silently drop back to no references.
            profiles.set_default(body.profile_id)
        return public_project(store.patch("projects", project_id, profile_id=body.profile_id))

    @app.get("/api/storage")
    def storage():
        return video_storage(root, store)

    @app.get("/api/storage/files")
    def stored_videos():
        return video_inventory(store, youtube.uploads.all().values(), youtube.uploads.tasks)

    def remove_stored_video(item):
        if item is None:
            raise HTTPException(409, "檔案已變更或已刪除，請重新整理清單後確認。")
        if item["blocked"]:
            raise HTTPException(409, item["blocked"])
        if item["job_id"]:
            freed = remove_clip(item["project_id"], get("jobs", item["job_id"]))
        else:
            try:
                media_path(root, item["path"]).unlink()
            except OSError:
                raise HTTPException(409, "檔案無法刪除，請確認權限並重新整理清單。") from None
            freed = item["bytes"]
        return {"id": item["id"], "bytes": freed, "job_id": item["job_id"], "project_id": item["project_id"]}

    @app.post("/api/storage/delete")
    async def delete_stored_video(body: DeleteStoredVideo):
        # No await between revalidation and unlink: new imports/exports cannot
        # start using this file while deletion is in progress.
        async with youtube.lock, youtube.uploads.lock, analysis_lock:
            inventory = video_inventory(store, youtube.uploads.all().values(), youtube.uploads.tasks)
            item = next((item for item in inventory["items"] if item["id"] == body.id), None)
            result = remove_stored_video(item)
            return {"deleted": True, **{key: value for key, value in result.items() if key != "id"}}

    @app.post("/api/storage/delete-batch")
    async def delete_stored_videos(body: DeleteStoredVideos):
        # Scan once for the whole batch. Hold the same locks and do not await
        # between validation and deletion, just like the single-file endpoint.
        async with youtube.lock, youtube.uploads.lock, analysis_lock:
            inventory = video_inventory(store, youtube.uploads.all().values(), youtube.uploads.tasks)
            by_id = {item["id"]: item for item in inventory["items"]}
            deleted, failed = [], []
            for key in body.ids:
                try:
                    deleted.append(remove_stored_video(by_id.get(key)))
                except HTTPException as error:
                    # Filesystem changes cannot be rolled back: report each
                    # outcome explicitly instead of claiming an atomic batch.
                    failed.append({"id": key, "detail": str(error.detail)})
            return {"deleted": deleted, "failed": failed, "bytes": sum(item["bytes"] for item in deleted)}

    @app.get("/api/locations")
    async def read_locations():
        return locations.status()

    @app.put("/api/locations")
    async def update_locations(body: LocationUpdate):
        changes = {kind: getattr(body, kind) for kind in body.model_fields_set}
        try:
            return await asyncio.to_thread(locations.update, changes)
        except LocationError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/codex")
    async def codex_status():
        return await codex.status()

    @app.get("/api/codex/usage")
    async def codex_usage(project_id: str | None = None):
        if project_id:
            get("projects", project_id)
        return usage_summary(store, project_id)

    @app.get("/api/codex/rate-limits")
    async def codex_rate_limits():
        return await codex.rate_limits()

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
            target = next((candidate for candidate in project_candidates(project, store.all("jobs"))
                           if candidate["id"] == body.candidate_id), None)
            if target is None:
                raise HTTPException(404, "找不到這個影片的候選片段。")
        status = await codex.status()
        if not status["available"]:
            raise ConnectionError(status["detail"])
        selected = next((m for m in await codex.models() if m["id"] == body.model), None)
        if not selected or "image" not in selected.get("input_modalities", []):
            raise ConnectionError("所選模型不支援畫面判讀，請在同一模型選單選擇支援影像的模型。")
        effort = resume_job["analysis"].get("effort") if resume_job else resolve_effort(selected, body.effort)
        effort_policy = resume_job["analysis"].get("effort_policy", body.effort_policy) if resume_job else body.effort_policy
        if "high" not in selected.get("supported_efforts", []) and selected.get("effort") != "high":
            effort_policy = "fixed"
        async with analysis_lock:
            if get("projects", project_id).get("analysis_generation", 0) != generation:
                raise HTTPException(409, "影片分析已重置，請重新搜尋。")
            if resume_job:
                saved_job = store.get("jobs", resume_job["id"])
                if not saved_job or saved_job.get("progress_reset"):
                    raise HTTPException(409, "舊分析進度已重置，請重新搜尋。")
            current = store.all("jobs")
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
                         else profiles.snapshot(profiles.resolve(get("projects", project_id))))
            submitted = jobs.submit(project_id, "analyze", analysis={**body.model_dump(exclude_none=True),
                **({"review_target": {key: target.get(key) for key in
                    ("id", "start", "end", "victory", "kind", "boss", "summary")}} if target else {}),
                "effort": effort,
                "effort_policy": effort_policy,
                **({"profile": reference} if reference else {}),
                "request_id": request_id, **({"resume_from": resume_job["id"]} if resume_job else {})})
            if project.get("youtube_analysis_error"):
                store.patch("projects", project_id, youtube_analysis_error=None)
            return submitted

    @app.post("/api/codex/chat")
    async def codex_chat(body: ChatRequest):
        project = get("projects", body.context.project_id) if body.context else None
        if project:
            all_jobs = store.all("jobs")
            latest = next((j for j in all_jobs if j["project_id"] == project["id"] and j["kind"] == "analyze" and not j.get("progress_reset")), None)
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
                    start=action["start"], end=action["end"], model=body.model, effort=body.effort), body.request_id,
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
            shutdown = asyncio.create_task(shutting_down.wait())
            try:
                yield json.dumps({"type": "waiting"}) + "\n"
                while not task.done() and not shutdown.done():
                    await asyncio.wait({task, shutdown}, timeout=5,
                                       return_when=asyncio.FIRST_COMPLETED)
                    if not task.done() and not shutdown.done():
                        yield json.dumps({"type": "waiting"}) + "\n"
                if not shutting_down.is_set():
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

    @app.post("/api/projects/{project_id}/analyze", status_code=202)
    async def analyze(project_id: str, body: AnalysisRequest):
        # Compatibility route: same validation, model selection and queue.
        return public_job(await enqueue_analysis(project_id, body, uuid4().hex))

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = ""
            while not shutting_down.is_set() and not await request.is_disconnected():
                current = json.dumps(state(), ensure_ascii=False)
                yield (
                    f"data: {current}\n\n" if current != previous else ": heartbeat\n\n"
                )
                previous = current
                try:
                    await asyncio.wait_for(shutting_down.wait(), timeout=1)
                except TimeoutError:
                    pass

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/api/sources")
    async def sources():
        result, seen = [], set()
        for kind in ("sources", "exports"):
            for path in sorted(locations.folder(kind).rglob("*")):
                if path.suffix.lower() in EXTENSIONS and path.is_file():
                    try:
                        resolved = local_source(root, str(path))
                    except ValueError:
                        continue
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    result.append(
                        {
                            "path": record_path(root, resolved),
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
                record_path(root, local_source(root, body.source))
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
        if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in store.all("jobs")) >= 8:
            raise HTTPException(429, "任務佇列已滿，請稍後再試。")
        project_id = uuid4().hex
        project = {
            "id": project_id,
            "title": Path(source).stem if source else "YouTube · " + url.split("v=")[1],
            "source": source,
            "url": url,
            "work": record_path(root, locations.project_folder("cache", project_id)),
            "ready": False,
            "created": time.time(),
            "thumbnails": [],
            **({"download_quality": body.download_quality} if body.kind == "youtube" else {}),
        }
        store.put("projects", project)
        return {
            "project": public_project(project),
            "job": jobs.submit(project["id"], "prepare"),
        }

    @app.get("/api/projects/{project_id}")
    async def project_details(project_id: str):
        project = get("projects", project_id)
        return public_project(project) | {
            "source": project.get("source"), "url": project.get("url"),
        }

    @app.patch("/api/projects/{project_id}")
    async def rename_project(project_id: str, body: ProjectUpdate):
        get("projects", project_id)
        if any(ord(char) < 32 for char in body.title):
            raise HTTPException(422, "專案名稱不能包含換行或控制字元。")
        return public_project(store.patch("projects", project_id, title=body.title))

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str):
        # Serialize with upload start/resume/restart, including their hash await.
        # Once deletion starts, no new uploader may slip past the cancellation.
        async with youtube.lock, analysis_lock:
            get("projects", project_id)
            deleting_projects.add(project_id)
            try:
                for upload in youtube.uploads.all().values():
                    if upload["project_id"] == project_id:
                        await youtube.uploads.pause(upload["id"])
                related = [job for job in store.all("jobs") if job["project_id"] == project_id]
                tasks = [jobs.tasks[job["id"]] for job in related if job["id"] in jobs.tasks]
                for task in tasks:
                    task.cancel()
                # Workers must finish cancellation before their database rows go.
                await asyncio.gather(*tasks, return_exceptions=True)
                store.delete_project(project_id)
            finally:
                deleting_projects.discard(project_id)
        return {"id": project_id, "deleted": True}

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

    @app.put("/api/projects/{project_id}/candidate-edit")
    async def edit_candidate(project_id: str, body: CandidateEditRequest):
        project = get("projects", project_id)
        if not project.get("ready"):
            raise HTTPException(409, "原片尚未就緒。")
        if not body.start < body.victory or body.victory + body.postroll > project["duration"]:
            raise HTTPException(422, "開始必須早於勝利，且勝利後須保留完整 5–10 秒，不可超出原片。")
        try:
            return store.set_candidate_edit(project_id, body.candidate_id, body.model_dump())
        except KeyError:
            raise HTTPException(404, "找不到這個影片的候選片段。") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    def clip_for_edit(project_id: str, job_id: str):
        job = get("jobs", job_id)
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

    @app.put("/api/projects/{project_id}/clips/{job_id}/draft")
    async def save_clip_draft(project_id: str, job_id: str, body: Draft):
        project = get("projects", project_id)
        job = clip_for_edit(project_id, job_id)
        validate_draft(project, body)
        if body.revision != editable_clip_draft(job)["revision"]:
            raise HTTPException(409, "片段草稿已更新，請重新載入專案。")
        draft = body.model_dump(exclude_none=True) | {"revision": body.revision + 1}
        store.patch("jobs", job_id, edit_draft=draft)
        return draft

    def remove_clip(project_id: str, job: dict):
        """Delete one finished export; callers hold the upload lock."""
        job_id = job["id"]
        if any(item["export_id"] == job_id and (item["id"] in youtube.uploads.tasks
               or item["status"] in {"queued", "uploading", "processing", "adding_to_playlist"})
               for item in youtube.uploads.all().values()):
            raise HTTPException(409, "這個成品正在上傳 YouTube，請先暫停上傳再刪除。")
        # Delete only an MP4 and receipt with the worker's layout, never through symlinks.
        try:
            output = export_path(root, job)
        except LocationError:
            raise HTTPException(409, "成品檔案位置異常，未刪除資料。") from None
        files = (output, output.with_suffix(".json"))
        if any(path.is_symlink() or path.resolve() != path for path in files):
            raise HTTPException(409, "成品檔案位置異常，未刪除資料。")
        if any(p.get("source") and media_path(root, p["source"]).resolve() in files for p in store.all("projects")):
            raise HTTPException(409, "這個成品正被用作專案原片，請先移除使用它的專案。")
        size = output.stat().st_size if output.is_file() else 0
        try:
            for path in files:
                path.unlink(missing_ok=True)
        except OSError as error:
            raise HTTPException(500, "成品檔案刪除未完成，請重試。") from error
        store.delete_clip(project_id, job_id)
        return size

    @app.delete("/api/projects/{project_id}/clips/{job_id}")
    async def delete_clip(project_id: str, job_id: str):
        # Serialize with upload startup, which hashes the file before queuing it.
        async with youtube.uploads.lock:
            get("projects", project_id)
            remove_clip(project_id, clip_for_edit(project_id, job_id))
            return {"deleted": True, "id": job_id}

    @app.post("/api/projects/{project_id}/clips/remove-published")
    async def remove_published_clips(project_id: str):
        async with youtube.uploads.lock:
            get("projects", project_id)
            uploads = clip_uploads()
            deleted, freed = [], 0
            for job in store.all("jobs"):
                if (job["project_id"] == project_id and job["kind"] == "export" and job["status"] == "succeeded"
                        and job.get("draft") and uploads.get(job["id"], {}).get("published")):
                    freed += remove_clip(project_id, job)
                    deleted.append(job["id"])
            return {"deleted": deleted, "bytes": freed}

    @app.put("/api/projects/{project_id}/draft")
    async def save_draft(project_id: str, body: Draft):
        project = get("projects", project_id)
        validate_draft(project, body)
        if body.revision != project["draft"]["revision"]:
            raise HTTPException(409, "草稿已更新，請重新載入專案。")
        draft = body.model_dump(exclude_none=True) | {"revision": body.revision + 1}
        store.patch("projects", project_id, draft=draft)
        return draft

    @app.post("/api/projects/{project_id}/exports", status_code=202)
    async def export(project_id: str, body: ExportRequest):
        project = get("projects", project_id)
        draft = (editable_clip_draft(clip_for_edit(project_id, body.source_job_id))
                 if body.source_job_id else project.get("draft"))
        if not draft or draft["revision"] != body.revision:
            raise HTTPException(409, "請先儲存目前草稿。")
        try:
            validate_draft(project, Draft.model_validate(draft))
        except ValidationError:
            raise HTTPException(422, "剪輯時間範圍無效，請修正後再匯出。") from None
        for job in store.all("jobs"):
            if (
                job["project_id"] == project_id
                and job["kind"] == "export"
                and job.get("source_job_id") == body.source_job_id
                and job.get("draft", {}).get("revision") == body.revision
                # Jobs from before quality presets were encoded with today's "fast" settings.
                and job.get("export_quality", "fast") == body.quality
                and job["status"] in ACTIVE | {"succeeded"}
            ):
                return public_job(job)
        if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in store.all("jobs")) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        return jobs.submit(project_id, "export", draft, source_job_id=body.source_job_id, export_quality=body.quality)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        job = get("jobs", job_id)
        task = jobs.tasks.get(job_id)
        if task and job["status"] in ACTIVE:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first instruction never enters execute().
            if store.get("jobs", job_id) is not None:
                store.patch("jobs", job_id, status="cancelled", stage="已取消")
        return public_job(get("jobs", job_id))

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry(job_id: str):
        job = get("jobs", job_id)
        get("projects", job["project_id"])
        if job.get("progress_reset"):
            raise HTTPException(409, "此分析的查看進度已重置，請重新搜尋。")
        if job["status"] not in {"failed", "cancelled", "interrupted"} and not (
            job["kind"] == "analyze" and job["status"] == "succeeded"
            and (job.get("result") or {}).get("can_continue")
        ):
            raise HTTPException(409, "此任務不需要重試。")
        if job["kind"] == "analyze":
            bounds = job["analysis"]
            checkpoint = project_work(root, get("projects", job["project_id"])) / "codex" / job["id"] / "checkpoint.json"
            return public_job(await enqueue_analysis(job["project_id"], AnalysisRequest(
                start=bounds["start"], end=bounds["end"], model=bounds.get("model", MODEL), effort=bounds.get("effort"),
                candidate_id=bounds.get("candidate_id")), uuid4().hex,
                resume_job=job if checkpoint.is_file() else None))
        if any(
            j["project_id"] == job["project_id"] and j["status"] in ACTIVE
            for j in store.all("jobs")
        ):
            raise HTTPException(409, "此專案已有任務執行中。")
        if job["kind"] == "prepare" and get("projects", job["project_id"])["ready"]:
            raise HTTPException(409, "此專案的原片已就緒，無需重新準備。")
        if sum(j["status"] in ACTIVE and j["kind"] != "analyze" for j in store.all("jobs")) >= 8:
            raise HTTPException(429, "任務佇列已滿。")
        return jobs.submit(
            job["project_id"], job["kind"], job.get("draft"), job.get("analysis"), job.get("source_job_id"),
            job.get("export_quality", "high") if job["kind"] == "export" else None,
        )

    async def clear_analysis(project_id: str, *, progress_only: bool = False):
        async with analysis_lock:
            project = get("projects", project_id)
            if not project.get("ready"):
                raise HTTPException(409, "請先完成原片準備。")
            analysis_jobs = [j for j in store.all("jobs")
                             if j["project_id"] == project_id and j["kind"] == "analyze"]
            # Join worker cancellation before removing any checkpoint or database row.
            for job in analysis_jobs:
                await cancel(job["id"])
            work = project_work(root, project)
            artifacts = work / "codex"
            if artifacts.is_symlink() or not artifacts.resolve().is_relative_to(work.resolve()):
                raise HTTPException(409, "分析目錄位置異常，未清除資料。")
            logs = root / "runs" / "web"
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
            project = store.reset_analysis(project_id, progress_only=progress_only)
            remaining_jobs = store.all("jobs")
            return {"project": public_project(project) | {"review_candidates": project_candidates(project, remaining_jobs)},
                    "jobs": [public_job(j) for j in remaining_jobs if j["project_id"] == project_id]}

    @app.post("/api/projects/{project_id}/reset-analysis")
    async def reset_analysis(project_id: str):
        return await clear_analysis(project_id)

    @app.post("/api/projects/{project_id}/reset-analysis-progress")
    async def reset_analysis_progress(project_id: str):
        return await clear_analysis(project_id, progress_only=True)

    @app.get("/api/projects/{project_id}/media/{filename}")
    async def media(project_id: str, filename: str):
        project = get("projects", project_id)
        if filename == "source":
            # A fixed endpoint serves only the registered source, never a path
            # supplied by the browser. Do not re-check today's storage folders:
            # existing projects keep their original locations when settings change.
            if not project.get("ready") or not project.get("source"):
                raise HTTPException(404, "原片尚未就緒。")
            path = media_path(root, project["source"])
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXTENSIONS:
                raise HTTPException(404, "找不到原片，請確認檔案仍在原來的位置。")
            mime = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
                    ".mov": "video/quicktime", ".mkv": "video/x-matroska"}[path.suffix.lower()]
            return LocalFileResponse(path, media_type=mime, range_limit=PREVIEW_RANGE_LIMIT)
        allowed = {"preview.mp4"} | {t["file"] for t in project["thumbnails"]}
        if not project["ready"] or filename not in allowed:
            raise HTTPException(404, "找不到預覽。")
        path = project_work(root, project) / filename
        if not path.is_file():
            raise HTTPException(404, "找不到預覽。")
        return LocalFileResponse(path, range_limit=PREVIEW_RANGE_LIMIT)

    @app.get("/api/jobs/{job_id}/download")
    async def download(job_id: str):
        job = get("jobs", job_id)
        if job["status"] != "succeeded" or job["kind"] != "export":
            raise HTTPException(404, "尚無可下載的剪輯。")
        title = (job.get("draft", {}).get("title") or "").strip()
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", title).strip(" .")
        return LocalFileResponse(
            media_path(root, job["output"]),
            filename=f"{filename or 'boss-fight-' + job_id[:8]}.mp4",
            media_type="video/mp4",
        )

    @app.get("/api/projects/{project_id}/review-packet")
    async def review_packet(project_id: str):
        project = get("projects", project_id)
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

    async def youtube_import(video_id: str, download_quality: DownloadQuality = "best"):
        return await import_project(ImportRequest(kind="youtube", source=f"https://www.youtube.com/watch?v={video_id}",
                                                  download_quality=download_quality))

    async def youtube_check_model(model: str):
        if not model:
            raise YouTubeError("請選擇 AI 模型，或取消匯入後自動找片段。", 422)
        status = await codex.status()
        if not status["available"]:
            raise YouTubeError("請先連接 AI 帳號，或取消匯入後自動找片段。", 422)
        selected = next((m for m in await codex.models() if m["id"] == model), None)
        if not selected or "image" not in selected.get("input_modalities", []):
            raise YouTubeError("請選擇支援畫面判讀的 AI 模型。", 422)
        return selected

    async def youtube_analyze(project: dict, model: str, request_id: str):
        selected = await youtube_check_model(model)
        # This entry point has no effort picker. Use the visual-review policy,
        # rather than silently inheriting the model's general chat default.
        supported = set(selected.get("supported_efforts", [])) | {selected.get("effort")}
        effort = next((value for value in ("xhigh", "high") if value in supported), selected.get("effort"))
        return await enqueue_analysis(project["id"], AnalysisRequest(
            start=0, end=project["duration"], model=model, effort=effort), request_id)

    youtube = YouTubeWorkspace(store, youtube_import, youtube_analyze, youtube_check_model)
    youtube.mount(app)
    app.state.youtube = youtube

    # State updates use SSE. Reject unsupported WebSocket upgrades before the
    # catch-all static mount, whose ASGI application only accepts HTTP scopes.
    @app.websocket("/{path:path}")
    async def reject_websocket(websocket: WebSocket):
        await websocket.close(code=1008)

    frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Local BossCut POC (one server process)"
    )
    parser.add_argument("--port", type=int, default=8000)
    # Containers need 0.0.0.0 so a published Docker port can reach the server.
    parser.add_argument("--host", default=os.environ.get("GAME_VOD_HOST", "127.0.0.1"))
    args = parser.parse_args()
    app = create_app()
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            timeout_graceful_shutdown=5)
    try:
        LocalServer(config, app.state.shutting_down).run()
    except KeyboardInterrupt:
        # Match uvicorn.run(): signal handling and cleanup already ran.
        pass
